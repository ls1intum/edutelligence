import hashlib
import tempfile
from pathlib import Path
from typing import Optional, cast, Dict, Any

from athena import contextvars

import httpx
from git.repo import Repo

cache_dir = Path(tempfile.mkdtemp())


def _ensure_auth_secret(authorization_secret: Optional[str]) -> str:
    if authorization_secret is None:
        if contextvars.repository_authorization_secret_context_var_empty():
            raise ValueError(
                "Authorization secret for the repository API is not set. Pass authorization_secret to this function or add the X-Repository-Authorization-Secret header to the request from the assessment module manager."
            )
        return cast(str, contextvars.get_repository_authorization_secret_context_var())
    return authorization_secret


def get_repository_files_map(url: str, authorization_secret: Optional[str] = None) -> Dict[str, str]:
    """
    Fetch a repository from Artemis which responds with a JSON map of
    { "<path>": "<content>" } and return it as a dict.
    """
    auth = _ensure_auth_secret(authorization_secret)
    with httpx.Client() as client:
        response = client.get(url, headers={"Authorization": auth})
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Expected JSON object {<path>: <content>} from repository endpoint")
        return {str(k): str(v) for k, v in cast(Dict[str, Any], data).items()}


def _write_files_to_directory(root: Path, files_map: Dict[str, str]) -> None:
    for rel_path, content in files_map.items():
        abs_path = root / rel_path
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(content, encoding="utf-8")


def get_repository(url: str, authorization_secret: Optional[str] = None) -> Repo:
    """
    Retrieve a code repository from the given URL, either from the cache or by
    downloading it, and return a Repo object.
    """

    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    dir_name = url_hash + ".git"
    cache_dir_path = cache_dir / dir_name

    if not cache_dir_path.exists():
        files_map = get_repository_files_map(url, authorization_secret)
        _write_files_to_directory(cache_dir_path, files_map)
        if not (cache_dir_path / ".git").exists():
            repo = Repo.init(cache_dir_path, initial_branch='main')
            # Config username and email to prevent Git errors
            repo.config_writer().set_value("user", "name", "athena").release()
            repo.config_writer().set_value("user", "email", "doesnotexist.athena@cit.tum.de").release()
            repo.git.add(all=True, force=True)
            repo.git.commit('-m', 'Initial commit')

    return Repo(cache_dir_path)