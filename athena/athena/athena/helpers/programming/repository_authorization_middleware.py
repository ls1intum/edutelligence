from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable, Awaitable

class RepositoryAuthorizationMiddleware(BaseHTTPMiddleware):
    """
    Capture the X-Repository-Authorization-Secret header from the assessment module manager and store it in the app state.
    This way, we avoid having to store the secret in the environment twice (once in the assessment module manager, once in the module).
    Instead, we only store it in the assessment module manager and pass it to the module via this middleware.
    """
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        x_repository_auth_secret = request.headers.get("X-Repository-Authorization-Secret")

        if x_repository_auth_secret:
            request.app.state.repository_authorization_secret = x_repository_auth_secret

        response = await call_next(request)
        return response


def init_repo_auth_middleware(app: FastAPI):
    app.add_middleware(RepositoryAuthorizationMiddleware)

    def init_repo_auth_secret():
        app.state.repository_authorization_secret = None
    app.on_event("startup")(init_repo_auth_secret)
