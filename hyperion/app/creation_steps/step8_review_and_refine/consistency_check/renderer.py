from typing import List, Optional, Tuple, Union, Dict

from langchain_core.runnables import RunnableLambda


def render_repository(
    files: List[Dict[str, str]],
    *,
    sep: str = "/",
    show_hidden: bool = False,
    repo_name: Optional[str] = None,
    width: int = 80,
) -> str:
    """Render a complete textual snapshot of a repository: first the tree,
    then the contents of every file.

    Args:
        files (List[RepositoryFile]): The repository's files (path + content pairs).
        sep (str, optional): Path separator used in the paths. Defaults to "/".
        show_hidden (bool, optional): Include dot-files if True. Defaults to False.
        repo_name (Optional[str], optional): Optional heading to precede this repository in multi-repo dumps.
                                             Defaults to None.
        width (int, optional): Horizontal-rule width for `render_file_string`. Defaults to 80.

    Returns:
        str: A single, ready-to-print string.
    """

    is_problem_statement = repo_name == "Problem Statement"

    repo_name_in_snake_case = (
        repo_name.replace(" ", "_").lower() if repo_name else "repository"
    ) if not is_problem_statement else None

    # 1) tree view
    if not is_problem_statement:
        paths = [file["path"] for file in files]
        tree_part = render_file_structure(
            repo_name_in_snake_case, paths, sep=sep, show_hidden=show_hidden
        )

    # 2) individual files (alphabetical for determinism)
    file_parts = [
        render_file_string(
            repo_name_in_snake_case, file["path"], file["content"], width=width
        )
        for file in sorted(files, key=lambda x: x["path"])
    ]
    body = "\n\n".join(file_parts)

    if repo_name:
        headline = f"\n===== {repo_name} =====\n"
        return headline + tree_part + "\n\n" + body
    return tree_part + "\n\n" + body


def render_file_structure(
    root: Optional[str], paths: List[str], sep: str = "/", show_hidden: bool = False
) -> str:
    """Build a tree view string representation of a list of file paths.

    Args:
        root (Optional[str]): The root directory name to display at the top of the tree.
        paths (List[str]): List of file paths to visualize. These paths do not have to exist on disk.
        sep (str, optional): Path separator used in `paths`. Defaults to "/".
        show_hidden (bool, optional): Include hidden files (starting with a dot) if True. Defaults to False.

    Returns:
        str: The complete tree visualization.
    """

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

    lines: List[str] = [root] if root else []

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


def render_file_string(
    root: Optional[str],
    path: str,
    content: Union[str, bytes],
    *,
    line_numbers: bool = True,
    width: int = 80,
) -> str:
    """Build a pretty, line-numbered string representation of a file.

    Args:
        root (Optional[str]): The root directory name to display at the top of the file.
        path (str): The file path to display in the header.
        content (Union[str, bytes]): The file content to display.
        line_numbers (bool, optional): Whether to show line numbers. Defaults to True.
        width (int, optional): The width of the output. Defaults to 80.

    Returns:
        str: The formatted file representation.
    """

    hr = "-" * width
    header = f"{hr}\n{root}/{path}:\n{hr}" if root else f"{hr}\n{path}:\n{hr}"

    # Binary data? — just note the size
    if isinstance(content, bytes):
        return f"{header}\n<binary file - {len(content)} bytes>"

    lines: List[str] = content.splitlines()
    if line_numbers:
        w = len(str(len(lines)))
        body = [f"{str(i).rjust(w)} | {line}" for i, line in enumerate(lines, 1)]
    else:
        body = lines

    return "\n".join([header, *body])


def context_renderer(*filter_keys: List[str]) -> RunnableLambda:
    def renderer(input_data: Dict) -> str:
        """Filter the context to only include specified keys."""
        repos: List[Tuple[str, List[Dict[str, str]]]] = []
        if "problem_statement" in filter_keys:
            repos.append(
                (
                    "Problem Statement",
                    [
                        {
                            "path": "problem_statement.md",
                            "content": input_data["problem_statement"],
                        }
                    ],
                )
            )
        if "template_repository" in filter_keys:
            repos.append(("Template Repository", input_data["template_repository"]))
        if "solution_repository" in filter_keys:
            repos.append(("Solution Repository", input_data["solution_repository"]))
        if "test_repository" in filter_keys:
            repos.append(("Test Repository", input_data["test_repository"]))

        return {
            "rendered_context": "\n\n".join(
                render_repository(files, repo_name=repo_name)
                for repo_name, files in repos
            )
        }

    return RunnableLambda(renderer, name="context_renderer")
