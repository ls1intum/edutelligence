"""Server-side DuckDuckGo searches for coding agents, without provider tokens."""

import asyncio
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

import httpx

SEARCH_URL = "https://html.duckduckgo.com/html/"
_MAX_RESPONSE_BYTES = 1_000_000
_SEARCH_SLOTS = asyncio.Semaphore(4)


class SearchUnavailable(Exception):
    """The search provider could not return usable results."""


def _result_url(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    try:
        parsed = urlsplit(href)
        if parsed.path == "/l/" and parsed.hostname in (None, "duckduckgo.com", "html.duckduckgo.com"):
            href = parse_qs(parsed.query).get("uddg", [""])[0]
            parsed = urlsplit(href)
    except ValueError:
        return ""
    if len(href) > 2048:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return ""
    if parsed.hostname == "duckduckgo.com" or parsed.hostname.endswith(".duckduckgo.com"):
        return ""
    return href


class _ResultsParser(HTMLParser):
    """Extract titles, target URLs and snippets from DuckDuckGo's HTML page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self.no_results = False
        self._field = ""
        self._tag = ""
        self._text: list[str] = []
        self._url = ""
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if "no-results" in classes:
            self.no_results = True
        if tag == "a" and "result__a" in classes:
            self._field = "title"
            self._current = None
            self._url = _result_url(attributes.get("href") or "")
        elif "result__snippet" in classes:
            self._field = "snippet"
        else:
            return
        self._tag = tag
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._field:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._field or tag != self._tag:
            return
        text = " ".join("".join(self._text).split())
        if self._field == "title" and self._url and text:
            self._current = {"title": text[:300], "url": self._url, "snippet": ""}
            self.results.append(self._current)
        elif self._field == "snippet" and self._current is not None:
            self._current["snippet"] = text[:1000]
        self._field = ""


async def search_web(query: str, max_results: int) -> list[dict[str, str]]:
    """Search from the server; only the fixed search host is contacted.

    Standard HTTP(S)_PROXY environment variables are honored by httpx, so
    operators can send the server's search traffic through their usual proxy.
    Result URLs are returned as data and never fetched here.

    Raises:
        SearchUnavailable: On network errors, rate limits, or challenge pages.
    """
    try:
        # Bound both concurrency and total time, including waiting for a slot.
        async with asyncio.timeout(20), _SEARCH_SLOTS:
            async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
                async with client.stream(
                    "GET",
                    SEARCH_URL,
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (compatible; LogosSearch)"},
                ) as response:
                    if response.status_code != 200:
                        raise SearchUnavailable("DuckDuckGo is unavailable or rate limiting searches. Try again later.")
                    page = bytearray()
                    async for chunk in response.aiter_bytes():
                        page.extend(chunk)
                        if len(page) > _MAX_RESPONSE_BYTES:
                            raise SearchUnavailable("DuckDuckGo returned an oversized response.")
    except (httpx.HTTPError, TimeoutError) as exc:
        raise SearchUnavailable("The search request failed or timed out. Try again later.") from exc

    html = page.decode("utf-8", errors="replace")
    if "anomaly.js" in html or "anomaly-modal" in html:
        raise SearchUnavailable("DuckDuckGo requires a bot challenge. Try again later.")
    parser = _ResultsParser()
    parser.feed(html)
    if not parser.results and not parser.no_results:
        raise SearchUnavailable("DuckDuckGo returned an unrecognized search page.")
    seen: set[str] = set()
    results = []
    for result in parser.results:
        if result["url"] not in seen:
            seen.add(result["url"])
            results.append(result)
        if len(results) >= max_results:
            break
    return results
