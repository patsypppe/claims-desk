"""Injectable clock so deadline logic is deterministic in tests and evals."""
from datetime import date
from typing import Protocol


class Clock(Protocol):
    def today(self) -> date: ...


class SystemClock:
    def today(self) -> date:
        return date.today()


class FixedClock:
    def __init__(self, fixed: date) -> None:
        self._fixed = fixed

    def today(self) -> date:
        return self._fixed
