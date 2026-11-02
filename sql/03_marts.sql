-- Marts: what the dashboard (Metabase or similar) reads. Weeks start on Monday, in Central time.
-- People are counted in the week of their first contact (cohort view), so a booking made in a later week still
-- counts towards the week that the spend brought the person in.

create or replace table mart_channel_week as
with spend as (
    select date_trunc('week', spend_date) as week, channel, sum(cost_usd) as spend_usd, sum(clicks) as clicks
    from stg_spend group by all
),
people as (
    select date_trunc('week', first_contact_date_local) as week, channel,
           count(*) as leads, count(*) filter (where booked) as booked, sum(occurred)::bigint as occurred
    from person_outcome group by all
)
select coalesce(s.week, p.week)::date          as week,
       coalesce(s.channel, p.channel)          as channel,
       coalesce(s.spend_usd, 0)                as spend_usd,
       coalesce(s.clicks, 0)                   as clicks,
       coalesce(p.leads, 0)                    as leads,
       coalesce(p.booked, 0)                   as booked_people,
       coalesce(p.occurred, 0)                 as occurred_appointments,
       round(s.spend_usd / nullif(p.leads, 0), 2)    as cost_per_lead,
       round(s.spend_usd / nullif(p.occurred, 0), 2) as cost_per_occurred
from spend s full outer join people p on s.week = p.week and s.channel = p.channel
order by week, channel;

-- Whole-period view per paid campaign: the number a marketing lead actually asks for.
create or replace table mart_campaign as
with spend as (
    select channel, campaign, sum(cost_usd) as spend_usd from stg_spend group by all
),
people as (
    select channel, campaign, count(*) as leads, count(*) filter (where booked) as booked, sum(occurred)::bigint as occurred
    from person_outcome group by all
)
select s.channel, s.campaign, s.spend_usd, p.leads, p.booked as booked_people, p.occurred as occurred_appointments,
       round(s.spend_usd / nullif(p.leads, 0), 2)    as cost_per_lead,
       round(s.spend_usd / nullif(p.booked, 0), 2)   as cost_per_booked,
       round(s.spend_usd / nullif(p.occurred, 0), 2) as cost_per_occurred
from spend s left join people p using (channel, campaign)
order by cost_per_occurred;

-- Booking-flow A/B test (flow B asks for insurance before the form). Visitors are split 50/50 from launch.
-- Three rates, each B minus A with a 95% Wald interval:
--   lead_rate     = people whose first contact came from a visit in the arm / visits in the arm
--   booking_rate  = booked people / those people
--   booked_per_visit = booked people / visits   (the one that pays the bills)
create or replace table mart_booking_flow_test as
with arms as (
    select booking_flow as arm,
           (select count(*) from stg_visits v where v.booking_flow = p.booking_flow) as visits,
           count(*)                         as lead_people,
           count(*) filter (where booked)   as booked_people
    from person_outcome p
    where booking_flow is not null
    group by booking_flow
),
rates as (
    select metric, arm, n, k, k / n as p from arms,
    lateral (values ('lead_rate', visits, lead_people),
                    ('booking_rate', lead_people, booked_people),
                    ('booked_per_visit', visits, booked_people)) as t(metric, n, k)
)
select a.metric, a.n as n_a, a.p as rate_a, b.n as n_b, b.p as rate_b,
       b.p - a.p                                                          as diff,
       b.p - a.p - 1.96 * sqrt(a.p * (1 - a.p) / a.n + b.p * (1 - b.p) / b.n) as ci_low,
       b.p - a.p + 1.96 * sqrt(a.p * (1 - a.p) / a.n + b.p * (1 - b.p) / b.n) as ci_high,
       (b.p - a.p) / a.p                                                  as relative_lift
from rates a join rates b on a.metric = b.metric and a.arm = 'A' and b.arm = 'B'
order by a.metric;
