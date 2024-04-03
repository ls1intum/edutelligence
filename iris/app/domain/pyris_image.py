from datetime import datetime


class PyrisImage:
    """
    Represents an image from the Pyris dataset
    """

    prompt: str
    base64: str
    timestamp: datetime
    mime_type: str = "jpeg"
    raw_data: any = None

    def __init__(
        self,
        prompt: str,
        base64: str,
        timestamp: datetime,
        mime_type: str = "jpeg",
        raw_data: any = None,
    ):
        self.prompt = prompt
        self.base64 = base64
        self.timestamp = timestamp
        self.raw_data = raw_data
        self.mime_type = mime_type
