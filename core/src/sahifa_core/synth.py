"""A small shop dataset with injected faults, and its clean twin (spec 003), for demos and tests.

Every R1 rule check has at least one fault to find; the clean twin has none. Baseline checks
(pattern, accepted values, length, range, freshness) only propose on a first scan, so they
are tested by evaluating them against changed data (core/tests).
"""

from __future__ import annotations

import csv
import random
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


def _write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def write_shop(
    directory: str | Path,
    *,
    clean: bool = False,
    rows: int = 10_000,
    seed: int = 7,
    now: datetime | None = None,
) -> list[Path]:
    """Write the shop as CSV files into `directory`; returns the paths."""
    rng = random.Random(seed)
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    now = (now or datetime.now(UTC)).replace(tzinfo=None, microsecond=0)
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
    files = [
        (
            out / "customers.csv",
            ["id", "name", "email", "iban", "city", "country", "phone", "created_at"],
            customers,
        ),
        (out / "products.csv", ["id", "sku", "title", "price", "currency", "category"], products),
        (
            out / "orders.csv",
            ["id", "customer_id", "product_id", "quantity", "amount", "status", "ordered_at", "shipped_at"],
            orders,
        ),
        (out / "invoices.csv", ["id", "order_id", "vat_id", "total", "issued_at"], invoices),
        (out / "events.csv", ["id", "kind", "occurred_at", "payload_size"], events),
    ]
    if not clean:
        files.append((out / "returns.csv", ["id", "order_id", "reason", "returned_at"], []))
    for path, header, data in files:
        _write(path, header, data)
    return [p for p, _, _ in files]
