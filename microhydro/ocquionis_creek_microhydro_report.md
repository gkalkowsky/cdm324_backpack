# Micro-Hydro Site Assessment

**Point of interest:** 42.9334279, -74.9668656  
**Report generated:** 2026-08-24T23:39:57+00:00  
**Target scale:** 0.5–10 kW, home / off-grid

## ⚠️ Stream identity — read this first

You described this point as being on **Ocquionis Creek (Fish Creek)**. The USGS National Hydrography Dataset flowline that this coordinate snaps to is:

- **GNIS name: Flat Creek**
- NHD COMID: `22745729`, reach length 3.771 km, type StreamRiver
- Watershed: HUC12 `020200040705` (Fulmer Creek) → HUC8 `02020004` (Mohawk)

**These do not match.** Ocquionis Creek drains south to Otsego Lake in the Susquehanna basin; this coordinate is in the Mohawk basin, which drains north to the Mohawk and then the Hudson. Jordanville sits close to that divide, so a coordinate can easily land on the wrong side of it.

Everything below describes **the stream actually at this coordinate**. If you meant a point on Ocquionis Creek proper, re-run with the corrected latitude/longitude — the drainage area, and therefore every flow and power number here, would change.

## 0. Data source status

Every number below is a live API response. Sources that failed are named, not replaced with estimates.

| Source | Purpose | Status |
|---|---|---|
| USGS StreamStats (ss-delineate + ss-hydro) | Basin + characteristics | OK |
| StreamStats NSS regression | NY flow-duration statistics | OK (but out of range — see §2a) |
| USGS NWIS | Donor gauge flow-duration curve | OK |
| USGS NLDI + 3DEP EPQS | Downstream channel head | OK |
| ORNL HydroSource NSD | DOE potential cross-check | OK |
| USACE NID | Nearby dams | OK |

## 1. Watershed delineation and basin characteristics

*Source: USGS StreamStats `ss-delineate` + `ss-hydro` basin characteristics.*

- **Drainage area: 1.160 sq mi** (3.004 sq km)
- HUC12 `020200040705` — Fulmer Creek
- Regression regions: `GC740`, `GC741`, `GC1769`, `GC1770`, `GC1804`, `GC1805` …

This is a **very small headwater basin**. That single fact drives most of what follows: it puts the site below the valid range of New York's flow-duration regression, and it makes finding a comparable gauged basin hard.

| Code | Characteristic | Value | Unit |
|---|---|---|---|
| `BSLOPCM` | Mean Basin Slope ft per mi | 290.58 | feet per mi |
| `CENTROIDX` | CENTROIDX | 502558.8 | meters |
| `CENTROIDY` | CENTROIDY | 4752581.1 | meters |
| `CONTOUR` | Total length of all elevation contours in drainage area | 3.3707127 | miles |
| `CSL1085LO` | 10-85 slope of lower half of main channel | 45.047 | feet per mi |
| `CSL1085UP` | 10-85 slope of upper half of main channel | 69.337 | feet per mi |
| `CSL10_85` | Channel slope, 10-85 method | 39.75 | feet per mi |
| `DRNAREA` | Drainage area | 1.16 | square miles |
| `EL1200` | Percentage of Basin Above 1200 ft | 100.0 | percent |
| `FOREST` | Forest cover | 22.75 | percent |
| `JULAVPRE` | Mean July Precipitation | 4.6 | inches |
| `JUNAVPRE` | Mean June Precipitation | 4.382 | inches |
| `JUNMAXTMP` | Maximum June Temperature | 73.468 | degrees F |
| `LAGFACTOR` | Lag Factor | 0.03 | dimensionless |
| `LC11DEV` | Developed land cover | 3.746 | percent |
| `LC11IMP` | Impervious cover | 0.262 | percent |
| `LENGTH` | Main Channel Length | 1.969 | miles |
| `MAR` | Mean Annual Runoff in inches | 23.02 | inches |
| `MAYAVPRE` | Mean May Precipitation | 4.131 | inches |
| `MXSNO` | Median Seasonal Maximum Snow Depth | 18.34 | inches |
| `OUTLETX` | OUTLETX | 502705.0 | feet |
| `OUTLETY` | OUTLETY | 4753425.0 | feet |
| `PRECIP` | Mean annual precipitation | 42.11 | inches |
| `PRJUNAUG00` | Basin average mean precip for June to August | 12.989 | inches |
| `SLOPERATIO` | Slope Ratio NY | 0.1368 | dimensionless |
| `SSURGOA` | SSURGO Percent Hydrologic Soil Type A | 0.0 | percent |
| `SSURGOB` | SSURGO Percent Hydrologic Soil Type B | 62.943 | percent |
| `STORAGE` | Storage (lakes/wetlands) | 11.94 | percent |

## 2. Available flow

### 2a. New York regression equations (StreamStats)

Regression region: `GC1734` — Statewide_duration_flows_excl_LongIsl_2014_5220

> ### ⚠️ These equations do not apply to this basin
>
> StreamStats returned numbers, but the basin falls outside the range the equations were fitted over:
>
> | Parameter | Value | Valid range | Problem |
> |---|---|---|---|
> | `DRNAREA` | 1.16 | 3.14 – 4780.0 | **below minimum** |
> | `SSURGOA` | 0 | 0.62 – 51.2 | **below minimum** |
>
> Extrapolating a log-log regression below its calibration range is not reliable, so these values are reported for transparency but are **not** used for the power calculation.

> ### ⚠️ Suppressed false zeros
>
> These regressions are products of powers. A parameter whose value is exactly 0, carrying a positive exponent, collapses the entire product to zero regardless of hydrology. The following statistics came back as 0.0 purely for that reason and have been **excluded** rather than reported as a dry stream:
>
> | Statistic | Exceedance | Zero-valued parameter(s) |
> |---|---|---|
> | `D75` | 75.0% | `SSURGOA` |
> | `D80` | 80.0% | `SSURGOA` |
> | `D85` | 85.0% | `SSURGOA` |
> | `D90` | 90.0% | `SSURGOA` |
> | `D95` | 95.0% | `SSURGOA` |
> | `D99` | 99.0% | `SSURGOA` |
>
> **This does not mean the creek runs dry.** It means the equation could not be evaluated. Real low-flow behaviour has to come from the gauge transfer below, and ultimately from measurement on site.

<details><summary>All statistics returned by StreamStats</summary>

| Code | Statistic | Value (cfs) |
|---|---|---|
| `D0_01` | 0.01 Percent Duration | 72.4 |
| `D1` | 1 Percent Duration | 13.4 |
| `D5` | 5 Percent Duration | 5.88 |
| `D10` | 10 Percent Duration | 4.07 |
| `D15` | 15 Percent Duration | 3.1 |
| `D20` | 20 Percent Duration | 2.46 |
| `D25` | 25 Percent Duration | 2.13 |
| `D35` | 35 Percent Duration | 1.58 |
| `D50` | 50 Percent Duration | 1.12 |
| `D65` | 65 Percent Duration | 0.802 |
| `D75` | 75 Percent Duration | 0.0 |
| `D80` | 80 Percent Duration | 0.0 |
| `D85` | 85 Percent Duration | 0.0 |
| `D90` | 90 Percent Duration | 0.0 |
| `D95` | 95 Percent Duration | 0.0 |
| `D99` | 99 Percent Duration | 0.0 |
| `D99_99` | 99.99 Percent Duration | 0.0584 |

</details>

### 2b. Gauge transfer by drainage-area ratio

- **Donor gauge:** USGS 01424108 — SHERRUCK BROOK TRIBUTARY NEAR TROUT CREEK NY
- **Location:** 42.18778, -75.31556 (54.5 mi from the site)
- **Donor drainage area:** 1.30 sq mi
- **Record used:** 3,651 daily mean discharge values

**The work:**

```
Q_site(p) = Q_gauge(p) * ( DA_site / DA_gauge ) ^ x        with x = 1.0

DA_site  = 1.160 sq mi   (StreamStats delineation)
DA_gauge = 1.30 sq mi   (NWIS site record)
ratio    = 1.160 / 1.30 = 0.89231
```

| Exceedance | Meaning | Donor (cfs) | Scaled to site (cfs) | Site (m³/s) |
|---|---|---|---|---|
| Q5 | very high | 9.21 | 8.214 | 0.23259 |
| Q10 | high | 6.01 | 5.363 | 0.15186 |
| Q20 |  | 3.90 | 3.480 | 0.09854 |
| Q25 |  | 3.33 | 2.971 | 0.08414 |
| Q30 |  | 2.90 | 2.588 | 0.07328 |
| Q40 |  | 2.10 | 1.874 | 0.05306 |
| Q50 | median | 1.48 | 1.321 | 0.03740 |
| Q60 |  | 1.00 | 0.892 | 0.02527 |
| Q70 |  | 0.61 | 0.544 | 0.01541 |
| Q75 |  | 0.41 | 0.366 | 0.01036 |
| Q80 |  | 0.26 | 0.232 | 0.00657 |
| Q90 | low | 0.11 | 0.098 | 0.00278 |
| Q95 | very low | 0.08 | 0.071 | 0.00202 |

### 2c. Which curve drives the numbers below

**USGS gauge transfer (drainage-area ratio).** The NY regression could not be used: DRNAREA = 1.16 is below minimum of the equation's valid range (3.14–4780.0); SSURGOA = 0 is below minimum of the equation's valid range (0.62–51.2).

Where both methods produced a value, they compare as follows:

| Exceedance | StreamStats regression (cfs) | Gauge transfer (cfs) |
|---|---|---|
| Q0.01 | 72.400 | — |
| Q1 | 13.400 | — |
| Q5 | 5.880 | 8.214 |
| Q10 | 4.070 | 5.363 |
| Q15 | 3.100 | — |
| Q20 | 2.460 | 3.480 |
| Q25 | 2.130 | 2.971 |
| Q30 | — | 2.588 |
| Q35 | 1.580 | — |
| Q40 | — | 1.874 |
| Q50 | 1.120 | 1.321 |
| Q60 | — | 0.892 |
| Q65 | 0.802 | — |
| Q70 | — | 0.544 |
| Q75 | — | 0.366 |
| Q80 | — | 0.232 |
| Q90 | — | 0.098 |
| Q95 | — | 0.071 |
| Q99.99 | 0.058 | — |

Disagreement between two independent methods is the honest measure of how uncertain this site's flow really is.

## 3. Gross head

*Source: USGS NLDI downstream channel trace + USGS 3DEP EPQS elevations.*

- NHD COMID traced: `22745729`
- Channel run sampled: 1,000 ft downstream
- **Gross head: 20.5 ft (6.24 m)**
- Gross head over the first 500 ft: 9.5 ft
- Average gradient: 2.05%

<details><summary>Elevation profile — every sample</summary>

| Distance (ft) | Lat | Lon | 3DEP elevation (ft) |
|---|---|---|---|
| 0 | 42.933661 | -74.966676 | 1,510.30 |
| 50 | 42.933760 | -74.966550 | 1,510.40 |
| 100 | 42.933882 | -74.966489 | 1,516.85 |
| 150 | 42.933988 | -74.966381 | 1,514.90 |
| 200 | 42.934113 | -74.966304 | 1,512.94 |
| 250 | 42.934238 | -74.966228 | 1,506.13 |
| 300 | 42.934363 | -74.966151 | 1,503.93 |
| 350 | 42.934488 | -74.966074 | 1,504.73 |
| 400 | 42.934613 | -74.965998 | 1,503.15 |
| 450 | 42.934745 | -74.965947 | 1,502.06 |
| 500 | 42.934878 | -74.965900 | 1,500.80 |
| 550 | 42.935014 | -74.965910 | 1,499.28 |
| 600 | 42.935151 | -74.965921 | 1,499.42 |
| 650 | 42.935288 | -74.965933 | 1,503.26 |
| 700 | 42.935416 | -74.966001 | 1,493.17 |
| 750 | 42.935543 | -74.966069 | 1,493.48 |
| 800 | 42.935671 | -74.966136 | 1,492.80 |
| 850 | 42.935780 | -74.966247 | 1,492.94 |
| 900 | 42.935892 | -74.966345 | 1,490.29 |
| 950 | 42.936018 | -74.966401 | 1,490.03 |
| 1000 | 42.936136 | -74.966466 | 1,489.81 |

</details>

> **This is a screening number, not a survey.** 3DEP here is a ~10 m DEM with roughly 1–2 ft vertical RMSE, and it is worse in a narrow, wooded stream valley where the surface may never have resolved the channel bottom. Over a run this short, the DEM error is a large fraction of the answer. Measure it with a laser level or a hose and pressure gauge before spending anything.

## 4. Power potential

```
P(kW) = 9.81 * Q(m3/s) * H(m) * efficiency
```

Head **H = 20.5 ft = 6.24 m**; flow from *USGS gauge transfer (drainage-area ratio)*.

This is **gross** head. Net head after penstock friction is typically 85–90% of gross for a well-sized pipe; the efficiency columns carry only turbine, drive and generator losses.

| Exceedance | Flow (cfs) | Flow (m³/s) | Theoretical (kW) | @60% | @65% | @70% |
|---|---|---|---|---|---|---|
| Q5 | 8.214 | 0.23259 | 14.246 | 8.548 | 9.260 | 9.972 |
| Q10 | 5.363 | 0.15186 | 9.301 | 5.581 | 6.046 | 6.511 |
| Q20 | 3.480 | 0.09854 | 6.036 | 3.621 | 3.923 | 4.225 |
| Q25 | 2.971 | 0.08414 | 5.154 | 3.092 | 3.350 | 3.608 |
| Q30 | 2.588 | 0.07328 | 4.488 | 2.693 | 2.917 | 3.142 |
| Q40 | 1.874 | 0.05306 | 3.250 | 1.950 | 2.113 | 2.275 |
| Q50 | 1.321 | 0.03740 | 2.291 | 1.374 | 1.489 | 1.603 |
| Q60 | 0.892 | 0.02527 | 1.548 | 0.929 | 1.006 | 1.083 |
| Q70 | 0.544 | 0.01541 | 0.944 | 0.566 | 0.614 | 0.661 |
| Q75 | 0.366 | 0.01036 | 0.635 | 0.381 | 0.412 | 0.444 |
| Q80 | 0.232 | 0.00657 | 0.402 | 0.241 | 0.262 | 0.282 |
| Q90 | 0.098 | 0.00278 | 0.170 | 0.102 | 0.111 | 0.119 |
| Q95 | 0.071 | 0.00202 | 0.124 | 0.074 | 0.080 | 0.087 |

### Indicative annual energy

Turbine sized at the Q30 flow (2.588 cfs), spilling above it, shutting down below 0.259 cfs, 65% system efficiency, **no bypass flow deducted**:

- Rated output: **2.917 kW**
- Average output: **1.548 kW**
- Annual energy: **13,574 kWh/yr**
- Capacity factor: 53%

For scale: a typical US home uses roughly 10,500 kWh/yr; a deliberately efficient off-grid homestead often runs 2,000–4,000 kWh/yr.

## 5. Cross-check against ORNL / DOE data

*Source: ORNL HydroSource, New Stream-reach Development (NSD), hydrologic region 02, aggregated to HUC10.*

- HUC10 searched: `0202000407` (Nowadaga Creek-Mohawk River)
- 148 HUC10 watersheds in region 02; HUC10 0202000407 FOUND

**DOE does attribute new stream-reach potential to this HUC10:**

| Metric | Value |
|---|---|
| Stream reaches identified | 2  |
| Potential capacity | 4.553 MW |
| Potential annual energy | 2.663e+04 MWh |
| Average hydraulic head | 12.96 ft |
| Hydraulic capacity (Q30) | 2,322 cfs |
| Capacity factor | 0.6677 ratio |

> **Read this carefully.** NSD is a HUC10-wide aggregate covering **every** candidate reach in the watershed, at utility screening scale and with its own assumptions about head and hydraulic capacity. It is not an estimate for your specific point, and the capacity above is orders of magnitude larger than a homestead machine. It tells you the watershed is not devoid of potential; it says nothing about whether your particular 1,000 ft of channel is worth developing.

## 6. Constraints and permitting

### Nearby dams (USACE National Inventory of Dams)

14 dam(s) within 10 miles:

| Dam | NID ID | Distance (mi) | River | Purpose | Height (ft) | Year |
|---|---|---|---|---|---|---|
| Ilion Reservoir #3 Dam | NY00184 | 5.0 | Tr-Mohawk River | Water Supply | 76 | 1921 |
| Movable Dam At Herkimer | NY00966 | 5.9 | Erie Canal Mohawk River | Navigation | 6 | 1915 |
| Millers Mills Dam | NY01066 | 5.9 | Unadilla River | Recreation | 20 | 1917 |
| Ilion Reservoir #1 Dam | NY00186 | 6.1 | Tr-Steele Creek | Water Supply | 40 | 1895 |
| Ilion Reservoir #2 Dam | NY00185 | 6.2 | Steele Creek | Water Supply | 60 | 1903 |
| Mirror Lake Dam | NY17038 | 7.4 | Tr-West Canada Creek | Flood Risk Reduction | 25 |  |
| Allen Lake Dam | NY01267 | 7.4 | Tr-Otsego Lake | Water Supply | 10 | 1940 |
| Herkimer                                                          | NY01579 | 8.3 | West Canada Creek              | Hydroelectric | 12 | 1922 |
| Frankfort Reservoir Dam | NY14970 | 8.6 | Tr-Mohawk River | Water Supply | 45 | 1908 |
| Little Falls State Dam - North                                    | NY12517 | 8.8 | Mohawk River                   | Hydroelectric | 6 | 1894 |
| Clarke Pond Dam | NY01264 | 9.0 | Cripple Creek | Recreation | 14 | 1847 |
| Burke Pond Dam | NY16050 | 9.1 | Tr-Wharton Creek | Recreation | 24 | 2001 |
| Lock E-17 Embankment Dam | NY17230 | 9.3 | Mohawk River | Hydroelectric | 50 | 1918 |
| Lock E-17 Dam At Little Falls | NY12515 | 9.4 | Mowhawk River | Hydroelectric | 60 | 1982 |


**None of these is on Flat Creek itself** — they are on neighbouring streams and on the Mohawk. So no upstream impoundment is controlling your flow, which is good news for a run-of-river scheme. They matter as context rather than as a direct constraint.

4 of the 14 are already generating (Herkimer, Little Falls State Dam - North, Lock E-17 Embankment Dam, Lock E-17 Dam At Little Falls), which shows the wider basin supports hydro at a much larger scale than anything contemplated here.

### Existing hydropower (ORNL EHA)

The EHA plant inventory was located on HydroSource but **was not spatially queried** in this run — the published product is a bulk download rather than a point query service. Existing hydro near this reach is therefore **unverified**. Given the basin size, an existing plant on this stream is unlikely, but that is reasoning, not data.

### Environmental sensitivity

**Not queried in this run — do not read that as 'no constraints'.** The datasets that would answer it are the NYSDEC water quality classification for this reach, NYSDEC trout-stream and spawning designations, a USFWS IPaC listed-species review, and NY Natural Heritage Program records. A cold headwater creek in central New York has a realistic chance of carrying a trout designation, which raises the bar substantially for any in-channel structure.

### FERC thresholds

General statutory parameters only. This is not a legal opinion, and a
jurisdictional determination can come only from FERC itself.

- **Qualifying conduit hydropower facility.** The Hydropower Regulatory
  Efficiency Act of 2013 created a pathway for facilities on a *non-federally
  owned conduit* operated primarily for a purpose other than power generation.
  These need neither a license nor an exemption; the developer files a notice of
  intent and FERC issues a determination. The America's Water Infrastructure Act
  of 2018 raised the ceiling to 40 MW. **A natural stream channel is not a
  conduit**, so a run-of-river intake on this creek would not normally qualify.
- **Conduit exemption.** A separate exemption for conduit facilities, also
  capped at 40 MW. Same conduit limitation applies.
- **Small hydroelectric power project exemption.** Up to 10 MW, generally
  requiring an existing dam or a natural water feature without a dam.
- **FERC jurisdiction generally** attaches where a project sits on a navigable
  water of the United States, occupies federal land, uses surplus water from a
  federal dam, or affects interstate commerce. The last test is broad and is
  where most small stream projects land. Many genuinely small off-grid systems
  on non-navigable headwater streams end up outside FERC jurisdiction, but that
  conclusion has to be confirmed, not assumed.
- **New York State**, independently of FERC: NYSDEC Article 15 Protection of
  Waters (disturbance of a protected stream bed or bank), Clean Water Act
  Section 401 water quality certification, SEQRA review, and possibly a USACE
  Section 404 permit. Whether Article 15 applies turns on this reach's DEC water
  quality classification, which must be looked up for this specific segment.


## Plain-language summary

**First, the coordinate is not on the stream you named.** NHD calls it **Flat Creek**, in the Mohawk/Hudson basin rather than Ocquionis Creek's Susquehanna basin. If the coordinate is what you meant, read on. If the *name* is what you meant, these numbers are for the wrong creek. The basin above this point is **1.16 sq mi** — very small — and the DEM puts **20.5 ft of gross head** in 1,000 ft of channel (a 2.0% gradient). At median flow (Q50 = 1.32 cfs) a 65%-efficient machine makes about **1.49 kW**. At the low-flow condition that actually sizes an off-grid system (Q90 = 0.10 cfs) it makes about **0.11 kW**. That is below what most people would consider a useful home system, and it is the number that matters most, because a system you cannot run in August is a system you cannot rely on. **Now weigh the confidence.** New York's own flow-duration equations could not be applied — this basin sits below their minimum drainage area — so the flow above comes from a gauge transfer instead. That transfer is unusually well matched on size: the donor basin is 1.3 sq mi against this site's 1.16 sq mi, a ratio of 0.89, right in the band where the drainage-area method is considered sound. The weakness is not scale but location — the donor sits 54 miles away in a different river basin, so it shares this site's size without necessarily sharing its geology, soils or storage. It carries 10 years of record, which captures ordinary dry summers but not necessarily a severe drought. The head comes from a 10 m DEM over a short run, where the vertical error is a large fraction of the answer — that number is the softest thing in this report. The honest summary: **this is a plausible micro-hydro site that has not yet been shown to be a good one.** Nothing here rules it out, and nothing here justifies buying equipment. A year of actual flow measurements and one afternoon with a level would tell you more than every dataset in this report combined — and cost almost nothing.

## What to field-verify before spending real money

1. **Confirm which stream you are actually on.** The coordinate resolves to a different named stream, in a different river basin, than the one you named. Settle this first — everything else depends on it.
2. **Measure the flow, repeatedly, through a dry season.** Every flow figure here is a statistical transfer from a different watershed, and the one method purpose-built for New York does not apply to a basin this small. A weir box or bucket-and-stopwatch reading taken monthly for a year — and above all in late summer and in a drought year — is what decides this site. Late-summer low flow, not median flow, sizes an off-grid system.
3. **Survey the real head** with a laser level, rod, or hose-and-gauge, to the actual powerhouse location you could physically build on.
4. **Walk the penstock route.** Length, diameter, buried vs. surface, stream crossings and rock drive both net head and cost, and at this scale cost is dominated by pipe.
5. **Confirm you control both ends** — property boundaries and riparian rights at the intake and at the tailrace.
6. **Look up this reach's DEC classification** and get a real read on Article 15, 401 certification, SEQRA, and any USACE 404 nexus.
7. **Get a written FERC jurisdictional determination** rather than relying on a threshold reading.
8. **Plan for winter.** Frazil and anchor ice, leaf litter and spring debris decide whether the intake runs unattended.
9. **Confirm the load and the distance to it** — transmission run from powerhouse to house, and battery vs. grid-tied.

## Appendix A — Every API call

| # | Source | Status | Endpoint |
|---|---|---|---|
| 1 | StreamStats ss-delineate: watershed delineation | OK 200 | `https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/NY?lat=42.9334279&lon=-74.9668656` |
| 2 | StreamStats NSS: regression regions for the basin | OK 200 | `https://streamstats.usgs.gov/nssservices/regressionregions/bylocation` |
| 3 | StreamStats ss-hydro: compute basin characteristics | OK 200 | `https://streamstats.usgs.gov/ss-hydro/v1/basin-characteristics/calculate` |
| 4 | National Map WBD: HUC codes at the point | OK 200 | `https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/identify?geometry=-74.9668656%2C42.9334279&geometryType` |
| 5 | StreamStats NSS: flow-duration scenarios | OK 200 | `https://streamstats.usgs.gov/nssservices/scenarios?regions=NY&statisticgroups=5&regressionregions=GC740%2CGC741%2CGC1769` |
| 6 | StreamStats NSS: estimate flow-duration statistics | OK 200 | `https://streamstats.usgs.gov/nssservices/scenarios/estimate?regions=NY` |
| 7 | USGS NWIS site search (bounding box around site) | OK 200 | `https://waterservices.usgs.gov/nwis/site/?format=rdb&bBox=-75.716866%2C42.183428%2C-74.216866%2C43.683428&siteType=ST&si` |
| 8 | USGS NWIS daily values, gauge 01424108 (full period of record) | OK 200 | `https://waterservices.usgs.gov/nwis/dv/?format=rdb&sites=01424108&parameterCd=00060&statCd=00003&startDT=1900-01-01&endD` |
| 9 | USGS NLDI: locate NHD flowline (COMID) at the point | OK 200 | `https://api.water.usgs.gov/nldi/linked-data/comid/position?coords=POINT%28-74.9668656+42.9334279%29&f=json` |
| 10 | USGS NLDI: downstream-main flowlines from COMID 22745729 | OK 200 | `https://api.water.usgs.gov/nldi/linked-data/comid/22745729/navigation/DM/flowlines?distance=0.45720000000000005&f=json` |
| 11 | USGS 3DEP EPQS elevation @ 42.933661,-74.966676 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.966676101&y=42.9336605&units=Feet&wkid=4326&includeDate=false` |
| 12 | USGS 3DEP EPQS elevation @ 42.933760,-74.966550 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96654952465956&y=42.93375978164017&units=Feet&wkid=4326&includeDate=false` |
| 13 | USGS 3DEP EPQS elevation @ 42.933882,-74.966489 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96648853806617&y=42.93388222192375&units=Feet&wkid=4326&includeDate=false` |
| 14 | USGS 3DEP EPQS elevation @ 42.933988,-74.966381 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96638092533205&y=42.93398814545643&units=Feet&wkid=4326&includeDate=false` |
| 15 | USGS 3DEP EPQS elevation @ 42.934113,-74.966304 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96630429945264&y=42.934113194219634&units=Feet&wkid=4326&includeDate=false` |
| 16 | USGS 3DEP EPQS elevation @ 42.934238,-74.966228 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96622767357326&y=42.934238242982836&units=Feet&wkid=4326&includeDate=false` |
| 17 | USGS 3DEP EPQS elevation @ 42.934363,-74.966151 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96615104769386&y=42.93436329174604&units=Feet&wkid=4326&includeDate=false` |
| 18 | USGS 3DEP EPQS elevation @ 42.934488,-74.966074 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96607442181445&y=42.93448834050924&units=Feet&wkid=4326&includeDate=false` |
| 19 | USGS 3DEP EPQS elevation @ 42.934613,-74.965998 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96599779593507&y=42.93461338927244&units=Feet&wkid=4326&includeDate=false` |
| 20 | USGS 3DEP EPQS elevation @ 42.934745,-74.965947 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96594702147395&y=42.93474519912971&units=Feet&wkid=4326&includeDate=false` |
| 21 | USGS 3DEP EPQS elevation @ 42.934878,-74.965900 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96589992917856&y=42.93487763100499&units=Feet&wkid=4326&includeDate=false` |
| 22 | USGS 3DEP EPQS elevation @ 42.935014,-74.965910 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96591049819382&y=42.93501446882574&units=Feet&wkid=4326&includeDate=false` |
| 23 | USGS 3DEP EPQS elevation @ 42.935151,-74.965921 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.9659210672091&y=42.9351513066465&units=Feet&wkid=4326&includeDate=false` |
| 24 | USGS 3DEP EPQS elevation @ 42.935288,-74.965933 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96593291007302&y=42.93528794221859&units=Feet&wkid=4326&includeDate=false` |
| 25 | USGS 3DEP EPQS elevation @ 42.935416,-74.966001 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96600071518957&y=42.935415692676145&units=Feet&wkid=4326&includeDate=false` |
| 26 | USGS 3DEP EPQS elevation @ 42.935543,-74.966069 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96606852030611&y=42.9355434431337&units=Feet&wkid=4326&includeDate=false` |
| 27 | USGS 3DEP EPQS elevation @ 42.935671,-74.966136 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96613632542265&y=42.93567119359126&units=Feet&wkid=4326&includeDate=false` |
| 28 | USGS 3DEP EPQS elevation @ 42.935780,-74.966247 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.966247346909&y=42.93578000748977&units=Feet&wkid=4326&includeDate=false` |
| 29 | USGS 3DEP EPQS elevation @ 42.935892,-74.966345 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96634505940828&y=42.93589233606146&units=Feet&wkid=4326&includeDate=false` |
| 30 | USGS 3DEP EPQS elevation @ 42.936018,-74.966401 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.96640119790806&y=42.936017994774026&units=Feet&wkid=4326&includeDate=false` |
| 31 | USGS 3DEP EPQS elevation @ 42.936136,-74.966466 | OK 200 | `https://epqs.nationalmap.gov/v1/json?x=-74.9664661442373&y=42.93613577032598&units=Feet&wkid=4326&includeDate=false` |
| 32 | National Map NHD: flowline attributes for COMID 22745729 | OK 200 | `https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/4/query?where=COMID%3D22745729&outFields=COMID%2CGNIS_N` |
| 33 | ORNL HydroSource NSD (New Stream-reach Development) (cached) | OK 200 | `https://hydrosource.s3.us-east-2.amazonaws.com/files/data/datasets/hydropower-potential-new-stream-reach-development-mid` |
| 34 | USACE National Inventory of Dams (cached) | OK 200 | `https://nid.sec.usace.army.mil/api/nation/csv` |
| 35 | ORNL HydroSource EHA (Existing Hydropower Assets) | OK 200 | `https://hydrosource.ornl.gov/wp-json/wp/v2/search?search=EHA+plant&per_page=5` |

---

*Generated by `hydro_assessment.py`. Every value is either a live API response or an explicit NOT AVAILABLE / FAILED marker.*