-- Core: who is a person, where did each contact come from, and which person owns each appointment.

-- Identity. Contacts sharing a normalised email OR phone are the same person, transitively: if A shares an email
-- with B and B shares a phone with C, all three are one person. The person id is the smallest contact id.
create or replace table contact_person as
with recursive edges as (
    select a.contact_id as src, b.contact_id as dst
    from stg_contacts a join stg_contacts b on a.email_norm = b.email_norm
    union
    select a.contact_id, b.contact_id
    from stg_contacts a join stg_contacts b on a.phone_norm = b.phone_norm
),
reach(src, dst) as (
    select src, dst from edges
    union
    select r.src, e.dst from reach r join edges e on r.dst = e.src
)
select c.contact_id, coalesce(min(r.dst), c.contact_id) as person_id
from stg_contacts c left join reach r on r.src = c.contact_id
group by c.contact_id;

-- Source of each contact: the CRM's hidden UTM fields when present, else the web visit the form was sent from
-- (joined on the visitor id the form also carries). Hand-made contacts have neither.
create or replace table contact_touch as
select c.contact_id, cp.person_id, c.created_at_utc, c.visitor_id,
       case when c.utm_source is not null then channel_of(c.utm_source, c.utm_medium, null)
            else coalesce(v.channel, 'unattributed') end as channel,
       case when c.utm_source is not null then c.utm_campaign else v.campaign end as campaign,
       v.booking_flow, v.visit_date_local
from stg_contacts c
join contact_person cp using (contact_id)
left join stg_visits v on v.visitor_id = c.visitor_id;

-- One row per person, first-touch attributed: the channel of their earliest contact.
create or replace table dim_person as
select person_id,
       min(created_at_utc)                                 as first_contact_utc,
       cast(utc_to_local(min(created_at_utc)) as date)     as first_contact_date_local,
       arg_min(channel, created_at_utc)                    as channel,
       arg_min(campaign, created_at_utc)                   as campaign,
       arg_min(booking_flow, created_at_utc)               as booking_flow,
       arg_min(visit_date_local, created_at_utc)           as first_visit_date_local,
       count(*)                                            as n_contacts
from contact_touch
group by person_id;

create or replace table fct_appointment as
select a.*, cp.person_id
from stg_appointments a join contact_person cp using (contact_id);

-- Person-level outcomes used by every mart.
create or replace table person_outcome as
select p.*,
       count(a.appointment_id) > 0                       as booked,
       count(a.appointment_id)                           as appointments,
       count(*) filter (where a.status = 'occurred')    as occurred,
       count(*) filter (where a.status = 'no_show')     as no_shows
from dim_person p left join fct_appointment a using (person_id)
group by all;
