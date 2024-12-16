import pandas as pd
from langid import classify
from typing import List
import mysql.connector
from dotenv import load_dotenv, find_dotenv
import os

def execute_query(sql_query: str):
    def load_env():
        load_dotenv(find_dotenv('.env.example'), override=True)
        load_dotenv(find_dotenv('.env'), override=True)

    def connect_to_database():
        conn = mysql.connector.connect(
            host=os.getenv('DB_HOST'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME'),
            port=int(os.getenv('DB_PORT'))
        )
        cursor = conn.cursor()
        return conn, cursor

    def disconnect_from_database(conn, cursor):
        cursor.close()
        conn.close()

    load_env()
    conn, cursor = connect_to_database()

    cursor.execute(sql_query)
    column_names = [desc[0] for desc in cursor.description]
    results = [dict(zip(column_names, row)) for row in cursor.fetchall()]

    disconnect_from_database(conn, cursor)

    return results

def fetch_data_from_db(exercise_ids: List[int]) -> pd.DataFrame:
    """Fetches data from the database for the given exercise IDs."""
    sql_query = f"""
        SELECT
            {get_columns("exercise", ["id", "title", "max_points", "bonus_points", "grading_instructions", "problem_statement", "example_solution"])},
            {get_columns("submission", ["id", "text", "language"])},
            {get_columns("result", ["id", "score", "results_order"])},
            {get_columns("grading_criterion", ["id", "title"])},
            {get_columns("grading_instruction", ["id", "credits", "grading_scale", "instruction_description", "feedback", "usage_count"])},
            {get_columns("feedback", ["id", "text", "detail_text", "credits", "grading_instruction_id"])},
            {get_columns("text_block", ["start_index", "end_index"])},
            /* Add a column to distinguish feedback types */
            "Tutor" as feedback_type
        FROM exercise
        LEFT JOIN participation ON exercise.id = participation.exercise_id
        LEFT JOIN submission ON participation.id = submission.participation_id
        LEFT JOIN result ON submission.id = result.submission_id
        LEFT JOIN feedback ON result.id = feedback.result_id
        LEFT JOIN text_block ON feedback.reference = text_block.id
        LEFT JOIN grading_criterion ON grading_criterion.exercise_id = exercise.id
        LEFT JOIN grading_instruction ON grading_instruction.grading_criterion_id = grading_criterion.id
        WHERE exercise.id IN ({', '.join(map(str, exercise_ids))})
          AND (result.results_order = 0)
    """
    data = execute_query(sql_query)

    print(f"Fetched {len(data)} records from the database.")
    return pd.DataFrame(data)

def filter_missing_data(data: pd.DataFrame) -> pd.DataFrame:
    """Filters out rows with missing or invalid data."""
    print("Filtering out rows with missing or invalid data...")

    data = data.dropna(subset=["submission_text", "result_score"])
    data = data[data["submission_text"].str.strip() != ""]

    print(f"Filtered down to {len(data)} rows.")
    return data

def filter_english_submissions(data: pd.DataFrame) -> pd.DataFrame:
    """Filters out non-English and empty submissions efficiently."""
    print("Filtering English and non-empty submissions...")

    data = data.dropna(subset=["submission_text"])
    data = data[data["submission_text"].str.strip() != ""]

    is_english = data["submission_text"].apply(lambda text: classify(text)[0] == "en")
    filtered_data = data[is_english]

    print(f"Filtered down to {len(filtered_data)} rows.")
    return filtered_data


def get_data(exercise_ids: List[int]) -> pd.DataFrame:
    """
    Fetches raw data from the database, filters English submissions,
    and returns a flat DataFrame.
    """
    data = fetch_data_from_db(exercise_ids)

    data = filter_missing_data(data)

    data = filter_english_submissions(data)

    print(f"Returning flat DataFrame with {len(data)} rows.")
    return data


def get_columns(table_name: str, column_names: List[str]) -> str:
    """
    Generate SQL column selection with table name prefixes.

    Args:
        table_name (str): Name of the table.
        column_names (List[str]): List of column names to include.

    Returns:
        str: Comma-separated column selections with table name prefixes.
    """
    return ", ".join([f"{table_name}.{col} AS {table_name}_{col}" for col in column_names])
