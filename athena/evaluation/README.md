# Project with Jupytext Workflow

This project uses [Jupytext](https://jupytext.readthedocs.io) to manage Jupyter notebooks as Python scripts. Only `.py` script files are tracked in version control, while `.ipynb` notebooks are excluded. Notebooks can be recreated locally for interactive use.

## Directory Structure

- `scripts/`: Contains the Python script files (`.py`) derived from Jupyter notebooks.
- `notebooks/`: Used for Jupyter notebooks (`.ipynb`). These files are **not tracked** by version control.

## Setup Instructions

### 1. Install Jupytext
Install Jupytext to enable notebook-script synchronization:
```bash
pip install jupytext
```

### 2. Generate Notebooks
To recreate Jupyter notebooks from the `.py` files and place them in the `notebooks/` directory:
```bash
for file in scripts/*.py; do jupytext --to ipynb --output notebooks/$(basename "${file%.py}.ipynb") "$file"; done
```
Notebooks will be created in the `notebooks/` directory.

### 3. Edit Notebooks
Work on the `.ipynb` notebooks interactively. Once changes are saved, sync them back to the `.py` scripts:
```bash
for file in notebooks/*.ipynb; do jupytext --to py:percent --output scripts/$(basename "${file%.ipynb}.py") "$file"; done
```

### 4. Commit Changes
- Only commit changes to the `.py` files in `scripts/`.
- Notebooks in `notebooks/` are ignored by Git and should not be committed.

## Notes

- Use the `py:percent` format (`# %%` markers) in Python scripts to ensure compatibility with interactive environments like VS Code and PyCharm.
- Never manually edit the `.ipynb` files outside of Jupyter Notebook or Jupytext synchronization.
