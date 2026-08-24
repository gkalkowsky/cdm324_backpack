# Micro-hydro site assessment — Ocquionis (Fish) Creek

Feasibility screening for a small run-of-river micro-hydro installation
(target 0.5–10 kW, home / off-grid) at:

- **Latitude:** 42.9334279
- **Longitude:** -74.9668656
- Ocquionis Creek (Fish Creek), near Jordanville, NY (Herkimer/Otsego County)

## Run it

```bash
pip install requests
python3 hydro_assessment.py
```

Writes `ocquionis_creek_microhydro_report.md` and `provenance.json`
(one entry per HTTP call, so every number in the report is traceable).

Options: `--lat --lon --rcode --run-ft --step-ft --out --provenance-json`.

## What it does

| Step | Source |
|---|---|
| 1. Watershed delineation + basin characteristics | USGS StreamStats `ss-delineate` + `ss-hydro` |
| 2. Flow-duration curve | StreamStats regression stats; falls back to nearest comparable USGS NWIS gauge scaled by drainage-area ratio |
| 3. Gross head | USGS NLDI downstream channel trace + USGS 3DEP EPQS elevations |
| 4. Power | `P(kW) = 9.81 * Q(m3/s) * H(m) * efficiency` at 60 / 65 / 70% |
| 5. DOE cross-check | ORNL HydroSource NSD, by HUC10 |
| 6. Constraints | USACE NID (national CSV, filtered locally), ORNL EHA, WBD/HUC, FERC threshold summary |

The legacy `/streamstatsservices/*.json` API is retired and returns 404. This
script uses the current five-call chain (delineate → regression regions →
scenarios → basin characteristics → estimate) per the USGS
"StreamStats Flow Statistics Workflow" notebook.

Large downloads (the ~65 MB NID national CSV and the NSD workbooks) are cached;
point `--cache-dir` at a scratch directory to keep them out of the repo.

## Design rule: no invented numbers

Every value in the report is either a live API response or an explicit
`NOT AVAILABLE` / `FAILED` marker. When a source is unreachable the report
names the endpoint and the error instead of substituting a placeholder,
a textbook figure, or a remembered value. If flow or head is missing,
the power section refuses to compute rather than guess.

## Status of the committed report

The committed `ocquionis_creek_microhydro_report.md` is a **complete live
run**: 35 of 35 API calls succeeded. Headline results for the supplied
coordinate:

| | |
|---|---|
| Stream at the coordinate | **Flat Creek** (not Ocquionis Creek — see the report) |
| Drainage area | 1.16 sq mi |
| Gross head | 20.5 ft over 1,000 ft |
| Q50 / Q90 flow | 1.32 / 0.098 cfs |
| Power at 65% | 1.49 kW (median), 0.11 kW (low flow) |

Two findings drive the report and are easy to miss:

1. **The coordinate is not on the stream it was described as.** NHD names
   the flowline Flat Creek, in the Mohawk/Hudson basin, not Ocquionis
   Creek's Susquehanna basin.
2. **New York's flow-duration regression does not apply to this basin.**
   `DRNAREA` = 1.16 sq mi is below the equation's 3.14 sq mi minimum, and
   `SSURGOA` = 0 is below its minimum. Because these equations are products
   of powers, a zero-valued parameter with a positive exponent collapses the
   whole product, so StreamStats returns exactly `0.0` for D75 through D99.
   Those zeros are an artifact, **not** a prediction that the creek runs
   dry; the script detects and suppresses them rather than reporting a dry
   stream, and falls back to a gauge transfer.

The computational core (RDB parsing, flow-duration percentiles,
drainage-area ratio scaling, the power equation, annual-energy integration,
and the zero-artifact detector) is verified independently against synthetic
inputs.

## Caveats that survive a successful run

- Flows from the drainage-area ratio method are transferred from a
  different watershed; the ratio is printed so it can be judged, and the
  report warns when it falls outside the defensible 0.3–3.0 band.
- Head from a ~10 m DEM over a ~1000 ft run carries error that is a large
  fraction of the answer. It is a screening value, not a survey.
- Gross head, not net — penstock friction loss is not deducted.
- No bypass / environmental flow is deducted from the power tables.
