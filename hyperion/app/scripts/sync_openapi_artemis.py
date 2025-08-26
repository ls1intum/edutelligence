#!/usr/bin/env python3
"""
Simple OpenAPI File Synchronization Script for Artemis Integration

This script synchronizes the Hyperion OpenAPI file with the Artemis project.
It maintains a simple configuration file to remember the Artemis path.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Configuration file name (will be gitignored)
CONFIG_FILE = ".artemis_sync_config.json"


def load_config() -> dict:
    """Load configuration from file."""
    config_path = Path(__file__).parent.parent.parent / CONFIG_FILE
    if config_path.exists():
        try:
            return json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_config(config: dict) -> None:
    """Save configuration to file."""
    config_path = Path(__file__).parent.parent.parent / CONFIG_FILE
    try:
        config_path.write_text(json.dumps(config, indent=2))
    except OSError as e:
        print(f"⚠️  Warning: Could not save config: {e}")


def find_artemis_project() -> Optional[Path]:
    """Simple search for Artemis project."""
    # Start from current directory and look for Artemis
    current_dir = Path.cwd()

    # Common paths to check
    potential_paths = [
        # If we're in hyperion, look for artemis as sibling
        current_dir.parent / "Artemis",
        current_dir.parent / "artemis",
        # Check Documents folder
        Path.home() / "Documents" / "Artemis",
        Path.home() / "Documents" / "artemis",
    ]

    for path in potential_paths:
        if path.exists() and (path / "build.gradle").exists():
            return path

    return None


def get_artemis_path(config: dict, provided_path: Optional[str] = None) -> Path:
    """Get Artemis project path with user confirmation."""

    if provided_path:
        path = Path(provided_path).resolve()
        if not path.exists():
            print(f"❌ Provided path does not exist: {path}")
            sys.exit(1)
        if not (path / "build.gradle").exists():
            print(f"❌ Not an Artemis project (no build.gradle): {path}")
            sys.exit(1)
        return path

    # Check saved config
    saved_path = config.get("artemis_path")
    if saved_path:
        path = Path(saved_path)
        if path.exists() and (path / "build.gradle").exists():
            # Only ask for confirmation if the user hasn't run this script recently
            # or if there are multiple potential paths
            return path

    # Try to find automatically
    auto_path = find_artemis_project()
    if auto_path:
        response = (
            input(f"🔍 Found Artemis project: {auto_path}. Use this? [Y/n]: ")
            .strip()
            .lower()
        )
        if response in ("", "y", "yes"):
            config["artemis_path"] = str(auto_path)
            save_config(config)
            return auto_path

    # Ask user for path
    while True:
        user_path = input("📂 Enter path to Artemis project: ").strip()
        if not user_path:
            print("❌ Path cannot be empty")
            continue

        path = Path(user_path).expanduser().resolve()
        if not path.exists():
            print(f"❌ Path does not exist: {path}")
            continue

        if not (path / "build.gradle").exists():
            print(f"❌ Not an Artemis project (no build.gradle): {path}")
            continue

        # Save the path
        config["artemis_path"] = str(path)
        save_config(config)
        return path


def generate_openapi_spec(dry_run: bool = False) -> bool:
    """Generate the OpenAPI specification from the Hyperion service."""

    if dry_run:
        print("🔍 DRY RUN: Would generate OpenAPI specification")
        return True

    print("📝 Generating OpenAPI specification...")

    try:
        # Get the directory where this script is located (hyperion root)
        hyperion_root = Path(__file__).parent.parent.parent

        result = subprocess.run(
            ["poetry", "run", "openapi"],
            cwd=hyperion_root,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            print("❌ Failed to generate OpenAPI spec")
            print(f"Error output: {result.stderr}")
            return False
        else:
            print("✅ OpenAPI specification generated successfully")
            return True

    except subprocess.TimeoutExpired:
        print("❌ OpenAPI generation timed out")
        return False
    except Exception as e:
        print(f"❌ Error generating OpenAPI spec: {e}")
        return False


def run_gradle_tasks(artemis_path: Path, dry_run: bool = False) -> bool:
    """Run the necessary Gradle tasks in Artemis to generate the client."""

    if dry_run:
        print("🔍 DRY RUN: Would run Gradle tasks in Artemis")
        return True

    print("🔄 Running Gradle tasks in Artemis...")

    try:
        # Generate the Hyperion Java client from the OpenAPI spec
        # The generated code will be compiled automatically when Artemis runs
        tasks = ["generateHyperionJavaClient"]

        for task in tasks:
            print(f"   Running: ./gradlew {task}")
            result = subprocess.run(
                ["./gradlew", task, "--console=plain"],
                cwd=artemis_path,
                capture_output=True,
                text=True,
                timeout=60,  # 1 minute should be enough for generation
            )

            if result.returncode != 0:
                print(f"❌ Failed to run ./gradlew {task}")
                print(f"Error output: {result.stderr}")
                return False
            else:
                print(f"✅ Completed: ./gradlew {task}")

        return True

    except subprocess.TimeoutExpired:
        print("❌ Gradle task timed out")
        return False
    except Exception as e:
        print(f"❌ Error running Gradle tasks: {e}")
        return False


def sync_openapi_file(
    source_path: Path, target_path: Path, dry_run: bool = False
) -> bool:
    """Synchronize the OpenAPI file."""

    print(f"📂 Source: {source_path}")
    print(f"📂 Target: {target_path}")

    if not source_path.exists():
        print(f"❌ Source OpenAPI file not found: {source_path}")
        return False

    if dry_run:
        print(f"🔍 DRY RUN: Would copy OpenAPI file to {target_path}")
        if target_path.exists():
            print("⚠️  Target file already exists and would be overwritten")
        return True

    try:
        # Create target directory if needed
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy the file
        shutil.copy2(source_path, target_path)

        # Show success
        size = target_path.stat().st_size
        print(f"✅ OpenAPI file synchronized successfully! ({size} bytes)")
        return True

    except Exception as e:
        print(f"❌ Error synchronizing OpenAPI file: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Synchronize Hyperion OpenAPI file with Artemis project",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  poetry run sync-openapi-artemis                        # Generate, sync, and build automatically (default)
  poetry run sync-openapi-artemis --no-build             # Generate and sync only (skip client generation)
  poetry run sync-openapi-artemis --no-generate          # Skip generation, just sync existing spec
  poetry run sync-openapi-artemis --artemis-path /path   # Specify Artemis path
  poetry run sync-openapi-artemis --dry-run              # Preview all changes
        """,
    )

    parser.add_argument("--artemis-path", type=str, help="Path to Artemis project root")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    parser.add_argument(
        "--no-build",
        action="store_true",
        help="Skip running Gradle tasks (only sync the OpenAPI file)",
    )

    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="Skip OpenAPI generation and use existing spec file",
    )

    args = parser.parse_args()

    print("🚀 Hyperion → Artemis OpenAPI Synchronization")
    print("=" * 50)

    # Load configuration
    config = load_config()

    # Get source openapi file (we know where this is)
    source_openapi = Path(__file__).parent.parent.parent / "openapi.yaml"

    # Get Artemis path
    artemis_path = get_artemis_path(config, args.artemis_path)
    target_openapi = artemis_path / "openapi" / "hyperion.yaml"

    # Generate OpenAPI spec first (unless --no-generate is specified)
    if not args.no_generate:
        openapi_success = generate_openapi_spec(args.dry_run)
        if not openapi_success:
            print("❌ Failed to generate OpenAPI specification!")
            sys.exit(1)

    # Perform synchronization
    success = sync_openapi_file(source_openapi, target_openapi, args.dry_run)

    if success:
        if not args.dry_run:
            # Run Gradle tasks by default (unless --no-build is specified)
            if not args.no_build:
                print()
                gradle_success = run_gradle_tasks(artemis_path, args.dry_run)
                if gradle_success:
                    print("✅ Client generation completed successfully!")
                else:
                    print("❌ Client generation failed, but sync was successful")
            else:
                print()
                print("🎯 Next Steps:")
                print(
                    "1. Run './gradlew generateHyperionJavaClient' in Artemis to generate client"
                )
                print("2. Start/restart Artemis to use the updated client")
                print()
                print("💡 Tip: Remove --no-build flag to generate client automatically")

            print()
            print("✅ Synchronization completed!")
        sys.exit(0)
    else:
        print("❌ Synchronization failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
