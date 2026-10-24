# Real, freely available data for this project

Short answer: **real facility-level stock data is not openly downloadable.** The national system (KHIS) needs authorised access, and one study found it captures only a small share of what facilities record on stock cards. So the realistic plan is: synthetic stock data, anchored by real public data for everything around it.

## Good, open, usable now
| Source | What it gives | Licence (as listed) | Use it for |
|---|---|---|---|
| Kenya Healthcare Facilities, energydata.info (from the Government of Kenya) https://energydata.info/dataset/kenya-healthcare-facilities | About 10,000 facilities with type, owner, county, sub-county and GPS (CSV, JSON) | CC-BY 4.0 | Replace our 30 fictional facilities with real names, types and locations. Real distances for the transfer drafter |
| Kenya Health Facilities, HOT OpenStreetMap export on HDX https://data.humdata.org/dataset/hotosm_ken_health_facilities | Facility points and polygons, updated monthly | ODbL (OpenStreetMap, crowd-sourced, not exhaustive) | Cross-checking and maps |
| Consolidated County Budget Implementation Review Reports, Controller of Budget on openAFRICA https://bulk.openafrica.net/ca/dataset/groups/consolidated-county-budget-implementation-review-reports | County spending against budget (public reports) | CC-BY | The payments table: real county health spending and absorption. Mostly PDFs, a good job for the NVIDIA document-extraction step |
| CEMA Health Data Catalogue, University of Nairobi https://cema-africa.uonbi.ac.ke/resources/data-catalogue | Kenyan health datasets; some public, some for registered users | Varies | Worth browsing; check what is open |
| Kenya supplies and financing study (ThinkWell / Health Systems Insight) https://thinkwell.global/wp-content/uploads/2024/10/Final_Kenya-supplies-financing_30-September-2024.pdf | Stock-out findings for 17 tracer maternal and child health medicines in sampled counties | Report (cite it) | **Calibrate the generator**: realistic stock-out rates per medicine, inventory accuracy, causes. Cite it in the README |

## Also worth checking (verify the licence before using)
- Rainfall data (for example CHIRPS) and the DHIS2 public demo databases, as extra context or structure examples.
- KEMSA public tender and supply notices, as the real version of `web_notes.json`. This is what Bright Data should fetch live.

## A realistic data strategy
1. Keep synthetic stock, order and payment records as the working data. Label it clearly.
2. Swap in the **real facility list** (names, types, GPS).
3. Calibrate stock-out rates and causes using the **ThinkWell study** numbers and cite it.
4. Use real **county budget** reports for the payments context, and extract them with the NVIDIA model.
5. Use **Bright Data** for live public notices.
6. In the README, say exactly which parts are real and which are synthetic.
