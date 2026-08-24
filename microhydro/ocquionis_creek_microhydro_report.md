# Micro-Hydro Site Assessment — Ocquionis (Fish) Creek

**Point of interest:** 42.9334279, -74.9668656  
**Stream:** Ocquionis Creek (Fish Creek), near Jordanville, NY  
**Report generated:** 2026-08-24T23:13:54+00:00  
**Target scale:** 0.5–10 kW, home / off-grid

## 0. Data source status

Every number below comes from a live API response logged in the appendix.
Sources that failed are named here and are **not** substituted with estimates.

| Source | Purpose | Status |
|---|---|---|
| USGS StreamStats (NY) | Watershed + basin characteristics | **FAILED** |
| StreamStats flow statistics | NY regression flow stats | **NO DATA / FAILED** |
| USGS NWIS | Donor gauge flow-duration curve | **FAILED** |
| USGS NLDI + 3DEP EPQS | Downstream channel head | **FAILED** |
| ORNL HydroSource (NSD / EHA) | DOE potential cross-check | **FAILED** |
| USACE NID | Nearby dams | **FAILED** |

> **11 HTTP call(s) failed.** See Appendix B for the exact endpoint and error for each.

## 1. Watershed delineation and basin characteristics

*Source: USGS StreamStats web services, rcode=NY.*

**FAILED — no delineation.** StreamStats watershed delineation (rcode=NY): ProxyError: HTTPSConnectionPool(host='streamstats.usgs.gov', port=443): Max retries exceeded with url: /streamstatsservices/watershed.json?rcode=NY&xlocation=-74.9668656&ylocation=42.9334279&crs=4326&includeparameters=true&includeflowtypes=false&includefeatures=true&simplify=true (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))

Because the drainage area is unknown, the drainage-area ratio in Step 2 cannot be computed and no flow estimate is possible from this run.
## 2. Available flow

### 2a. StreamStats regression flow statistics

**No flow statistics from StreamStats.** No StreamStats workspaceID (delineation failed), so no flow stats.

Falling back to the drainage-area ratio method against a gauged basin.

### 2b. Donor gauge and drainage-area ratio transfer

**FAILED — no flow-duration curve could be built.** USGS NWIS site search (bounding box around site): ProxyError: HTTPSConnectionPool(host='waterservices.usgs.gov', port=443): Max retries exceeded with url: /nwis/site/?format=rdb&bBox=-75.716866%2C42.183428%2C-74.216866%2C43.683428&siteType=ST&siteOutput=expanded&hasDataTypeCd=dv&parameterCd=00060&siteStatus=all (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))

## 3. Gross head

*Source: USGS NLDI downstream channel trace + USGS 3DEP EPQS point elevations.*

**FAILED — no head estimate.** USGS NLDI: locate NHD flowline (COMID) at the point: ProxyError: HTTPSConnectionPool(host='api.water.usgs.gov', port=443): Max retries exceeded with url: /nldi/linked-data/comid/position?coords=POINT%28-74.9668656+42.9334279%29&f=json (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))

## 4. Power potential

```
P(kW) = 9.81 * Q(m3/s) * H(m) * efficiency
```

**Cannot be computed.** Power requires both a head value and a flow value; at least one of them failed above. Specifically:
- head: **unavailable**
- flow: **unavailable**

No power numbers are given here, because any number would be invented.
## 5. Cross-check against ORNL / DOE data

*Target: ORNL HydroSource — New Stream-reach Development (NSD) potential.*

| Endpoint | Result |
|---|---|
| HydroSource site root | **FAILED** — HydroSource site root: ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: / (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))) |
| HydroSource ArcGIS REST catalog | **FAILED** — HydroSource ArcGIS REST catalog: ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /arcgis/rest/services?f=json (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))) |
| HydroSource NSD dataset landing | **FAILED** — HydroSource NSD dataset landing: ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /dataset/new-stream-reach-development-nsd (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))) |
| HydroSource EHA dataset landing | **FAILED** — HydroSource EHA dataset landing: ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /dataset/existing-hydropower-assets-eha (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))) |
| HydroSource CKAN package search (NSD) | **FAILED** — HydroSource CKAN package search (NSD): ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /api/3/action/package_search?q=new+stream-reach+development&rows=10 (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))) |
| HydroSource CKAN package search (EHA) | **FAILED** — HydroSource CKAN package search (EHA): ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /api/3/action/package_search?q=existing+hydropower+assets&rows=10 (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))) |

**No ORNL/DOE data was retrieved.** No NSD estimate is reported for this reach, because none was obtained. This must be checked manually at <https://hydrosource.ornl.gov/>.

> **Context for interpreting NSD either way.** The NSD assessment screened new stream-reach potential nationally and its published reach inventory is oriented to utility-relevant capacity — the national reporting threshold sits far above a 0.5–10 kW homestead machine. A reach of this size being absent from NSD is therefore expected and is **not** evidence against a home-scale project; conversely, a hit would indicate a much larger opportunity than the one being evaluated here.

## 6. Constraints and permitting

### Nearby dams and existing hydropower

**USACE NID query failed** — nearby dams NOT checked. USACE National Inventory of Dams (nearby dams): ProxyError: HTTPSConnectionPool(host='nid.sec.usace.army.mil', port=443): Max retries exceeded with url: /api/dams/search?stateKey=NY&size=5000 (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))

**ORNL Existing Hydropower Assets (EHA) was not retrieved**, so existing hydro facilities near this reach are unverified in this run.

### Environmental sensitivity

Not retrieved in this run. The datasets that would answer it — NYSDEC water quality classification for this reach, NYSDEC trout-stream and spawning designations, USFWS IPaC listed-species review, and NY Natural Heritage Program records — were not queried here and should not be assumed benign. A small headwater creek in this part of central New York has a realistic chance of carrying a trout designation, which raises the permitting bar for any in-channel structure.

### FERC thresholds (general parameters, not legal advice)

These are the general statutory parameters only. They are not a legal opinion,
and a jurisdictional determination for this site can only come from FERC.

- **Conduit hydro.** The Hydropower Regulatory Efficiency Act of 2013 created a
  "qualifying conduit hydropower facility" pathway: a facility on a *non-federally
  owned conduit* that is operated primarily for a purpose other than power
  generation. Qualifying conduit facilities are not required to be licensed or
  exempted; the developer files a notice of intent and FERC issues a determination.
  The capacity ceiling for this pathway was raised to 40 MW by the America's
  Water Infrastructure Act of 2018. A natural stream channel is **not** a
  conduit, so a run-of-river intake on Ocquionis Creek would not normally fit
  this pathway.
- **Conduit exemption.** A separate exemption exists for conduit facilities, also
  capped at 40 MW.
- **Small hydroelectric power project exemption.** Up to 10 MW, generally
  requiring use of an existing dam or a natural water feature without a dam.
- **FERC jurisdiction generally** attaches where a project is on a navigable
  water of the United States, occupies federal land, uses surplus water from a
  federal dam, or affects interstate commerce (this last test is broad and is
  where most small stream projects land).
- **New York State.** Independently of FERC, work in a stream bed in New York
  typically implicates NYSDEC Article 15 Protection of Waters (stream disturbance),
  water-quality certification under Clean Water Act Section 401, SEQRA review,
  and potentially a US Army Corps Section 404 permit. Ocquionis Creek's DEC water
  quality classification determines whether a Protection of Waters permit is
  required at all -- that classification must be looked up for this specific reach.


## Plain-language summary

**No verdict can be given from this run.** The following inputs could not be obtained from their live sources: **watershed delineation, flow, head**. Rather than guess, this report stops here. See the source status table at the top and Appendix B for exactly which endpoints failed and why. Re-run the script from a network that can reach the USGS and ORNL services and the report will populate.

## What must be field-verified before spending real money

1. **Measure the actual flow, repeatedly, through a dry season.** Everything in Step 2 is a statistical transfer from a different watershed. Weir-box or bucket-and-stopwatch measurements taken monthly for at least one full year — and above all in late summer and in a drought year — are what decide whether this site works. Late-summer low flow, not average flow, sets the size of the machine you can actually run.
2. **Survey the real head.** Replace the DEM number with a laser level, a surveyor's rod, or a hose filled with water and a pressure gauge read at the proposed turbine location. Measure to the actual, physically reachable powerhouse site, not to an arbitrary point 1,000 ft downstream.
3. **Walk the penstock route.** Length, pipe diameter, buried vs. surface, stream crossings, rock, and the resulting friction loss determine net head and dominate cost at this scale.
4. **Confirm you control both ends.** Property boundaries and, where the channel is not entirely yours, riparian rights at both the intake and the tailrace.
5. **Get the DEC classification for this reach** and a formal read on Article 15 Protection of Waters, 401 water-quality certification, SEQRA, and any USACE 404 nexus.
6. **Get a written FERC jurisdictional determination** rather than relying on a threshold reading.
7. **Winter behaviour.** Frazil and anchor ice, leaf litter, and spring debris load at the intake decide whether the system runs unattended; screening and intake design follow from that.
8. **Confirm the load and the distance to it** — transmission distance from powerhouse to house, and whether the system is battery-based or grid-tied.

## Appendix A — All API calls made

| # | Source | Status | Endpoint |
|---|---|---|---|
| 1 | StreamStats watershed delineation (rcode=NY) | **FAIL ** | `https://streamstats.usgs.gov/streamstatsservices/watershed.json` |
| 2 | National Map WBD: HUC12 at point | **FAIL ** | `https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/identify` |
| 3 | USGS NWIS site search (bounding box around site) | **FAIL ** | `https://waterservices.usgs.gov/nwis/site/` |
| 4 | USGS NLDI: locate NHD flowline (COMID) at the point | **FAIL ** | `https://api.water.usgs.gov/nldi/linked-data/comid/position` |
| 5 | HydroSource site root | **FAIL ** | `https://hydrosource.ornl.gov/` |
| 6 | HydroSource ArcGIS REST catalog | **FAIL ** | `https://hydrosource.ornl.gov/arcgis/rest/services` |
| 7 | HydroSource NSD dataset landing | **FAIL ** | `https://hydrosource.ornl.gov/dataset/new-stream-reach-development-nsd` |
| 8 | HydroSource EHA dataset landing | **FAIL ** | `https://hydrosource.ornl.gov/dataset/existing-hydropower-assets-eha` |
| 9 | HydroSource CKAN package search (NSD) | **FAIL ** | `https://hydrosource.ornl.gov/api/3/action/package_search` |
| 10 | HydroSource CKAN package search (EHA) | **FAIL ** | `https://hydrosource.ornl.gov/api/3/action/package_search` |
| 11 | USACE National Inventory of Dams (nearby dams) | **FAIL ** | `https://nid.sec.usace.army.mil/api/dams/search` |

## Appendix B — Failures in detail

- **StreamStats watershed delineation (rcode=NY)**  
  `https://streamstats.usgs.gov/streamstatsservices/watershed.json`  
  → ProxyError: HTTPSConnectionPool(host='streamstats.usgs.gov', port=443): Max retries exceeded with url: /streamstatsservices/watershed.json?rcode=NY&xlocation=-74.9668656&ylocation=42.9334279&crs=4326&includeparameters=true&includeflowtypes=false&includefeatures=true&simplify=true (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **National Map WBD: HUC12 at point**  
  `https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/identify`  
  → ProxyError: HTTPSConnectionPool(host='hydro.nationalmap.gov', port=443): Max retries exceeded with url: /arcgis/rest/services/wbd/MapServer/identify?geometry=-74.9668656%2C42.9334279&geometryType=esriGeometryPoint&sr=4326&layers=all&tolerance=2&mapExtent=-75.0168656%2C42.8834279%2C-74.91686560000001%2C42.983427899999995&imageDisplay=600%2C600%2C96&returnGeometry=false&f=json (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **USGS NWIS site search (bounding box around site)**  
  `https://waterservices.usgs.gov/nwis/site/`  
  → ProxyError: HTTPSConnectionPool(host='waterservices.usgs.gov', port=443): Max retries exceeded with url: /nwis/site/?format=rdb&bBox=-75.716866%2C42.183428%2C-74.216866%2C43.683428&siteType=ST&siteOutput=expanded&hasDataTypeCd=dv&parameterCd=00060&siteStatus=all (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **USGS NLDI: locate NHD flowline (COMID) at the point**  
  `https://api.water.usgs.gov/nldi/linked-data/comid/position`  
  → ProxyError: HTTPSConnectionPool(host='api.water.usgs.gov', port=443): Max retries exceeded with url: /nldi/linked-data/comid/position?coords=POINT%28-74.9668656+42.9334279%29&f=json (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **HydroSource site root**  
  `https://hydrosource.ornl.gov/`  
  → ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: / (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **HydroSource ArcGIS REST catalog**  
  `https://hydrosource.ornl.gov/arcgis/rest/services`  
  → ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /arcgis/rest/services?f=json (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **HydroSource NSD dataset landing**  
  `https://hydrosource.ornl.gov/dataset/new-stream-reach-development-nsd`  
  → ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /dataset/new-stream-reach-development-nsd (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **HydroSource EHA dataset landing**  
  `https://hydrosource.ornl.gov/dataset/existing-hydropower-assets-eha`  
  → ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /dataset/existing-hydropower-assets-eha (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **HydroSource CKAN package search (NSD)**  
  `https://hydrosource.ornl.gov/api/3/action/package_search`  
  → ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /api/3/action/package_search?q=new+stream-reach+development&rows=10 (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **HydroSource CKAN package search (EHA)**  
  `https://hydrosource.ornl.gov/api/3/action/package_search`  
  → ProxyError: HTTPSConnectionPool(host='hydrosource.ornl.gov', port=443): Max retries exceeded with url: /api/3/action/package_search?q=existing+hydropower+assets&rows=10 (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))
- **USACE National Inventory of Dams (nearby dams)**  
  `https://nid.sec.usace.army.mil/api/dams/search`  
  → ProxyError: HTTPSConnectionPool(host='nid.sec.usace.army.mil', port=443): Max retries exceeded with url: /api/dams/search?stateKey=NY&size=5000 (Caused by ProxyError('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')))

---

*Generated by `hydro_assessment.py`. Every value above is either a live API response or an explicit NOT AVAILABLE / FAILED marker. No placeholder or remembered values were substituted.*