# Data dictionary

Every file is one table. Months are text like `2026-03`. Units are generic units of the medicine. 24 months from 2024-10 to 2026-09.

## stock.csv (one row per facility, medicine and month)
| Column | Meaning |
|---|---|
| id | Row ID (used in citations like `stock#1746`) |
| facility_id | e.g. FAC-009 |
| commodity | Medicine name |
| month | Month of the report |
| opening | Stock at the start of the month |
| received | Units delivered during the month |
| wastage | Units written off (expired or damaged) at the start of the month |
| consumed | Units issued to patients |
| closing | Stock at the end of the month |
| reported_stockout_days | Days the facility **reported** being out of stock |

Stock identity: `opening - wastage + received - consumed = closing`. A facility can report stock-out days that its own numbers contradict. That is the "record error" case.

## orders.csv (one row per facility, medicine and order cycle)
| Column | Meaning |
|---|---|
| id | Row ID (`orders#2825`) |
| facility_id, commodity | As above |
| month | The month the order was placed |
| cutoff_date | The cycle cut-off (the 10th). An order after it misses the cycle |
| order_date | When the facility actually ordered |
| qty_requested, qty_delivered | What was asked for and what the supplier delivered |
| delivery_month | When it arrived (normally the next month; two months if the order was late) |

## payments.csv (county level, one row per month)
`id`, `month`, `county_arrears_flag` (1 if the county owed the supplier), `amount_owed_kes`. Arrears of KES 30 million or more count as major.

## facilities.csv
`facility_id`, `lat`, `lon`, `facility_name`, `facility_type` (dispensary, health centre, sub-county hospital), `county`, `sub_county`, `osm_id`.
These are real public health facilities in Kitui County, Kenya, taken from OpenStreetMap. Scout, the action drafter and the Evaluator use them to name facilities and to find the nearest facility with spare stock. The stock, order and payment records attached to these facilities are synthetic and do not describe what really happened at them.

## web_notes.json
Public-notice stand-ins: `month`, `commodity`, `source`, `title`, `url`, and `synthetic: true`. In live mode the same notices are read through Zetaris (`stockwhy_web`).

## manifest.json
`seed`, `n_facilities`, `synthetic: true`. The planted cause is deliberately **not** stored anywhere in a dataset folder.

## The seven hypotheses and the data each one reads
| # | Hypothesis | Data used | What the check does |
|---|---|---|---|
| 1 | Late or missed ordering | orders | Days between `order_date` and `cutoff_date`; delivery slipped? |
| 2 | Supplier under-fill (facility-specific) | orders | This facility's fill rate versus other facilities in the same cycle |
| 3 | Payment arrears | payments, orders | County-wide fill drop plus a major arrears record |
| 4 | Demand surge | stock | `consumed` versus the facility's recent average |
| 5 | Stock-record error | stock | Reported stock-out days versus normal issues and stock left at month end |
| 6 | Expiry or wastage | stock | `wastage` relative to normal monthly use |
| 7 | National supply disruption | orders, web_notes | County-wide fill drop plus a public notice for that medicine |

`facilities.csv` is used by Scout (binding facility ids), the action drafter (names, nearest facility with spare stock) and the Evaluator (re-checks the transfer's units and distance).

## Honest caveats
- Everything is generated. Real facility records are messier and the causes are tangled.
- Rates and sizes are plausible, not calibrated to real Kenyan data. See PUBLIC_DATA_SOURCES.md for how to calibrate.
- Real facility-level stock data was not found as an open download.
