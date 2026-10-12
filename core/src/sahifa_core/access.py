"""The verdict and advice of an access report (spec 021).

The connectors collect what a login or process may do; this module turns it into one verdict
and one sentence a person can act on.
"""

from __future__ import annotations

from .models import ACCESS_NAMES_SHOWN, SourceAccess

GUIDE = "docs/guides/read-only-login.md"


def postgres_access(
    *,
    readable: int,
    unreadable: int,
    writable: list[str],
    can_create_in: list[str],
    role_flags: list[str],
) -> SourceAccess:
    """The report of a Postgres login: `can_write` as soon as anything could change the database."""
    advice: list[str] = []
    if role_flags:
        advice.append(f"Use a plain login role, not one with {', '.join(role_flags)}")
    if writable:
        n = len(writable)
        tables = "table" if n == 1 else "tables"
        advice.append(f"Revoke INSERT, UPDATE, DELETE and TRUNCATE (and ownership) on {n} {tables}")
    if can_create_in:
        advice.append(f"Revoke CREATE on {', '.join(can_create_in)}")
    can_write = bool(writable or can_create_in or role_flags)
    return SourceAccess(
        verdict="can_write" if can_write else "read_only",
        readable=readable,
        unreadable=unreadable,
        writable=sorted(writable)[:ACCESS_NAMES_SHOWN],
        writable_count=len(writable),
        can_create_in=can_create_in,
        role_flags=role_flags,
        advice=("; ".join(advice) + f". See {GUIDE}.") if advice else None,
    )


def files_access(*, readable: int, unreadable: int, writable: list[str]) -> SourceAccess:
    """The report of files: `can_write` when the process could change or delete them."""
    return SourceAccess(
        verdict="can_write" if writable else "read_only",
        readable=readable,
        unreadable=unreadable,
        writable=sorted(writable)[:ACCESS_NAMES_SHOWN],
        writable_count=len(writable),
        advice="Mount the folder read-only (`:ro` in compose) or remove write permission for Sahifa's user."
        if writable
        else None,
    )
