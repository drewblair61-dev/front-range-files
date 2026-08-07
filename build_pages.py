#!/usr/bin/env python3
"""
Generates static county x category pages from entities.db.

Each page shows the 10 most recent filings in full, then gates the rest
behind an email signup. Real counts and dates stay visible so the page
has genuine substance for search engines and for a visitor deciding
whether the full list is worth an email.

Only generates a page when the segment has at least MIN_ROWS records —
thin pages with two rows on them hurt the whole site's standing.

Output: docs/  (point GitHub Pages at this folder)
"""

import os
import re
import html
import sqlite3
from datetime import datetime, timedelta, timezone
from collections import Counter

DB_PATH = os.environ.get("DB_PATH", "entities.db")
OUT = os.environ.get("PAGES_DIR", "docs")
SITE = os.environ.get("SITE_NAME", "Front Range Filings")
BASE = os.environ.get("BASE_URL", "")          # e.g. https://yourdomain.com
FORM = os.environ.get("FORM_ACTION", "#")      # your email form endpoint
GSV = os.environ.get("GOOGLE_VERIFY", "")      # Search Console verification code
WINDOW_DAYS = 30
MIN_ROWS = 8          # below this, no page
PREVIEW_ROWS = 10     # shown in full before the gate

CATEGORY_LABEL = {
    "construction": "Construction", "real_estate": "Real Estate",
    "food_beverage": "Food & Beverage", "professional": "Professional Services",
    "retail": "Retail", "health": "Health & Medical", "beauty": "Beauty & Salon",
    "transport": "Transport & Trucking", "fitness": "Fitness", "auto": "Automotive",
    "cleaning": "Cleaning Services", "tech": "Technology", "other": "Other",
}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")


def esc(text):
    return html.escape(str(text or ""))


# ---------- template ----------

CSS = """
:root{--ink:#16232E;--soft:#4A5A66;--paper:#F2F3EF;--card:#FBFBF9;
--rule:#D6D9D0;--pen:#2F5D8C;--deep:#1E4165;--stamp:#B0342C}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font:17px/1.6 'Source Sans 3',system-ui,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:0 22px}
a{color:var(--deep)}
header{border-bottom:2px solid var(--ink);padding:16px 0}
header .wrap{display:flex;justify-content:space-between;align-items:baseline;
gap:14px;flex-wrap:wrap}
.mark{font-weight:700;font-size:18px;text-decoration:none;color:var(--ink)}
.mark span{color:var(--pen)}
.asof{font-family:ui-monospace,monospace;font-size:12px;color:var(--soft);
text-transform:uppercase;letter-spacing:.07em}
h1{font-size:clamp(27px,4.2vw,40px);line-height:1.12;letter-spacing:-.015em;
margin:44px 0 0;max-width:19ch}
.lede{color:var(--soft);max-width:60ch;margin-top:15px}
.stats{display:flex;gap:34px;flex-wrap:wrap;margin:30px 0 8px;
padding:18px 0;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule)}
.stat b{display:block;font-size:29px;font-weight:700;line-height:1.1}
.stat span{font-family:ui-monospace,monospace;font-size:11px;color:var(--soft);
text-transform:uppercase;letter-spacing:.09em}
table{width:100%;border-collapse:collapse;font-size:15px;margin-top:30px}
th{font-family:ui-monospace,monospace;font-size:11px;font-weight:500;
letter-spacing:.08em;text-transform:uppercase;color:var(--soft);text-align:left;
padding:10px 12px;border-bottom:1px solid var(--rule);white-space:nowrap}
td{padding:10px 12px;border-bottom:1px solid #E8EAE3}
.nm{font-weight:600}
.mono{font-family:ui-monospace,monospace;font-size:13px;color:var(--soft);
white-space:nowrap}
.scroll{overflow-x:auto}
.gate{margin-top:0;padding:28px 24px;background:var(--card);
border:2px solid var(--ink);border-top:0;border-radius:0 0 3px 3px}
.gate h2{font-size:22px;margin:0}
.gate p{color:var(--soft);margin:9px 0 17px;max-width:52ch}
.f{display:flex;gap:9px;flex-wrap:wrap}
.f input{flex:1 1 250px;font:16px inherit;padding:12px 13px;
border:1px solid var(--rule);border-radius:2px;background:#fff}
.f button{font:600 16px inherit;padding:12px 22px;background:var(--deep);
color:#fff;border:0;border-radius:2px;cursor:pointer}
.f button:hover{background:var(--pen)}
.fine{font-size:13px;color:var(--soft);margin-top:12px}
.src{margin:44px 0;padding:17px 19px;background:var(--card);
border-left:3px solid var(--pen);font-size:15px;color:var(--soft)}
.rel{margin:44px 0}
.rel h2{font-size:20px;margin-bottom:14px}
.rel ul{list-style:none;padding:0;columns:2;column-gap:26px}
.rel li{margin-bottom:7px;break-inside:avoid;font-size:15.5px}
footer{border-top:2px solid var(--ink);padding:26px 0 46px;
font-size:13.5px;color:var(--soft);margin-top:44px}
:focus-visible{outline:2px solid var(--pen);outline-offset:2px}
@media(max-width:620px){.rel ul{columns:1}.stats{gap:22px}}
"""


def page(title, desc, h1, lede, stats, rows, hidden, county, category,
         related, canonical):
    head_rows = "".join(
        f"<tr><td class='nm'>{esc(r[0])}</td><td class='mono'>{esc(r[1])}</td>"
        f"<td>{esc(r[2])}</td><td class='mono'>{esc(r[3])}</td></tr>"
        for r in rows)

    stat_html = "".join(
        f"<div class='stat'><b>{v}</b><span>{k}</span></div>" for k, v in stats)

    rel_html = ""
    if related:
        items = "".join(f"<li><a href='{u}'>{esc(t)}</a></li>" for t, u in related)
        rel_html = f"<div class='rel'><h2>Other segments</h2><ul>{items}</ul></div>"

    gate = ""
    if hidden > 0:
        gate = f"""
<div class="gate">
  <h2>{hidden} more {esc(category)} filings from the last 30 days</h2>
  <p>The full list, with street addresses and registered agents, as a
     spreadsheet. Free, one email, no card.</p>
  <form class="f" action="{FORM}" method="post">
    <input type="hidden" name="segment" value="{esc(county)}|{esc(category)}">
    <input type="email" name="email" placeholder="you@company.com" required
           aria-label="Email address">
    <button type="submit">Send me the full list</button>
  </form>
  <p class="fine">One email with the file attached. Unsubscribe in one click.</p>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
{f'<meta name="google-site-verification" content="{GSV}">' if GSV else ''}
{f'<link rel="canonical" href="{canonical}">' if canonical else ''}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<header><div class="wrap">
  <a class="mark" href="{BASE or '/'}">Front Range <span>Filings</span></a>
  <div class="asof">Updated {datetime.now(timezone.utc).strftime('%d %b %Y')}</div>
</div></header>

<div class="wrap">
  <h1>{esc(h1)}</h1>
  <p class="lede">{esc(lede)}</p>
  <div class="stats">{stat_html}</div>
  <div class="scroll"><table>
    <thead><tr><th>Business name</th><th>Registered</th><th>City</th><th>Type</th></tr></thead>
    <tbody>{head_rows}</tbody>
  </table></div>
  {gate}

  <div class="src">
    Every record here comes from the Colorado Secretary of State's public
    open data portal, pulled daily. {esc(SITE)} is an independent service and
    is not affiliated with or endorsed by the State of Colorado.
  </div>

  {rel_html}
</div>

<footer><div class="wrap">
  Business registration data is public record published by the State of
  Colorado. Any outreach you do using it remains subject to CAN-SPAM, the
  TCPA, and Colorado telemarketing rules.
</div></footer>
</body></html>"""


# ---------- generation ----------

def main():
    conn = sqlite3.connect(DB_PATH)
    since = (datetime.now(timezone.utc)
             - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    os.makedirs(OUT, exist_ok=True)

    segments = conn.execute(
        """SELECT county, category, COUNT(*) c FROM entities
           WHERE formation_date >= ? AND county != '' AND out_of_state = 0
           GROUP BY county, category HAVING c >= ?
           ORDER BY c DESC""", (since, MIN_ROWS)).fetchall()

    print(f"{len(segments)} segments clear the {MIN_ROWS}-row minimum")

    # Build the link map first so pages can cross-reference each other.
    paths = {(c, k): f"/{slug(c)}-county-{slug(k)}.html" for c, k, _ in segments}
    by_county = {}
    for (c, k), p in paths.items():
        by_county.setdefault(c, []).append((CATEGORY_LABEL.get(k, k), p))

    written, urls = 0, []
    for county, category, total in segments:
        label = CATEGORY_LABEL.get(category, category.title())
        rows = conn.execute(
            """SELECT entity_name, formation_date, city, entity_type
               FROM entities WHERE county=? AND category=? AND formation_date>=?
               AND out_of_state=0 ORDER BY formation_date DESC LIMIT ?""",
            (county, category, since, PREVIEW_ROWS)).fetchall()

        cities = Counter(r[0] for r in conn.execute(
            "SELECT city FROM entities WHERE county=? AND category=? "
            "AND formation_date>=? AND out_of_state=0",
            (county, category, since)))
        top_city = cities.most_common(1)[0][0] if cities else county
        newest = rows[0][1] if rows else ""
        hidden = max(total - len(rows), 0)

        fname = f"{slug(county)}-county-{slug(category)}.html"
        canonical = f"{BASE}/{fname}" if BASE else ""

        related = [(t, u) for t, u in by_county.get(county, [])
                   if u != f"/{fname}"][:12]

        content = page(
            title=f"New {label} Businesses in {county} County, Colorado — Updated Daily",
            desc=(f"{total} new {label.lower()} businesses registered in "
                  f"{county} County in the last 30 days. Names, dates, and "
                  f"cities from official Colorado records."),
            h1=f"New {label.lower()} businesses in {county} County",
            lede=(f"{total} {label.lower()} businesses registered in {county} "
                  f"County over the last 30 days. Most recent first, pulled "
                  f"daily from the Colorado Secretary of State."),
            stats=[("Last 30 days", total), ("Top city", top_city),
                   ("Newest filing", newest)],
            rows=rows, hidden=hidden, county=county, category=label,
            related=related, canonical=canonical)

        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as fh:
            fh.write(content)
        written += 1
        urls.append(fname)

    # Homepage. Without one, the county pages are orphans and crawlers
    # have no single entry point to follow.
    total_all = conn.execute(
        "SELECT COUNT(*) FROM entities WHERE formation_date >= ? "
        "AND out_of_state = 0", (since,)).fetchone()[0]

    blocks = []
    for county in sorted(by_county):
        links = "".join(f"<li><a href='{u}'>{esc(t)}</a></li>"
                        for t, u in sorted(by_county[county]))
        blocks.append(f"<div class='rel'><h2>{esc(county)} County</h2>"
                      f"<ul>{links}</ul></div>")

    home = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>New Colorado Business Registrations — Updated Daily | {esc(SITE)}</title>
<meta name="description" content="Browse new businesses registered in Colorado
by county and industry. {total_all} filings in the last 30 days, pulled daily
from official state records.">
{f'<meta name="google-site-verification" content="{GSV}">' if GSV else ''}
{f'<link rel="canonical" href="{BASE}/">' if BASE else ''}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head>
<body>
<header><div class="wrap">
  <a class="mark" href="{BASE or '/'}">Front Range <span>Filings</span></a>
  <div class="asof">Updated {datetime.now(timezone.utc).strftime('%d %b %Y')}</div>
</div></header>
<div class="wrap">
  <h1>New Colorado business registrations, by county and industry</h1>
  <p class="lede">Every business registered with the Colorado Secretary of
  State, sorted into the segments people actually sell to. Pulled daily from
  the state's public open data portal.</p>
  <div class="stats">
    <div class="stat"><b>{total_all}</b><span>Filings, last 30 days</span></div>
    <div class="stat"><b>{len(by_county)}</b><span>Counties covered</span></div>
    <div class="stat"><b>{len(segments)}</b><span>Segments tracked</span></div>
  </div>
  {''.join(blocks)}
  <div class="src">
    Records come from the Colorado Secretary of State's public open data
    portal. {esc(SITE)} is independent and not affiliated with or endorsed
    by the State of Colorado.
  </div>
</div>
<footer><div class="wrap">
  Business registration data is public record. Any outreach you do using it
  remains subject to CAN-SPAM, the TCPA, and Colorado telemarketing rules.
</div></footer>
</body></html>"""

    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(home)
    urls.insert(0, "")
    print("wrote index.html")

    # sitemap so search engines find all of them
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entries = "".join(
        f"<url><loc>{BASE}/{u}</loc><lastmod>{today}</lastmod>"
        f"<changefreq>daily</changefreq></url>" for u in urls)
    with open(os.path.join(OUT, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>'
                 '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 f'{entries}</urlset>')

    with open(os.path.join(OUT, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n")

    print(f"wrote {written} pages + sitemap.xml + robots.txt to {OUT}/")
    conn.close()


if __name__ == "__main__":
    main()
