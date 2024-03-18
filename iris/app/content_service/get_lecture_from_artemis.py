import requests
import tempfile

DOWNLOAD_BUFFER_SIZE = 8 * 1024


def download_lecture_pdf(base_url: str, unit_id: int) -> tempfile.NamedTemporaryFile:
    """
    Download a single lecture unit from Artemis
    """
    artemis_url = f"{base_url}/api/v1/public/pyris/data/lecture-units/{unit_id}/pdf"
    response = requests.get(artemis_url, stream=True)
    if response.status_code != 200:
        print(f"Failed to download the file. Status code: {response.status_code}")
        raise ConnectionError

    temp_file = tempfile.NamedTemporaryFile()
    for chunk in response.iter_content(chunk_size=DOWNLOAD_BUFFER_SIZE):
        if chunk:
            temp_file.write(chunk)
    return temp_file
