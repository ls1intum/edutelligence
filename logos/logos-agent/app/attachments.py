"""The images a request carries, fetched so the agent can look at them.

An issue that says "the statistics page looks wrong" and attaches a
screenshot *is* that screenshot. The agent phase has no network, so it met
one of those with `WebFetch`, was refused, read code for an hour and changed
nothing — the request had no text to work from and the picture that was the
whole description stayed on GitHub.

So the runner fetches them. It holds the token and the egress the sandbox
deliberately does not, writes the images into the session's own artefact
directory, and tells the agent where they are. Claude Code reads a local
image perfectly well; it just cannot go and get one.

Bounded on purpose: a handful of images, a few megabytes each, and only what
looks like an image when it arrives. A request is a thing a stranger can
write, and this is the one place where its text turns into fetches.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# How much of a request's imagery is worth carrying. Beyond this a session is
# reading pictures instead of code.
MAX_IMAGES = 5
MAX_BYTES = 8 * 1024 * 1024

# Markdown images, HTML `<img src>`, and the bare attachment links GitHub
# produces when somebody pastes a screenshot into a comment.
_MARKDOWN = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)")
_HTML = re.compile(r"<img[^>]+src=[\"'](https?://[^\"']+)[\"']", re.IGNORECASE)
_BARE = re.compile(r"https?://(?:user-images\.githubusercontent\.com|github\.com/user-attachments/assets)/[^\s\"'<>)]+")

# What a fetched attachment may be. The runner is asking on behalf of an
# unattended agent, so anything that is not an image is not worth having.
_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def urls_in(text: str) -> list[str]:
    """Every image URL a request refers to, in the order it mentions them."""
    found: list[str] = []
    for pattern in (_MARKDOWN, _HTML, _BARE):
        for url in pattern.findall(text or ""):
            cleaned = url.rstrip(".,)")
            if cleaned not in found:
                found.append(cleaned)
    return found[:MAX_IMAGES]


def name_for(index: int, content_type: str) -> str:
    """What a fetched image is called in the artefact directory."""
    suffix = _IMAGE_TYPES.get(content_type.split(";")[0].strip().lower(), "")
    return f"{index:02d}{suffix}" if suffix else ""


def is_image(content_type: str) -> bool:
    return content_type.split(";")[0].strip().lower() in _IMAGE_TYPES


def directory(artifacts: Path) -> Path:
    return artifacts / "attachments"


__all__ = ["MAX_BYTES", "MAX_IMAGES", "directory", "is_image", "name_for", "urls_in"]
