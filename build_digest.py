#!/usr/bin/env python3
"""
Builds one CSV per active subscriber, filtered to what they pay for.

Reads:  entities.db (populated by collect.py)
        subscribers.csv  -> email,tier,counties,categories,active
Writes: out/<email>_<date>.csv  plus out/sample_<date>.csv (free lead magnet)

Tiers:  county   = one county, weekly
        state    = all Colorado, weekly
        daily    = all Colorado, daily
"""

import csv
import os
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = os.environ.get("DB_PATH", "entities.db")
OUT_DIR = os.environ.get("OUT_DIR", "out")
SUBS = os.environ.get("SUBS_PATH", "subscribers.csv")

FIELDS = ["entity_name", "entity_type", "formation_date", "street",
          "city", "county", "zip5", "category", "agent_name", "entity_id"]


def load_subscribers(path=SUBS):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh)
                if r.get("active", "").strip().lower() in ("1", "true", "yes")]


def query(conn, days, counties=None, categories=None):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    sql = f"SELECT {','.join(FIELDS)} FROM entities WHERE formation_date >= ?"
    args = [since]

    if counties:
        sql += f" AND county IN ({','.join('?' * len(counties))})"
        args += [c.strip().title() for c in counties]
    if categories:
        sql += f" AND category IN ({','.join('?' * len(categories))})"
        args += [c.strip().lower() for c in categories]

    sql += " ORDER BY formation_date DESC, entity_name"
    return conn.execute(sql, args).fetchall()


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(FIELDS)
        writer.writerows(rows)
    return len(rows)


def main():
    conn = sqlite3.connect(DB_PATH)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Free sample: last 7 days, capped at 25 rows. This is the lead magnet.
    sample = query(conn, days=7)[:25]
    write_csv(f"{OUT_DIR}/sample_{stamp}.csv", sample)
    print(f"sample: {len(sample)} rows")

    for sub in load_subscribers():
        tier = sub.get("tier", "county").strip().lower()
        days = 1 if tier == "daily" else 7
        counties = [c for c in sub.get("counties", "").split("|") if c] \
            if tier == "county" else None
        categories = [c for c in sub.get("categories", "").split("|") if c] or None

        rows = query(conn, days=days, counties=counties, categories=categories)
        safe = sub["email"].replace("@", "_at_").replace(".", "_")
        count = write_csv(f"{OUT_DIR}/{safe}_{stamp}.csv", rows)
        print(f"{sub['email']}: {count} rows ({tier})")

        # An empty file is a refund request waiting to happen. Flag it.
        if count == 0:
            print(f"  WARNING: empty digest for {sub['email']} — widen filters")

    conn.close()


if __name__ == "__main__":
    main()
