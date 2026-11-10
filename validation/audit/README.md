# Supplementary material: manual audit

Supplementary material for *Delineating Open Retail Centre Boundaries for the United Kingdom*
(Sections 3.4, 4.1 and 4.2.2): the randomly sampled cases used to check the land-use filter, the
one-cell merges, retail park detection and the 2022 centres absent from the update.

## Files

| File | Contents |
|---|---|
| `audit_cases.gpkg` | Audited cases with their boundaries and final judgement (EPSG:4326). Layers: `land_use` (210 cases), `merges` (50), `merge_parts` (the two parts and the bridging cells of each merge), `retail_parks` (75) |
| `audit_summary.csv` | For each audit group: population, cases sampled and the judgements |
| `absent_2022_centres.csv` | All 498 Macdonald et al. (2022) centres with no overlapping 2026 centre, with the judgement for the 40 audited (`audit_sample`, `audit_retail_centre`) |

In `audit_cases.gpkg`, `Judgement` answers the case's `Question`; `Pipeline_Correct` says whether
the pipeline's decision (`Pipeline_Decision`) agrees with it. Merge and land-use cases are pipeline
networks, not published centres, so they have no `RC_ID`; retail parks carry their published `RC_ID_2026`.

## How cases were judged

Each case is judged against current aerial imagery (Esri World Imagery), OpenStreetMap POI, and Street View imagery. 
 Each question is answered **Yes**, **No** or **Unsure**; Unsure cases are
reported separately and excluded from error rates.

- **Retail centre**: a cluster of roughly ten or more retail, food and drink, or consumer-service
  units open to the public, contiguous along a street or around a shared space.
- **Retail park**: a car-oriented retail site containing at least one operating big-box
  (large-format) store, usually with surface car parking and away from a traditional high street.

| Audit group | Population | Question | "Yes" means the pipeline was |
|---|---|---|---|
| Land-use removal (75% or more overlap, under 20 POIs) | networks removed by the commercial/industrial land-use filter | Is this a retail centre? | wrong |
| Land-use removal near threshold (75-80% overlap) | removed networks just above the overlap threshold | Is this a retail centre? | wrong |
| Land-use removal near POI exemption (15-19 POIs) | removed networks with 75%+ overlap just below the 20-POI exemption | Is this a retail centre? | wrong |
| Land-use kept below threshold (50-75% overlap) | networks kept with overlap just below the threshold | Is this a retail centre? | right |
| Land-use kept near threshold (70-75% overlap) | kept networks closest to the threshold | Is this a retail centre? | right |
| Land-use kept by 20-POI exemption (75% or more overlap) | networks kept only by the 20-POI exemption | Is this a retail centre? | right |
| Land-use kept near POI exemption (20-24 POIs) | exempt networks with 20-24 POIs | Is this a retail centre? | right |
| One-cell merge | network pairs joined across a one-cell gap | Do the two parts form one continuous retail centre? | right |
| Detected retail park | published Small and Large Retail Parks | Is this a retail park? | right |
| Absent 2022 centres, top 20 (in `absent_2022_centres.csv`) | the 20 absent 2022 centres with the most 2022 retail units; chosen, not sampled | Is there a functioning retail centre here today? | wrong |
| Absent 2022 centres, random 20 (in `absent_2022_centres.csv`) | random sample of the 422 absent English 2022 Small Local Centres | Is there a functioning retail centre here today? | wrong |

Population sizes and sample counts are in `audit_summary.csv`. The near-threshold groups were added
after labelling began, as top-ups either side of each threshold.

**Sampling:** simple random sample without replacement within each group, seed 505, except the
top 20 absent centres, which were chosen by size, so their result describes those 20 only.

Boundaries are derived from Foursquare Open Source Places and OpenStreetMap (© OpenStreetMap contributors, ODbL).
