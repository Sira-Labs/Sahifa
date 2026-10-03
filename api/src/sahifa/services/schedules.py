"""Scan schedules (spec 010): cron validation and next-run computation.

A schedule is a 5-field cron expression read on the wall clock of an IANA time zone; its
times are stored in UTC. Daylight-saving changes follow the wall clock:

- a time that happens twice when the clocks go back fires once, at its first occurrence;
- a time that does not exist when the clocks go forward fires as far after the jump as it
  would have been after the hour before it (02:30 in Zurich on the last Sunday of March
  fires at 03:30 summer time), so a nightly scan never skips a night.

`croniter` (MIT) walks the cron on naive wall-clock times, `zoneinfo` maps each one to UTC.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from itertools import pairwise
from zoneinfo import ZoneInfo, available_timezones

from croniter import CroniterBadDateError, CroniterError, croniter

FIELDS = 5
# Times compared to find the shortest interval of a schedule (spec 010).
INTERVAL_SAMPLE = 50
# Wall-clock times are walked from this far before "after", so that a time moved by a
# daylight-saving change (at most 2 hours anywhere) is not missed.
DST_SLACK = timedelta(hours=3)
# croniter's random (`R`) and hashed (`H`) fields: the first changes at every read, the second
# needs an id; neither belongs in a schedule people read.
RANDOM_OR_HASHED = re.compile(r"(?i)^[hr](\(|/|$)")
CRON_HELP = "A cron expression has five fields: minute hour day-of-month month day-of-week, e.g. 0 2 * * *."


class ScheduleError(ValueError):
    """A schedule the API refuses with 422: a code for the web app, the field and a sentence."""

    def __init__(
        self, code: str, field: str | None, message: str, extra: dict[str, int] | None = None
    ) -> None:
        super().__init__(message)
        self.code, self.field, self.message, self.extra = code, field, message, extra

    def body(self) -> dict[str, object]:
        return {"detail": self.code, "field": self.field, "message": self.message, **(self.extra or {})}


def invalid_cron(message: str) -> ScheduleError:
    return ScheduleError("invalid_cron", "cron", message)


@lru_cache(maxsize=1)
def known_zones() -> frozenset[str]:
    """The IANA names zoneinfo can load: the system's database and the `tzdata` package."""
    return frozenset(available_timezones())


def zone(name: str) -> ZoneInfo:
    """The time zone called `name`; `ScheduleError` for a name zoneinfo does not know."""
    if name not in known_zones():
        raise ScheduleError(
            "unknown_timezone",
            "timezone",
            f"{name} is not a known time zone; use an IANA name such as Europe/Zurich.",
        )
    return ZoneInfo(name)


def normalize_cron(cron: str) -> str:
    """The cron with single spaces; `ScheduleError` unless croniter reads exactly 5 fields."""
    fields = cron.split()
    if len(fields) != FIELDS:
        raise invalid_cron(CRON_HELP)
    if any(RANDOM_OR_HASHED.match(part) for f in fields for part in f.split(",")):
        raise invalid_cron(f"Random (R) and hashed (H) fields are not supported. {CRON_HELP}")
    text = " ".join(fields)
    if not croniter.is_valid(text):
        raise invalid_cron(f"{text} is not a valid cron expression. {CRON_HELP}")
    return text


def fire_times(cron: str, tz: ZoneInfo, after: datetime, count: int) -> list[datetime]:
    """The next `count` times (UTC) the cron fires strictly after `after`, read in `tz`."""
    start = after.astimezone(tz).replace(tzinfo=None) - DST_SLACK
    walk = croniter(cron, start)
    out: list[datetime] = []
    # Each step yields a time, or drops one before `after` (the slack) or one that a gap moved
    # onto a time already taken; the bound only guards against a cron croniter walks oddly.
    for _ in range(count + 10_000):
        if len(out) == count:
            break
        wall: datetime = walk.get_next(datetime)
        # fold=0: the first of two equal wall times; in a gap, the offset from before the jump.
        at = wall.replace(tzinfo=tz, fold=0).astimezone(UTC)
        if at > after and (not out or at > out[-1]):
            out.append(at)
    return out


def shortest_interval(cron: str, tz: ZoneInfo, after: datetime) -> timedelta:
    """The smallest gap between the next `INTERVAL_SAMPLE` fire times."""
    return min(b - a for a, b in pairwise(fire_times(cron, tz, after, INTERVAL_SAMPLE)))


def validate(cron: str, timezone: str, *, min_interval_minutes: int, now: datetime) -> str:
    """Check a schedule (spec 010): 5 cron fields, a known time zone, and no two runs closer
    than `min_interval_minutes`. Returns the cron with single spaces."""
    text = normalize_cron(cron)
    tz = zone(timezone)
    try:
        gap = shortest_interval(text, tz, now)
    except CroniterBadDateError as e:
        raise invalid_cron(f"{text} never fires.") from e
    except (CroniterError, ValueError) as e:
        raise invalid_cron(f"{text} is not a valid cron expression. {CRON_HELP}") from e
    minutes = int(gap.total_seconds() // 60)
    if minutes < min_interval_minutes:
        raise ScheduleError(
            "too_frequent",
            "cron",
            f"This schedule runs every {minutes} minutes at its closest; the minimum is "
            f"{min_interval_minutes} minutes.",
            {"min_interval_minutes": min_interval_minutes, "interval_minutes": minutes},
        )
    return text


def next_run(cron: str, timezone: str, after: datetime) -> datetime:
    """The first time the schedule fires after `after`, in UTC."""
    return fire_times(cron, ZoneInfo(timezone), after, 1)[0]


def upcoming(cron: str, timezone: str, next_run_at: datetime | None, count: int = 3) -> list[datetime]:
    """The next `count` runs: the stored next run (which may be due already), then the ones
    after it. A disabled schedule has none."""
    if next_run_at is None:
        return []
    return [next_run_at, *fire_times(cron, ZoneInfo(timezone), next_run_at, count - 1)]
