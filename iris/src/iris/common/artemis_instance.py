from urllib.parse import urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}


def canonical_artemis_base_url(url: str | None) -> str:
    """Return the canonical form of an Artemis base URL, used as its instance identity.

    Several Artemis instances may share one Weaviate, and their course and post ids
    overlap. Everything Course Memory stores, looks up or deletes is therefore scoped by
    this string, so two spellings of the same instance (``https://Artemis.example/`` and
    ``https://artemis.example``) must map to one value: the scheme and host are
    lowercased, a default port and trailing slashes are dropped, and the path is kept.

    The identity must not change while entries exist; see
    ``COURSE_MEMORY_ARTEMIS_INTEGRATION.md`` for changing ``server.url``.

    Raises:
        ValueError: if the URL is missing, blank, not http(s) or has no host.
    """
    if url is None or not url.strip():
        raise ValueError("an Artemis base URL is required")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS or not parts.hostname:
        raise ValueError(f"not an http(s) Artemis base URL: {url!r}")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    netloc = (
        host if port is None or port == _DEFAULT_PORTS[scheme] else f"{host}:{port}"
    )
    path = parts.path.rstrip("/")
    return f"{scheme}://{netloc}{path}"
