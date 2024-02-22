import tempfile
import zipfile

import requests

DOWNLOAD_BUFFER_SIZE = 8 * 1024


def download_repository_zip(url) -> tempfile.NamedTemporaryFile:
    """
    Downloads a zip file from a given URL and saves it to the specified path.

    :param url: The URL of the zip file to download.
    :param save_path: The path (including the file name) where the zip file will be saved.
    """
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        # Open the file in binary write mode and write the content of the response
        temp_file = tempfile.NamedTemporaryFile()
        for chunk in response.iter_content(chunk_size=DOWNLOAD_BUFFER_SIZE):
            if chunk:  # filter out keep-alive new chunks
                temp_file.write(chunk)
        # Return the path to the temporary file.
        # File should delete itself when it goes out of scope at the call site
        return temp_file


def unzip(zip_file_path: str, directory_to: str):
    """
    Extracts the zip file to the specified directory.
    """
    # Open the zip file in read mode and extract all contents
    with zipfile.ZipFile(zip_file_path) as zip_ref:
        zip_ref.extractall(directory_to)
