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
| 1. Watershed delineation + basin characteristics | USGS StreamStats (`rcode=NY`) |
| 2. Flow-duration curve | StreamStats regression stats; falls back to nearest comparable USGS NWIS gauge scaled by drainage-area ratio |
| 3. Gross head | USGS NLDI downstream channel trace + USGS 3DEP EPQS elevations |
| 4. Power | `P(kW) = 9.81 * Q(m3/s) * H(m) * efficiency` at 60 / 65 / 70% |
| 5. DOE cross-check | ORNL HydroSource (NSD) |
| 6. Constraints | ORNL EHA, USACE NID, WBD/HUC, FERC threshold summary |

## Design rule: no invented numbers

Every value in the report is either a live API response or an explicit
`NOT AVAILABLE` / `FAILED` marker. When a source is unreachable the report
names the endpoint and the error instead of substituting a placeholder,
a textbook figure, or a remembered value. If flow or head is missing,
the power section refuses to compute rather than guess.

## Status of the committed report

The committed `ocquionis_creek_microhydro_report.md` is a **failed run**:
all 11 API calls returned `403 Forbidden` at the sandbox egress proxy that
generated it. It contains no site data — it is committed as a record of
which endpoints were attempted and how they failed. Re-run from a network
that can reach `streamstats.usgs.gov`, `waterservices.usgs.gov`,
`api.water.usgs.gov`, `epqs.nationalmap.gov`, `hydro.nationalmap.gov`,
`hydrosource.ornl.gov` and `nid.sec.usace.army.mil` to populate it.

The computational core (RDB parsing, flow-duration percentiles,
drainage-area ratio scaling, the power equation and annual-energy
integration) is verified independently against synthetic inputs and is
unaffected by the network failure.

## Caveats that survive a successful run

- Flows from the drainage-area ratio method are transferred from a
  different watershed; the ratio is printed so it can be judged, and the
  report warns when it falls outside the defensible 0.3–3.0 band.
- Head from a ~10 m DEM over a ~1000 ft run carries error that is a large
  fraction of the answer. It is a screening value, not a survey.
- Gross head, not net — penstock friction loss is not deducted.
- No bypass / environmental flow is deducted from the power tables.
