"""Process-local ownership of worker model lanes during an internal benchmark."""

from asyncio import Future
from collections.abc import Callable
from threading import RLock


class BenchmarkReservations:
    """Keep production traffic off a benchmark's lanes, including between batch runs.

    Ownership follows the provider/model pair so it survives cold loading and
    lane replacement. Already admitted requests drain before benchmark traffic
    starts. New requests require internal authentication. Other models on the
    same worker remain available.
    """

    def __init__(self):
        self._owners: dict[tuple[int, str], int] = {}
        self._requests: dict[str, tuple[int, str, int]] = {}
        self._admitted: dict[str, tuple[int, str]] = {}
        self._lock = RLock()

    def reserve(self, provider_id: int, model: str, job_id: int) -> None:
        with self._lock:
            owner = self._owners.get((provider_id, model))
            if owner is not None and owner != job_id:
                raise RuntimeError("The model lanes are already reserved for another benchmark")
            self._owners[provider_id, model] = job_id

    def try_admit(self, provider_id: int, model: str, request_id: str, reserve_capacity: Callable[[], bool]) -> bool:
        """Atomically admit capacity before a benchmark can take ownership."""
        with self._lock:
            if not self.allows(provider_id, model, request_id) or not reserve_capacity():
                return False
            self._admitted[request_id] = (provider_id, model)
            return True

    def admit_queued(self, provider_id: int, model: str, dequeue: Callable):
        """Keep queue removal and admission atomic with benchmark acquisition."""
        with self._lock:
            owner = self._owners.get((provider_id, model))
            task, entry = dequeue(owner)
            if isinstance(task, Future) and not task.done() and entry is not None:
                request_id = getattr(entry, "request_id", None)
                if request_id:
                    self._admitted[request_id] = (provider_id, model)
            return task, entry

    def admitted_requests(self, provider_id: int, model: str) -> set[str]:
        with self._lock:
            return {rid for rid, pair in self._admitted.items() if pair == (provider_id, model)}

    def provider_owner(self, provider_id: int) -> int | None:
        """Include cancelled jobs whose worker cleanup has not finished."""
        with self._lock:
            return next((owner for (pid, _), owner in self._owners.items() if pid == provider_id), None)

    def owner(self, provider_id: int, model: str) -> int | None:
        with self._lock:
            return self._owners.get((provider_id, model))

    def register_request(self, provider_id: int, model: str, job_id: int, request_id: str) -> None:
        with self._lock:
            if self._owners.get((provider_id, model)) != job_id:
                raise RuntimeError("The benchmark no longer owns the model lanes")
            self._requests[request_id] = (provider_id, model, job_id)

    def allows(self, provider_id: int, model: str, request_id: str | None = None) -> bool:
        with self._lock:
            owner = self._owners.get((provider_id, model))
            return (
                owner is None
                or self._requests.get(request_id) == (provider_id, model, owner)
                or self._admitted.get(request_id) == (provider_id, model)
            )

    def finish_request(self, request_id: str) -> None:
        with self._lock:
            self._requests.pop(request_id, None)
            self._admitted.pop(request_id, None)

    def release(self, job_id: int) -> None:
        with self._lock:
            self._owners = {key: owner for key, owner in self._owners.items() if owner != job_id}
            self._requests = {key: value for key, value in self._requests.items() if value[2] != job_id}


benchmark_reservations = BenchmarkReservations()
