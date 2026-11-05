# Audit labelling protocol (v1)

One labeller, one pass, one protocol for all strata. Each case is judged against current aerial
imagery (Esri World Imagery), with OpenStreetMap and Google Street View as supporting evidence.
The labeller sees the case metric but not the pipeline's decision rule outcome beyond what the
stratum implies. Answer the stratum's question with **Yes**, **No** or **Unsure**; add a note when
the answer is not obvious.

**Retail centre**: a cluster of roughly ten or more retail, food and drink, or consumer-service
units open to the public, contiguous along a street or around a shared space.
**Retail park**: a car-oriented retail site containing at least one operating big-box
(large-format) store, usually with surface car parking and away from a traditional high street.

| Stratum | Population | Question | "Yes" means the pipeline was |
|---|---|---|---|
| `landuse_removal` | networks removed by the commercial/industrial land-use filter | Is this a retail centre? | wrong (false removal) |
| `merge` | pairs joined across a one-cell gap | Do the two parts form one continuous retail centre? | right |
| `retail_park` | published Small/Large Retail Parks | Is this a retail park? | right |
| `landuse_kept` | networks kept by the land-use filter with 50% to under 75% overlap (just below the threshold); added after labelling began | Is this a retail centre? | right |
| `landuse_poi_exempt` | networks with 75% or more overlap kept only by the 20-POI exemption; added after labelling began | Is this a retail centre? | right |
| `missing_top` | the 20 2022 centres (UK, any class) with no overlapping 2025 centre and the most 2022 retail POIs; chosen, not sampled, so its error rate describes these 20 only | Is there a functioning retail centre here today? | wrong (missed centre) |
| `missing_slc` | random sample of the 422 English 2022 Small Local Centres with no overlapping 2025 centre; added after labelling began | Is there a functioning retail centre here today? | wrong (missed centre) |
| `park_ratio_gained` | parks that appear only when the brand-ratio threshold is lowered from 5% to 2.5% (sensitivity run); added after labelling began | Is this a retail park? | wrong (missed park at 5%) |
| `park_ratio_lost` | published parks that disappear when the threshold is raised to 7.5%; added after labelling began | Is this a retail park? | right (keeping it at 5% was correct) |
| `landuse_kept_near` | top-up: kept networks with 70% to under 75% overlap not already in `landuse_kept` (that random sample drew only 4 of 45); added after labelling began | Is this a retail centre? | right |
| `landuse_removal_near` | top-up: removed networks with 75% to under 80% overlap not already in `landuse_removal` (4 of 32 drawn); added after labelling began | Is this a retail centre? | wrong (false removal) |
| `exempt_kept_near` | top-up: networks with 75%+ overlap kept by the 20-POI exemption with 20–24 POIs, not already sampled; added after labelling began | Is this a retail centre? | right |
| `exempt_removed_near` | top-up: networks with 75%+ overlap removed with 15–19 POIs, not already sampled; added after labelling began | Is this a retail centre? | wrong (false removal) |

**Unsure** cases are reported separately and excluded from error rates. Cases can be flagged as
paper examples. The flag only affects which figures are rendered, never the statistics.

Sample: simple random sample without replacement within each stratum except `missing_top`, seed 505
(`validation/build_audit.py`). Labels: `validation/outputs/audit/labels.csv`, append-only; the
latest row per case wins.
