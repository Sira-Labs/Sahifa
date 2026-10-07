"""`sahifa` command line: scan a source, write the demo shop, list the catalogue (spec 003), and
the performance and accuracy benchmarks (specs 013, 014)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .errors import SahifaError, UsageError

SEV_MARK = {"critical": "●", "high": "●", "medium": "●", "low": "●"}


def _fmt_interval(value: float | None, low: float | None, high: float | None) -> str:
    if value is None:
        return "—  no active checks"
    if low == high:
        return f"{value:5.1f}  full read"
    return f"{value:5.1f}  {low:.1f}–{high:.1f}"


def pretty(report: dict) -> str:  # type: ignore[type-arg]
    s = report["score"]
    st = report["stats"]
    lines = [
        f"Sahifa scan of {report['source']['label']} ({report['source']['kind']})",
        f"{st['assets']} assets · {st['columns']} columns · {st['checks_active']} checks active · "
        f"{st['checks_proposed']} proposed · {st['duration_s']} s",
        "",
        f"  Store score   {_fmt_interval(s['overall'], s['low'], s['high'])}",
    ]
    for name, d in s["dimensions"].items():
        lines.append(f"  {name:<13} {_fmt_interval(d['value'], d['low'], d['high'])}")
    lines.append("")
    for f in report["findings"]:
        lines.append(f"{SEV_MARK[f['severity']]} {f['severity']:<8} {f['summary']}  ({f['check_type']})")
    if not report["findings"]:
        lines.append("No findings from active checks.")
    for h in report["health"]:
        lines.append(f"  health   {h['summary']}  ({h['type']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sahifa", description="Assess the quality of a data store.")
    parser.add_argument("--version", action="version", version=f"sahifa {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="profile, check and score a source")
    scan.add_argument(
        "source", nargs="+", help="files, directories, globs, duckdb:///file or postgresql:// URL"
    )
    scan.add_argument("--sample-rows", type=int, default=100_000)
    scan.add_argument("--all-rows", action="store_true", help="read every row (no sampling)")
    scan.add_argument("--seed", type=int, default=42)
    scan.add_argument(
        "--workers", type=int, default=2, help="Postgres sessions scanning assets at once (default 2)"
    )
    out = scan.add_mutually_exclusive_group()
    out.add_argument("--json", action="store_true", help="print the report as JSON")
    out.add_argument("--pretty", action="store_true", help="print a summary (default)")
    scan.add_argument("--out", type=Path, help="also write the JSON report to this file")

    synth = sub.add_parser("synth", help="write the demo shop dataset")
    synth.add_argument("directory", type=Path)
    form = synth.add_mutually_exclusive_group()
    form.add_argument("--clean", action="store_true", help="write the twin without faults")
    form.add_argument(
        "--drift", action="store_true", help="write the clean twin with one fault per baseline check"
    )
    synth.add_argument("--rows", type=int, default=10_000)
    synth.add_argument("--seed", type=int, default=7)

    sub.add_parser("checks", help="list the check catalogue")

    bench = sub.add_parser(
        "bench-schema", help="create the wide Postgres schema of the performance run (spec 013)"
    )
    bench.add_argument("url", help="postgresql:// URL of a benchmark database, never a source")
    bench.add_argument("--schema", default="bench")
    bench.add_argument(
        "--mix", default=None, help="tiers as TABLESxROWS,...; default 700x10000,270x100000,30x1000000"
    )

    accuracy = sub.add_parser(
        "bench-accuracy", help="measure each check against the synthetic shop's known faults (spec 014)"
    )
    accuracy.add_argument("--seeds", type=int, default=20)
    accuracy.add_argument("--rows", type=int, default=5000)
    accuracy.add_argument("--sample-rows", type=int, default=500)
    accuracy.add_argument("--json", action="store_true", help="print the measures as JSON")

    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0

    if args.command == "synth":
        from .synth import write_shop

        for p in write_shop(
            args.directory, clean=args.clean, drift=args.drift, rows=args.rows, seed=args.seed
        ):
            print(p)
        return 0
    if args.command == "bench-schema":
        from .bench import DEFAULT_MIX, create_schema

        try:
            n = create_schema(args.url, schema=args.schema, mix=args.mix or DEFAULT_MIX, progress=print)
        except UsageError as e:
            print(f"sahifa: {e}", file=sys.stderr)
            return 2
        print(f"{n} tables in schema {args.schema}")
        return 0
    if args.command == "bench-accuracy":
        from .accuracy import render_markdown, run_benchmark

        try:
            result = run_benchmark(
                seeds=args.seeds,
                rows=args.rows,
                sample_rows=args.sample_rows,
                progress=lambda m: print(m, file=sys.stderr),
            )
        except UsageError as e:
            print(f"sahifa: {e}", file=sys.stderr)
            return 2
        print(json.dumps(result.as_dict(), indent=2) if args.json else render_markdown(result))
        return 0
    if args.command == "checks":
        from .checks import CATALOGUE

        for c in CATALOGUE:
            print(f"{c.type:<24} {c.dimension.value:<13} {c.kind:<9} {c.severity.value:<9} {c.release}")
        return 0

    from .scan import ScanOptions, run_scan

    try:
        report = run_scan(
            args.source if len(args.source) > 1 else args.source[0],
            ScanOptions(
                sample_rows=0 if args.all_rows else args.sample_rows,
                seed=args.seed,
                workers=max(1, args.workers),
            ),
        )
    except UsageError as e:
        print(f"sahifa: {e}", file=sys.stderr)
        return 2
    except SahifaError as e:
        print(f"sahifa: {e}", file=sys.stderr)
        return 3
    data = report.model_dump(mode="json")
    if args.out:
        args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(json.dumps(data, ensure_ascii=False) if args.json else pretty(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
