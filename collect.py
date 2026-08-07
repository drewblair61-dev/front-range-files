#!/usr/bin/env python3
"""
Colorado new-business-registration collector.

Source: Colorado Information Marketplace (Socrata), dataset 4ykn-tg5h
        "Business Entities in Colorado" — official state open data.

Pulls entities registered since the last run, normalizes them, dedupes
against what's already stored, and writes new rows to SQLite.

Run daily. Set SOCRATA_APP_TOKEN for a higher rate-limit tier
(free, from data.colorado.gov/profile/edit/developer_settings).
"""

import os
import re
import sys
import json
import time
import sqlite3
import logging
from datetime import datetime, timedelta, timezone

import requests

DOMAIN = "data.colorado.gov"
DATASET = "4ykn-tg5h"
ENDPOINT = f"https://{DOMAIN}/resource/{DATASET}.json"
APP_TOKEN = os.environ.get("SOCRATA_APP_TOKEN", "")
DB_PATH = os.environ.get("DB_PATH", "entities.db")
PAGE_SIZE = 1000
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "7"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("collector")


# ---------- storage ----------

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id       TEXT PRIMARY KEY,
    entity_name     TEXT,
    entity_type     TEXT,
    entity_status   TEXT,
    formation_date  TEXT,
    street          TEXT,
    city            TEXT,
    state           TEXT,
    zip5            TEXT,
    county          TEXT,
    agent_name      TEXT,
    category        TEXT,
    first_seen      TEXT,
    raw             TEXT
);
CREATE INDEX IF NOT EXISTS idx_formation ON entities(formation_date);
CREATE INDEX IF NOT EXISTS idx_city ON entities(city);
CREATE INDEX IF NOT EXISTS idx_category ON entities(category);

CREATE TABLE IF NOT EXISTS runs (
    run_at      TEXT,
    fetched     INTEGER,
    inserted    INTEGER,
    ok          INTEGER,
    note        TEXT
);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


# ---------- normalization ----------

STREET_FIXES = [
    (r"\bST\.?\b", "Street"), (r"\bAVE\.?\b", "Avenue"),
    (r"\bRD\.?\b", "Road"), (r"\bBLVD\.?\b", "Boulevard"),
    (r"\bDR\.?\b", "Drive"), (r"\bLN\.?\b", "Lane"),
    (r"\bCT\.?\b", "Court"), (r"\bSTE\.?\b", "Suite"),
]

# Crude but useful industry guess from the entity name. This is the
# enrichment buyers actually pay for — refine the keyword lists as you
# learn which categories your subscribers care about.
CATEGORY_RULES = {
    "food_beverage": ["restaurant", "cafe", "coffee", "bakery", "brewing",
                      "brewery", "kitchen", "catering", "pizza", "taco",
                      "grill", "bar ", "bistro", "deli", "juice", "food"],
    "construction":  ["construction", "contracting", "roofing", "plumbing",
                      "electric", "hvac", "remodel", "builders", "concrete",
                      "landscaping", "excavat", "paving", "drywall"],
    "retail":        ["boutique", "shop", "store", "retail", "goods",
                      "market", "supply", "outfitters", "apparel"],
    "health":        ["dental", "clinic", "wellness", "therapy", "chiro",
                      "medical", "health", "massage", "counseling", "care"],
    "beauty":        ["salon", "spa", "barber", "nails", "beauty",
                      "aesthetic", "lash", "hair"],
    "professional":  ["consulting", "advisors", "accounting", "cpa", "law",
                      "legal", "bookkeep", "tax", "insurance", "realty",
                      "real estate", "agency", "marketing", "design"],
    "transport":     ["trucking", "logistics", "transport", "hauling",
                      "delivery", "courier", "moving"],
    "fitness":       ["fitness", "gym", "yoga", "pilates", "crossfit",
                      "training", "athletic"],
}


def clean_name(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def title_street(value):
    if not value:
        return ""
    out = re.sub(r"\s+", " ", str(value)).strip().upper()
    for pattern, replacement in STREET_FIXES:
        out = re.sub(pattern, replacement.upper(), out)
    return out.title()


def zip5(value):
    if not value:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits[:5] if len(digits) >= 5 else ""


def categorize(name):
    lowered = (name or "").lower()
    for category, keywords in CATEGORY_RULES.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return "other"


def normalize(record):
    """Map one raw Socrata record to our schema."""
    name = clean_name(record.get("entityname"))
    return {
        "entity_id":      clean_name(record.get("entityid")),
        "entity_name":    name,
        "entity_type":    clean_name(record.get("entitytype")),
        "entity_status":  clean_name(record.get("entitystatus")),
        "formation_date": (record.get("entityformdate") or "")[:10],
        "street":         title_street(record.get("principaladdress1")),
        "city":           clean_name(record.get("principalcity")).title(),
        "state":          clean_name(record.get("principalstate")).upper(),
        "zip5":           zip5(record.get("principalzipcode")),
        "county":         clean_name(record.get("principalcounty")).title(),
        "agent_name":     clean_name(record.get("agentfirstname", "") + " "
                                     + record.get("agentlastname", "")),
        "category":       categorize(name),
        "first_seen":     datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw":            json.dumps(record, separators=(",", ":")),
    }


# ---------- fetching ----------

def fetch_since(since_date, session=None):
    """Page through Socrata for entities formed on/after since_date."""
    session = session or requests.Session()
    headers = {"X-App-Token": APP_TOKEN} if APP_TOKEN else {}
    offset, out = 0, []

    while True:
        params = {
            "$where": f"entityformdate >= '{since_date}T00:00:00.000'",
            "$order": "entityformdate DESC",
            "$limit": PAGE_SIZE,
            "$offset": offset,
        }
        for attempt in range(4):
            try:
                resp = session.get(ENDPOINT, params=params,
                                   headers=headers, timeout=60)
                resp.raise_for_status()
                page = resp.json()
                break
            except Exception as exc:
                wait = 2 ** attempt
                log.warning("fetch failed (%s), retry in %ss", exc, wait)
                time.sleep(wait)
        else:
            raise RuntimeError("giving up after 4 attempts")

        if not page:
            break
        out.extend(page)
        log.info("fetched %d (total %d)", len(page), len(out))
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return out


# ---------- main ----------

def store(conn, rows):
    """Insert, ignoring entity_ids we already have. Returns count inserted."""
    before = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    conn.executemany(
        """INSERT OR IGNORE INTO entities
           (entity_id, entity_name, entity_type, entity_status,
            formation_date, street, city, state, zip5, county,
            agent_name, category, first_seen, raw)
           VALUES (:entity_id, :entity_name, :entity_type, :entity_status,
                   :formation_date, :street, :city, :state, :zip5, :county,
                   :agent_name, :category, :first_seen, :raw)""",
        rows,
    )
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    return after - before


def main():
    since = (datetime.now(timezone.utc)
             - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    conn = connect()
    fetched = inserted = 0
    ok, note = 1, ""

    try:
        raw = fetch_since(since)
        fetched = len(raw)
        rows = [normalize(r) for r in raw]
        rows = [r for r in rows if r["entity_id"] and r["entity_name"]]
        inserted = store(conn, rows)
        log.info("fetched=%d inserted=%d", fetched, inserted)
        # A run that inserts nothing usually means the feed broke, not that
        # Colorado stopped registering businesses. Treat it as a failure.
        if inserted == 0:
            ok, note = 0, "zero new rows — check the source"
    except Exception as exc:
        ok, note = 0, str(exc)
        log.error("run failed: %s", exc)

    conn.execute(
        "INSERT INTO runs (run_at, fetched, inserted, ok, note) VALUES (?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),
         fetched, inserted, ok, note),
    )
    conn.commit()
    conn.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
