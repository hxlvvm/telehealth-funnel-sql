# telehealth-funnel-sql

Marketing analytics for an insurance-billed telehealth practice, written as a layered SQL model in DuckDB.
It joins ad spend from three platforms, web analytics, CRM contacts and appointments, and answers the
question a marketing team actually asks: **what does one *occurred* appointment cost, per channel and
campaign, and did the new booking flow help?**

All data is synthetic. A seeded generator writes the raw exports, quirks included, together with the
answers the SQL has to recover. The tests check that the SQL gets those answers back exactly, so they are
not just smoke tests.

## What the raw data gets wrong (on purpose)

| Source | Problem the SQL has to handle |
|---|---|
| Google Ads | cost in micros |
| Microsoft Ads | `MM/DD/YYYY` dates, money as `"1,234.56"` strings |
| Meta Ads | different column names; campaign names in a different case than the UTMs |
| Web analytics | UTMs only inside the landing URL; A/B arm stored as a visit-scope custom dimension |
| CRM | timestamps in **Central local time** (the others are UTC), emails with stray case and spaces, phones in four formats, 10% of hidden UTM fields empty |
| CRM | 7% of people have a second contact that staff typed in by hand: no UTM, no visitor id, matching the first only by email *or* phone |
| Scheduler | status in mixed case; appointments after the export date are still `scheduled` |

## Layers

```
sql/01_staging.sql   typed, cleaned views: one row per source record, one channel vocabulary
sql/02_core.sql      identity (transitive email/phone matching), first-touch attribution, person outcomes
sql/03_marts.sql     mart_channel_week, mart_campaign, mart_booking_flow_test
```

- **Identity.** A recursive CTE treats contacts as one person if they share a normalised email or phone,
  transitively.
- **Attribution.** First touch: the channel of a person's earliest contact. The CRM's hidden UTM fields are
  used when present; otherwise the web visit the form came from.
- **Cohorts.** Bookings and occurred appointments count towards the week the person first arrived, so spend
  and outcomes line up.

See [SPEC.md](SPEC.md) for the definitions, edge cases and acceptance criteria, written as the engineering
ticket. See [TRACKING_PLAN.md](TRACKING_PLAN.md) for the event and custom-dimension design the model relies on.

## Results (synthetic, seed 7, 17 weeks)

12,995 CRM contacts resolve to 12,162 people (833 people had duplicate contacts).

| Channel | Spend | Leads | Booked | Occurred | Cost per occurred appointment |
|---|---:|---:|---:|---:|---:|
| Google Ads | $201,823.46 | 6,018 | 1,906 | 1,533 | $131.65 |
| Microsoft Ads | $43,701.31 | 1,487 | 462 | 374 | $116.85 |
| Meta Ads | $55,372.20 | 2,280 | 721 | 570 | $97.14 |
| Organic search | – | 1,748 | 537 | 445 | – |
| Direct | – | 629 | 207 | 167 | – |

Per campaign, cost per occurred appointment ranges from $54 (Google brand) to $181 (Google diabetes
nutrition). That gap is what a budget decision is made on.

**Booking-flow test.** Flow B asks for insurance before the contact form. Visitors were split 50/50 from 3 Aug.

| Metric | A | B | B − A (95% CI) |
|---|---:|---:|---|
| Lead rate per visit | 6.45% | 5.97% | −0.47 pts (−0.79 to −0.16) |
| Booking rate per lead | 29.4% | 35.8% | +6.4 pts (+4.0 to +8.9) |
| Booked people per visit | 1.89% | 2.14% | +0.25 pts (+0.06 to +0.43), +13% relative |

Flow B loses some form submits but gains more bookings, and the per-visit metric is the one that decides. The
generator planted lead rate ×0.92 and booking rate 30% → 36% (a true +10.4% per visit). The intervals cover
those values.

## Run it

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m funnel.generate data/raw              # about 4 s, about 40 MB of CSV
.venv/bin/python -m funnel.run data/raw --export results  # prints the marts, writes CSVs
.venv/bin/python -m funnel.run data/raw --db funnel.duckdb # keep a file a BI tool can read
.venv/bin/python -m pytest -q                             # 11 tests: planted-truth checks + golden cases
```

## What would change on real data

- **Attribution model.** First touch is a choice, not a fact. With real data I would add last-touch and
  position-based views next to it, and show where they disagree.
- **Phone-only matches.** Two people can share a household phone. On real data I'd flag phone-only matches
  for review instead of merging them silently.
- **The test.** The Wald interval assumes independent visits. Returning visitors break that a little, and the
  test was not pre-registered with a stopping rule. On a live test I would fix the sample size first.
- **Reconciliation.** Spend reconciles to the cent here by construction. In production the check would be
  against each platform's own UI totals, run daily.

MIT licence.
