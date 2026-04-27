from enum import Enum


class VideoSourceType(str, Enum):
    """How a lecture video is hosted, driving download-step selection.

    Backward compatibility: missing / null on the wire is treated as TUM_LIVE
    by consumers so that older Artemis deployments continue to work.
    """

    TUM_LIVE = "TUM_LIVE"
    YOUTUBE = "YOUTUBE"
