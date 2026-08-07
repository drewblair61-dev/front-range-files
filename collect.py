#!/usr/bin/env python3
"""
Colorado new-business-registration collector — v2

Fixes over v1:
  * County: tries several possible source fields, then falls back to a
    city->county lookup, so the column stops coming back empty.
  * Categories: word-boundary matching (v1 tagged "Space Battalion" as
    beauty because "Space" contains "spa"), plus real-estate detection
    for the address-named holding LLCs that dominate the feed.
  * Flags entities whose principal address is outside Colorado.
  * Logs the available source fields on the first run so mismatches are
    visible instead of silent.

Source: Colorado Information Marketplace (Socrata), dataset 4ykn-tg5h
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

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("collector")


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
    county_source   TEXT,
    out_of_state    INTEGER,
    agent_name      TEXT,
    category        TEXT,
    first_seen      TEXT,
    raw             TEXT
);
CREATE INDEX IF NOT EXISTS idx_formation ON entities(formation_date);
CREATE INDEX IF NOT EXISTS idx_county ON entities(county);
CREATE INDEX IF NOT EXISTS idx_category ON entities(category);

CREATE TABLE IF NOT EXISTS runs (
    run_at TEXT, fetched INTEGER, inserted INTEGER, ok INTEGER, note TEXT
);
"""


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    # Let v1 databases pick up the new columns without being rebuilt.
    existing = {r[1] for r in conn.execute("PRAGMA table_info(entities)")}
    for col, decl in [("county_source", "TEXT"), ("out_of_state", "INTEGER")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE entities ADD COLUMN {col} {decl}")
    conn.commit()
    return conn


# ---------- county resolution ----------

# Socrata column names vary between dataset revisions. Try each in turn.
COUNTY_FIELDS = ["principalcounty", "entitycounty", "county",
                 "principal_county", "principaladdresscounty"]

# Colorado's population is concentrated in a handful of counties, so a
# modest city lookup covers most filings. Anything unmatched stays blank
# rather than being guessed at.
CITY_COUNTY = {
    "denver": "Denver", "aurora": "Arapahoe", "centennial": "Arapahoe",
    "littleton": "Arapahoe", "englewood": "Arapahoe", "greenwood village": "Arapahoe",
    "lakewood": "Jefferson", "arvada": "Jefferson", "golden": "Jefferson",
    "wheat ridge": "Jefferson", "westminster": "Jefferson", "evergreen": "Jefferson",
    "littleton co": "Arapahoe",
    "colorado springs": "El Paso", "fountain": "El Paso", "monument": "El Paso",
    "fort carson": "El Paso", "peyton": "El Paso", "falcon": "El Paso",
    "boulder": "Boulder", "longmont": "Boulder", "louisville": "Boulder",
    "lafayette": "Boulder", "superior": "Boulder", "nederland": "Boulder",
    "fort collins": "Larimer", "loveland": "Larimer", "estes park": "Larimer",
    "wellington": "Larimer", "windsor": "Weld",
    "greeley": "Weld", "evans": "Weld", "brighton": "Adams", "erie": "Weld",
    "thornton": "Adams", "northglenn": "Adams", "commerce city": "Adams",
    "federal heights": "Adams", "bennett": "Adams",
    "castle rock": "Douglas", "parker": "Douglas", "lone tree": "Douglas",
    "highlands ranch": "Douglas", "castle pines": "Douglas",
    "pueblo": "Pueblo", "pueblo west": "Pueblo",
    "grand junction": "Mesa", "fruita": "Mesa", "palisade": "Mesa",
    "durango": "La Plata", "bayfield": "La Plata",
    "steamboat springs": "Routt", "craig": "Moffat",
    "glenwood springs": "Garfield", "rifle": "Garfield", "carbondale": "Garfield",
    "aspen": "Pitkin", "vail": "Eagle", "avon": "Eagle", "edwards": "Eagle",
    "breckenridge": "Summit", "frisco": "Summit", "silverthorne": "Summit",
    "dillon": "Summit", "keystone": "Summit",
    "montrose": "Montrose", "delta": "Delta", "gunnison": "Gunnison",
    "crested butte": "Gunnison", "salida": "Chaffee", "buena vista": "Chaffee",
    "canon city": "Fremont", "florence": "Fremont",
    "trinidad": "Las Animas", "walsenburg": "Huerfano",
    "alamosa": "Alamosa", "monte vista": "Rio Grande",
    "sterling": "Logan", "fort morgan": "Morgan", "brush": "Morgan",
    "lamar": "Prowers", "la junta": "Otero", "rocky ford": "Otero",
    "burlington": "Kit Carson", "limon": "Lincoln", "julesburg": "Sedgwick",
    "telluride": "San Miguel", "ouray": "Ouray", "silverton": "San Juan",
    "pagosa springs": "Archuleta", "cortez": "Montezuma", "mancos": "Montezuma",
    "woodland park": "Teller", "cripple creek": "Teller",
    "idaho springs": "Clear Creek", "georgetown": "Clear Creek",
    "black hawk": "Gilpin", "central city": "Gilpin",
    "leadville": "Lake", "fairplay": "Park", "bailey": "Park",
    "walden": "Jackson", "hot sulphur springs": "Grand",
    "granby": "Grand", "winter park": "Grand", "kremmling": "Grand",
    "meeker": "Rio Blanco", "rangely": "Rio Blanco",
    "eaton": "Weld", "ault": "Weld", "platteville": "Weld", "firestone": "Weld",
    "frederick": "Weld", "dacono": "Weld", "johnstown": "Weld", "mead": "Weld",
    "berthoud": "Larimer", "timnath": "Larimer",
    "elizabeth": "Elbert", "kiowa": "Elbert",
    "strasburg": "Adams", "watkins": "Adams",
}


def resolve_county(record, city, state):
    """Return (county, source). Blank beats a wrong guess."""
    for field in COUNTY_FIELDS:
        value = record.get(field)
        if value and str(value).strip():
            return str(value).strip().title(), "source"
    if state and state != "CO":
        return "", "out_of_state"
    hit = CITY_COUNTY.get((city or "").strip().lower())
    return (hit, "city_lookup") if hit else ("", "unresolved")


# ---------- categories ----------

# Matched with word boundaries. v1 used substrings, which tagged
# "Space Battalion" as beauty because "Space" contains "spa".
CATEGORY_RULES = {
    "food_beverage": ["restaurant", "cafe", "coffee", "bakery", "brewing",
                      "brewery", "kitchen", "catering", "pizza", "taco",
                      "grill", "bistro", "deli", "juice", "eatery", "diner",
                      "taqueria", "sushi", "bbq", "barbecue", "creamery",
                      "distillery", "winery", "cantina", "noodle", "burger"],
    "construction": ["construction", "contracting", "contractors", "roofing",
                     "plumbing", "electrical", "electric", "hvac", "remodeling",
                     "remodel", "builders", "building", "concrete", "landscaping",
                     "landscape", "excavating", "excavation", "paving", "drywall",
                     "painting", "flooring", "carpentry", "masonry", "fencing",
                     "handyman", "restoration", "insulation", "framing",
                     "welding", "fabrication", "roofers", "plumbers",
                     "hardscape", "gutter", "siding", "windows", "doors",
                     "renovation", "renovations", "utilities", "septic"],
    "real_estate": ["realty", "real estate", "properties", "property",
                    "homes", "estates", "land", "rentals", "leasing",
                    "development", "investments", "capital", "equity"],
    "retail": ["boutique", "shop", "store", "retail", "market", "supply",
               "outfitters", "apparel", "goods", "mercantile", "emporium",
               "trading", "gallery"],
    "health": ["dental", "dentistry", "clinic", "wellness", "therapy",
               "chiropractic", "medical", "health", "massage", "counseling",
               "psychiatry", "psychology", "pharmacy", "nursing", "hospice",
               "homecare", "podiatry", "optometry", "veterinary"],
    "beauty": ["salon", "spa", "barber", "barbershop", "nails", "beauty",
               "aesthetics", "esthetics", "lash", "lashes", "brows",
               "cosmetics", "skincare", "hair"],
    "professional": ["consulting", "consultants", "advisors", "advisory",
                     "accounting", "cpa", "bookkeeping", "law", "legal",
                     "attorney", "tax", "insurance", "agency", "marketing",
                     "design", "media", "studios", "solutions", "partners",
                     "associates", "staffing", "recruiting"],
    "transport": ["trucking", "logistics", "transport", "transportation",
                  "hauling", "delivery", "courier", "moving", "movers",
                  "freight", "carriers", "dispatch", "towing"],
    "fitness": ["fitness", "gym", "yoga", "pilates", "crossfit", "athletics",
                "athletic", "training", "martial arts", "dance"],
    "auto": ["automotive", "auto", "motors", "collision", "detailing",
             "tire", "tires", "mechanic", "garage"],
    "cleaning": ["cleaning", "janitorial", "maid", "housekeeping",
                 "sanitation", "carpet"],
    "tech": ["software", "technologies", "technology", "systems", "digital",
             "data", "cyber", "computing", "labs", "networks"],
}

COMPILED = {
    cat: re.compile(r"\b(" + "|".join(re.escape(k) for k in kws) + r")\b", re.I)
    for cat, kws in CATEGORY_RULES.items()
}

# A large share of new Colorado LLCs are single-property holding entities
# named after the address, e.g. "10710 Reunion Parkway LLC". Catching
# these turns the biggest chunk of "other" into a segment you can sell.
ADDRESS_NAME = re.compile(
    r"^\s*\d{2,6}\s+[\w.'-]+(\s+[\w.'-]+)*\s+"
    r"(st|street|ave|avenue|rd|road|dr|drive|ln|lane|ct|court|pl|place|"
    r"blvd|boulevard|way|cir|circle|pkwy|parkway|ter|terrace|trl|trail|"
    r"hwy|highway)\b", re.I)


def categorize(name):
    if not name:
        return "other"
    cleaned = re.sub(r"[^\w\s&'-]", " ", name)
    if ADDRESS_NAME.match(cleaned):
        return "real_estate"
    # Specific industries win over the broad real_estate keyword list.
    order = [c for c in COMPILED if c != "real_estate"] + ["real_estate"]
    for cat in order:
        if COMPILED[cat].search(cleaned):
            return cat
    return "other"


# ---------- normalization ----------

STREET_FIXES = [(r"\bST\.?\b", "STREET"), (r"\bAVE\.?\b", "AVENUE"),
                (r"\bRD\.?\b", "ROAD"), (r"\bBLVD\.?\b", "BOULEVARD"),
                (r"\bDR\.?\b", "DRIVE"), (r"\bLN\.?\b", "LANE"),
                (r"\bCT\.?\b", "COURT"), (r"\bSTE\.?\b", "SUITE"),
                (r"\bPKWY\.?\b", "PARKWAY"), (r"\bCIR\.?\b", "CIRCLE")]


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def title_street(value):
    out = clean(value).upper()
    for pattern, repl in STREET_FIXES:
        out = re.sub(pattern, repl, out)
    return out.title()


def zip5(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:5] if len(digits) >= 5 else ""


def normalize(record):
    name = clean(record.get("entityname"))
    city = clean(record.get("principalcity")).title()
    state = clean(record.get("principalstate")).upper()
    county, source = resolve_county(record, city, state)
    return {
        "entity_id":     clean(record.get("entityid")),
        "entity_name":   name,
        "entity_type":   clean(record.get("entitytype")),
        "entity_status": clean(record.get("entitystatus")),
        "formation_date": (record.get("entityformdate") or "")[:10],
        "street":        title_street(record.get("principaladdress1")),
        "city":          city,
        "state":         state,
        "zip5":          zip5(record.get("principalzipcode")),
        "county":        county,
        "county_source": source,
        "out_of_state":  1 if (state and state != "CO") else 0,
        "agent_name":    clean(f"{record.get('agentfirstname','')} "
                               f"{record.get('agentlastname','')}"),
        "category":      categorize(name),
        "first_seen":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "raw":           json.dumps(record, separators=(",", ":")),
    }


# ---------- fetch ----------

def fetch_since(since_date, session=None):
    session = session or requests.Session()
    headers = {"X-App-Token": APP_TOKEN} if APP_TOKEN else {}
    offset, out, logged = 0, [], False

    while True:
        params = {"$where": f"entityformdate >= '{since_date}T00:00:00.000'",
                  "$order": "entityformdate DESC",
                  "$limit": PAGE_SIZE, "$offset": offset}
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

        # Print the real field names once so a mismatch is visible in the log.
        if not logged:
            log.info("SOURCE FIELDS: %s", sorted(page[0].keys()))
            found = [f for f in COUNTY_FIELDS if f in page[0]]
            log.info("county field present: %s", found or "NONE — using city lookup")
            logged = True

        out.extend(page)
        log.info("fetched %d (total %d)", len(page), len(out))
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return out


# ---------- main ----------

COLS = ["entity_id", "entity_name", "entity_type", "entity_status",
        "formation_date", "street", "city", "state", "zip5", "county",
        "county_source", "out_of_state", "agent_name", "category",
        "first_seen", "raw"]


def store(conn, rows):
    before = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    conn.executemany(
        f"INSERT OR IGNORE INTO entities ({','.join(COLS)}) "
        f"VALUES ({','.join(':' + c for c in COLS)})", rows)
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0] - before


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

        # Quality readout — watch these numbers each run.
        filled = sum(1 for r in rows if r["county"])
        oos = sum(1 for r in rows if r["out_of_state"])
        cats = {}
        for r in rows:
            cats[r["category"]] = cats.get(r["category"], 0) + 1
        log.info("fetched=%d inserted=%d", fetched, inserted)
        log.info("county filled: %d/%d (%.0f%%)", filled, len(rows),
                 100 * filled / max(len(rows), 1))
        log.info("out-of-state principal address: %d", oos)
        log.info("categories: %s", dict(sorted(cats.items(),
                                               key=lambda x: -x[1])))
        if fetched == 0:
            ok, note = 0, "zero rows from source — check the feed"
    except Exception as exc:
        ok, note = 0, str(exc)
        log.error("run failed: %s", exc)

    conn.execute("INSERT INTO runs VALUES (?,?,?,?,?)",
                 (datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  fetched, inserted, ok, note))
    conn.commit()
    conn.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
