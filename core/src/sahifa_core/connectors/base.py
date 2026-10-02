"""The connector protocol every source implements (docs/architecture/03-system-architecture.md)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Literal, Self

from ..models import AssetInfo, AssetRef
from ..sql import Dialect

log = logging.getLogger("sahifa_core.connectors")


@dataclass(frozen=True)
class Relation:
    """A sampled view of one asset that later queries select from.

    `prefix` is prepended to every query (a CTE on engines where the sample cannot be
    materialised in a read-only session); `ref` is what follows `FROM`. `full` is the whole
    asset, used where a check must see every row (foreign-key parents, freshness).
    """

    asset: AssetRef
    ref: str
    full: str
    prefix: str = ""
    method: str = "full"

    def query(self, body: str) -> str:
        return self.prefix + body


class Connector(ABC):
    """A read-only handle on one source."""

    kind: Literal["duckdb", "postgres"]
    dialect: Dialect
    label: str

    def __init__(self) -> None:
        self.queries = 0

    @abstractmethod
    def list_assets(self) -> list[AssetRef]: ...

    @abstractmethod
    def describe(self, ref: AssetRef) -> AssetInfo: ...

    @abstractmethod
    def count_rows(self, ref: AssetRef, info: AssetInfo) -> tuple[int, bool]:
        """Population size and whether it is exact (False: a planner estimate)."""

    @abstractmethod
    def sample(self, ref: AssetRef, rows: int, seed: int, population: int) -> Relation:
        """Draw the scan's sample of `rows` rows (0: every row) reproducibly from `seed`."""

    def full_ref(self, ref: AssetRef) -> str:
        """What follows FROM to read every row of `ref`."""
        return self.dialect.table(ref)

    @abstractmethod
    def _execute(self, sql: str) -> list[tuple[Any, ...]]: ...

    def query(self, sql: str) -> list[tuple[Any, ...]]:
        self.queries += 1
        log.debug("query", extra={"sql": sql})
        return self._execute(sql)

    def release(self, relation: Relation) -> None:  # noqa: B027 - optional hook
        """Free what `sample` created; the default does nothing."""

    @abstractmethod
    def close(self) -> None: ...

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
