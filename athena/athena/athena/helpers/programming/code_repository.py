import hashlib
import tempfile
from pathlib import Path
from typing import Optional, cast
from zipfile import ZipFile

from athena import contextvars

import httpx
from git.repo import Repo

cache_dir = Path(tempfile.mkdtemp())


def get_repository_zip(url: str, authorization_secret: Optional[str] = None) -> ZipFile:
    """
    Retrieve a zip file of a code repository from the given URL, either from
    the cache or by downloading it, and return a ZipFile object.
    Optional: Authorization secret for the API. If omitted, it will be auto-determined given the request session.
    """
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    file_name = url_hash + ".zip"
    cache_file_path = cache_dir / file_name

    if not cache_file_path.exists():
        if authorization_secret is None:
            if contextvars.repository_authorization_secret_context_var_empty():
                raise ValueError("Authorization secret for the repository API is not set. Pass authorization_secret to this function or add the X-Repository-Authorization-Secret header to the request from the assessment module manager.")
            authorization_secret = contextvars.get_repository_authorization_secret_context_var()
        with httpx.stream("GET", url, headers={ "Authorization": cast(str, authorization_secret) }) as response:
            response.raise_for_status()
            with open(cache_file_path, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)

    return ZipFile(cache_file_path)


def get_repository(url: str, authorization_secret: Optional[str] = None) -> Repo:
    """
    Retrieve a code repository from the given URL, either from the cache or by
    downloading it, and return a Repo object.
    """

    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    dir_name = url_hash + ".git"
    cache_dir_path = cache_dir / dir_name

    if not cache_dir_path.exists():
        repo_zip = get_repository_zip(url, authorization_secret)
        repo_zip.extractall(cache_dir_path)
        if not (cache_dir_path / ".git").exists():
            repo = Repo.init(cache_dir_path, initial_branch='main')
            # Config username and email to prevent Git errors
            repo.config_writer().set_value("user", "name", "athena").release()
            repo.config_writer().set_value("user", "email", "doesnotexist.athena@cit.tum.de").release()
            repo.git.add(all=True, force=True)
            repo.git.commit('-m', 'Initial commit')

    return Repo(cache_dir_path)