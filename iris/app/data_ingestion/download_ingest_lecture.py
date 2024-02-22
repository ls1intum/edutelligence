import requests
import tempfile

DOWNLOAD_BUFFER_SIZE = 8 * 1024


# TODO: Get correct parameters here
def download_lecture_pdf(
    base_url: str, course_id: int, lecture_id: int, lecture_unit_id: int
) -> tempfile.NamedTemporaryFile:
    """
    Download a single lecture unit from Artemis
    """
    # Send a GET request to the URL TODO: Validate Artemis URL
    artemis_url = (
        f"{base_url}/iris/lecture-slides/{course_id}/{lecture_id}/{lecture_unit_id}"
    )
    response = requests.get(artemis_url, stream=True)
    if response.status_code != 200:
        print(f"Failed to download the file. Status code: {response.status_code}")
        raise ConnectionError

    # Place the PDF into a temporary file
    temp_file = tempfile.NamedTemporaryFile()
    for chunk in response.iter_content(chunk_size=DOWNLOAD_BUFFER_SIZE):
        if chunk:  # filter out keep-alive new chunks
            temp_file.write(chunk)

    # Return the path to the temporary file.
    # File should delete itself when it goes out of scope at the call site
    return temp_file


# CALL THE RIGHT PIPELINE FOR INGESTION OF LECTURE PDF THAT HAS IMAGE INTERPRETATION.
