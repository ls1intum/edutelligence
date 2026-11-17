"""Normalisation of the base URLs that Artemis installations send to Iris."""

from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_base_url(base_url: str | None) -> str | None:
    """Reduce a base URL to the form in which two spellings of the same one are equal.

    Scheme and host are compared case-insensitively, a port that is the default of the
    scheme and trailing slashes of the path make no difference. A value that is not a plain
    http(s) base URL, that is without a host, or that carries user information, a query or
    a fragment, has no normal form.

    :param base_url: the base URL as it was sent or configured
    :return: the normal form, or None if the value is not a usable base URL
    """
    if base_url is None:
        return None
    parts = urlsplit(base_url.strip())
    if parts.scheme.lower() not in _DEFAULT_PORTS or not parts.hostname:
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
