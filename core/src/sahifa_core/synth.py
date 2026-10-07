"""A small shop dataset with injected faults, its clean twin and its drift twin (specs 003, 014),
for demos, tests and the accuracy benchmark.

Every R1 rule check has at least one fault to find in the faulty shop; the clean twin has none.
Baseline checks (pattern, accepted values, length, range, freshness) only propose on a first
scan, so the drift twin is the clean twin plus one fault per baseline check, to be scanned
against baselines locked on the clean twin.

`shop_tables` also lists the faults the data holds (`Fault`), counted from the final rows by a
plain predicate per fault, so one fault overwriting another, or a side effect such as an invoice
whose order key was duplicated away, is counted as it is.
"""

from __future__ import annotations

import csv
import random
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

FIRST = [
    "Anna",
    "Ben",
    "Clara",
    "David",
    "Elif",
    "Farid",
    "Greta",
    "Hamza",
    "Ines",
    "Jonas",
    "Karim",
    "Lea",
    "Maryam",
    "Noah",
    "Omar",
    "Paula",
    "Rania",
    "Samir",
    "Tara",
    "Yusuf",
]
LAST = [
    "Schmidt",
    "Yilmaz",
    "Weber",
    "Haddad",
    "Fischer",
    "Rahman",
    "Wagner",
    "Becker",
    "Hoffmann",
    "Aziz",
    "Koch",
    "Richter",
    "Klein",
    "Wolf",
    "Neumann",
    "Schwarz",
]
CITIES = [
    "Berlin",
    "Hamburg",
    "München",
    "Köln",
    "Frankfurt",
    "Stuttgart",
    "Leipzig",
    "Wien",
    "Zürich",
    "Bremen",
]
COUNTRIES = ["DE", "DE", "DE", "AT", "CH", "FR", "NL"]
CATEGORIES = ["books", "garden", "kitchen", "toys", "tools"]
STATUSES = ["paid", "shipped", "delivered", "cancelled"]


def iban_de(rng: random.Random) -> str:
    bban = f"{rng.randrange(10**7, 10**8)}{rng.randrange(10**9, 10**10)}"
    digits = "".join(str(int(ch, 36)) for ch in bban + "DE00")
    check = 98 - int(digits) % 97
    return f"DE{check:02d}{bban}"


# Smallest shop whose products table (rows // 50) is large enough for baselines (50 rows).
MIN_DRIFT_ROWS = 2500
TS_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class Fault:
    """Rows of one asset (and column) that one check should count as failing."""

    check: str
    asset: str
    column: str | None
    rows: int


@dataclass
class Table:
    name: str
    header: list[str]
    rows: list[list[object]]

    def values(self, column: str) -> list[object]:
        i = self.header.index(column)
        return [r[i] for r in self.rows]


@dataclass
class Shop:
    tables: list[Table]
    faults: list[Fault] = field(default_factory=list)

    def table(self, name: str) -> Table:
        return next(t for t in self.tables if t.name == name)

    def write(self, directory: str | Path) -> list[Path]:
        """Write each table as a CSV file into `directory`; returns the paths."""
        out = Path(directory)
        out.mkdir(parents=True, exist_ok=True)
        paths = []
        for t in self.tables:
            path = out / f"{t.name}.csv"
            _write(path, t.header, t.rows)
            paths.append(path)
        return paths


def _write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _ts(dt: datetime) -> str:
    return dt.strftime(TS_FORMAT)


def write_shop(
    directory: str | Path,
    *,
    clean: bool = False,
    drift: bool = False,
    rows: int = 10_000,
    seed: int = 7,
    now: datetime | None = None,
) -> list[Path]:
    """Write the shop as CSV files into `directory`; returns the paths. The fault list is not
    written: a scan of the directory would read it as an asset."""
    return shop_tables(clean=clean, drift=drift, rows=rows, seed=seed, now=now).write(directory)


def shop_tables(
    *,
    clean: bool = False,
    drift: bool = False,
    rows: int = 10_000,
    seed: int = 7,
    now: datetime | None = None,
) -> Shop:
    """The shop in memory with the faults it holds. `drift` adds the baseline faults to the clean
    twin (it implies `clean`); the faulty shop is the default."""
    rng = random.Random(seed)
    now = (now or datetime.now(UTC)).replace(tzinfo=None, microsecond=0)
    clean = clean or drift
    n_customers, n_products, n_orders = max(rows // 5, 50), max(rows // 50, 20), rows

    customers: list[list[object]] = []
    for i in range(1, n_customers + 1):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        customers.append(
            [
                i,
                f"{first} {last}",
                f"{first.lower()}.{last.lower()}{i}@example.org",
                iban_de(rng),
                rng.choice(CITIES),
                rng.choice(COUNTRIES),
                f"+49 30 {rng.randrange(1000000, 9999999)}",
                _ts(now - timedelta(days=rng.randrange(30, 900), minutes=rng.randrange(1440))),
            ]
        )
    products = [
        [i, f"SKU-{i:05d}", f"Product {i}", round(rng.uniform(5, 200), 2), "EUR", rng.choice(CATEGORIES)]
        for i in range(1, n_products + 1)
    ]
    orders: list[list[object]] = []
    for i in range(1, n_orders + 1):
        ordered = now - timedelta(days=rng.randrange(1, 400), minutes=rng.randrange(1440))
        price = float(products[rng.randrange(n_products)][3])  # type: ignore[arg-type]
        qty = rng.randrange(1, 5)
        orders.append(
            [
                i,
                rng.randrange(1, n_customers + 1),
                rng.randrange(1, n_products + 1),
                qty,
                round(price * qty, 2),
                rng.choice(STATUSES),
                _ts(ordered),
                _ts(min(ordered + timedelta(hours=rng.randrange(2, 96)), now)),
            ]
        )
    invoices = [
        [i, i, f"DE{rng.randrange(10**8, 10**9)}", o[4], o[6]]
        for i, o in enumerate(orders[: int(n_orders * 0.8)], start=1)
    ]
    events = [
        [
            i,
            rng.choice(["view", "cart", "checkout"]),
            _ts(now - timedelta(minutes=rng.randrange(5, 60 * 24 * 7))),
            rng.randrange(100, 5000),
        ]
        for i in range(1, n_orders // 2 + 1)
    ]

    if not clean:
        pick = rng.sample
        for c in pick(customers, max(3, n_customers // 50)):
            c[2] = None  # missing email
        for c in pick(customers, 5):
            c[2] = "N/A"  # placeholder
        for c in pick(customers, max(3, n_customers // 100)):
            iban = str(c[3])
            c[3] = iban[:-2] + ("00" if iban[-2:] != "00" else "11")  # broken IBAN checksum
        for c in pick(customers, 8):
            c[4] = f" {c[4]} "  # whitespace
        for c in pick(customers, 12):
            c[4] = str(c[4]).strip().lower()  # casing variant
        for c in pick(customers, 3):
            c[1] = f"{c[1]}​"  # zero-width space
        customers[0][7] = _ts(now + timedelta(days=40))  # future date
        customers[1][7] = "1899-12-31 00:00:00"  # default date
        for o in pick(orders, 25):
            o[1] = n_customers + rng.randrange(1, 500)  # orphan customer
        for o in pick(orders, 4):
            o[1] = None  # missing foreign key
        for o in pick(orders, 6):
            o[0] = orders[rng.randrange(n_orders)][0]  # duplicate key
        orders += [list(o) for o in orders[:10]]  # identical rows
        for o in pick(orders, max(5, n_orders // 50)):
            o[4] = float(str(o[4])) * 1000  # decimal-shift outlier
        for o in pick(orders, 15):
            o[6], o[7] = o[7], o[6]  # shipped before ordered
        for inv in pick(invoices, 4):
            inv[2] = "DE12345"  # malformed VAT ID
        for inv in pick(invoices, 6):
            inv[3] = "twelve"  # number column with text
    tables = [
        Table(
            "customers", ["id", "name", "email", "iban", "city", "country", "phone", "created_at"], customers
        ),
        Table("products", ["id", "sku", "title", "price", "currency", "category"], products),
        Table(
            "orders",
            ["id", "customer_id", "product_id", "quantity", "amount", "status", "ordered_at", "shipped_at"],
            orders,
        ),
        Table("invoices", ["id", "order_id", "vat_id", "total", "issued_at"], invoices),
        Table("events", ["id", "kind", "occurred_at", "payload_size"], events),
    ]
    if not clean:
        tables.append(Table("returns", ["id", "order_id", "reason", "returned_at"], []))
    shop = Shop(tables)
    if drift:
        _add_drift(shop, random.Random(seed + 1))
    else:
        shop.faults = rule_faults(shop, now)
    return shop


# --- drift twin -----------------------------------------------------------------------------


def _add_drift(shop: Shop, rng: random.Random) -> None:
    """One fault per R1 baseline check, on columns where the clean twin's baselines apply. Each
    fault is counted against the clean values it replaces, as a locked baseline sees it."""
    customers, products, orders = shop.table("customers"), shop.table("products"), shop.table("orders")
    events = shop.table("events")
    seen_status = set(orders.values("status"))
    longest = max(len(str(v)) for v in customers.values("name"))
    lowest_amount = min(float(str(v)) for v in orders.values("amount"))
    first_event = min(_dt(v) for v in events.values("occurred_at"))

    status = orders.header.index("status")
    for o in rng.sample(orders.rows, 20):
        o[status] = "lost"  # a status never seen before
    sku = products.header.index("sku")
    for p in rng.sample(products.rows, 5):
        p[sku] = f"SKU-{str(p[sku])[-4:]}X"  # same length, new shape
    name = customers.header.index("name")
    for c in rng.sample(customers.rows, 5):
        c[name] = f"{c[name]} von Hohenzollern"  # longer than any name before
    amount = orders.header.index("amount")
    for o in rng.sample(orders.rows, 10):
        o[amount] = -float(str(o[amount]))  # below the smallest amount seen
    occurred = events.header.index("occurred_at")
    for e in events.rows:
        e[occurred] = _ts(_dt(e[occurred]) - timedelta(days=30))  # the feed stopped a month ago

    shop.faults = [
        Fault(
            "sah.accepted_values",
            "orders",
            "status",
            sum(1 for v in orders.values("status") if v not in seen_status),
        ),
        Fault(
            "sah.pattern",
            "products",
            "sku",
            sum(1 for v in products.values("sku") if not SKU.fullmatch(str(v))),
        ),
        Fault(
            "sah.length",
            "customers",
            "name",
            sum(1 for v in customers.values("name") if len(str(v)) > longest),
        ),
        Fault(
            "sah.range",
            "orders",
            "amount",
            sum(1 for v in orders.values("amount") if float(str(v)) < lowest_amount),
        ),
        Fault(
            "sah.range",
            "events",
            "occurred_at",
            sum(1 for v in events.values("occurred_at") if _dt(v) < first_event),
        ),
        Fault("sah.freshness", "events", None, 1),
    ]


# --- fault list of the faulty shop ----------------------------------------------------------

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.IGNORECASE)
VAT_DE = re.compile(r"DE\d{9}")
SKU = re.compile(r"SKU-\d{5}")
PLACEHOLDERS = {"", "n/a", "na", "null", "none", "-", "?"}
# Columns with a declared or inferred parent: (child asset, column, parent asset).
REFERENCES = (
    ("orders", "customer_id", "customers"),
    ("orders", "product_id", "products"),
    ("invoices", "order_id", "orders"),
)
TIMESTAMPS = {"created_at", "ordered_at", "shipped_at", "issued_at", "occurred_at", "returned_at"}


def _dt(value: object) -> datetime:
    return datetime.strptime(str(value), TS_FORMAT)


def _iban_ok(value: str) -> bool:
    s = value[4:] + value[:4]
    return int("".join(str(int(ch, 36)) for ch in s)) % 97 == 1


def _non_printing(value: str) -> bool:
    return any(unicodedata.category(ch) in ("Cc", "Cf") for ch in value)


def _is_number(value: object) -> bool:
    try:
        float(str(value))
    except ValueError:
        return False
    return True


def rule_faults(shop: Shop, now: datetime) -> list[Fault]:
    """What each R1 rule check should count in the shop, from the final rows."""
    out: list[Fault] = []

    def add(check: str, asset: str, column: str | None, n: int) -> None:
        if n:
            out.append(Fault(check, asset, column, n))

    for t in shop.tables:
        if not t.rows:
            add("sah.row_count", t.name, None, 1)
            continue
        add("sah.duplicate_rows", t.name, None, len(t.rows) - len({tuple(r) for r in t.rows}))
        for col in t.header:
            vals = t.values(col)
            present = [v for v in vals if v is not None]
            texts = [v for v in present if isinstance(v, str)]
            add("sah.not_null", t.name, col, len(vals) - len(present))
            add("sah.whitespace", t.name, col, sum(1 for v in texts if v != v.strip()))
            add("sah.non_printing", t.name, col, sum(1 for v in texts if _non_printing(v)))
            add("sah.not_blank", t.name, col, sum(1 for v in texts if v.strip().lower() in PLACEHOLDERS))
            if col == "id":
                add("sah.unique", t.name, col, len(present) - len(set(present)))
            if col in TIMESTAMPS:
                stamps = [_dt(v) for v in present]
                add("sah.future_dates", t.name, col, sum(1 for d in stamps if d > now))
                add("sah.implausible_dates", t.name, col, sum(1 for d in stamps if not 1900 <= d.year < 2200))

    customers, orders, invoices = shop.table("customers"), shop.table("orders"), shop.table("invoices")
    emails = [v for v in customers.values("email") if v is not None]
    add("sah.semantic_format", "customers", "email", sum(1 for v in emails if not EMAIL.fullmatch(str(v))))
    add(
        "sah.semantic_format",
        "customers",
        "iban",
        sum(1 for v in customers.values("iban") if not _iban_ok(str(v))),
    )
    add(
        "sah.semantic_format",
        "invoices",
        "vat_id",
        sum(1 for v in invoices.values("vat_id") if not VAT_DE.fullmatch(str(v))),
    )
    add(
        "sah.type_conformance",
        "invoices",
        "total",
        sum(1 for v in invoices.values("total") if not _is_number(v)),
    )

    # Spelling variants: every value of a trimmed, case-folded group but its most frequent one.
    groups: dict[str, Counter[str]] = {}
    for v in customers.values("city"):
        groups.setdefault(str(v).strip().lower(), Counter())[str(v)] += 1
    add(
        "sah.casing_variants",
        "customers",
        "city",
        sum(sum(c.values()) - c.most_common(1)[0][1] for c in groups.values()),
    )

    for child, col, parent in REFERENCES:
        keys = set(shop.table(parent).values("id"))
        add(
            "sah.foreign_key",
            child,
            col,
            sum(1 for v in shop.table(child).values(col) if v is not None and v not in keys),
        )

    ordered, shipped = orders.values("ordered_at"), orders.values("shipped_at")
    add(
        "sah.column_order",
        "orders",
        None,
        sum(1 for a, b in zip(ordered, shipped, strict=True) if _dt(b) < _dt(a)),
    )
    # Decimal-shift outliers: every legitimate amount is at most 4 × 200 EUR.
    add(
        "sah.outliers",
        "orders",
        "amount",
        sum(1 for v in orders.values("amount") if _is_number(v) and float(str(v)) > 1000),
    )
    return out
