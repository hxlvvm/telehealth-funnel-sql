"""Load the raw exports into DuckDB, run the SQL layers in order, and print or export the marts."""
import argparse
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
RAW_FILES = ["google_ads", "microsoft_ads", "meta_ads", "web_visits", "web_events", "crm_contacts", "appointments"]
MARTS = ["mart_campaign", "mart_booking_flow_test", "mart_channel_week"]


def build(raw_dir, db=":memory:"):
    con = duckdb.connect(str(db))
    for name in RAW_FILES:
        # all_varchar: every cast happens in sql/01_staging.sql, where it can be read and tested
        con.execute(f"create or replace table raw_{name} as "
                    f"select * from read_csv(?, header = true, all_varchar = true)", [str(Path(raw_dir) / f"{name}.csv")])
    for sql in sorted((ROOT / "sql").glob("*.sql")):
        con.execute(sql.read_text())
    return con


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("raw_dir", nargs="?", default="data/raw")
    ap.add_argument("--db", default=":memory:", help="DuckDB file to keep, e.g. funnel.duckdb for Metabase")
    ap.add_argument("--export", metavar="DIR", help="also write each mart to DIR/<mart>.csv")
    a = ap.parse_args()
    con = build(a.raw_dir, a.db)
    for m in MARTS[:2]:
        print(f"\n== {m}")
        con.table(m).show(max_width=200)
    if a.export:
        Path(a.export).mkdir(parents=True, exist_ok=True)
        for m in MARTS:
            con.table(m).write_csv(str(Path(a.export) / f"{m}.csv"))
        print(f"\nmarts written to {a.export}/")


if __name__ == "__main__":
    main()
