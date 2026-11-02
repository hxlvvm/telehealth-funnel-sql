"""End-to-end: generate seeded data with planted answers, run the SQL, and check the answers come back."""
import json
from decimal import Decimal

import pytest

from funnel.generate import generate
from funnel.run import build


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    raw = tmp_path_factory.mktemp("raw")
    truth = generate(raw, seed=7)
    return build(raw), truth


def test_spend_reconciles_to_each_platform_to_the_cent(run):
    con, truth = run
    got = dict(con.execute("select channel, sum(cost_usd) from stg_spend group by 1").fetchall())
    assert {k: Decimal(v) for k, v in truth["spend_usd"].items()} == got


def test_every_contact_lands_on_the_right_person(run):
    con, truth = run
    contacts, persons = con.execute("select count(*), count(distinct person_id) from contact_person").fetchone()
    assert contacts == truth["contacts"]
    assert persons == truth["persons"]


def test_crm_local_time_converts_to_utc_across_dst(run):
    # Each web contact is created by the CRM 5-60 s after its form-submit event. A wrong time zone (or ignoring
    # daylight saving) would put them 5-6 hours apart.
    con, _ = run
    worst = con.execute("""
        select max(abs(epoch(c.created_at_utc) - epoch(e.event_time_utc)))
        from stg_contacts c
        join stg_visits v using (visitor_id)
        join stg_events e on e.visit_id = v.visit_id and e.event_action = 'lead_form_submit'
    """).fetchone()[0]
    assert worst <= 60


def test_first_touch_attribution_matches_truth_per_channel(run):
    con, truth = run
    rows = con.execute("""select channel, count(*), count(*) filter (where booked), sum(occurred)
                      from person_outcome group by 1""").fetchall()
    got = {ch: dict(persons=n, booked_persons=b, occurred_appointments=o) for ch, n, b, o in rows}
    assert got == truth["by_channel"]


def test_hand_made_duplicates_do_not_steal_bookings(run):
    con, _ = run
    # every booking belongs to a person whose first touch came from a real visit
    assert con.execute("select count(*) from person_outcome where channel = 'unattributed' and booked").fetchone()[0] == 0
    # and the duplicates really were there to be merged
    assert con.execute("select count(*) from dim_person where n_contacts > 1").fetchone()[0] > 500


def test_booking_flow_counts_and_interval(run):
    con, truth = run
    t = truth["booking_flow_test"]
    rows = {m: (na, nb, diff, lo, hi) for m, na, nb, diff, lo, hi in con.execute(
        "select metric, n_a, n_b, diff, ci_low, ci_high from mart_booking_flow_test").fetchall()}
    assert rows["lead_rate"][:2] == (t["A"]["visits"], t["B"]["visits"])
    assert rows["booking_rate"][:2] == (t["A"]["lead_persons"], t["B"]["lead_persons"])
    planted = truth["planted"]["book_rate"]
    _, _, diff, lo, hi = rows["booking_rate"]
    assert lo < planted["B"] - planted["A"] < hi      # the interval covers the planted +6 points (this seed)
    assert lo > 0


def test_weekly_mart_keeps_unpaid_channels_and_all_spend(run):
    con, truth = run
    total = con.execute("select sum(spend_usd) from mart_channel_week").fetchone()[0]
    assert total == sum(Decimal(v) for v in truth["spend_usd"].values())
    unpaid = con.execute("select count(*) from mart_channel_week where channel = 'organic_search' and leads > 0").fetchone()[0]
    assert unpaid == 17  # one row per week
