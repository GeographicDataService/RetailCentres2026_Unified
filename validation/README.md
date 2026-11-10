# Validation

The validation and sensitivity analyses in the paper (Sections 3.4 and 4.2–4.3, Tables 4 and 5). Run everything from
the repo root:

```bash
bash validation/run_all.sh
```

| Step | Script | Paper | Output (`validation/outputs/`) |
|---|---|---|---|
| 1 | `planning.py` | Table 4, Figure 7, Section 4.2.1 | `planning/table4.csv`, `small_parades.csv`, `birmingham_map.png` |
| 2 | `retail_parks.py` | Section 4.2.2 (recall, precision lower bound) | `retail_parks/recall_precision.csv` |
| 3 | `audit.py` | Sections 3.4, 4.1, 4.2.2 (audits of random samples) | `audit/results.csv` |
| 4 | `sensitivity.py` | Table 5, Section 4.3.1 (Leiden) | `sensitivity/sensitivity_runs.csv`, `leiden.csv`, `subcentre_stability.csv` |
| 5 | `postcode.py` | Section 4.3 (postcode check by country, urban/rural) | `postcode/pois.csv`, `centres.csv` |

`common.py` holds the shared paths and loaders.

## Inputs and one-off preparation (`prep/`)

`run_all.sh` uses what is already on disk. These were run once and are not re-run by it:

- **Planning designations:** `prep/fetch_planning.py` downloads the NI, Scotland (Spatial Hub, needs a free key in
  `~/.spatialhub_key`), London (GLA) and Core Cities layers into `validation/data/`; `prep/digitise_cardiff.py` extracts
  Cardiff's centres from its Deposit Plan PDF. Layers change: the paper uses the October 2026 downloads (Appendix D),
  and a fresh download can differ (Spatial Hub added North Ayrshire on 27 October 2026).
- **Boundaries runs for the sensitivity analysis:** `prep/rerun_quality_filters.py` regenerates the published run's
  quality-filter IDs, then `prep/run_sensitivity.sh` and `prep/run_postcode_sensitivity.sh` write
  `Boundaries/data/outputs/runs/val2_*` (many hours, ~29 GB peak). `val2_baseline` reproduces the published run.
- **Audit sample:** `prep/build_audit.py` drew the frozen sample (`outputs/audit/cases.gpkg`); it was labelled with
  `prep/label_server.py` (open http://localhost:8765; questions in `audit/README.md`); labels are saved to `outputs/audit/labels.csv`, which `audit.py` scores.
- **OS Points of Interest** (licensed, through Digimap): the class *Shopping centres and retail parks* as GeoPackage in
  `validation/data/os/`. Only statistics leave this folder.

Licences: GLA and Spatial Hub layers are OGL; most council and DfI layers state none, so they are used for
statistics only.
