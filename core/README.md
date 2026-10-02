# sahifa-core

The Sahifa engine: connectors (DuckDB for files, Postgres), sampling, column profiles, the
check catalogue, scoring with 95 % intervals, the scan report and the `sahifa` CLI. See the
repository README and `docs/` for the design.

```bash
uv sync
uv run sahifa synth /tmp/shop
uv run sahifa scan /tmp/shop --pretty
```
