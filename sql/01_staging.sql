-- Staging: one clean, typed row per source record. Raw tables are loaded as all-VARCHAR (raw_<file>), so every
-- cast and every cleaning rule is written down here, not guessed by a CSV sniffer.

-- The business reports in Central time, web analytics and the scheduler export UTC, the CRM exports local time.
create or replace macro utc_to_local(ts) as timezone('America/Chicago', ts at time zone 'UTC');
create or replace macro local_to_utc(ts) as timezone('UTC', ts at time zone 'America/Chicago');

-- One channel vocabulary for every source. UTMs arrive in any case and several spellings.
create or replace macro channel_of(src, med, ref) as
    case
        when lower(trim(med)) in ('cpc', 'ppc', 'paid') and lower(trim(src)) = 'google' then 'google_ads'
        when lower(trim(med)) in ('cpc', 'ppc', 'paid') and lower(trim(src)) in ('bing', 'microsoft') then 'microsoft_ads'
        when lower(trim(med)) in ('paid_social', 'cpc', 'paid')
             and lower(trim(src)) in ('facebook', 'fb', 'instagram', 'ig', 'meta') then 'meta_ads'
        when coalesce(trim(src), '') = '' and ref = 'search' then 'organic_search'
        when coalesce(trim(src), '') = '' and ref = 'direct' then 'direct'
        else 'other'
    end;

-- Ad spend: three schemas into one. Google reports micros, Microsoft formats money with thousands separators,
-- Meta sends a plain decimal. Campaign names are matched case-insensitively against utm_campaign.
create or replace view stg_spend as
select cast(day as date)                                         as spend_date,
       'google_ads'                                              as channel,
       lower(trim(campaign))                                     as campaign,
       cast(cast(cost_micros as decimal(18, 0)) * 0.000001 as decimal(14, 2)) as cost_usd,  -- exact, no float
       cast(clicks as integer)                                   as clicks
from raw_google_ads
union all
select strptime(TimePeriod, '%m/%d/%Y')::date, 'microsoft_ads', lower(trim(CampaignName)),
       cast(replace(Spend, ',', '') as decimal(14, 2)), cast(Clicks as integer)
from raw_microsoft_ads
union all
select cast(date_start as date), 'meta_ads', lower(trim(campaign_name)),
       cast(spend as decimal(14, 2)), cast(inline_link_clicks as integer)
from raw_meta_ads;

-- Visits: UTMs live inside the landing URL. booking_flow is a visit-scope custom dimension (blank before launch).
create or replace view stg_visits as
with v as (
    select visit_id, visitor_id, cast(visit_start_utc as timestamp) as visit_start_utc, referrer_type,
           nullif(booking_flow, '')                                    as booking_flow,
           regexp_extract(landing_url, '[?&]utm_source=([^&]*)', 1)   as utm_source,
           regexp_extract(landing_url, '[?&]utm_medium=([^&]*)', 1)   as utm_medium,
           regexp_extract(landing_url, '[?&]utm_campaign=([^&]*)', 1) as utm_campaign
    from raw_web_visits
)
select visit_id, visitor_id, visit_start_utc,
       cast(utc_to_local(visit_start_utc) as date)      as visit_date_local,
       channel_of(utm_source, utm_medium, referrer_type) as channel,
       nullif(lower(utm_campaign), '')                   as campaign,
       booking_flow
from v;

-- Events: insurance_carrier is an action-scope dimension, set only on booking events.
create or replace view stg_events as
select visit_id, cast(event_time_utc as timestamp) as event_time_utc, event_category, event_action,
       nullif(insurance_carrier, '') as insurance_carrier
from raw_web_events;

-- CRM contacts: local timestamps to UTC, emails trimmed and lower-cased, phones reduced to 10 digits.
create or replace view stg_contacts as
with c as (
    select *, regexp_replace(phone, '[^0-9]', '', 'g') as phone_digits from raw_crm_contacts
)
select contact_id,
       local_to_utc(strptime(created_at, '%Y-%m-%d %H:%M:%S'))           as created_at_utc,
       nullif(lower(trim(email)), '')                                    as email_norm,
       case when length(phone_digits) >= 10 then right(phone_digits, 10) end as phone_norm,
       nullif(trim(utm_source), '')                                      as utm_source,
       nullif(trim(utm_medium), '')                                      as utm_medium,
       nullif(lower(trim(utm_campaign)), '')                             as utm_campaign,
       nullif(visitor_id, '')                                            as visitor_id,
       insurance_carrier
from c;

-- Appointments: status arrives in any case; 'scheduled' means still in the future at export time.
create or replace view stg_appointments as
select appointment_id, contact_id,
       cast(booked_at_utc as timestamp)     as booked_at_utc,
       cast(scheduled_for_utc as timestamp) as scheduled_for_utc,
       lower(trim(status))                  as status
from raw_appointments;
