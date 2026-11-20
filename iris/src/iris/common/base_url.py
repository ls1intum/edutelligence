"""Normalisation of the base URLs that Artemis installations send to Iris."""

import ipaddress
import re
from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}

# An authority with a bracketed host is exactly "[address]" with an optional ":port". The parser of
# some Python versions reads "[::1]]" as "[::1]", so the shape is checked here instead.
_BRACKETED_AUTHORITY = re.compile(r"\[([0-9A-Fa-f:.]+)\](?::[0-9]*)?")


def normalize_base_url(base_url: str | None) -> str | None:
    """Reduce a base URL to the form in which two spellings of the same one are equal.

    Scheme and host are compared case-insensitively, a port that is the default of the
    scheme and trailing slashes of the path make no difference. A value that is not a plain
    http(s) base URL, that is without a host, or that carries user information, a query, a
    fragment, any whitespace or control character, or a host that cannot be parsed, has no
    normal form. The URL parser drops some of these characters silently, which would let two
    different strings pass for one URL.

    :param base_url: the base URL as it was sent or configured
    :return: the normal form, or None if the value is not a usable base URL
    """
    if base_url is None or any(
        character.isspace() or ord(character) < 32 or ord(character) == 127
        for character in base_url
    ):
        return None
    try:
        parts = urlsplit(base_url)
    except ValueError:
        # for example an unmatched or invalid bracketed host such as "https://[" or "https://[x]"
        return None
    if parts.scheme.lower() not in _DEFAULT_PORTS or not parts.hostname:
        return None
    if "[" in parts.netloc or "]" in parts.netloc:
        bracketed = _BRACKETED_AUTHORITY.fullmatch(parts.netloc)
        if bracketed is None:
            return None
        try:
            ipaddress.IPv6Address(bracketed.group(1))
        except ValueError:
            return None
    if parts.username is not None or parts.password is not None:
        return None
    if parts.query or parts.fragment or "?" in base_url or "#" in base_url:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        host = f"{host}:{port}"
    path = parts.path.rstrip("/")
    return f"{scheme}://{host}{path}"
