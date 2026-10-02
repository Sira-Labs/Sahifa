"""The check contract (docs/checks/00-check-specification.md)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal

from ..connectors.base import Connector, Relation
from ..models import AssetProfile, CheckSpec, CheckStatus, ColumnProfile, Dimension, Severity
from ..sql import Dialect

Evaluation = Literal["sql", "python", "profile"]


@dataclass
class Context:
    """What a check may look at while generating and evaluating; no I/O beyond `src` queries."""

    asset: AssetProfile
    assets: dict[str, AssetProfile]
    src: Connector
    rel: Relation
    scan_time: datetime
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def d(self) -> Dialect:
        return self.src.dialect

    def q(self, column: str) -> str:
        return f"s.{self.d.ident(column)}"


class Check:
    """Base class: one check type of the catalogue."""

    type: ClassVar[str]
    title: ClassVar[str]
    dimension: ClassVar[Dimension]
    level: ClassVar[Literal["column", "asset"]] = "column"
    kind: ClassVar[Literal["rule", "baseline"]] = "rule"
    severity: ClassVar[Severity] = Severity.MEDIUM
    evaluation: ClassVar[Evaluation] = "sql"
    next_step: ClassVar[str] = ""
    release: ClassVar[str] = "R1"

    # -- generation -------------------------------------------------------------------------
    def applies(self, col: ColumnProfile, ctx: Context) -> bool:
        return False

    def params(self, col: ColumnProfile, ctx: Context) -> dict[str, Any]:
        return {}

    def generate(self, ctx: Context) -> list[CheckSpec]:
        out = []
        if self.level == "column":
            for col in ctx.asset.columns:
                if self.applies(col, ctx):
                    out.append(
                        self.spec(
                            ctx,
                            column=col.name,
                            params=self.params(col, ctx),
                            severity=self.severity_for(col),
                            tolerance=self.tolerance_for(col),
                        )
                    )
        return out

    def severity_for(self, col: ColumnProfile | None) -> Severity:
        return self.severity

    def tolerance_for(self, col: ColumnProfile | None) -> float:
        return 0.0

    def spec(
        self,
        ctx: Context,
        *,
        column: str | None = None,
        columns: list[str] | None = None,
        params: dict[str, Any] | None = None,
        severity: Severity | None = None,
        tolerance: float = 0.0,
        origin: str = "generated",
    ) -> CheckSpec:
        target = column or ",".join(columns or [])
        return CheckSpec(
            id=f"{self.type}:{ctx.asset.ref.label}:{target}",
            type=self.type,
            asset=ctx.asset.ref,
            column=column,
            columns=columns or [],
            params=params or {},
            dimension=self.dimension,
            severity=severity or self.severity,
            kind=self.kind,
            status=CheckStatus.ACTIVE if self.kind == "rule" else CheckStatus.PROPOSED,
            max_fail_ratio=tolerance,
            origin=origin,  # type: ignore[arg-type]
        )

    # -- SQL evaluation ---------------------------------------------------------------------
    def domain(self, spec: CheckSpec, ctx: Context) -> str:
        """Rows the check applies to (n); default: the column is not null."""
        return f"{ctx.q(spec.column)} IS NOT NULL" if spec.column else "TRUE"

    def fail(self, spec: CheckSpec, ctx: Context) -> str:
        raise NotImplementedError

    def n_expr(self, spec: CheckSpec, ctx: Context) -> str:
        return ctx.d.sum_case(self.domain(spec, ctx))

    def k_expr(self, spec: CheckSpec, ctx: Context) -> str:
        return ctx.d.sum_case(f"({self.domain(spec, ctx)}) AND ({self.fail(spec, ctx)})")

    def example_value(self, spec: CheckSpec, ctx: Context) -> str | None:
        return ctx.d.as_text(ctx.q(spec.column)) if spec.column else None

    def examples_sql(self, spec: CheckSpec, ctx: Context) -> str | None:
        value = self.example_value(spec, ctx)
        if value is None:
            return None
        return ctx.rel.query(
            f"SELECT {value} AS v, count(*) AS n FROM {ctx.rel.ref} AS s "
            f"WHERE ({self.domain(spec, ctx)}) AND ({self.fail(spec, ctx)}) GROUP BY {value} "
            f"ORDER BY n DESC, v LIMIT 5"
        )

    # -- Python and profile evaluation -------------------------------------------------------
    def evaluate_values(
        self, spec: CheckSpec, values: list[tuple[str, int]]
    ) -> tuple[int, int, list[tuple[str, int]]]:
        raise NotImplementedError

    def evaluate_profile(self, spec: CheckSpec, ctx: Context) -> tuple[int, int, list[tuple[str, int]]]:
        raise NotImplementedError

    def accept(self, spec: CheckSpec, n: int, k: int) -> bool:
        """Keep the result? Candidates (inferred foreign keys) are dropped when the evidence is weak."""
        return True

    # -- explanation ------------------------------------------------------------------------
    def summary(self, spec: CheckSpec, n: int, k: int) -> str:
        return f"{k:,} of {n:,} rows fail {self.title.lower()} in {where(spec)} ({pct(k, n)})."


def where(spec: CheckSpec) -> str:
    target = spec.column or ", ".join(spec.columns)
    return f"{spec.asset.label}.{target}" if target else spec.asset.label


def pct(k: int, n: int) -> str:
    if n == 0:
        return "0 %"
    v = 100 * k / n
    return f"{v:.2f} %" if v < 1 else f"{v:.1f} %"
