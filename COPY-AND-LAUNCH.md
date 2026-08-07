# Colorado New Business Feed — copy and launch pack

Working name: **Front Range Filings**. Swap it if you have better.

---

## Positioning

**Who buys:** salespeople and small service businesses in Colorado who sell to
brand-new companies — commercial insurance agents, bookkeepers and CPAs,
merchant services reps, business bankers, web designers, signage and print
shops, commercial cleaners, IT support shops.

**Why they buy:** a business registered last week has no vendors yet. The first
credible provider to reach them usually wins. Existing feeds are national,
expensive, and full of stale records. You are local, filtered, and cheap.

**Your actual edge is not the data.** Colorado gives it away free. Your edge is
that it arrives filtered to their county and their industry, deduped, with
addresses cleaned, in a spreadsheet they can use in thirty seconds. That's the
work they're paying you to skip.

---

## Pricing

| Tier | Price | What they get |
|---|---|---|
| County Weekly | $39/mo | One county, one industry category, weekly CSV |
| Statewide Weekly | $89/mo | All Colorado, all categories, weekly CSV |
| Statewide Daily | $149/mo | All Colorado, delivered every weekday |

Annual = 10 months. Offer a 14-day free trial — it removes the only real
objection and costs you nothing, since delivery is automated.

Do not launch below $39. Cheap data subscriptions attract the customers who
complain most and churn fastest.

---

## Landing page

### Headline
**Every new Colorado business, in your inbox before your competitors find them.**

### Subhead
Filtered to your county and your industry. Cleaned, deduped, and delivered as a
spreadsheet every Monday morning. Straight from official Colorado Secretary of
State records.

### The three-bullet value prop
- **Fresh.** Pulled daily from the state's official registration feed, not a
  recycled list someone sold five times already.
- **Filtered.** Pick your counties and industries. You get 40 relevant records,
  not 4,000 irrelevant ones.
- **Ready to use.** Clean addresses, standard industry tags, no duplicates.
  Import it into your CRM and start working.

### Primary CTA
**Get 25 free leads from last week** → [email field] → Send them to me

### Secondary CTA
Start a 14-day free trial — $39/month after

### Trust block
Sourced entirely from the Colorado Secretary of State's public open-data
portal. No scraping, no gray-market lists. Cancel anytime from your receipt.

### Sample table
Show 8 real rows on the page. Blur nothing. Seeing the actual columns is what
converts.

### FAQ
**Where does the data come from?** The Colorado Secretary of State publishes
business registrations as open data. We pull it daily, clean it, and filter it.

**How fresh is it?** Records reach us within days of the filing being processed
by the state.

**Do you include phone numbers and emails?** No. We provide what the state
publishes: business name, address, entity type, formation date, and registered
agent. Anyone promising verified emails on brand-new filings is guessing.

**Can I get a different state?** Not yet. Colorado only. Reply to any email and
tell me which state you want — it decides what I build next.

**How do I cancel?** One click in your receipt email. No conversation required.

**Is this legal to use for outreach?** The data is public record. Your outreach
still has to follow CAN-SPAM, TCPA, and Colorado's telemarketing rules. That
part is on you.

---

## Email sequence

### Email 1 — immediately after they request the free sample
**Subject:** Your 25 Colorado leads are attached

Attached are 25 businesses that registered in Colorado in the last seven days.
Real records, straight from the state.

Two things worth knowing before you use them:

1. Sort by formation date and work the newest first. A business that filed
   three days ago is a different conversation than one that filed in March.
2. The registered agent is often the owner's attorney or filing service, not
   the owner. Use the principal address.

I pull this daily and send a filtered version every Monday. If that's useful,
the trial's free for 14 days: [link]

### Email 2 — day 2
**Subject:** The mistake most people make with new-business lists

Most people buy a list of 5,000 new businesses and email all of them.

That fails for a boring reason: a new bakery and a new trucking company have
nothing in common except a filing date. The pitch that works for one is noise
to the other.

Filtering to one industry in one county gets you 30–60 records a week. It feels
too small. It converts several times better, because you can write one message
that's actually right for all of them.

That's the whole product: [link]

### Email 3 — day 4
**Subject:** Why I don't sell you email addresses

Every competitor advertises verified emails on new business filings.

Here's the problem. A company that registered nine days ago usually has no
website, no domain, and no published email. Vendors "verify" these by guessing
patterns against a domain that doesn't exist yet. That's how you end up with a
40% bounce rate and a burned sending domain.

What the state actually publishes is a name, a physical address, an entity
type, and a formation date. That's enough for direct mail, for a walk-in, for a
LinkedIn lookup, or for a phone call. It's honest data.

If you'd rather have real records than inflated ones: [link]

### Email 4 — day 7, objection handling
**Subject:** "Can't I just get this free from the state?"

Yes. Genuinely — Colorado publishes it, and the API is public. If you're
technical and enjoy this kind of thing, go build it. I'll send you the dataset
ID.

What you'd be signing up for: paging a million-row API, deduping against your
own history, cleaning addresses, tagging industries, and fixing it every time
the schema shifts. Call it fifteen hours to build and an hour a month forever.

$39 is roughly twenty minutes of your billable time. That's the trade.

Trial's here if you'd rather skip it: [link]

### Email 5 — day 10, close
**Subject:** Closing your trial Friday

Your trial ends Friday. No action needed if you'd rather stop — nothing bills
and I won't chase you.

If you did use the list: reply with the county and industry you want and I'll
set your filters before the next send.

One thing worth saying plainly. This works if you contact people. The list
doesn't sell anything by itself. The subscribers who renew are the ones who
picked a lane, wrote one good message, and sent it every Monday.

[Continue for $39/month]

---

## Launch checklist — what only you can do

1. Register a free Socrata app token at
   data.colorado.gov/profile/edit/developer_settings, add it to your GitHub
   repo as the secret `SOCRATA_APP_TOKEN`.
2. Push this folder to a private GitHub repo. The Action runs daily, free.
3. Run once manually. Confirm the row count looks sane before you sell anything.
4. Backfill 90 days by setting `LOOKBACK_DAYS=90` for one run.
5. Create a Stripe account and three Payment Links at $39 / $89 / $149.
6. Put up the landing page (Carrd, ~$19/yr, or a static page on Vercel, free).
7. Connect the email list (MailerLite free to 1,000 subscribers).
8. Publish the free sample and the landing page where the buyers already are —
   r/sales, Colorado small-business Facebook groups, local BNI chapters online,
   insurance and bookkeeping forums. Follow each community's self-promotion rules.
9. Write three SEO pages: "new businesses registered in Denver County",
   "Colorado LLC filings this week", "how to find newly formed businesses in
   Colorado". Low competition, high intent.

## Compliance notes

- Data is official Colorado open data used within its published terms. Keep it
  that way. Do not add scraped sources later without checking their terms.
- Add a privacy policy and terms page before taking payment. Stripe expects it.
- Your subscribers' outreach is subject to CAN-SPAM and TCPA. Say so in your
  terms so their compliance failures aren't your problem.
- Never claim your data includes verified contact information. It doesn't.
