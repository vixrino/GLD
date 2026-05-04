"""Canonical long-format schema. Every connector outputs at minimum these columns.

Long-format rationale: one row = one observation. Quants can then pivot/join at will.

Example row:
    date=2025-10-01, value=2650.3, metric="gold_close_usd", unit="usd/oz",
    source="yahoo", ingested_at=2025-10-01T22:05:00Z
"""

CANONICAL_COLUMNS = [
    "date",          # datetime64[ns]  — the observation date (T-1 or T)
    "metric",        # str             — what is measured (e.g. "GLD_tonnes", "real_yield_10y")
    "value",         # float           — numeric observation
    "unit",          # str             — "usd/oz", "tonnes", "bps", "contracts", "pct", ...
    "source",        # str             — provenance (e.g. "fred", "cftc_cot", "spdr_gld")
    "ingested_at",   # datetime64[ns, UTC]
]
