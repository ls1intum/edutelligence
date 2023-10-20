import hashlib
import tempfile
from pathlib import Path
from zipfile import ZipFile

import httpx
from git.repo import Repo

cache_dir = Path(tempfile.mkdtemp())


def get_repository_zip(url: str) -> ZipFile:
    """
    Retrieve a zip file of a code repository from the given URL, either from
    the cache or by downloading it, and return a ZipFile object.
    """
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    file_name = url_hash + ".zip"
    cache_file_path = cache_dir / file_name

    if not cache_file_path.exists():
        with httpx.stream("GET", url) as response:
            response.raise_for_status()
            with open(cache_file_path, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)

    return ZipFile(cache_file_path)


def get_repository(url: str) -> Repo:
    """
    Retrieve a code repository from the given URL, either from the cache or by
    downloading it, and return a Repo object.
    """

    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    dir_name = url_hash + ".git"
    cache_dir_path = cache_dir / dir_name

    if not cache_dir_path.exists():
        repo_zip = get_repository_zip(url)
        repo_zip.extractall(cache_dir_path)
        if not (cache_dir_path / ".git").exists():
            repo = Repo.init(cache_dir_path, initial_branch='main')
            repo.git.add(all=True, force=True)
            repo.git.commit('-m', 'Initial commit')

    return Repo(cache_dir_path)