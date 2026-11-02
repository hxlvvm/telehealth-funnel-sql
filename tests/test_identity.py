"""Hand-written golden cases for the identity and cleaning rules."""
import duckdb
import pytest

from funnel.run import ROOT


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""create table raw_crm_contacts as select * from (values
        ('C1', '2026-07-01 09:00:00', 'Jane.Doe@Mail.example ', '(312) 555-0101', 'Google', 'CPC', 'Brand', 'u1', 'Aetna'),
        ('C2', '2026-07-03 10:00:00', 'jdoe@work.example',      '+1 312 555 0101', '',     '',    '',      '',   'Aetna'),
        ('C3', '2026-07-05 11:00:00', ' JDOE@work.example',     '',              '',       '',    '',      '',   'Aetna'),
        ('C4', '2026-07-05 11:00:00', 'solo@mail.example',      '312-555-0199',  'ig',     'paid_social', 'pcos_reels', '', 'Cigna'),
        ('C5', '2026-07-06 08:00:00', '',                       '555-01',        '',       '',    '',      '',   'Cigna')
    ) t(contact_id, created_at, email, phone, utm_source, utm_medium, utm_campaign, visitor_id, insurance_carrier)""")
    c.execute("create table raw_web_visits (visit_id varchar, visitor_id varchar, visit_start_utc varchar, "
              "landing_url varchar, referrer_type varchar, booking_flow varchar)")
    for t in ["raw_google_ads(day varchar, campaign varchar, cost_micros varchar, clicks varchar)",
              "raw_microsoft_ads(TimePeriod varchar, CampaignName varchar, Spend varchar, Clicks varchar)",
              "raw_meta_ads(date_start varchar, campaign_name varchar, spend varchar, inline_link_clicks varchar)",
              "raw_web_events(visit_id varchar, event_time_utc varchar, event_category varchar, event_action varchar, insurance_carrier varchar)",
              "raw_appointments(appointment_id varchar, contact_id varchar, booked_at_utc varchar, scheduled_for_utc varchar, status varchar)"]:
        c.execute(f"create table {t}")
    for sql in sorted((ROOT / "sql").glob("*.sql")):
        c.execute(sql.read_text())
    return c


def test_email_and_phone_links_are_transitive(con):
    # C3 shares only an email with C2 (case, spacing), C2 shares only a phone with C1 (format): C3 reaches C1 in
    # two hops, so a one-hop join would wrongly give C3 the person id C2.
    got = dict(con.execute("select contact_id, person_id from contact_person").fetchall())
    assert got["C1"] == got["C2"] == got["C3"] == "C1"
    assert got["C4"] == "C4"


def test_contact_without_usable_email_or_phone_is_its_own_person(con):
    # C5 has no email and only a 6-digit phone: it must not match anyone, and must not vanish
    assert con.execute("select person_id from contact_person where contact_id = 'C5'").fetchone()[0] == "C5"


def test_first_touch_comes_from_the_earliest_contact(con):
    ch, camp, n = con.execute("select channel, campaign, n_contacts from dim_person where person_id = 'C1'").fetchone()
    assert (ch, camp, n) == ("google_ads", "brand", 3)
    assert con.execute("select channel from dim_person where person_id = 'C4'").fetchone()[0] == "meta_ads"


def test_central_daylight_time_is_five_hours_behind_utc(con):
    ts = con.execute("select created_at_utc from stg_contacts where contact_id = 'C1'").fetchone()[0]
    assert str(ts) == "2026-07-01 14:00:00"
