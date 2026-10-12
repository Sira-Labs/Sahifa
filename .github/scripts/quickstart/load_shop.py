"""Load the faulty shop's CSV files into the quick-start source (CI job `quickstart`, spec 021).

    python load_shop.py <folder of CSV files> <postgresql:// URL of the owner>

Runs inside the api image, which has DuckDB and psycopg. Test data only: the table names come
from the generated files, and the values travel through COPY, never through SQL text.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import psycopg
from psycopg import sql

TYPES = {
    "BIGINT": "bigint",
    "DOUBLE": "double precision",
    "TIMESTAMP": "timestamp",
    "BOOLEAN": "boolean",
    "DATE": "date",
}


def main(folder: str, url: str) -> None:
    with psycopg.connect(url, autocommit=True) as con:
        for path in sorted(Path(folder).glob("*.csv")):
            rel = duckdb.sql(
                "SELECT * FROM read_csv(?, auto_detect = true, sample_size = -1)", params=[str(path)]
            )
            columns = sql.SQL(", ").join(
                sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(TYPES.get(str(kind).upper(), "text")))
                for name, kind in zip(rel.columns, rel.dtypes, strict=True)
            )
            table = sql.Identifier("public", path.stem)
            con.execute(sql.SQL("CREATE TABLE {} ({})").format(table, columns))
            with con.cursor().copy(sql.SQL("COPY {} FROM STDIN").format(table)) as copy:
                for row in rel.fetchall():
                    copy.write_row(row)
            print(f"loaded {path.stem}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
