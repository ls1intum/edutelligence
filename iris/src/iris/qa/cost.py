from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable

from iris.qa.schema import Scenario

# pylint: disable=missing-class-docstring


MILLION = Decimal(1_000_000)


@dataclass(frozen=True)
class ModelRate:
    model: str
    input_per_million: Decimal
    output_per_million: Decimal

    def cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        return (
            Decimal(input_tokens) * self.input_per_million
            + Decimal(output_tokens) * self.output_per_million
        ) / MILLION


@dataclass(frozen=True)
class UsageRecord:
    run_id: str
    scenario_id: str
    model: str
    pipeline: str
    input_tokens: int
    output_tokens: int
    cost_usd: str
    recorded_at: str
    reservation: bool = False


class BudgetExceeded(RuntimeError):
    """Raised before a paid call would exceed the configured hard ceiling."""


class SpendLedger:
    def __init__(self, path: Path):
        self.path = path

    def records(self) -> list[UsageRecord]:
        if not self.path.exists():
            return []
        records: list[UsageRecord] = []
        with self.path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    record = UsageRecord(**json.loads(line))
                    cost = Decimal(record.cost_usd)
                    if (
                        not cost.is_finite()
                        or cost < 0
                        or record.input_tokens < 0
                        or record.output_tokens < 0
                    ):
                        raise ValueError("negative or non-finite usage")
                    records.append(record)
                except (
                    json.JSONDecodeError,
                    TypeError,
                    ValueError,
                    InvalidOperation,
                ) as error:
                    raise ValueError(
                        f"Invalid spend ledger line {line_number}: {error}"
                    ) from error
        return records

    def total(self) -> Decimal:
        return sum((Decimal(record.cost_usd) for record in self.records()), Decimal(0))

    def append(self, record: UsageRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            payload = json.dumps(asdict(record), sort_keys=True) + "\n"
            os.write(descriptor, payload.encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @contextmanager
    def exclusive_paid_run(self) -> Iterator[None]:
        """Prevent concurrent paid commands from sharing a stale budget view."""
        lock_path = self.path.with_name(f"{self.path.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        acquired = False
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError as error:
                raise BudgetExceeded(
                    f"Another paid Iris QA command holds the ledger lock {lock_path}"
                ) from error
            yield
        finally:
            try:
                if acquired:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


class BudgetGuard:
    def __init__(self, ledger: SpendLedger, hard_limit_usd: Decimal):
        self.ledger = ledger
        self.hard_limit_usd = hard_limit_usd

    @property
    def remaining(self) -> Decimal:
        return max(Decimal(0), self.hard_limit_usd - self.ledger.total())

    def require_capacity(self, planned_cost: Decimal) -> None:
        if planned_cost < 0:
            raise ValueError("planned cost must not be negative")
        spent = self.ledger.total()
        if spent + planned_cost > self.hard_limit_usd:
            raise BudgetExceeded(
                f"Paid run refused: spent ${spent:.4f} + planned "
                f"${planned_cost:.4f} exceeds hard limit ${self.hard_limit_usd:.2f}"
            )

    def record_usage(
        self,
        *,
        run_id: str,
        scenario_id: str,
        pipeline: str,
        rate: ModelRate,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> UsageRecord:
        if input_tokens is None or output_tokens is None:
            raise BudgetExceeded("Provider omitted paid token usage; failing closed")
        if input_tokens < 0 or output_tokens < 0:
            raise BudgetExceeded(
                "Provider reported negative token usage; failing closed"
            )
        cost = rate.cost(input_tokens, output_tokens)
        spent = self.ledger.total()
        record = UsageRecord(
            run_id=run_id,
            scenario_id=scenario_id,
            model=rate.model,
            pipeline=pipeline,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=f"{cost:.8f}",
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self.ledger.append(record)
        if spent + cost > self.hard_limit_usd:
            raise BudgetExceeded(
                f"Billable usage was recorded, but spent ${spent:.4f} + actual "
                f"${cost:.4f} exceeds hard limit ${self.hard_limit_usd:.2f}"
            )
        return record

    def record_reservation(
        self,
        *,
        run_id: str,
        scenario_id: str,
        pipeline: str,
        model: str,
        cost_usd: Decimal,
    ) -> UsageRecord:
        """Reserve a conservative upper bound for an ambiguous provider call."""
        if not cost_usd.is_finite() or cost_usd <= 0:
            raise ValueError("reservation cost must be finite and greater than zero")
        spent = self.ledger.total()
        if spent + cost_usd > self.hard_limit_usd:
            raise BudgetExceeded(
                f"Ambiguous provider call cannot be reserved: spent ${spent:.4f} + "
                f"reserve ${cost_usd:.4f} exceeds hard limit "
                f"${self.hard_limit_usd:.2f}"
            )
        record = UsageRecord(
            run_id=run_id,
            scenario_id=scenario_id,
            model=model,
            pipeline=pipeline,
            input_tokens=0,
            output_tokens=0,
            cost_usd=f"{cost_usd:.8f}",
            recorded_at=datetime.now(timezone.utc).isoformat(),
            reservation=True,
        )
        self.ledger.append(record)
        return record


def estimate_candidate_cost(
    scenarios: Iterable[Scenario],
    rates: Iterable[ModelRate],
    *,
    repetitions: int = 1,
) -> dict[str, Decimal]:
    if repetitions < 1:
        raise ValueError("repetitions must be at least one")
    totals: dict[str, Decimal] = {}
    scenario_list = list(scenarios)
    for rate in rates:
        totals[rate.model] = (
            sum(
                (
                    rate.cost(
                        scenario.token_ceiling.max_input_tokens,
                        scenario.token_ceiling.max_output_tokens,
                    )
                    for scenario in scenario_list
                ),
                Decimal(0),
            )
            * repetitions
        )
    return totals
