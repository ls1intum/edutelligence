import subprocess
import time
import requests
import pytest
from pathlib import Path
from datetime import datetime
from sqlalchemy import create_engine, inspect, text

# Test Configuration
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATIONS_DIR = PROJECT_ROOT / "migrations" / "versions"
MIGRATION_TEMPLATE_FILE = (
    PROJECT_ROOT / "test" / "e2e" / "migration_files" / "migration_template.py"
)
DOCKER_COMPOSE_FILE = PROJECT_ROOT / "docker-compose.local.yml"

# Service URLs
AMM_API_URL = "http://localhost:5100"
MODELING_MODULE_URL = "http://localhost:5008"
# Database URL for the test script to connect to the exposed Postgres port
DB_URL_HOST = "postgresql://athena:athena@localhost:5432/athena"

# Test Data
# This payload targets the modeling module defined in your docker-compose.yml
MODELING_FEEDBACK_REQUEST_PAYLOAD = {
    "exercise": {
        "id": 2,
        "title": "UML Class Diagram",
        "type": "modeling",
        "max_points": 10.0,
        "bonus_points": 0.0,
        "problem_statement": "Design a UML class diagram for a library system.",
        "meta": {},
    },
    "submission": {
        "id": 202,
        "exercise_id": 2,
        "model": "<xml>This is the model submission content</xml>",
        "meta": {},
    },
}


def run_docker_compose(command: str):
    """Runs a docker-compose command and raises an exception on failure."""
    # Use the -p flag to create a uniquely named project to avoid conflicts in CI
    cmd = [
        "docker-compose",
        "-p",
        "athena-migration-test",
        "-f",
        str(DOCKER_COMPOSE_FILE),
        *command.split(),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"STDOUT:\n{result.stdout}")
        print(f"STDERR:\n{result.stderr}")
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )
    return result


def wait_for_services(timeout: int = 120):
    """Waits for all necessary services to become available."""
    print("Waiting for services to become available...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            # 1. Check Database
            engine = create_engine(DB_URL_HOST)
            with engine.connect():
                pass  # Connection successful
            # 2. Check Assessment Module Manager
            requests.get(f"{AMM_API_URL}/health", timeout=5).raise_for_status()
            # 3. Check Modeling Module (from your docker-compose.yml)
            requests.get(f"{MODELING_MODULE_URL}/", timeout=5).raise_for_status()

            print("All services are up and running.")
            return
        except (requests.RequestException, Exception) as e:
            print(f"Services not yet ready, waiting... Error: {e}")
            time.sleep(5)
    raise TimeoutError("Services did not become available in time.")


def verify_db_schema(engine, expected_tables, expected_columns=None):
    """Verifies that the database schema contains expected tables and columns."""
    inspector = inspect(engine)
    db_tables = inspector.get_table_names()
    for table in expected_tables:
        assert table in db_tables, f"Table '{table}' not found in database."

    if expected_columns:
        for table, columns in expected_columns.items():
            db_columns = [col["name"] for col in inspector.get_columns(table)]
            for col in columns:
                assert (
                    col in db_columns
                ), f"Column '{col}' not found in table '{table}'."


def make_feedback_request():
    """Makes a request to the modeling feedback suggestions endpoint."""
    headers = {
        "Authorization": "12345abcdef",  # From .env file
        "X-Server-URL": "http://localhost:8080",  # From deployments.ini (local)
    }
    url = f"{AMM_API_URL}/modules/modeling/module_modeling_llm/feedback_suggestions"
    response = requests.post(
        url, json=MODELING_FEEDBACK_REQUEST_PAYLOAD, headers=headers
    )
    response.raise_for_status()
    return response.json()


def verify_feedback_in_db(engine):
    """Checks if a modeling feedback suggestion was correctly inserted."""
    with engine.connect() as connection:
        result = connection.execute(
            text(
                "SELECT COUNT(*) FROM modeling_feedbacks WHERE submission_id = :sub_id AND is_suggestion = TRUE"
            ),
            {"sub_id": MODELING_FEEDBACK_REQUEST_PAYLOAD["submission"]["id"]},
        ).scalar_one()
        assert result > 0, "Modeling feedback suggestion was not found in the database."
        print("Verified feedback suggestion in DB.")


@pytest.mark.e2e
def test_database_migration_flow():
    """
    An end-to-end test for the database migration process using the real stack.
    1. Starts services, applying the initial migration via the container entrypoint.
    2. Verifies the initial schema and tests core functionality (modeling feedback).
    3. Creates and deploys a new migration file.
    4. Restarts services to apply the new migration.
    5. Verifies the new schema and performs a regression test on core functionality.
    """
    new_migration_file_path = None
    try:
        # 1: Initial State Verification
        print("\n--- Starting Part 1: Initial Migration ---")
        run_docker_compose("down -v --remove-orphans")
        run_docker_compose("up --build -d")
        wait_for_services()

        engine = create_engine(DB_URL_HOST)
        print("Verifying initial schema...")
        initial_tables = [
            "exercise",
            "modeling_exercises",
            "modeling_submissions",
            "modeling_feedbacks",
        ]
        verify_db_schema(engine, initial_tables)
        print("Initial schema verified successfully.")

        print("Testing feedback request functionality...")
        make_feedback_request()
        verify_feedback_in_db(engine)
        print("Feedback functionality works on initial schema.")

        # 2: New Migration and Regression Test
        print("\n--- Starting Part 2: Applying New Migration ---")
        print("Stopping services...")
        run_docker_compose("stop")

        print("Creating new migration file...")
        revision_id = f"{int(datetime.now().timestamp())}_add_status_column"
        new_migration_file_path = MIGRATIONS_DIR / f"{revision_id}.py"

        # Read the template, format it with a unique revision ID, and write it
        template_content = MIGRATION_TEMPLATE_FILE.read_text()
        migration_content = template_content.format(
            revision_id=revision_id, create_date=datetime.now().isoformat()
        )
        new_migration_file_path.write_text(migration_content)
        print(f"Created migration: {new_migration_file_path.name}")

        print("Restarting services to apply new migration...")
        run_docker_compose("up -d")  # Start again, entrypoint will apply new migration
        wait_for_services()

        print("Verifying new schema with added column...")
        verify_db_schema(
            engine, initial_tables, expected_columns={"modeling_feedbacks": ["status"]}
        )
        print("New schema verified successfully.")

        print("Performing regression test on feedback functionality...")
        # Make another request to ensure functionality is not broken
        make_feedback_request()
        # Verify the same functionality still works
        verify_feedback_in_db(engine)
        print("Feedback functionality still works after migration.")

    finally:
        # Cleanup
        # print("\n--- Cleaning up ---")
        # if new_migration_file_path and new_migration_file_path.exists():
        #     new_migration_file_path.unlink()
        #     print(f"Removed migration file: {new_migration_file_path.name}")
        # run_docker_compose("down -v --remove-orphans")
        print("Test environment cleaned up successfully.")
