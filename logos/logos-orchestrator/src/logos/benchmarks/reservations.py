"""Process-local ownership of worker model lanes during an internal benchmark."""

from threading import RLock


class BenchmarkReservations:
    """Keep production traffic off a benchmark's lanes, including between batch runs.

    Ownership follows the provider/model pair so it survives cold loading and
    lane replacement. Only request IDs registered after internal authentication
    can use it. Other models on the same worker remain available.
    """

    def __init__(self):
        self._owners: dict[tuple[int, str], int] = {}
        self._requests: dict[str, tuple[int, str, int]] = {}
        self._lock = RLock()

    def reserve(self, provider_id: int, model: str, job_id: int) -> None:
        with self._lock:
            owner = self._owners.get((provider_id, model))
            if owner is not None and owner != job_id:
                raise RuntimeError("The model lanes are already reserved for another benchmark")
            self._owners[provider_id, model] = job_id

    def owner(self, provider_id: int, model: str) -> int | None:
        with self._lock:
            return self._owners.get((provider_id, model), self._owners.get((provider_id, "*")))

    def register_request(self, provider_id: int, model: str, job_id: int, request_id: str) -> None:
        with self._lock:
            if self._owners.get((provider_id, model)) != job_id:
                raise RuntimeError("The benchmark no longer owns the model lanes")
            self._requests[request_id] = (provider_id, model, job_id)

    def allows(self, provider_id: int, model: str, request_id: str | None = None) -> bool:
        with self._lock:
            owner = self._owners.get((provider_id, model), self._owners.get((provider_id, "*")))
            return owner is None or self._requests.get(request_id) == (provider_id, model, owner)

    def finish_request(self, request_id: str) -> None:
        with self._lock:
            self._requests.pop(request_id, None)

    def release(self, job_id: int) -> None:
        with self._lock:
            self._owners = {key: owner for key, owner in self._owners.items() if owner != job_id}
            self._requests = {key: value for key, value in self._requests.items() if value[2] != job_id}


benchmark_reservations = BenchmarkReservations()
