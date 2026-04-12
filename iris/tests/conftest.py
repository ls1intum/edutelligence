import os
from pathlib import Path

# Set APPLICATION_YML_PATH before any pipeline imports trigger Settings loading.
os.environ.setdefault(
    "APPLICATION_YML_PATH",
    str(Path(__file__).resolve().parent.parent / "application.example.yml"),
)
