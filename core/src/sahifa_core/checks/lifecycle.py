"""Saved and generated checks of one asset, reconciled before evaluation (spec 007, ADR-0005).

| Saved status | Generated now | Result |
|---|---|---|
| none | yes | the generated spec with its default status |
| `proposed` or `active` (generated) | yes | the generated spec (new parameters), saved status |
| `proposed` or `active` (generated) | no | dropped this scan |
| `locked` | either | the saved spec unchanged |
| `retired` | either | dropped (not evaluated, not re-created) |
| origin `manual` | either | the saved spec unchanged |

Checks with origin `declared` (a declared foreign key) are generated like any other.
"""

from __future__ import annotations

from ..models import CheckSpec, CheckStatus


def keeps_saved(saved: CheckSpec) -> bool:
    """Whether the saved spec is evaluated as it is, whatever the profile says now."""
    return saved.status == CheckStatus.LOCKED or saved.origin == "manual"


def reconcile(generated: list[CheckSpec], saved: list[CheckSpec]) -> list[CheckSpec]:
    """The checks to evaluate for one asset, keyed by `CheckSpec.id`: generated ones in their
    order, then saved ones that were not generated this time."""
    by_id = {s.id: s for s in saved}
    out: list[CheckSpec] = []
    seen: set[str] = set()
    for g in generated:
        if g.id in seen:
            continue
        seen.add(g.id)
        s = by_id.get(g.id)
        if s is None:
            out.append(g)
        elif s.status == CheckStatus.RETIRED:
            continue
        elif keeps_saved(s):
            out.append(s)
        else:
            out.append(g.model_copy(update={"status": s.status}))
    for s in saved:
        if s.id not in seen and s.status != CheckStatus.RETIRED and keeps_saved(s):
            seen.add(s.id)
            out.append(s)
    return out
