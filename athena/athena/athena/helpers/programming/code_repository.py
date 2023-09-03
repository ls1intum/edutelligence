import hashlib
import tempfile
from pathlib import Path
from typing import Optional, cast
from zipfile import ZipFile

import athena # for importing athena.app (which is not directly possible because of circular imports)
from athena.logger import logger

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
            # auto-determine from FastAPI app state
            if athena.app.state.repository_authorization_secret is None:
                raise ValueError("Authorization secret for the repository API is not set. Pass authorization_secret to this function or add the X-Repository-Authorization-Secret header to the request from the assessment module manager.")
            authorization_secret = athena.app.state.repository_authorization_secret
        logger.info("app.state: %s", athena.app.state)
        logger.info("headers: %s", { "Authorization": cast(str, authorization_secret) })
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
            repo.index.add(repo.untracked_files)
            repo.index.commit("Initial commit")

    return Repo(cache_dir_path)