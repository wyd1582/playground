"""make views — (re)create the OPS.md A.3 views and print each one through DuckDB."""
from __future__ import annotations

import sys

import pandas as pd

from registry import Registry

VIEWS = ["v_funnel", "v_cost_per_promotion", "v_adoption", "v_realized", "v_drift", "v_diversity", "v_critic_quality",
         "v_marker_value", "v_customer_scorecard"]


def main() -> int:
    reg = Registry()
    reg.create_views()
    try:
        import duckdb
        con = duckdb.connect()
        for v in VIEWS:
            df = reg.df(f"SELECT * FROM {v}")
            con.register(v, df)
            print(f"\n== {v} ({len(df)} rows, via DuckDB) ==")
            print(con.execute(f"SELECT * FROM {v} LIMIT 20").df().to_string(index=False) if len(df) else "(empty)")
    except ImportError:
        for v in VIEWS:
            df = reg.df(f"SELECT * FROM {v}")
            print(f"\n== {v} ({len(df)} rows) ==")
            print(df.head(20).to_string(index=False) if len(df) else "(empty)")
    return 0


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    sys.exit(main())
