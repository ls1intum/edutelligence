import os

from contextlib import contextmanager
from collections.abc import Iterator
from typing import List, Dict, Optional, Callable, Tuple

from git import Remote
from git.repo import Repo
from langchain_community.document_loaders import GitLoader

from athena import GradingCriterion

def load_files_from_repo(repo: Repo, file_filter: Optional[Callable[[str], bool]] = None) -> Dict[str, str]:
    return {
        doc.metadata['file_path']: doc.page_content
        for doc in GitLoader(repo_path=str(repo.working_tree_dir), file_filter=file_filter).load()
    }


def merge_repos_by_filepath(*repos: Repo, file_filter: Optional[Callable[[str], bool]] = None) -> Iterator[Tuple[str, List[Optional[str]]]]:
    docs = [load_files_from_repo(repo, file_filter) for repo in repos]
    files = {file for doc in docs for file in doc}

    for file in files:
        yield (file, [doc.get(file) for doc in docs])


def format_grading_instructions(grading_instructions: Optional[str], grading_criteria: Optional[List[GradingCriterion]]) -> Optional[str]:
    """Formats grading instructions and the grading criteria with nested structured grading instructions into a single string.

    Args:
        grading_instructions (Optional[str]): Grading instructions
        grading_criteria (Optional[List[GradingCriterion]]): Grading criteria with nested structured grading instructions

    Returns:
        Optional[str]: Formatted grading instructions or None if no grading instructions or grading criteria are provided
    """

    if not grading_instructions and not grading_criteria:
        return None

    result = ""
    if grading_instructions:
        result += grading_instructions + "\n\n"

    if grading_criteria:
        for grading_criterion in grading_criteria:
            result += f'Criterion > "{(grading_criterion.title or "Unnamed criterion")}":\n'
            for grading_instruction in grading_criterion.structured_grading_instructions:
                result += f'  - grading_instruction_id={grading_instruction.id} > "{grading_instruction.feedback}": ('
                if grading_instruction.usage_count > 0:
                    result += f'can be used {grading_instruction.usage_count} times in total'
                else:
                    result += "can be used unlimited times"
                result += f', gives {grading_instruction.credits} credits for "{grading_instruction.grading_scale}" grading scale, '
                result += f'usage description: "{grading_instruction.instruction_description}")\n'
            result += "\n"

    return result.strip()


def add_line_numbers(content: str) -> str:
    lines = content.splitlines()
    line_number_max_length = len(str(len(lines)))
    return "\n".join(
        f"{str(line_number).rjust(line_number_max_length)} {line}" 
        for line_number, line 
        in enumerate(lines)
    )


def get_programming_language_file_extension(programming_language: str) -> str | None:
    # JAVA, C, OCAML, HASKELL, PYTHON, SWIFT, VHDL, ASSEMBLER, EMPTY, KOTLIN
    file_extensions = {
        "JAVA": ".java",
        "C": ".c",
        "OCAML": ".ml",
        "HASKELL": ".hs",
        "PYTHON": ".py",
        "SWIFT": ".swift",
        "VHDL": ".vhd",
        "ASSEMBLER": ".asm",
        "KOTLIN": ".kt",
    }
    return file_extensions.get(programming_language.upper())


@contextmanager
def temporary_remote(remote_name: str, repo: Repo, remote_url: str) -> Iterator[Optional[Remote]]:
    """Context manager for temporarily adding a remote to a Git repository.
    
    Args:
        remote_name (str): The name of the remote
        repo (Repo): The repository to add the remote to
        remote_url (str): The URL of the remote
    """
    try:
        remote = repo.remote(remote_name)
        yield remote
    except ValueError:
        remote = repo.create_remote(remote_name, remote_url)
        remote.fetch()
        yield remote
        repo.delete_remote(remote)


# pylint: disable=too-many-positional-arguments
def get_diff(src_repo: Repo, 
             dst_repo: Repo, 
             src_prefix: str = "a",
             dst_prefix: str = "b",
             file_path: Optional[str] = None,
             name_only: bool = False,
             branch: str = "main", 
             remote_name: str = "diff_target") -> str:
    """Get the diff between two branches of two Git repositories.

    Args:
        src_repo (Repo): Repository to diff from
        dst_repo (Repo): Repository to diff to
        src_prefix (str, optional): Prefix for the source files. Defaults to "a".
        dst_prefix (str, optional): Prefix for the destination files. Defaults to "b".
        file_path (Optional[str], optional): Path to the file(s), supports glob patterns. Defaults to None.
        name_only (bool, optional): Only show names of changed files. Defaults to False.
        branch (str, optional): Branch to diff. Defaults to "main".
        remote_name (str, optional): Name of the remote to use. Defaults to "diff_target".

    Returns:
        str: The diff between the two branches
    """

    # Check if we are diffing a specific file
    if file_path is not None and "*" not in file_path:
        specific_file_path = os.path.join(str(src_repo.working_tree_dir), file_path)
        if not os.path.exists(specific_file_path):
            # Change error from 'No such file or directory' to something more meaningful (non-standard diff output)
            return f"- {src_prefix}/{file_path} does not exist.\n+ {dst_prefix}/{file_path} has been added."

    with temporary_remote(remote_name, src_repo, str(dst_repo.working_tree_dir)):
        diff = src_repo.git.diff(branch, f"{remote_name}/{branch}", f"--src-prefix={src_prefix}/", f"--dst-prefix={dst_prefix}/", file_path, name_only=name_only)
    return diff
