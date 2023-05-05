import zipfile
from tempfile import NamedTemporaryFile

import httpx

from athena.schemas import ProgrammingSubmission


def get_programming_submission_zip(submission: ProgrammingSubmission) -> zipfile.ZipFile:
    """
    Get the programming submission content, which is a zip file of the code.
    This will download the submission and return a ZipFile object.
    """
    url = submission.repository_url
    with httpx.stream("GET", url) as response:
        response.raise_for_status()
        temp_file = NamedTemporaryFile()
        for chunk in response.iter_bytes():
            temp_file.write(chunk)
        temp_file.flush()
    return zipfile.ZipFile(temp_file.name)
