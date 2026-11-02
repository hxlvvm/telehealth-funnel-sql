# Tracking plan

What the website must send so that spend can be joined to bookings. The SQL model assumes exactly this.

## UTM convention

| Parameter | Rule | Example |
|---|---|---|
| `utm_source` | platform, lower-case | `google`, `bing`, `facebook`, `instagram` |
| `utm_medium` | `cpc` for search ads, `paid_social` for social ads | `cpc` |
| `utm_campaign` | the campaign name exactly as in the ad platform, lower-case | `pcos_dietitian` |

The model also accepts the spellings it sees in practice (`fb`, `ig`, `CPC`, `Google`). The convention is
there to keep that list short.

## Events

| Category | Action | When | Dimension sent |
|---|---|---|---|
| `page` | `page_view` | every page | – |
| `booking` | `insurance_check` | flow B only: the insurance step is completed | `insurance_carrier` |
| `booking` | `lead_form_submit` | the contact form is submitted successfully (not on click) | `insurance_carrier` |

## Custom dimensions

| Name | Scope | Values | Why that scope |
|---|---|---|---|
| `booking_flow` | **visit** | `A`, `B` | It describes the whole visit's experience, and one value per visit lets the test be analysed per visit. |
| `insurance_carrier` | **action** | carrier name | It belongs to the specific booking event; a visit may change its answer. |

## Hand-off to the CRM

The contact form posts these hidden fields with every submission: `utm_source`, `utm_medium`, `utm_campaign`
(copied from the landing URL, persisted for the session) and `visitor_id` (the analytics visitor id). If the
UTM fields come through empty, the `visitor_id` still links the contact back to its visit, which is how the
model recovers the 10% of contacts with lost hidden fields.

## What breaks the model

- A form that fires `lead_form_submit` on click instead of on success over-counts leads.
- Redirects that drop the query string remove the UTMs. The visit then shows as direct.
- Staff-created contacts can't carry a visitor id. They are matched on email or phone instead, which is why
  the CRM must store both.
