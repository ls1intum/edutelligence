"""Process-local ownership of worker model lanes during an internal benchmark."""

from collections.abc import Callable
from threading import RLock


class BenchmarkReservations:
    """Keep production traffic off a benchmark's lanes, including between batch runs.

    Ownership follows the provider/model pair so it survives cold loading and
    lane replacement. Only request IDs registered after internal authentication
    can use it. Other models on the same worker remain available.
    """

    def __init__(self):
        self._owners: dict[tuple[int, str], int] = {}
        self._request_guards: dict[str, Callable[[], bool]] = {}
        self._draining: dict[str, tuple[int, str, int]] = {}
        self._requests: dict[str, tuple[int, str, int]] = {}
        self._lock = RLock()

    def reserve(self, provider_id: int, model: str, job_id: int, *, draining: dict[str, str] | None = None) -> None:
        with self._lock:
            owner = self._owners.get((provider_id, model))
            if owner is not None and owner != job_id:
                raise RuntimeError("The model lanes are already reserved for another benchmark")
            self._owners[provider_id, model] = job_id
            for request_id, request_model in (draining or {}).items():
                self._draining[request_id] = (provider_id, request_model, job_id)

    def owner(self, provider_id: int, model: str, *, exact: bool = False) -> int | None:
        with self._lock:
            return self._owners.get((provider_id, model), None if exact else self._owners.get((provider_id, "*")))

    def register_request(
        self, provider_id: int, model: str, job_id: int, request_id: str, *, guard: Callable[[], bool] | None = None
    ) -> None:
        with self._lock:
            if self._owners.get((provider_id, model)) != job_id:
                raise RuntimeError("The benchmark no longer owns the model lanes")
            self._requests[request_id] = (provider_id, model, job_id)
            if guard is not None:
                self._request_guards[request_id] = guard

    def allows(self, provider_id: int, model: str, request_id: str | None = None) -> bool:
        with self._lock:
            guard = self._request_guards.get(request_id)
            if guard is not None and not guard():
                return False
            owner = self._owners.get((provider_id, model), self._owners.get((provider_id, "*")))
            return (
                owner is None
                or self._requests.get(request_id) == (provider_id, model, owner)
                or self._draining.get(request_id) == (provider_id, model, owner)
            )

    def finish_request(self, request_id: str) -> None:
        with self._lock:
            self._request_guards.pop(request_id, None)
            self._requests.pop(request_id, None)
            self._draining.pop(request_id, None)

    def release(self, job_id: int) -> None:
        with self._lock:
            self._draining = {key: value for key, value in self._draining.items() if value[2] != job_id}
            self._owners = {key: owner for key, owner in self._owners.items() if owner != job_id}
            self._requests = {key: value for key, value in self._requests.items() if value[2] != job_id}
            self._request_guards = {key: guard for key, guard in self._request_guards.items() if key in self._requests}


benchmark_reservations = BenchmarkReservations()
