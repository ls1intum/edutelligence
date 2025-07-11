#!/usr/bin/env python3
"""
Consistency Issue Inspector
Validates the taxonomy against real exercise data to see what consistency issues actually exist.
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Tuple


class RepositoryFile:
    """Simple representation of a repository file."""
    def __init__(self, path: str, content: str):
        self.path = path
        self.content = content


def render_file_structure(root: str, paths: List[str], sep: str = "/", show_hidden: bool = False) -> str:
    """Build a tree view string representation of a list of file paths."""
    
    tree: Dict[str, Dict] = {}
    for p in paths:
        parts = [part for part in p.split(sep) if part]
        if not show_hidden and any(part.startswith(".") for part in parts):
            continue
        node = tree
        for part in parts:
            node = node.setdefault(part, {})

    def _sort_key(item):
        name, children = item
        return (1 if children == {} else 0, name.lower())  # dirs first

    lines: List[str] = [root]

    def _collect(subtree: Dict[str, Dict], prefix: str = "") -> None:
        items = sorted(subtree.items(), key=_sort_key)
        for idx, (name, children) in enumerate(items):
            connector = "└── " if idx == len(items) - 1 else "├── "
            lines.append(prefix + connector + name)
            if children:
                extension = "    " if idx == len(items) - 1 else "│   "
                _collect(children, prefix + extension)

    _collect(tree)
    return "\n".join(lines)


def render_file_string(root: str, path: str, content: str, line_numbers: bool = True, width: int = 80) -> str:
    """Build a pretty, line-numbered string representation of a file."""
    
    hr = "-" * width
    header = f"{hr}\n{root}/{path}:\n{hr}"

    # Binary data? — just note the size
    if content.startswith("<binary"):
        return f"{header}\n{content}"

    lines: List[str] = content.splitlines()
    if line_numbers and len(lines) <= 50:  # Only show line numbers for shorter files
        w = len(str(len(lines)))
        body = [f"{str(i).rjust(w)} | {line}" for i, line in enumerate(lines, 1)]
    else:
        # For long files, just show first 20 lines
        body = lines[:20]
        if len(lines) > 20:
            body.append(f"... ({len(lines) - 20} more lines)")

    return "\n".join([header, *body])


def load_exercise_data(exercise_path: Path) -> Dict[str, Any]:
    """Load all artifacts for a single exercise."""
    exercise_data = {
        "name": exercise_path.name,
        "problem_statement": "",
        "template_files": [],
        "solution_files": [],
        "test_files": []
    }
    
    # Load problem statement
    problem_statement_path = exercise_path / "problem-statement.md"
    if problem_statement_path.exists():
        exercise_data["problem_statement"] = problem_statement_path.read_text(encoding='utf-8')
    
    # Load template repository
    template_path = exercise_path / "template"
    if template_path.exists():
        exercise_data["template_files"] = load_repository_files(template_path)
    
    # Load solution repository  
    solution_path = exercise_path / "solution"
    if solution_path.exists():
        exercise_data["solution_files"] = load_repository_files(solution_path)
    
    # Load test repository
    tests_path = exercise_path / "tests"
    if tests_path.exists():
        exercise_data["test_files"] = load_repository_files(tests_path)
    
    return exercise_data


def load_repository_files(repo_path: Path) -> List[RepositoryFile]:
    """Load all files from a repository directory into RepositoryFile objects."""
    files = []
    
    if not repo_path.exists():
        return files
    
    # Walk through all files in the repository
    for root, dirs, filenames in os.walk(repo_path):
        # Skip hidden directories and files
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        for filename in filenames:
            if filename.startswith('.'):
                continue
                
            file_path = Path(root) / filename
            relative_path = file_path.relative_to(repo_path)
            
            try:
                # Try to read as text first
                content = file_path.read_text(encoding='utf-8')
                files.append(RepositoryFile(
                    path=str(relative_path),
                    content=content
                ))
            except (UnicodeDecodeError, PermissionError):
                # Binary file or permission issue
                try:
                    size = file_path.stat().st_size
                    files.append(RepositoryFile(
                        path=str(relative_path),
                        content=f"<binary file - {size} bytes>"
                    ))
                except:
                    continue
    
    return files


def analyze_consistency_issues(exercise_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Analyze actual consistency issues in exercise data."""
    issues = []
    
    problem_statement = exercise_data["problem_statement"]
    template_files = exercise_data["template_files"]
    test_files = exercise_data["test_files"]
    
    # Look for Java class definitions mentioned in problem statement
    java_classes_mentioned = extract_java_classes_from_problem(problem_statement)
    java_classes_in_template = extract_java_classes_from_files(template_files)
    
    # Check for missing classes
    for class_name in java_classes_mentioned:
        if class_name not in java_classes_in_template:
            issues.append({
                "type": "MISSING_REQUIRED_ELEMENT",
                "severity": "CRITICAL",
                "description": f"Class '{class_name}' mentioned in problem statement but not found in template",
                "evidence": {
                    "mentioned_in_problem": class_name in problem_statement,
                    "found_in_template": class_name in java_classes_in_template
                }
            })
    
    # Check for template-specific issues
    for template_file in template_files:
        if template_file.path.endswith('.java'):
            file_issues = analyze_java_file_consistency(template_file, problem_statement)
            issues.extend(file_issues)
    
    return issues


def extract_java_classes_from_problem(problem_statement: str) -> List[str]:
    """Extract Java class names mentioned in the problem statement."""
    import re
    
    classes = []
    
    # Look for class mentions in various formats
    patterns = [
        r'class\s+(\w+)',           # "class ClassName"
        r'`(\w+)`',                 # `ClassName` in backticks
        r'implement\s+(\w+)',       # "implement ClassName"
        r'extends\s+(\w+)',         # "extends ClassName"
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, problem_statement, re.IGNORECASE)
        classes.extend(matches)
    
    # Common Java classes that should be filtered out
    java_builtin = {'String', 'Object', 'Integer', 'Boolean', 'List', 'ArrayList', 
                   'LocalTime', 'LocalDate', 'Duration', 'DayOfWeek'}
    
    # Filter out common Java built-ins and duplicates
    unique_classes = list(set([c for c in classes if c not in java_builtin and c[0].isupper()]))
    
    return unique_classes


def extract_java_classes_from_files(files: List[RepositoryFile]) -> Dict[str, str]:
    """Extract Java class definitions from repository files."""
    import re
    
    classes = {}
    
    for file in files:
        if file.path.endswith('.java'):
            # Extract class name from file content
            class_match = re.search(r'(public|abstract)?\s*class\s+(\w+)', file.content)
            if class_match:
                class_name = class_match.group(2)
                classes[class_name] = file.path
    
    return classes


def analyze_java_file_consistency(file: RepositoryFile, problem_statement: str) -> List[Dict[str, Any]]:
    """Analyze consistency issues in a specific Java file."""
    import re
    
    issues = []
    
    # Check if file is just a TODO stub
    if "TODO" in file.content and len(file.content.strip().split('\n')) <= 10:
        issues.append({
            "type": "INCOMPLETE_TEMPLATE",
            "severity": "HIGH", 
            "description": f"Template file {file.path} contains only TODO comments",
            "evidence": {
                "file_content": file.content,
                "line_count": len(file.content.strip().split('\n'))
            }
        })
    
    # Extract class name from file
    class_match = re.search(r'(public|abstract)?\s*class\s+(\w+)', file.content)
    if class_match:
        is_abstract = 'abstract' in class_match.group(0)
        class_name = class_match.group(2)
        
        # Check if problem statement mentions this should be abstract
        problem_mentions_abstract = f"abstract class {class_name}" in problem_statement or f"abstract {class_name}" in problem_statement
        
        if problem_mentions_abstract and not is_abstract:
            issues.append({
                "type": "CLASS_MODIFIER_MISMATCH",
                "severity": "CRITICAL",
                "description": f"Class {class_name} should be abstract according to problem statement",
                "evidence": {
                    "problem_mentions_abstract": problem_mentions_abstract,
                    "template_is_abstract": is_abstract,
                    "file_path": file.path
                }
            })
    
    return issues


def main():
    """Main inspection script - show full content for specific exercise."""
    print("🔍 RAW EXERCISE CONTENT INSPECTOR")
    print("=" * 50)
    
    # Check for exercise name argument
    if len(sys.argv) != 2:
        print("Usage: python inspect_consistency.py <exercise_name>")
        print("\nAvailable exercises:")
        data_dir = Path(__file__).parent.parent / "data"
        if data_dir.exists():
            exercises = []
            for course_dir in data_dir.iterdir():
                if course_dir.is_dir():
                    for exercise_dir in course_dir.iterdir():
                        if exercise_dir.is_dir() and (exercise_dir / "problem-statement.md").exists():
                            exercises.append(exercise_dir.name)
            
            exercises.sort()
            for i, exercise in enumerate(exercises, 1):
                print(f"  {i:2d}. {exercise}")
        return
    
    exercise_name = sys.argv[1]
    data_dir = Path(__file__).parent.parent / "data"
    
    if not data_dir.exists():
        print(f"❌ Data directory not found: {data_dir}")
        return
    
    # Find the specific exercise
    exercise_path = None
    for course_dir in data_dir.iterdir():
        if course_dir.is_dir():
            for exercise_dir in course_dir.iterdir():
                if exercise_dir.is_dir() and exercise_dir.name == exercise_name:
                    if (exercise_dir / "problem-statement.md").exists():
                        exercise_path = exercise_dir
                        break
    
    if not exercise_path:
        print(f"❌ Exercise '{exercise_name}' not found!")
        return
    
    print("=" * 80)
    print(f"EXERCISE: {exercise_path.name}")
    print("=" * 80)
    
    # Load exercise data
    exercise_data = load_exercise_data(exercise_path)
    
    # Show complete problem statement
    print("\n📋 PROBLEM STATEMENT:")
    print("-" * 50)
    print(exercise_data["problem_statement"])
    
    # Show template files
    print(f"\n📂 TEMPLATE FILES ({len(exercise_data['template_files'])} files):")
    print("-" * 50)
    template_java_files = [f for f in exercise_data["template_files"] if f.path.endswith('.java')]
    
    for java_file in template_java_files:
        print(f"\n📄 TEMPLATE: {java_file.path}")
        print("." * 40)
        lines = java_file.content.splitlines()
        for i, line in enumerate(lines, 1):
            print(f"{i:3d}: {line}")
    
    # Show corresponding solution files
    print(f"\n📂 SOLUTION FILES ({len(exercise_data['solution_files'])} files):")
    print("-" * 50)
    solution_java_files = [f for f in exercise_data["solution_files"] if f.path.endswith('.java')]
    
    for java_file in solution_java_files:
        print(f"\n📄 SOLUTION: {java_file.path}")
        print("." * 40)
        lines = java_file.content.splitlines()
        for i, line in enumerate(lines, 1):
            print(f"{i:3d}: {line}")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    main()
