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

import ipaddress
import logging
import re
from pathlib import Path
from urllib.parse import urlsplit

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


# Where a request's images may come from. This is not a nicety: the text is
# written by whoever opened the issue, and every URL in it is a URL the
# runner would otherwise connect to while holding a GitHub token — at a host
# of the author's choosing, from inside the network the orchestrator and the
# database live on. So only GitHub's own attachment origins are followed,
# and the token only ever goes to GitHub itself.
_ATTACHMENT_HOSTS = frozenset({"user-images.githubusercontent.com", "raw.githubusercontent.com"})
_ATTACHMENT_PATHS = ("/user-attachments/assets/",)
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com", "api.github.com"})
_ASSET_PATH = re.compile(r"^/[^/]+/[^/]+/assets/", re.IGNORECASE)


def from_github(url: str) -> bool:
    """Whether this is an image GitHub itself is serving.

    Anything else is a stranger's host named in a stranger's issue.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host in _ATTACHMENT_HOSTS or host.endswith(".githubusercontent.com"):
        return True
    if host in _GITHUB_HOSTS:
        return parsed.path.startswith(_ATTACHMENT_PATHS) or bool(_ASSET_PATH.match(parsed.path))
    return False


def may_carry_the_token(url: str) -> bool:
    """Whether our credential may be sent to this hop.

    GitHub answers an attachment link with a redirect to signed storage, and
    a signed URL carries its own authorisation. Ours has no business there —
    and on any host that is not GitHub's, no business at all.
    """
    parsed = urlsplit(url)
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in _GITHUB_HOSTS


def is_public(url: str) -> bool:
    """Whether a redirect may be followed at all.

    A hop that names a bare host or a private address is not a picture on
    the internet; it is the runner being pointed at its own network.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    try:
        return not ipaddress.ip_address(host).is_private
    except ValueError:
        return "." in host and not host.endswith(".local")


def urls_in(text: str) -> list[str]:
    """Every image URL a request refers to that GitHub itself serves.

    In the order the request mentions them, not in the order the patterns
    happen to run: the files are numbered from this list and the prompt
    lists them by that number, so "the first screenshot" has to mean the
    first one in the text — even in a comment that mixes an `<img>` tag with
    a markdown image.
    """
    seen: set[str] = set()
    found: list[tuple[int, str]] = []
    for pattern in (_MARKDOWN, _HTML, _BARE):
        for match in pattern.finditer(text or ""):
            url = (match.group(1) if match.groups() else match.group(0)).rstrip(".,)")
            if url in seen or not from_github(url):
                continue
            seen.add(url)
            found.append((match.start(), url))
    # Cut after ordering rather than during: which five a request gets is
    # its first five, whichever notation they were written in.
    return [url for _, url in sorted(found)[:MAX_IMAGES]]


def name_for(index: int, content_type: str) -> str:
    """What a fetched image is called in the artefact directory."""
    suffix = _IMAGE_TYPES.get(content_type.split(";")[0].strip().lower(), "")
    return f"{index:02d}{suffix}" if suffix else ""


def is_image(content_type: str) -> bool:
    return content_type.split(";")[0].strip().lower() in _IMAGE_TYPES


def directory(artifacts: Path) -> Path:
    return artifacts / "attachments"


__all__ = [
    "MAX_BYTES",
    "MAX_IMAGES",
    "directory",
    "from_github",
    "is_image",
    "is_public",
    "may_carry_the_token",
    "name_for",
    "urls_in",
]
