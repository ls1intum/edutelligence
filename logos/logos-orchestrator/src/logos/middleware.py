"""ASGI middleware for the orchestrator's HTTP surface."""


class APIPrefixStripperMiddleware:
    """Strip a leading `/api` from incoming HTTP and WebSocket paths.

    Lets the UI namespace all of its calls under `/api/*` so a single Traefik
    route handles every UI-internal endpoint, while existing bare paths
    (workernode protocol, public `/v1`/`/openai`/`/jobs`, `/docs`, `/metrics`)
    still resolve unchanged.
    """

    def __init__(self, app, prefix: str = "/api") -> None:
        self.app = app
        self.prefix = prefix.rstrip("/")
        self._prefix_bytes = self.prefix.encode("ascii")

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == self.prefix or path.startswith(self.prefix + "/"):
                new_scope = dict(scope)
                new_scope["path"] = path[len(self.prefix) :] or "/"
                raw = scope.get("raw_path")
                if isinstance(raw, bytes) and raw.startswith(self._prefix_bytes):
                    rest = raw[len(self._prefix_bytes) :]
                    q = rest.find(b"?")
                    path_part = rest[:q] if q >= 0 else rest
                    query_part = rest[q:] if q >= 0 else b""
                    new_scope["raw_path"] = (path_part or b"/") + query_part
                scope = new_scope
        await self.app(scope, receive, send)
