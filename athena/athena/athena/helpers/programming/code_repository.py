import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, cast, Dict, Any, Union
from pydantic import AnyUrl

from athena import contextvars
from athena.helpers.programming.path_utils import ensure_safe_path

import httpx
from git.repo import Repo

cache_dir = Path(tempfile.mkdtemp())


def _ensure_auth_secret(authorization_secret: Optional[str]) -> str:
    """
    Ensure that an authorization secret is available for repository API access.
    
    Args:
        authorization_secret: Optional authorization secret. If None, attempts to
            retrieve it from context variables.
            
    Returns:
        The authorization secret to use for API requests.
        
    Raises:
        ValueError: If no authorization secret is provided and none is available
            in the context variables.
    """
    if authorization_secret is None:
        if contextvars.repository_authorization_secret_context_var_empty():
            raise ValueError(
                "Authorization secret for the repository API is not set. "
                "Pass authorization_secret to this function or add the "
                "X-Repository-Authorization-Secret header to the request from the assessment module manager."
            )
        return cast(str, contextvars.get_repository_authorization_secret_context_var())
    return authorization_secret


def get_repository_files_map(url: str, authorization_secret: Optional[str] = None) -> Dict[str, str]:
    """
    Fetch a repository from Artemis which responds with a JSON map of
    { "<path>": "<content>" } and return it as a dict.
    """
    auth = _ensure_auth_secret(authorization_secret)
    with httpx.Client(timeout=60) as client:
        response = client.get(url, headers={"Authorization": auth})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected JSON object {<path>: <content>} from repository endpoint")
        return {str(k): str(v) for k, v in cast(Dict[str, Any], data).items()}


def _write_files_to_directory(root: Path, files_map: Dict[str, str]) -> None:
    """
    Write files from a map to a directory structure.
    
    Args:
        root: The root directory to write files to.
        files_map: Dictionary mapping relative file paths to their content.
        
    Note:
        Unsafe paths (those that would escape the root directory or access .git
        internals) are silently skipped.
    """
    root = root.resolve()
    for rel_path, content in files_map.items():
        try:
            candidate = ensure_safe_path(root, rel_path, ignore_git=True)
        except ValueError:
            continue # skip unsafe paths
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(content, encoding="utf-8")


def get_repository(url: Union[str, AnyUrl], authorization_secret: Optional[str] = None) -> Repo:
    """
    Retrieve a code repository from the given URL, either from the cache or by
    downloading it, and return a Repo object.
    """

    url_str = str(url)
    url_hash = hashlib.md5(url_str.encode("utf-8")).hexdigest()
    dir_name = url_hash + ".git"
    cache_dir_path = cache_dir / dir_name

    if not cache_dir_path.exists():
        files_map = get_repository_files_map(url_str, authorization_secret)
        # Build in a unique temp dir and atomically rename into place.
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"{dir_name}.tmp.", dir=str(cache_dir)))
        try:
            _write_files_to_directory(tmp_dir, files_map)
            if not (tmp_dir / ".git").exists():
                repo = Repo.init(tmp_dir, initial_branch='main')
                # Config username and email to prevent Git errors
                repo.config_writer().set_value("user", "name", "athena").release()
                repo.config_writer().set_value("user", "email", "doesnotexist.athena@cit.tum.de").release()
                repo.git.add(all=True, force=True)
                repo.git.commit('-m', 'Initial commit')
            # Atomic within the same filesystem
            try:
                os.rename(tmp_dir, cache_dir_path)
            except FileExistsError:
                pass
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return Repo(cache_dir_path)
