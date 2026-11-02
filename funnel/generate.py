"""Seeded generator for a synthetic insurance-billed telehealth practice.

It writes the raw exports a marketing-ops person actually receives, each with its own quirks, and a
truth.json holding the answers the SQL pipeline must recover:

- three ad platforms with different column names, money formats and campaign-name casing;
- web analytics visits (UTMs inside the landing URL, a visit-scope A/B dimension) and events (an action-scope
  insurance dimension on the lead form);
- CRM contacts with local-time timestamps, messy emails/phones/UTMs, missing hidden fields, and duplicate
  contacts that staff created by hand;
- appointments booked against either contact of a duplicated person, some still in the future.

All data is synthetic.
"""
import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("America/Chicago")
START = date(2026, 6, 1)        # a Monday
DAYS = 119                      # 17 full weeks
LAUNCH = date(2026, 8, 3)       # booking flow B (insurance check before the form) goes live, 50/50 split
CUTOFF = datetime(2026, 9, 30, tzinfo=LOCAL)  # export time: later appointments are still 'scheduled'

# channel, campaign as the ad platform spells it, clicks/day, cost per click
CAMPAIGNS = [
    ("google_ads", "Brand", 180, 1.10),
    ("google_ads", "Diabetes_Nutrition", 260, 3.40),
    ("google_ads", "PCOS_Dietitian", 200, 2.90),
    ("microsoft_ads", "brand", 60, 0.95),
    ("microsoft_ads", "Weight_Management", 120, 2.60),
    ("meta_ads", "ED_Recovery_Lookalike", 220, 1.40),
    ("meta_ads", "PCOS_Reels", 180, 0.90),
]
UNPAID = [("organic_search", 250), ("direct", 120)]
LEAD_RATE = {"google_ads": 0.08, "microsoft_ads": 0.07, "meta_ads": 0.05, "organic_search": 0.06, "direct": 0.04}
LEAD_RATE_B = 0.92              # flow B: the extra insurance step loses some form submits...
BOOK_RATE = {"A": 0.30, "B": 0.36}  # ...but more of the people who submit go on to book
DUP_RATE = 0.07                 # people who end up with a second, hand-made CRM contact
CARRIERS = ["Aetna", "BCBS IL", "Cigna", "UnitedHealthcare", "Medicare", "Humana"]


def utm_for(channel, campaign, rng):
    if channel == "google_ads":
        return "google", "cpc", campaign.lower()
    if channel == "microsoft_ads":
        return "bing", "cpc", campaign.lower()
    return rng.choice(["facebook", "fb", "instagram", "ig"]), "paid_social", campaign.lower()


def mangle_case(s, rng):
    return rng.choice([s, s.upper(), s.title(), s.lower()])


def fmt_phone(d, rng):
    a, b, c = d[:3], d[3:6], d[6:]
    return rng.choice([f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"+1 {a} {b} {c}", d])


def fmt_email(e, rng):
    e = rng.choice([e, e.upper(), e.capitalize()])
    return rng.choice([e, f" {e}", f"{e} "])


def generate(out_dir, seed=7):
    rng = random.Random(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    spend_rows = {"google_ads": [], "microsoft_ads": [], "meta_ads": []}
    spend_cents = {"google_ads": 0, "microsoft_ads": 0, "meta_ads": 0}
    visits, events, contacts, appts = [], [], [], []
    persons = []        # dicts with the true first-touch channel and arm
    n_visit = n_contact = n_appt = 0

    def new_visit(day, channel, campaign):
        nonlocal n_visit
        n_visit += 1
        local = datetime(day.year, day.month, day.day, tzinfo=LOCAL) + timedelta(seconds=rng.randrange(86400))
        utc = local.astimezone(timezone.utc).replace(tzinfo=None)
        arm = rng.choice("AB") if day >= LAUNCH else ""
        if campaign:
            src, med, camp = utm_for(channel, campaign, rng)
            url = f"https://telehealth.example/lp/{camp}?utm_source={src}&utm_medium={med}&utm_campaign={camp}"
            ref = "campaign"
        else:
            src = med = camp = ""
            url = "https://telehealth.example/"
            ref = "search" if channel == "organic_search" else "direct"
        v = dict(visit_id=f"V{n_visit:07d}", visitor_id=f"u{rng.getrandbits(48):012x}",
                 visit_start_utc=utc.isoformat(sep=" ", timespec="seconds"), landing_url=url,
                 referrer_type=ref, booking_flow=arm)
        visits.append(v)
        events.append(dict(visit_id=v["visit_id"], event_time_utc=v["visit_start_utc"], event_category="page",
                           event_action="page_view", insurance_carrier=""))
        rate = LEAD_RATE[channel] * (LEAD_RATE_B if arm == "B" else 1.0)
        if rng.random() < rate:
            new_lead(v, utc, channel, campaign, src, med, camp, arm or "A", day)

    def add_contact(created_utc, email, phone, utm, visitor_id, carrier):
        nonlocal n_contact
        n_contact += 1
        local = created_utc.replace(tzinfo=timezone.utc).astimezone(LOCAL)
        src, med, camp = utm
        contacts.append(dict(contact_id=f"C{n_contact:07d}", created_at=local.strftime("%Y-%m-%d %H:%M:%S"),
                             email=email, phone=phone, utm_source=src, utm_medium=med, utm_campaign=camp,
                             visitor_id=visitor_id, insurance_carrier=carrier))
        return contacts[-1]["contact_id"]

    def new_lead(v, visit_utc, channel, campaign, src, med, camp, arm, day):
        pid = len(persons)
        carrier = rng.choice(CARRIERS)
        submit = visit_utc + timedelta(seconds=rng.randrange(60, 900))
        if arm == "B" and day >= LAUNCH:
            events.append(dict(visit_id=v["visit_id"], event_time_utc=(submit - timedelta(seconds=30)).isoformat(sep=" "),
                               event_category="booking", event_action="insurance_check", insurance_carrier=carrier))
        events.append(dict(visit_id=v["visit_id"], event_time_utc=submit.isoformat(sep=" "), event_category="booking",
                           event_action="lead_form_submit", insurance_carrier=carrier))
        email = f"patient{pid:06d}@mail.example"
        phone = f"312{pid:07d}"
        utm = ("", "", "") if rng.random() < 0.10 else (mangle_case(src, rng), mangle_case(med, rng), mangle_case(camp, rng))
        created = submit + timedelta(seconds=rng.randrange(5, 60))   # CRM webhook lag
        has_phone = rng.random() > 0.1
        cid = add_contact(created, fmt_email(email, rng), fmt_phone(phone, rng) if has_phone else "",
                          utm, v["visitor_id"], carrier)
        persons.append(dict(pid=pid, channel=channel, campaign=(campaign or "").lower(), arm=arm,
                            post_launch=day >= LAUNCH, first=created, email=email, phone=phone,
                            has_phone=has_phone, contacts=[cid], carrier=carrier))

    for d in range(DAYS):
        day = START + timedelta(days=d)
        for channel, campaign, base, cpc in CAMPAIGNS:
            clicks = int(base * rng.uniform(0.8, 1.2))
            cents = round(clicks * cpc * rng.uniform(0.85, 1.15) * 100)
            spend_cents[channel] += cents
            if channel == "google_ads":
                spend_rows[channel].append(dict(day=day.isoformat(), campaign=campaign, cost_micros=cents * 10000, clicks=clicks))
            elif channel == "microsoft_ads":
                spend_rows[channel].append(dict(TimePeriod=day.strftime("%m/%d/%Y"), CampaignName=campaign,
                                                Spend=f"{cents / 100:,.2f}", Clicks=clicks))
            else:
                spend_rows[channel].append(dict(date_start=day.isoformat(), campaign_name=campaign,
                                                spend=f"{cents / 100:.2f}", inline_link_clicks=clicks))
            for _ in range(clicks):
                new_visit(day, channel, campaign)
        for channel, base in UNPAID:
            for _ in range(int(base * rng.uniform(0.8, 1.2))):
                new_visit(day, channel, None)

    # Duplicates: staff create a second contact by hand days later (no UTM, no visitor id). It always shares the
    # email or the phone, but never in the same format.
    for p in persons:
        if rng.random() < DUP_RATE:
            created = p["first"] + timedelta(days=rng.uniform(1, 10))
            same_email = not p["has_phone"] or rng.random() < 0.5   # a phone-only match needs a phone on file
            cid = add_contact(created, fmt_email(p["email"], rng) if same_email else f"alt{p['pid']:06d}@other.example",
                              fmt_phone(p["phone"], rng), ("", "", ""), "", p["carrier"])
            p["contacts"].append(cid)

    def add_appt(p, booked, status_rates):
        nonlocal n_appt
        n_appt += 1
        when = booked + timedelta(days=rng.uniform(2, 14))
        if when.replace(tzinfo=timezone.utc) > CUTOFF:
            status = "scheduled"
        else:
            r = rng.random()
            status = "occurred" if r < status_rates[0] else "no_show" if r < status_rates[0] + status_rates[1] else "cancelled"
        appts.append(dict(appointment_id=f"A{n_appt:07d}", contact_id=rng.choice(p["contacts"]),
                          booked_at_utc=booked.isoformat(sep=" ", timespec="seconds"),
                          scheduled_for_utc=when.isoformat(sep=" ", timespec="seconds"), status=mangle_case(status, rng)))
        return status, when

    for p in persons:
        p["booked"] = rng.random() < BOOK_RATE[p["arm"]]
        p["occurred"] = 0
        if p["booked"]:
            status, when = add_appt(p, p["first"] + timedelta(hours=rng.uniform(0.1, 72)), (0.82, 0.10))
            p["occurred"] += status == "occurred"
            if status == "cancelled" and rng.random() < 0.5:   # rebooked
                status, _ = add_appt(p, when, (0.85, 0.08))
                p["occurred"] += status == "occurred"

    def write(name, rows):
        with open(out / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)

    write("google_ads.csv", spend_rows["google_ads"])
    write("microsoft_ads.csv", spend_rows["microsoft_ads"])
    write("meta_ads.csv", spend_rows["meta_ads"])
    write("web_visits.csv", visits)
    write("web_events.csv", events)
    write("crm_contacts.csv", contacts)
    write("appointments.csv", appts)

    by_channel = {}
    for p in persons:
        c = by_channel.setdefault(p["channel"], dict(persons=0, booked_persons=0, occurred_appointments=0))
        c["persons"] += 1
        c["booked_persons"] += p["booked"]
        c["occurred_appointments"] += p["occurred"]
    post_visits = {"A": 0, "B": 0}
    for v in visits:
        if v["booking_flow"]:
            post_visits[v["booking_flow"]] += 1
    test = {arm: dict(visits=post_visits[arm],
                      lead_persons=sum(p["post_launch"] and p["arm"] == arm for p in persons),
                      booked_persons=sum(p["post_launch"] and p["arm"] == arm and p["booked"] for p in persons))
            for arm in "AB"}
    truth = dict(seed=seed, spend_usd={k: f"{v / 100:.2f}" for k, v in spend_cents.items()},
                 contacts=len(contacts), persons=len(persons), by_channel=by_channel, booking_flow_test=test,
                 planted=dict(lead_rate_b_multiplier=LEAD_RATE_B, book_rate=BOOK_RATE, launch=LAUNCH.isoformat()))
    (out / "truth.json").write_text(json.dumps(truth, indent=2))
    return truth


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir", nargs="?", default="data/raw")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args()
    t = generate(a.out_dir, a.seed)
    print(f"wrote {a.out_dir}: {t['contacts']} contacts, {t['persons']} people")
