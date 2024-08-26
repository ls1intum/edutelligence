import os
import json
import re
from IPython.display import HTML, display

def parse_filename(filename):
    """Extracts exercise ID and technique from the filename."""
    match = re.match(r'exercise-(\d+)-?(.*)\.json', filename)
    if not match:
        raise ValueError(f"Filename '{filename}' does not match the expected pattern.")
    exercise_id, technique = match.groups()
    exercise_id = int(exercise_id)
    technique = technique or 'manual'  # Default to 'manual' if no technique is specified
    return exercise_id, technique

def load_data(directory):
    """Loads all JSON files from the directory and returns their contents with exercise ID and technique."""
    data = []

    for filename in os.listdir(directory):
        if filename.endswith('.json'):
            filepath = os.path.join(directory, filename)
            with open(filepath, 'r') as file:
                file_data = json.load(file)
                exercise_id, technique = parse_filename(filename)
                data.append((exercise_id, technique, file_data))

    # Display a summary of loaded data
    summary_message = (
            f"<div style='color: green; font-weight: bold;'>"
            f"Success! {len(data)} JSON file(s) loaded.</div>"
    )
    display(HTML(summary_message))

    return data
