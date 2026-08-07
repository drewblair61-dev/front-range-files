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
CONTACT = os.environ.get("CONTACT_EMAIL", "")  # shown on privacy/terms pages
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
  <p><a href="{BASE}/privacy.html">Privacy</a> &nbsp;·&nbsp;
     <a href="{BASE}/terms.html">Terms</a></p>
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

    # Privacy and terms. Generated automatically so they stay in sync with
    # the site and can never be forgotten before the email form goes live.
    legal_css = CSS + """
.legal h2{font-size:20px;margin:32px 0 8px}
.legal p,.legal li{color:var(--soft);max-width:64ch}
.legal ul{padding-left:20px}
"""
    updated = datetime.now(timezone.utc).strftime("%d %B %Y")
    mail = (f'<a href="mailto:{CONTACT}">{esc(CONTACT)}</a>'
            if CONTACT else "the contact address on this site")

    def legal_page(title, body):
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — {esc(SITE)}</title>
<meta name="robots" content="noindex">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet">
<style>{legal_css}</style>
</head>
<body>
<header><div class="wrap">
  <a class="mark" href="{BASE or '/'}">Front Range <span>Filings</span></a>
  <div class="asof">Updated {updated}</div>
</div></header>
<div class="wrap legal">
  <h1>{esc(title)}</h1>
  {body}
</div>
<footer><div class="wrap">
  <a href="{BASE}/privacy.html">Privacy</a> &nbsp;·&nbsp;
  <a href="{BASE}/terms.html">Terms</a>
</div></footer>
</body></html>"""

    privacy_body = f"""
<p class="lede">This site publishes public business registration records and
offers an optional email list. This page explains what happens to your data.
Last updated {updated}.</p>

<h2>What we collect</h2>
<p>Only your email address, and only if you type it into a form here. We also
record which segment you asked about, so we know which file to send you.</p>

<h2>What we do with it</h2>
<p>We send you the file you requested, and occasionally an email about this
service. Nothing else.</p>

<h2>What we never do</h2>
<p>We do not sell, rent, trade, or share your email address. We do not add you
to third-party marketing lists. We do not use it for advertising.</p>

<h2>Who else touches it</h2>
<p>Form submissions are handled by our form provider, and email delivery by our
email provider. Each processes data on our behalf under its own privacy policy.
The site itself is hosted by GitHub Pages, which records standard server logs.</p>

<h2>The business records on this site</h2>
<p>The business registration data published here comes from the Colorado
Secretary of State's public open data portal. These are public records
maintained by the State of Colorado, not by us. If you are a business owner and
a record about your company is wrong, the correction must be made with the
Secretary of State — we mirror the official data and cannot alter it. Once the
state updates its record, our next daily pull reflects the change.</p>

<h2>Your rights</h2>
<p>Email {mail} to see what we hold about you, correct it, or have it deleted.
We will action it within 30 days. Every email we send has a working unsubscribe
link.</p>

<h2>How long we keep it</h2>
<p>While you are subscribed, and for 12 months after you unsubscribe for
accounting records. Then it is deleted.</p>

<h2>Cookies</h2>
<p>This site sets no tracking cookies and runs no advertising trackers.</p>

<h2>Changes</h2>
<p>Updates are posted on this page with a new date at the top.</p>
"""

    terms_body = f"""
<p class="lede">Plain terms for using this site and its email list.
Last updated {updated}.</p>

<h2>1. What this site is</h2>
<p>A free directory of new business registrations in Colorado, compiled from
the Colorado Secretary of State's public open data portal, with an optional
email list that sends fuller versions of the same data.</p>

<h2>2. Not affiliated with the State</h2>
<p>{esc(SITE)} is an independent service. We are not affiliated with, endorsed
by, or acting on behalf of the Colorado Secretary of State or any government
body. Do not contact the State about this site.</p>

<h2>3. What we do not promise</h2>
<p>The data originates with the State of Colorado and we do not control it. We
do not guarantee it is complete, current, or free of errors. Industry
categories are assigned automatically from business names and will sometimes be
wrong. We do not promise any commercial result from using this data. The
service is provided "as is" and may be unavailable or delayed.</p>

<h2>4. Your responsibilities</h2>
<p>You are solely responsible for how you contact anyone whose details appear
here. That includes compliance with the CAN-SPAM Act, the Telephone Consumer
Protection Act, federal and state Do Not Call registries, Colorado telemarketing
law, and any other rule that applies to your outreach. We publish public record
data. We do not provide consent to contact anyone. You agree to indemnify us
against claims arising from your outreach.</p>

<h2>5. Acceptable use</h2>
<p>Use this data for your own business. Do not republish or resell our compiled
files as a competing data product, and do not use automated tools that place
unreasonable load on this site. The underlying records are free from the State
of Colorado if you want to build your own.</p>

<h2>6. Removal requests</h2>
<p>These are public records published by the State of Colorado. If you want a
record changed, the change must be made at the source with the Secretary of
State. Contact {mail} if you believe we have displayed something incorrectly.</p>

<h2>7. Changes</h2>
<p>We may update these terms. Continued use after an update means you accept
it.</p>

<h2>8. Governing law</h2>
<p>These terms are governed by the laws of the United States and the state in
which the operator resides.</p>
"""

    with open(os.path.join(OUT, "privacy.html"), "w", encoding="utf-8") as fh:
        fh.write(legal_page("Privacy Policy", privacy_body))
    with open(os.path.join(OUT, "terms.html"), "w", encoding="utf-8") as fh:
        fh.write(legal_page("Terms of Use", terms_body))
    print("wrote privacy.html + terms.html")

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
