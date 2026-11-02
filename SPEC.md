# Ticket: cost per occurred appointment, by channel and week

**Ask (marketing lead):** "I need to know what we pay for a patient who actually shows up, per channel and
campaign, every week, so I can move budget."

**Done when:** a weekly table and a campaign table exist that a dashboard can read, they reconcile to the ad
platforms, and the definitions below are signed off.

## Definitions

| Term | Definition |
|---|---|
| Contact | One CRM record. A person can have several. |
| Person | Contacts linked by a normalised email (trimmed, lower-case) or phone (last 10 digits), transitively. |
| Lead | A person, counted once, in the week (Central time, Monday start) of their earliest contact. |
| Channel | From the earliest contact. Its own UTM fields if filled in; otherwise the UTMs or referrer of the web visit the form was sent from; otherwise `unattributed`. |
| Booked | The person has at least one appointment of any status. |
| Occurred appointment | An appointment with status `occurred`. A person can have more than one, e.g. after a rebooking. |
| Cost per occurred | Channel spend in the week ÷ occurred appointments of the people who arrived that week. |

## Inputs

- Ad spend exports: Google, Microsoft and Meta, one row per day and campaign, dated in the account time zone
  (Central).
- Web analytics visits and events (UTC).
- CRM contacts (local Central time).
- Scheduler appointments (UTC).

## Edge cases and decisions

1. **Duplicate contacts** made by staff carry no UTM and no visitor id. They must merge into the original
   person and must never become a new lead.
2. **Missing hidden fields.** When the CRM's UTM fields are empty, fall back to the visit, linked by the
   visitor id the form also carries.
3. **Time zones.** CRM timestamps are local and observe daylight saving; all joins happen in UTC, and week
   boundaries are drawn in Central time.
4. **Campaign names** differ in case between platforms and UTMs, so compare them lower-cased and trimmed.
5. **Future appointments** (`scheduled` at export time) count as booked but not as occurred, so the latest
   weeks look worse until they mature. The dashboard should shade the last two weeks.
6. **Unpaid channels** (organic, direct) appear with zero spend. Leaving them out would make the paid share look
   larger than it is.
7. **Out of scope:** refunds or chargebacks on spend, multi-touch attribution, and offline conversions sent
   back to the ad platforms.

## Acceptance criteria

- [x] Spend per platform in the model equals the platform export total to the cent.
- [x] Every contact maps to exactly one person, and the number of people equals the number of distinct real
  patients (checked against planted truth).
- [x] Contact and form-submit event times agree within 60 s after time-zone conversion, across daylight saving.
- [x] Leads, booked people and occurred appointments per channel equal planted truth.
- [x] No booking is attributed to `unattributed`.
- [x] Organic and direct appear in every week.

## Test plan

- **Golden fixtures** (`tests/test_identity.py`): hand-written contacts covering a two-hop identity chain, a
  contact with neither email nor phone, first-touch ordering, and the CDT offset.
- **Planted-truth run** (`tests/test_pipeline.py`): a seeded generator writes the raw exports and the answers;
  each acceptance criterion above is one test.
- **Mutation check:** removing the recursive step from the identity CTE fails the golden tests (verified once
  by hand).
