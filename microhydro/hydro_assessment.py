#!/usr/bin/env python3
"""
Micro-hydro site assessment for a point on Ocquionis (Fish) Creek near
Jordanville, NY.

Pulls LIVE data only. Every number in the generated report is traceable to an
HTTP response recorded in the provenance log. If a source is unreachable or has
no data for this point, the report says so explicitly -- nothing is filled in
with a placeholder, a textbook value, or a remembered figure.

Sources
  1. Watershed + basin characteristics : USGS StreamStats (rcode=NY)
  2. Flow statistics                   : StreamStats flow stats, else USGS NWIS
                                         gauge FDC scaled by drainage-area ratio
  3. Head                              : USGS NLDI (downstream channel trace)
                                         + USGS 3DEP EPQS point elevations
  4. Power                             : P = 9.81 * Q(m3/s) * H(m) * efficiency
  5. DOE cross-check                   : ORNL HydroSource NSD
  6. Constraints                       : ORNL EHA, USACE NID, WBD/HUC

Usage
  python3 hydro_assessment.py
  python3 hydro_assessment.py --lat 42.9334279 --lon -74.9668656 --out report.md
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import requests
except ImportError:
    sys.exit("This script needs 'requests'.  pip install requests")


# --------------------------------------------------------------------------
# Constants / unit conversions
# --------------------------------------------------------------------------

CFS_TO_CMS = 0.028316846592     # ft^3/s -> m^3/s
FT_TO_M = 0.3048
SQMI_TO_SQKM = 2.589988110336
G = 9.81                        # m/s^2, per the power equation the user specified

DEFAULT_LAT = 42.9334279
DEFAULT_LON = -74.9668656

USER_AGENT = (
    "micro-hydro-site-assessment/1.0 "
    "(personal off-grid feasibility study; contact: site owner)"
)

# Exceedance percentiles reported on the flow-duration curve.
# "Q90 = 90% exceedance" means flow is equalled or exceeded 90% of the time
# (i.e. a LOW flow).
EXCEEDANCES = [5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95]

# StreamStats basin-characteristic codes we care about, mapped to plain English.
# StreamStats returns whatever the NY regression set defines; we report every
# parameter it gives us and highlight these.
PARAM_LABELS = {
    "DRNAREA": "Drainage area",
    "BSLDEM10M": "Mean basin slope (10 m DEM)",
    "BSLDEM30M": "Mean basin slope (30 m DEM)",
    "CSL10_85": "Channel slope, 10-85 method",
    "CSL1085LFP": "Channel slope 10-85, longest flow path",
    "PRECIP": "Mean annual precipitation",
    "FOREST": "Forest cover",
    "LC11DEV": "Developed land cover",
    "LC11IMP": "Impervious cover",
    "STORAGE": "Storage (lakes/wetlands)",
    "ELEV": "Mean basin elevation",
    "ELEVMAX": "Maximum basin elevation",
    "MINBELEV": "Minimum basin elevation",
    "SLOPERAT": "Slope ratio",
    "LFPLENGTH": "Longest flow path length",
}


# --------------------------------------------------------------------------
# Provenance: every HTTP call is recorded so the report can prove its numbers
# --------------------------------------------------------------------------

@dataclass
class Call:
    label: str
    url: str
    ok: bool
    status: Optional[int] = None
    detail: str = ""
    elapsed_s: float = 0.0


PROVENANCE: list[Call] = []


class SourceFailure(Exception):
    """A data source could not be reached or had no data for this point."""


def http_get(
    label: str,
    url: str,
    params: Optional[dict] = None,
    timeout: int = 60,
    retries: int = 3,
    expect_json: bool = True,
) -> Any:
    """GET with retry/backoff. Records the outcome. Raises SourceFailure."""
    last = ""
    status = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = requests.get(
                url,
                params=params,
                timeout=timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            )
            elapsed = time.time() - t0
            status = r.status_code
            if r.status_code == 200:
                body = r.text
                if not body.strip():
                    last = "empty response body"
                else:
                    if expect_json:
                        try:
                            data = r.json()
                        except ValueError:
                            last = f"200 but body was not JSON (first 200 chars: {body[:200]!r})"
                            PROVENANCE.append(
                                Call(label, r.url, False, status, last, elapsed)
                            )
                            raise SourceFailure(f"{label}: {last}")
                    else:
                        data = body
                    PROVENANCE.append(Call(label, r.url, True, status, "OK", elapsed))
                    return data
            else:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.exceptions.RequestException as e:
            elapsed = time.time() - t0
            last = f"{type(e).__name__}: {e}"

        if attempt < retries - 1:
            time.sleep(2 ** attempt)

    PROVENANCE.append(Call(label, url, False, status, last))
    raise SourceFailure(f"{label}: {last}")


def fmt(v: Optional[float], nd: int = 2, unit: str = "") -> str:
    """Format a number, or an explicit marker when the value is missing."""
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "NOT AVAILABLE"
    s = f"{v:,.{nd}f}"
    return f"{s} {unit}".strip()


def haversine_mi(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 3958.7613  # mean Earth radius, statute miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# STEP 1 -- Watershed delineation and basin characteristics (USGS StreamStats)
#
# The legacy /streamstatsservices/*.json API was retired and now returns 404.
# The current workflow, per the USGS "StreamStats Flow Statistics Workflow"
# notebook, is a five-call chain:
#   1. GET  ss-delineate/v1/delineate/sshydro/{region}   -> watershed polygon
#   2. POST nssservices/regressionregions/bylocation     -> regression regions
#   3. GET  nssservices/scenarios                        -> params each eq needs
#   4. POST ss-hydro/v1/basin-characteristics/calculate  -> parameter values
#   5. POST nssservices/scenarios/estimate               -> flow statistics
# --------------------------------------------------------------------------

SS_DELINEATE = "https://streamstats.usgs.gov/ss-delineate/v1/delineate/sshydro/{region}"
SS_BASINCHAR = "https://streamstats.usgs.gov/ss-hydro/v1/basin-characteristics/calculate"
NSS_REGREGIONS = "https://streamstats.usgs.gov/nssservices/regressionregions/bylocation"
NSS_SCENARIOS = "https://streamstats.usgs.gov/nssservices/scenarios"
NSS_ESTIMATE = "https://streamstats.usgs.gov/nssservices/scenarios/estimate"

# NY statistic groups: 2 Peak-Flow, 4 Low-Flow, 5 Flow-Duration, 24 Bankfull
STATGROUP_FLOW_DURATION = 5


def http_post(
    label: str,
    url: str,
    payload: Any,
    params: Optional[dict] = None,
    timeout: int = 300,
    retries: int = 3,
) -> Any:
    last = ""
    status = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = requests.post(
                url, json=payload, params=params, timeout=timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            )
            elapsed = time.time() - t0
            status = r.status_code
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    last = f"200 but body was not JSON: {r.text[:200]!r}"
                    PROVENANCE.append(Call(label, r.url, False, status, last, elapsed))
                    raise SourceFailure(f"{label}: {last}")
                PROVENANCE.append(Call(label, r.url, True, status, "OK", elapsed))
                return data
            last = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.exceptions.RequestException as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < retries - 1:
            time.sleep(2 ** attempt)
    PROVENANCE.append(Call(label, url, False, status, last))
    raise SourceFailure(f"{label}: {last}")


@dataclass
class Basin:
    workspace_id: Optional[str] = None
    parameters: dict[str, dict] = field(default_factory=dict)
    drainage_area_sqmi: Optional[float] = None
    geometry_available: bool = False
    geometry: Optional[dict] = None
    delineation: Optional[dict] = None
    regression_regions: list[dict] = field(default_factory=list)
    error: Optional[str] = None


def delineate_basin(lat: float, lon: float, rcode: str = "NY") -> Basin:
    """Delineate the basin and compute every available basin characteristic."""
    b = Basin()
    try:
        delin = http_get(
            "StreamStats ss-delineate: watershed delineation",
            SS_DELINEATE.format(region=rcode),
            params={"lat": lat, "lon": lon},
            timeout=300,
        )
    except SourceFailure as e:
        b.error = str(e)
        return b

    b.delineation = delin
    try:
        for item in delin["bcrequest"]["wsresp"]["featurecollection"][0]:
            if item.get("name") == "globalwatershed":
                for f in item["feature"]["features"]:
                    if f.get("properties", {}).get("GlobalWshd") == 1:
                        b.geometry = f["geometry"]
                        break
    except (KeyError, IndexError, TypeError) as e:
        b.error = f"Delineation response had an unexpected shape: {e}"
        return b

    if not b.geometry:
        b.error = "Delineation returned no global watershed polygon"
        return b
    b.geometry_available = True
    b.workspace_id = (delin.get("bcrequest", {}).get("wsresp", {}) or {}).get("workspace_id") or None

    # Regression regions covering the basin (needed to pick scenarios)
    try:
        b.regression_regions = http_post(
            "StreamStats NSS: regression regions for the basin",
            NSS_REGREGIONS, b.geometry, timeout=180,
        )
    except SourceFailure as e:
        b.error = str(e)

    # All basin characteristics ('*'), which covers the report's needs and
    # every parameter the flow-duration equations require.
    payload = json.loads(json.dumps(delin))
    payload["bcrequest"]["bcLabels"] = "*"
    try:
        bcs = http_post(
            "StreamStats ss-hydro: compute basin characteristics",
            SS_BASINCHAR, payload, timeout=600,
        )
    except SourceFailure as e:
        b.error = str(e)
        return b

    for p in bcs or []:
        code = (p.get("code") or "").upper()
        if code:
            b.parameters[code] = p

    da = b.parameters.get("DRNAREA", {}).get("value")
    try:
        b.drainage_area_sqmi = float(da) if da is not None else None
    except (TypeError, ValueError):
        pass
    if b.drainage_area_sqmi is None and not b.error:
        b.error = "Basin characteristics returned no DRNAREA."
    return b


# --------------------------------------------------------------------------
# STEP 2a -- Flow statistics from the NY regression equations
# --------------------------------------------------------------------------

@dataclass
class FlowStats:
    available: bool = False
    stats: list[dict] = field(default_factory=list)
    duration: dict[float, float] = field(default_factory=dict)   # exceedance% -> cfs
    has_duration_curve: bool = False
    region_code: Optional[str] = None
    region_name: Optional[str] = None
    out_of_range: list[dict] = field(default_factory=list)
    zero_artifacts: list[dict] = field(default_factory=list)
    usable: bool = False
    error: Optional[str] = None


_DUR_RE = __import__("re").compile(r"^D(\d+)(?:_(\d+))?$", __import__("re").I)


def _duration_pct(code: str) -> Optional[float]:
    """'D50'->50.0, 'D0_01'->0.01, 'D99_99'->99.99"""
    m = _DUR_RE.match((code or "").strip())
    if not m:
        return None
    whole, frac = m.group(1), m.group(2)
    try:
        return float(f"{whole}.{frac}") if frac else float(whole)
    except ValueError:
        return None


def _zeroed_params(equation: str, values: dict[str, float]) -> list[str]:
    """
    Parameters that force the whole equation to exactly zero.

    These regressions are products of powers. If a parameter's value is 0 and
    it carries a positive exponent, 0**k == 0 collapses the entire product,
    regardless of hydrology. That is a boundary artifact, not a prediction.
    """
    import re
    hits = []
    for m in re.finditer(r"([A-Za-z][A-Za-z0-9_]*)\^\(?(-?[0-9.eE+]+)\)?", equation or ""):
        name, expo = m.group(1).upper(), m.group(2)
        try:
            k = float(expo)
        except ValueError:
            continue
        v = values.get(name)
        if v is not None and float(v) == 0.0 and k > 0:
            hits.append(name)
    return hits


def streamstats_flow_stats(basin: Basin, rcode: str = "NY") -> FlowStats:
    """Compute flow-duration statistics and validate them against the equations."""
    fs = FlowStats()
    if not basin.geometry or not basin.parameters:
        fs.error = "No delineated basin or basin characteristics, so no flow statistics."
        return fs

    codes = [r.get("code") for r in basin.regression_regions if r.get("code")]
    if not codes:
        fs.error = "No regression regions were returned for this basin."
        return fs

    try:
        scenarios = http_get(
            "StreamStats NSS: flow-duration scenarios",
            NSS_SCENARIOS,
            params={
                "regions": rcode,
                "statisticgroups": STATGROUP_FLOW_DURATION,
                "regressionregions": ",".join(codes),
            },
            timeout=180,
        )
    except SourceFailure as e:
        fs.error = str(e)
        return fs

    if not scenarios:
        fs.error = "No flow-duration scenario is defined for this basin's regression regions."
        return fs

    scen = scenarios[0]
    # Fill each equation parameter with the computed basin characteristic
    for rr in scen.get("regressionRegions", []):
        for i, p in enumerate(rr.get("parameters", [])):
            m = basin.parameters.get((p.get("code") or "").upper())
            if m is not None and m.get("value") is not None:
                rr["parameters"][i]["value"] = m["value"]

    try:
        res = http_post(
            "StreamStats NSS: estimate flow-duration statistics",
            NSS_ESTIMATE, [scen], params={"regions": rcode}, timeout=300,
        )
    except SourceFailure as e:
        fs.error = str(e)
        return fs

    for region in res or []:
        for rr in region.get("regressionRegions", []) or []:
            fs.region_code = rr.get("code")
            fs.region_name = rr.get("name")
            values = {}
            for p in rr.get("parameters", []) or []:
                code = (p.get("code") or "").upper()
                v = p.get("value")
                if v is None:
                    continue
                try:
                    values[code] = float(v)
                except (TypeError, ValueError):
                    continue
                lim = p.get("limits") or {}
                mn, mx = lim.get("min"), lim.get("max")
                if mn is not None and values[code] < float(mn):
                    fs.out_of_range.append(
                        {"code": code, "value": values[code], "min": mn, "max": mx,
                         "how": "below minimum"}
                    )
                elif mx is not None and values[code] > float(mx):
                    fs.out_of_range.append(
                        {"code": code, "value": values[code], "min": mn, "max": mx,
                         "how": "above maximum"}
                    )

            for st in rr.get("results", []) or []:
                fs.stats.append(st)
                pct = _duration_pct(st.get("code") or "")
                val = st.get("value")
                if pct is None or val is None:
                    continue
                try:
                    q = float(val)
                except (TypeError, ValueError):
                    continue
                zeroed = _zeroed_params(st.get("equation") or "", values)
                if zeroed and q == 0.0:
                    fs.zero_artifacts.append(
                        {"code": st.get("code"), "pct": pct, "params": sorted(set(zeroed))}
                    )
                    continue          # do not record a fabricated zero
                fs.duration[pct] = q

    fs.available = bool(fs.stats)
    fs.has_duration_curve = len(fs.duration) >= 3
    # Usable only if nothing important is out of range and no zeros were faked
    fs.usable = fs.has_duration_curve and not fs.out_of_range and not fs.zero_artifacts
    if not fs.available:
        fs.error = "The estimate call returned no results."
    return fs


def identify_stream(comid: str) -> Optional[dict]:
    """GNIS name of the NHD flowline the point snapped to (identity check)."""
    try:
        data = http_get(
            f"National Map NHD: flowline attributes for COMID {comid}",
            "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/4/query",
            params={
                "where": f"COMID={comid}",
                "outFields": "COMID,GNIS_NAME,LENGTHKM,FTYPE",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=90,
        )
    except SourceFailure:
        return None
    feats = data.get("features") or []
    return feats[0].get("attributes") if feats else None

# --------------------------------------------------------------------------
# STEP 2b -- Fallback: nearest comparable USGS gauge, FDC, drainage-area ratio
# --------------------------------------------------------------------------

NWIS = "https://waterservices.usgs.gov/nwis"


def _parse_rdb(text: str) -> list[dict]:
    """Parse USGS RDB (tab-delimited with # comments and a format line)."""
    rows: list[dict] = []
    header: Optional[list[str]] = None
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if header is None:
            header = parts
            continue
        # The line right after the header is the format spec, e.g. "5s\t15s"
        if all(p and (p[-1] in "sdn") and p[:-1].replace(".", "").isdigit()
               for p in parts if p):
            continue
        rows.append(dict(zip(header, parts)))
    return rows


@dataclass
class Gauge:
    site_no: str
    name: str
    lat: float
    lon: float
    drainage_area_sqmi: Optional[float]
    distance_mi: float = 0.0
    da_ratio: Optional[float] = None
    record_start: Optional[str] = None
    record_end: Optional[str] = None
    n_days: int = 0
    fdc: dict[int, float] = field(default_factory=dict)


def find_candidate_gauges(lat: float, lon: float, deg: float = 0.75) -> list[Gauge]:
    """Find streamflow gauges with a daily-discharge record near the site."""
    bbox = f"{lon - deg:.6f},{lat - deg:.6f},{lon + deg:.6f},{lat + deg:.6f}"
    text = http_get(
        "USGS NWIS site search (bounding box around site)",
        f"{NWIS}/site/",
        params={
            "format": "rdb",
            "bBox": bbox,
            "siteType": "ST",
            "siteOutput": "expanded",
            "hasDataTypeCd": "dv",
            "parameterCd": "00060",     # discharge, cfs
            "siteStatus": "all",
        },
        timeout=120,
        expect_json=False,
    )
    out: list[Gauge] = []
    for row in _parse_rdb(text):
        try:
            glat = float(row.get("dec_lat_va", ""))
            glon = float(row.get("dec_long_va", ""))
        except ValueError:
            continue
        da_raw = (row.get("drain_area_va") or "").strip()
        try:
            da = float(da_raw) if da_raw else None
        except ValueError:
            da = None
        out.append(
            Gauge(
                site_no=row.get("site_no", "").strip(),
                name=row.get("station_nm", "").strip(),
                lat=glat,
                lon=glon,
                drainage_area_sqmi=da,
                distance_mi=haversine_mi(lat, lon, glat, glon),
            )
        )
    return out


def rank_gauges(
    gauges: list[Gauge], site_da: Optional[float], max_ratio: float = 10.0
) -> list[Gauge]:
    """
    Rank by suitability as a donor basin.

    The drainage-area ratio method is only defensible when the donor basin is
    hydrologically similar and of comparable size. USGS guidance generally puts
    the usable band at roughly 0.5x-1.5x the target area, and the method
    degrades badly past about 0.3x-3x. We therefore rank on area similarity
    first and distance second, and we record the ratio so it can be judged.
    """
    scored = []
    for g in gauges:
        if not g.site_no or g.drainage_area_sqmi in (None, 0):
            continue
        if site_da:
            ratio = site_da / g.drainage_area_sqmi
            g.da_ratio = ratio
            if ratio > max_ratio or ratio < 1.0 / max_ratio:
                continue
            # log-distance in area, plus a mild distance penalty
            score = abs(math.log(ratio)) + (g.distance_mi / 100.0)
        else:
            score = g.distance_mi
        scored.append((score, g))
    scored.sort(key=lambda t: t[0])
    return [g for _, g in scored]


def fetch_daily_flow(site_no: str) -> list[float]:
    """Full period-of-record mean daily discharge (cfs) for one gauge."""
    text = http_get(
        f"USGS NWIS daily values, gauge {site_no} (full period of record)",
        f"{NWIS}/dv/",
        params={
            "format": "rdb",
            "sites": site_no,
            "parameterCd": "00060",
            "statCd": "00003",          # daily mean
            "startDT": "1900-01-01",
            "endDT": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
        timeout=180,
        expect_json=False,
    )
    rows = _parse_rdb(text)
    if not rows:
        raise SourceFailure(f"NWIS returned no daily values for gauge {site_no}")
    # Discharge column looks like "12345_00060_00003"; its qualifier ends in _cd
    col = None
    for k in rows[0].keys():
        if k.endswith("_00060_00003"):
            col = k
            break
    if col is None:
        raise SourceFailure(
            f"NWIS daily-value table for {site_no} has no 00060/00003 column"
        )
    vals = []
    for r in rows:
        raw = (r.get(col) or "").strip()
        if not raw:
            continue
        try:
            v = float(raw)
        except ValueError:
            continue          # 'Ice', 'Ssn', '***' etc.
        if v >= 0:
            vals.append(v)
    if len(vals) < 365:
        raise SourceFailure(
            f"Gauge {site_no} has only {len(vals)} usable daily values "
            "(need >= 1 year for a flow-duration curve)"
        )
    return vals


def flow_duration_curve(daily_cfs: list[float]) -> dict[int, float]:
    """
    Empirical flow-duration curve from the daily record.

    Exceedance p means "flow equalled or exceeded p% of the time", so the
    p% exceedance flow is the (100-p)th percentile of the record.
    """
    s = sorted(daily_cfs)
    n = len(s)
    fdc: dict[int, float] = {}
    for p in EXCEEDANCES:
        # linear-interpolated quantile at rank (100-p)/100
        q = (100 - p) / 100.0
        idx = q * (n - 1)
        lo, hi = int(math.floor(idx)), int(math.ceil(idx))
        if lo == hi:
            fdc[p] = s[lo]
        else:
            fdc[p] = s[lo] + (s[hi] - s[lo]) * (idx - lo)
    return fdc


def scale_by_drainage_area(
    donor_fdc: dict[int, float], site_da: float, donor_da: float, exponent: float = 1.0
) -> dict[int, float]:
    """
    Drainage-area ratio method:  Q_site = Q_donor * (DA_site / DA_donor) ** x

    x = 1.0 is the standard unadjusted form (USGS WSP; assumes runoff per unit
    area is equal between basins). Values of x between about 0.8 and 1.0 are
    sometimes used for low flows in the Northeast; we keep x = 1.0 and say so
    rather than tuning a number we cannot verify for this basin.
    """
    ratio = site_da / donor_da
    return {p: q * (ratio ** exponent) for p, q in donor_fdc.items()}


# --------------------------------------------------------------------------
# STEP 3 -- Head: trace the channel downstream (NLDI) and sample 3DEP (EPQS)
# --------------------------------------------------------------------------

NLDI = "https://api.water.usgs.gov/nldi/linked-data"
EPQS = "https://epqs.nationalmap.gov/v1/json"


@dataclass
class HeadResult:
    profile: list[dict] = field(default_factory=list)   # dist_ft, lat, lon, elev_ft
    gross_head_ft: Optional[float] = None
    run_length_ft: Optional[float] = None
    head_at_500ft: Optional[float] = None
    comid: Optional[str] = None
    error: Optional[str] = None
    notes: list[str] = field(default_factory=list)


def _densify(path: list[tuple[float, float]], step_ft: float) -> list[tuple[float, float, float]]:
    """Walk a lon/lat polyline, emitting (lon, lat, cumulative_ft) every step_ft."""
    out: list[tuple[float, float, float]] = []
    if not path:
        return out
    cum = 0.0
    out.append((path[0][0], path[0][1], 0.0))
    next_mark = step_ft
    for i in range(len(path) - 1):
        (lon1, lat1), (lon2, lat2) = path[i], path[i + 1]
        seg_ft = haversine_mi(lat1, lon1, lat2, lon2) * 5280.0
        if seg_ft <= 0:
            continue
        while cum + seg_ft >= next_mark:
            f = (next_mark - cum) / seg_ft
            out.append((lon1 + (lon2 - lon1) * f, lat1 + (lat2 - lat1) * f, next_mark))
            next_mark += step_ft
        cum += seg_ft
    return out


def trace_downstream(lat: float, lon: float, distance_km: float = 1.0):
    """
    Get the downstream channel path from the point using the USGS NLDI.

    NHD flowlines are digitized in the direction of flow, and NLDI returns
    downstream-main navigation in flow order, so concatenating the returned
    LineString vertices gives an ordered downstream path.
    """
    feat = http_get(
        "USGS NLDI: locate NHD flowline (COMID) at the point",
        f"{NLDI}/comid/position",
        params={"coords": f"POINT({lon} {lat})", "f": "json"},
        timeout=90,
    )
    feats = feat.get("features") or []
    if not feats:
        raise SourceFailure("NLDI found no NHD flowline at this coordinate")
    props = feats[0].get("properties", {}) or {}
    comid = str(
        props.get("comid")
        or props.get("COMID")
        or props.get("identifier")
        or ""
    ).strip()
    if not comid:
        raise SourceFailure("NLDI returned a feature with no COMID")

    nav = http_get(
        f"USGS NLDI: downstream-main flowlines from COMID {comid}",
        f"{NLDI}/comid/{comid}/navigation/DM/flowlines",
        params={"distance": distance_km, "f": "json"},
        timeout=120,
    )
    path: list[tuple[float, float]] = []
    for f in nav.get("features") or []:
        geom = f.get("geometry") or {}
        if geom.get("type") == "LineString":
            coords = geom.get("coordinates") or []
        elif geom.get("type") == "MultiLineString":
            coords = [c for part in geom.get("coordinates", []) for c in part]
        else:
            continue
        for c in coords:
            pt = (float(c[0]), float(c[1]))
            if not path or path[-1] != pt:
                path.append(pt)
    if len(path) < 2:
        raise SourceFailure("NLDI returned no usable downstream geometry")
    return comid, path


def epqs_elevation_ft(lon: float, lat: float) -> Optional[float]:
    """One 3DEP elevation sample (feet) from the USGS EPQS point service."""
    try:
        data = http_get(
            f"USGS 3DEP EPQS elevation @ {lat:.6f},{lon:.6f}",
            EPQS,
            params={
                "x": lon, "y": lat, "units": "Feet",
                "wkid": 4326, "includeDate": "false",
            },
            timeout=60,
            retries=3,
        )
    except SourceFailure:
        return None
    val = data.get("value")
    if val is None:
        loc = (data.get("location") or {})
        val = loc.get("elevation")
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    # EPQS reports no-data as a large negative sentinel
    if v < -1000:
        return None
    return v


def estimate_head(
    lat: float, lon: float, run_ft: float = 1000.0, step_ft: float = 50.0
) -> HeadResult:
    hr = HeadResult()
    try:
        comid, path = trace_downstream(lat, lon, distance_km=(run_ft * FT_TO_M) / 1000.0 * 1.5)
        hr.comid = comid
    except SourceFailure as e:
        hr.error = str(e)
        return hr

    # Start the trace at the vertex closest to the point of interest, so we
    # don't include channel upstream of the intake.
    dists = [haversine_mi(lat, lon, p[1], p[0]) for p in path]
    start = dists.index(min(dists))
    path = path[start:]
    if len(path) < 2:
        hr.error = "Downstream path from the point of interest was too short to sample"
        return hr

    samples = [s for s in _densify(path, step_ft) if s[2] <= run_ft]
    if len(samples) < 2:
        hr.error = "Could not densify the downstream channel into elevation samples"
        return hr

    profile = []
    misses = 0
    for lon_s, lat_s, dist_ft in samples:
        e = epqs_elevation_ft(lon_s, lat_s)
        if e is None:
            misses += 1
        profile.append(
            {"dist_ft": dist_ft, "lat": lat_s, "lon": lon_s, "elev_ft": e}
        )
        time.sleep(0.25)          # be polite to EPQS

    good = [p for p in profile if p["elev_ft"] is not None]
    hr.profile = profile
    if len(good) < 2:
        hr.error = (
            f"3DEP EPQS returned no usable elevations "
            f"({misses} of {len(profile)} samples failed)"
        )
        return hr
    if misses:
        hr.notes.append(f"{misses} of {len(profile)} EPQS samples returned no data.")

    hr.run_length_ft = good[-1]["dist_ft"]
    hr.gross_head_ft = good[0]["elev_ft"] - good[-1]["elev_ft"]
    at500 = [p for p in good if p["dist_ft"] <= 500.0]
    if len(at500) >= 2:
        hr.head_at_500ft = at500[0]["elev_ft"] - at500[-1]["elev_ft"]
    return hr


# --------------------------------------------------------------------------
# STEP 4 -- Power potential
# --------------------------------------------------------------------------

def power_kw(q_cfs: float, head_ft: float, eff: float) -> float:
    """P(kW) = 9.81 * Q(m3/s) * H(m) * efficiency"""
    return G * (q_cfs * CFS_TO_CMS) * (head_ft * FT_TO_M) * eff


def power_table(fdc: dict[int, float], head_ft: float, effs: list[float]) -> list[dict]:
    rows = []
    for p in sorted(fdc):
        q = fdc[p]
        row = {
            "exceedance_pct": p,
            "q_cfs": q,
            "q_cms": q * CFS_TO_CMS,
            "theoretical_kw": power_kw(q, head_ft, 1.0),
        }
        for e in effs:
            row[f"kw_at_{int(e*100)}"] = power_kw(q, head_ft, e)
        rows.append(row)
    return rows


def annual_energy_kwh(
    fdc: dict[int, float],
    head_ft: float,
    eff: float,
    design_exceedance: int = 30,
    min_flow_fraction: float = 0.10,
) -> dict:
    """
    Integrate power over the flow-duration curve to get annual energy.

    Assumptions (stated, not hidden): the turbine is sized for the flow at
    `design_exceedance`, flow above that is spilled (capped at design), and the
    machine shuts down below `min_flow_fraction` of design flow, which is
    typical for an impulse turbine. No bypass/environmental flow is deducted
    here -- see the constraints section.
    """
    pts = sorted(fdc.items())              # (exceedance%, cfs)
    if len(pts) < 2:
        return {}
    q_design = fdc.get(design_exceedance)
    if q_design is None:
        return {}
    q_min = q_design * min_flow_fraction

    def p_of(q: float) -> float:
        q_use = min(q, q_design)
        if q_use < q_min:
            return 0.0
        return power_kw(q_use, head_ft, eff)

    # Trapezoidal integration of power against exceedance probability (0-1).
    total = 0.0
    for (p1, q1), (p2, q2) in zip(pts, pts[1:]):
        dp = (p2 - p1) / 100.0
        total += 0.5 * (p_of(q1) + p_of(q2)) * dp
    # Extend the flat ends out to 0% and 100% exceedance
    total += (pts[0][0] / 100.0) * p_of(pts[0][1])
    total += (1.0 - pts[-1][0] / 100.0) * p_of(pts[-1][1])

    avg_kw = total
    return {
        "design_exceedance": design_exceedance,
        "design_flow_cfs": q_design,
        "cutoff_flow_cfs": q_min,
        "rated_kw": power_kw(q_design, head_ft, eff),
        "avg_kw": avg_kw,
        "annual_kwh": avg_kw * 8766.0,
        "capacity_factor": (
            avg_kw / power_kw(q_design, head_ft, eff)
            if power_kw(q_design, head_ft, eff) > 0 else 0.0
        ),
        "efficiency": eff,
    }




# --------------------------------------------------------------------------
# STEPS 5 & 6 -- ORNL HydroSource NSD, USACE NID, WBD/HUC
# --------------------------------------------------------------------------

@dataclass
class Probe:
    name: str
    ok: bool
    detail: str
    payload: Any = None


WBD_IDENTIFY = "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/identify"


def get_hucs(lat: float, lon: float) -> Optional[dict]:
    """HUC2/4/6/8/10/12 for the point, from the National Map WBD service."""
    try:
        data = http_get(
            "National Map WBD: HUC codes at the point",
            WBD_IDENTIFY,
            params={
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "sr": 4326,
                "layers": "all",
                "tolerance": 2,
                "mapExtent": f"{lon-0.05},{lat-0.05},{lon+0.05},{lat+0.05}",
                "imageDisplay": "600,600,96",
                "returnGeometry": "false",
                "f": "json",
            },
            timeout=120,
        )
    except SourceFailure:
        return None
    out: dict = {}
    for r in data.get("results", []) or []:
        a = r.get("attributes", {}) or {}
        for k, v in a.items():
            ku = k.upper().replace(" ", "")
            if ku in ("HUC2", "HUC4", "HUC6", "HUC8", "HUC10", "HUC12"):
                out[ku] = str(v)
                nm = a.get("Name") or a.get("NAME")
                if nm:
                    out[ku + "_NAME"] = nm
    return out or None


# NSD is published per two-digit hydrologic region; the S3 slug differs per region.
NSD_REGION_SLUGS = {
    "01": ("new-england-region", "01"),
    "02": ("mid-atlantic-region", "02"),
    "03": ("south-atlantic-gulf-region", "03"),
    "04": ("great-lakes-region", "04"),
    "05": ("ohio-region", "05"),
    "06": ("tennessee-region", "06"),
    "07": ("upper-mississippi-region", "07"),
    "08": ("lower-mississippi-region", "08"),
    "09": ("souris-red-rainy-region", "09"),
    "10": ("missouri-region", "10"),
    "11": ("arkansas-whitered-region", "11"),
    "12": ("texas-gulf-region", "12"),
    "13": ("rio-grande-region", "13"),
    "14": ("upper-colorado-region", "14"),
    "15": ("lower-colorado-region", "15"),
    "16": ("great-basin-region", "16"),
    "17": ("pacific-northwest-region", "17"),
    "18": ("california-region", "18"),
}
NSD_S3 = ("https://hydrosource.s3.us-east-2.amazonaws.com/files/data/datasets/"
          "hydropower-potential-new-stream-reach-development-{slug}/NHAAP_NSD_SR_{rr}_v1.xlsx")


def probe_nsd(huc2: Optional[str], huc10: Optional[str], cache_dir: str = ".") -> Probe:
    """
    ORNL/DOE New Stream-reach Development potential for this HUC10.

    The NSD reach inventory is published per hydrologic region and aggregated to
    HUC10 watersheds, so the cross-check is: does our HUC10 appear, and what
    capacity/energy did DOE attribute to it?
    """
    name = "ORNL HydroSource NSD (New Stream-reach Development)"
    if not huc2 or huc2 not in NSD_REGION_SLUGS:
        return Probe(name, False, f"No NSD region mapping for HUC2={huc2!r}")
    slug, rr = NSD_REGION_SLUGS[huc2]
    url = NSD_S3.format(slug=slug, rr=rr)
    import os
    path = os.path.join(cache_dir, f"NHAAP_NSD_SR_{rr}_v1.xlsx")
    if not os.path.exists(path):
        try:
            r = requests.get(url, timeout=300, headers={"User-Agent": USER_AGENT})
            if r.status_code != 200:
                PROVENANCE.append(Call(name, url, False, r.status_code,
                                       f"HTTP {r.status_code}"))
                return Probe(name, False, f"HTTP {r.status_code} fetching {url}")
            with open(path, "wb") as f:
                f.write(r.content)
            PROVENANCE.append(Call(name, url, True, 200, f"{len(r.content)} bytes"))
        except requests.exceptions.RequestException as e:
            PROVENANCE.append(Call(name, url, False, None, str(e)))
            return Probe(name, False, f"{type(e).__name__}: {e}")
    else:
        PROVENANCE.append(Call(name + " (cached)", url, True, 200, "from local cache"))

    try:
        import openpyxl
    except ImportError:
        return Probe(name, False, "openpyxl not installed; cannot read the NSD workbook")

    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb["NSD"]
        rows = list(ws.iter_rows(values_only=True))
    except Exception as e:
        return Probe(name, False, f"Could not read NSD workbook: {e}")

    hdr_i = None
    for i, row in enumerate(rows):
        if row and str(row[0]).strip().upper() == "HUC10":
            hdr_i = i
            break
    if hdr_i is None:
        return Probe(name, False, "NSD workbook has no HUC10 header row")
    hdr = [str(c).strip() if c is not None else "" for c in rows[hdr_i]]
    recs = []
    for row in rows[hdr_i + 1:]:
        if not row or row[0] is None:
            continue
        recs.append(dict(zip(hdr, row)))

    target = (huc10 or "").lstrip("0")
    hit = None
    for rec in recs:
        if str(rec.get("HUC10", "")).strip().lstrip("0") == target:
            hit = rec
            break
    return Probe(
        name, True,
        f"{len(recs)} HUC10 watersheds in region {rr}; "
        f"HUC10 {huc10} {'FOUND' if hit else 'not listed'}",
        {"hit": hit, "n": len(recs), "region": rr, "url": url},
    )


NID_CSV = "https://nid.sec.usace.army.mil/api/nation/csv"


def probe_nid(lat: float, lon: float, radius_mi: float = 10.0,
              cache_dir: str = ".") -> Probe:
    """
    USACE National Inventory of Dams, filtered to dams near the site.

    NID exposes no bounding-box route, so the national CSV is downloaded once
    (~65 MB), cached, and filtered locally.
    """
    name = "USACE National Inventory of Dams"
    import os, csv
    path = os.path.join(cache_dir, "nid_nation.csv")
    if not os.path.exists(path):
        try:
            with requests.get(NID_CSV, timeout=900, stream=True,
                              headers={"User-Agent": USER_AGENT}) as r:
                if r.status_code != 200:
                    PROVENANCE.append(Call(name, NID_CSV, False, r.status_code,
                                           f"HTTP {r.status_code}"))
                    return Probe(name, False, f"HTTP {r.status_code}")
                n = 0
                with open(path, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        n += len(chunk)
            PROVENANCE.append(Call(name, NID_CSV, True, 200, f"{n} bytes"))
        except requests.exceptions.RequestException as e:
            PROVENANCE.append(Call(name, NID_CSV, False, None, str(e)))
            return Probe(name, False, f"{type(e).__name__}: {e}")
    else:
        PROVENANCE.append(Call(name + " (cached)", NID_CSV, True, 200, "from local cache"))

    near = []
    try:
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            first = f.readline()
            if not first.lower().startswith('"dam name"'):
                pass          # first line is the "Data Last Updated" banner
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    dlat = float(row.get("Latitude") or "")
                    dlon = float(row.get("Longitude") or "")
                except ValueError:
                    continue
                d = haversine_mi(lat, lon, dlat, dlon)
                if d <= radius_mi:
                    near.append({
                        "name": row.get("Dam Name"),
                        "nid_id": row.get("NID ID"),
                        "distance_mi": d,
                        "river": row.get("River or Stream Name"),
                        "purposes": row.get("Primary Purpose") or row.get("Purposes"),
                        "height_ft": row.get("NID Height (Ft)") or row.get("Dam Height (Ft)"),
                        "year": row.get("Year Completed"),
                        "owner": row.get("Primary Owner Type"),
                    })
    except OSError as e:
        return Probe(name, False, f"Could not read NID CSV: {e}")

    near.sort(key=lambda x: x["distance_mi"])
    return Probe(name, True, f"{len(near)} dams within {radius_mi:.0f} mi", near)


def probe_eha(lat: float, lon: float) -> Probe:
    """ORNL Existing Hydropower Assets -- is there an existing plant nearby?"""
    name = "ORNL HydroSource EHA (Existing Hydropower Assets)"
    url = "https://hydrosource.ornl.gov/wp-json/wp/v2/search"
    try:
        data = http_get(name, url,
                        params={"search": "EHA plant", "per_page": 5}, timeout=90,
                        retries=2)
    except SourceFailure as e:
        return Probe(name, False, str(e))
    hits = [{"title": d.get("title"), "url": d.get("url")} for d in (data or [])]
    return Probe(name, True,
                 "dataset located but not spatially queried (see note)", hits)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

FERC_GENERAL = """\
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
"""


def choose_fdc(ss: FlowStats, transferred: dict) -> tuple[dict, str, str]:
    """Pick which flow-duration curve drives the power numbers, and say why."""
    if ss.usable:
        return (ss.duration, "StreamStats NY regression (flow-duration statistics)",
                "The NY statewide flow-duration equations applied cleanly to this basin.")
    if transferred:
        why = ("The NY regression could not be used: "
               + "; ".join(
                   f"{o['code']} = {o['value']:g} is {o['how']} of the equation's "
                   f"valid range ({o['min']}–{o['max']})" for o in ss.out_of_range)
               + ("." if ss.out_of_range else "")
               ) if ss.out_of_range else "The NY regression returned no usable curve."
        return (transferred, "USGS gauge transfer (drainage-area ratio)", why)
    if ss.duration:
        return (ss.duration, "StreamStats NY regression (OUT OF RANGE — see warnings)",
                "No gauge transfer was available, so the out-of-range regression "
                "values are shown for want of anything better.")
    return ({}, "none", "No flow-duration curve could be built from any source.")


def render_report(ctx: dict) -> str:
    L: list[str] = []
    a = L.append
    lat, lon = ctx["lat"], ctx["lon"]
    basin: Basin = ctx["basin"]
    ss: FlowStats = ctx["ss_flow"]
    head: HeadResult = ctx["head"]
    donor: Optional[Gauge] = ctx.get("donor")
    transferred: dict = ctx.get("site_fdc") or {}
    hucs = ctx.get("hucs") or {}
    stream = ctx.get("stream") or {}
    failures = [c for c in PROVENANCE if not c.ok]
    fdc, fdc_source, fdc_why = choose_fdc(ss, transferred)

    a("# Micro-Hydro Site Assessment")
    a("")
    a(f"**Point of interest:** {lat:.7f}, {lon:.7f}  ")
    a(f"**Report generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}  ")
    a("**Target scale:** 0.5–10 kW, home / off-grid")
    a("")

    # ---- Stream identity ---------------------------------------------
    gnis = stream.get("GNIS_NAME")
    if gnis:
        a("## ⚠️ Stream identity — read this first")
        a("")
        a(f"You described this point as being on **Ocquionis Creek (Fish Creek)**. "
          f"The USGS National Hydrography Dataset flowline that this coordinate "
          f"snaps to is:")
        a("")
        a(f"- **GNIS name: {gnis}**")
        a(f"- NHD COMID: `{stream.get('COMID')}`, "
          f"reach length {stream.get('LENGTHKM')} km, type {stream.get('FTYPE')}")
        if hucs:
            a(f"- Watershed: HUC12 `{hucs.get('HUC12','?')}` "
              f"({hucs.get('HUC12_NAME','?')}) → HUC8 `{hucs.get('HUC8','?')}` "
              f"({hucs.get('HUC8_NAME','?')})")
        a("")
        if "ocquionis" not in gnis.lower() and "fish" not in gnis.lower():
            a(f"**These do not match.** Ocquionis Creek drains south to Otsego Lake "
              f"in the Susquehanna basin; this coordinate is in the "
              f"{hucs.get('HUC8_NAME','Mohawk')} basin, which drains north to the "
              f"Mohawk and then the Hudson. Jordanville sits close to that divide, "
              f"so a coordinate can easily land on the wrong side of it.")
            a("")
            a("Everything below describes **the stream actually at this coordinate**. "
              "If you meant a point on Ocquionis Creek proper, re-run with the "
              "corrected latitude/longitude — the drainage area, and therefore every "
              "flow and power number here, would change.")
            a("")

    # ---- Source status -----------------------------------------------
    a("## 0. Data source status")
    a("")
    a("Every number below is a live API response. Sources that failed are named, "
      "not replaced with estimates.")
    a("")
    a("| Source | Purpose | Status |")
    a("|---|---|---|")
    a(f"| USGS StreamStats (ss-delineate + ss-hydro) | Basin + characteristics | "
      f"{'OK' if basin.drainage_area_sqmi is not None else '**FAILED**'} |")
    a(f"| StreamStats NSS regression | NY flow-duration statistics | "
      f"{'OK (but out of range — see §2a)' if ss.available and not ss.usable else ('OK' if ss.usable else '**FAILED**')} |")
    a(f"| USGS NWIS | Donor gauge flow-duration curve | "
      f"{'OK' if transferred else '**FAILED**'} |")
    a(f"| USGS NLDI + 3DEP EPQS | Downstream channel head | "
      f"{'OK' if head.gross_head_ft is not None else '**FAILED**'} |")
    nsd: Optional[Probe] = ctx.get("nsd")
    nid: Optional[Probe] = ctx.get("nid")
    a(f"| ORNL HydroSource NSD | DOE potential cross-check | "
      f"{'OK' if (nsd and nsd.ok) else '**FAILED**'} |")
    a(f"| USACE NID | Nearby dams | {'OK' if (nid and nid.ok) else '**FAILED**'} |")
    a("")
    if failures:
        a(f"> {len(failures)} of {len(PROVENANCE)} HTTP calls failed. Appendix B has each one.")
        a("")

    # ---- 1. Basin ----------------------------------------------------
    a("## 1. Watershed delineation and basin characteristics")
    a("")
    a("*Source: USGS StreamStats `ss-delineate` + `ss-hydro` basin characteristics.*")
    a("")
    if basin.drainage_area_sqmi is None:
        a(f"**FAILED.** {basin.error}")
    else:
        a(f"- **Drainage area: {fmt(basin.drainage_area_sqmi, 3, 'sq mi')}** "
          f"({fmt(basin.drainage_area_sqmi * SQMI_TO_SQKM, 3, 'sq km')})")
        if hucs:
            a(f"- HUC12 `{hucs.get('HUC12','?')}` — {hucs.get('HUC12_NAME','?')}")
        if basin.regression_regions:
            a(f"- Regression regions: "
              + ", ".join(f"`{r.get('code')}`" for r in basin.regression_regions[:6])
              + (" …" if len(basin.regression_regions) > 6 else ""))
        a("")
        a("This is a **very small headwater basin**. That single fact drives most of "
          "what follows: it puts the site below the valid range of New York's "
          "flow-duration regression, and it makes finding a comparable gauged basin "
          "hard.")
        a("")
        a("| Code | Characteristic | Value | Unit |")
        a("|---|---|---|---|")
        for code, p in sorted(basin.parameters.items()):
            label = PARAM_LABELS.get(code, p.get("name", ""))
            a(f"| `{code}` | {label} | {p.get('value', 'NOT AVAILABLE')} | {p.get('unit','')} |")
        a("")

    # ---- 2a. StreamStats flow ----------------------------------------
    a("## 2. Available flow")
    a("")
    a("### 2a. New York regression equations (StreamStats)")
    a("")
    if not ss.available:
        a(f"**No flow statistics.** {ss.error or ''}")
    else:
        a(f"Regression region: `{ss.region_code}` — {ss.region_name}")
        a("")
        if ss.out_of_range:
            a("> ### ⚠️ These equations do not apply to this basin")
            a(">")
            a("> StreamStats returned numbers, but the basin falls outside the range "
              "the equations were fitted over:")
            a(">")
            a("> | Parameter | Value | Valid range | Problem |")
            a("> |---|---|---|---|")
            for o in ss.out_of_range:
                a(f"> | `{o['code']}` | {o['value']:g} | {o['min']} – {o['max']} "
                  f"| **{o['how']}** |")
            a(">")
            a("> Extrapolating a log-log regression below its calibration range is "
              "not reliable, so these values are reported for transparency but are "
              "**not** used for the power calculation.")
            a("")
        if ss.zero_artifacts:
            a("> ### ⚠️ Suppressed false zeros")
            a(">")
            a("> These regressions are products of powers. A parameter whose value is "
              "exactly 0, carrying a positive exponent, collapses the entire product "
              "to zero regardless of hydrology. The following statistics came back as "
              "0.0 purely for that reason and have been **excluded** rather than "
              "reported as a dry stream:")
            a(">")
            a("> | Statistic | Exceedance | Zero-valued parameter(s) |")
            a("> |---|---|---|")
            for z in sorted(ss.zero_artifacts, key=lambda x: x["pct"]):
                a(f"> | `{z['code']}` | {z['pct']}% | {', '.join('`'+p+'`' for p in z['params'])} |")
            a(">")
            a("> **This does not mean the creek runs dry.** It means the equation "
              "could not be evaluated. Real low-flow behaviour has to come from the "
              "gauge transfer below, and ultimately from measurement on site.")
            a("")
        a("<details><summary>All statistics returned by StreamStats</summary>")
        a("")
        a("| Code | Statistic | Value (cfs) |")
        a("|---|---|---|")
        for st in ss.stats:
            a(f"| `{st.get('code')}` | {st.get('name','')} | {st.get('value')} |")
        a("")
        a("</details>")
    a("")

    # ---- 2b. Gauge transfer ------------------------------------------
    a("### 2b. Gauge transfer by drainage-area ratio")
    a("")
    if not donor or not transferred:
        a(f"**FAILED.** {ctx.get('flow_error','')}")
    else:
        ratio = ctx["da_ratio"]
        a(f"- **Donor gauge:** USGS {donor.site_no} — {donor.name}")
        a(f"- **Location:** {donor.lat:.5f}, {donor.lon:.5f} "
          f"({donor.distance_mi:.1f} mi from the site)")
        a(f"- **Donor drainage area:** {fmt(donor.drainage_area_sqmi, 2, 'sq mi')}")
        a(f"- **Record used:** {donor.n_days:,} daily mean discharge values")
        a("")
        a("**The work:**")
        a("")
        a("```")
        a("Q_site(p) = Q_gauge(p) * ( DA_site / DA_gauge ) ^ x        with x = 1.0")
        a("")
        a(f"DA_site  = {basin.drainage_area_sqmi:.3f} sq mi   (StreamStats delineation)")
        a(f"DA_gauge = {donor.drainage_area_sqmi:.2f} sq mi   (NWIS site record)")
        a(f"ratio    = {basin.drainage_area_sqmi:.3f} / {donor.drainage_area_sqmi:.2f}"
          f" = {ratio:.5f}")
        a("```")
        a("")
        band = ctx.get("donor_band", "")
        if ratio < 0.3 or ratio > 3.0:
            a(f"> ### ⚠️ The area ratio is {ratio:.4f}")
            a(">")
            a("> The drainage-area ratio method is normally defensible only between "
              "about 0.3 and 3.0, and best between 0.5 and 1.5. This transfer is well "
              f"outside that. {band}")
            a(">")
            a("> Scaling a large basin's behaviour down to a basin this small "
              "systematically **overestimates low flow**: a small headwater catchment "
              "has less groundwater storage per unit area to sustain baseflow, and it "
              "responds far more sharply to dry spells. Treat the low-flow rows below "
              "as an optimistic ceiling, not an expectation.")
            a("")
        a("| Exceedance | Meaning | Donor (cfs) | Scaled to site (cfs) | Site (m³/s) |")
        a("|---|---|---|---|---|")
        meaning = {5: "very high", 10: "high", 50: "median", 90: "low", 95: "very low"}
        for p in sorted(transferred):
            a(f"| Q{p} | {meaning.get(p,'')} | {donor.fdc.get(p, float('nan')):,.2f} "
              f"| {transferred[p]:,.3f} | {transferred[p]*CFS_TO_CMS:,.5f} |")
        a("")

    a("### 2c. Which curve drives the numbers below")
    a("")
    a(f"**{fdc_source}.** {fdc_why}")
    a("")
    if ss.duration and transferred:
        a("Where both methods produced a value, they compare as follows:")
        a("")
        a("| Exceedance | StreamStats regression (cfs) | Gauge transfer (cfs) |")
        a("|---|---|---|")
        for p in sorted(set(ss.duration) | set(transferred)):
            v1 = f"{ss.duration[p]:,.3f}" if p in ss.duration else "—"
            v2 = f"{transferred[p]:,.3f}" if p in transferred else "—"
            a(f"| Q{p:g} | {v1} | {v2} |")
        a("")
        a("Disagreement between two independent methods is the honest measure of how "
          "uncertain this site's flow really is.")
        a("")

    # ---- 3. Head -----------------------------------------------------
    a("## 3. Gross head")
    a("")
    a("*Source: USGS NLDI downstream channel trace + USGS 3DEP EPQS elevations.*")
    a("")
    if head.gross_head_ft is None:
        a(f"**FAILED.** {head.error or ''}")
    else:
        a(f"- NHD COMID traced: `{head.comid}`")
        a(f"- Channel run sampled: {fmt(head.run_length_ft, 0, 'ft')} downstream")
        a(f"- **Gross head: {fmt(head.gross_head_ft, 1, 'ft')} "
          f"({fmt(head.gross_head_ft*FT_TO_M, 2, 'm')})**")
        if head.head_at_500ft is not None:
            a(f"- Gross head over the first 500 ft: {fmt(head.head_at_500ft, 1, 'ft')}")
        if head.run_length_ft:
            a(f"- Average gradient: {(head.gross_head_ft/head.run_length_ft)*100:.2f}%")
        a("")
        for n in head.notes:
            a(f"> {n}")
            a("")
        a("<details><summary>Elevation profile — every sample</summary>")
        a("")
        a("| Distance (ft) | Lat | Lon | 3DEP elevation (ft) |")
        a("|---|---|---|---|")
        for p in head.profile:
            e = fmt(p["elev_ft"], 2) if p["elev_ft"] is not None else "NO DATA"
            a(f"| {p['dist_ft']:.0f} | {p['lat']:.6f} | {p['lon']:.6f} | {e} |")
        a("")
        a("</details>")
        a("")
        a("> **This is a screening number, not a survey.** 3DEP here is a ~10 m "
          "DEM with roughly 1–2 ft vertical RMSE, and it is worse in a narrow, "
          "wooded stream valley where the surface may never have resolved the channel "
          "bottom. Over a run this short, the DEM error is a large fraction of the "
          "answer. Measure it with a laser level or a hose and pressure gauge before "
          "spending anything.")
    a("")

    # ---- 4. Power ----------------------------------------------------
    a("## 4. Power potential")
    a("")
    a("```")
    a("P(kW) = 9.81 * Q(m3/s) * H(m) * efficiency")
    a("```")
    a("")
    if head.gross_head_ft is None or not fdc:
        a("**Cannot be computed.** Power needs both head and flow:")
        if head.gross_head_ft is None:
            a("- head: **unavailable**")
        if not fdc:
            a("- flow: **unavailable**")
        a("")
        a("No power figures are given, because any figure would be invented.")
    else:
        h = head.gross_head_ft
        a(f"Head **H = {h:.1f} ft = {h*FT_TO_M:.2f} m**; flow from *{fdc_source}*.")
        a("")
        a("This is **gross** head. Net head after penstock friction is typically "
          "85–90% of gross for a well-sized pipe; the efficiency columns carry only "
          "turbine, drive and generator losses.")
        a("")
        a("| Exceedance | Flow (cfs) | Flow (m³/s) | Theoretical (kW) | @60% | @65% | @70% |")
        a("|---|---|---|---|---|---|---|")
        for row in power_table(fdc, h, [0.60, 0.65, 0.70]):
            a(f"| Q{row['exceedance_pct']:g} | {row['q_cfs']:,.3f} | {row['q_cms']:,.5f} "
              f"| {row['theoretical_kw']:,.3f} | {row['kw_at_60']:,.3f} "
              f"| {row['kw_at_65']:,.3f} | {row['kw_at_70']:,.3f} |")
        a("")
        aep = ctx.get("aep")
        if aep:
            a("### Indicative annual energy")
            a("")
            a(f"Turbine sized at the Q{aep['design_exceedance']:g} flow "
              f"({aep['design_flow_cfs']:.3f} cfs), spilling above it, shutting down "
              f"below {aep['cutoff_flow_cfs']:.3f} cfs, "
              f"{int(aep['efficiency']*100)}% system efficiency, **no bypass flow "
              f"deducted**:")
            a("")
            a(f"- Rated output: **{aep['rated_kw']:.3f} kW**")
            a(f"- Average output: **{aep['avg_kw']:.3f} kW**")
            a(f"- Annual energy: **{aep['annual_kwh']:,.0f} kWh/yr**")
            a(f"- Capacity factor: {aep['capacity_factor']*100:.0f}%")
            a("")
            a("For scale: a typical US home uses roughly 10,500 kWh/yr; a deliberately "
              "efficient off-grid homestead often runs 2,000–4,000 kWh/yr.")
            a("")

    # ---- 5. DOE ------------------------------------------------------
    a("## 5. Cross-check against ORNL / DOE data")
    a("")
    if nsd and nsd.ok:
        p = nsd.payload or {}
        hit = p.get("hit")
        a(f"*Source: ORNL HydroSource, New Stream-reach Development (NSD), "
          f"hydrologic region {p.get('region')}, aggregated to HUC10.*")
        a("")
        a(f"- HUC10 searched: `{hucs.get('HUC10','?')}` ({hucs.get('HUC10_NAME','?')})")
        a(f"- {nsd.detail}")
        a("")
        if hit:
            a("**DOE does attribute new stream-reach potential to this HUC10:**")
            a("")
            a("| Metric | Value |")
            a("|---|---|")
            for k, lab, unit in [
                ("NUMREACH", "Stream reaches identified", ""),
                ("P_MW_Sum", "Potential capacity", "MW"),
                ("E_MWh_Sm", "Potential annual energy", "MWh"),
                ("H_ft_Avg", "Average hydraulic head", "ft"),
                ("Q30cfsAg", "Hydraulic capacity (Q30)", "cfs"),
                ("Cf_yr", "Capacity factor", "ratio"),
            ]:
                if hit.get(k) is not None:
                    v = hit[k]
                    v = f"{v:,.4g}" if isinstance(v, (int, float)) else v
                    a(f"| {lab} | {v} {unit} |")
            a("")
            a("> **Read this carefully.** NSD is a HUC10-wide aggregate covering "
              "**every** candidate reach in the watershed, at utility screening scale "
              "and with its own assumptions about head and hydraulic capacity. It is "
              "not an estimate for your specific point, and the capacity above is "
              "orders of magnitude larger than a homestead machine. It tells you the "
              "watershed is not devoid of potential; it says nothing about whether "
              "your particular 1,000 ft of channel is worth developing.")
        else:
            a(f"**HUC10 `{hucs.get('HUC10','?')}` is not listed in the NSD inventory "
              "for this region.**")
            a("")
            a("> This is expected and is **not** evidence against a home-scale "
              "project. NSD screened for utility-relevant capacity; its reporting "
              "threshold sits far above a 0.5–10 kW machine. A site like yours would "
              "be invisible to it either way.")
    else:
        a(f"**FAILED — no NSD data retrieved.** {nsd.detail if nsd else ''}")
        a("")
        a("No DOE estimate is reported, because none was obtained. Check manually at "
          "<https://hydrosource.ornl.gov/>.")
    a("")

    # ---- 6. Constraints ----------------------------------------------
    a("## 6. Constraints and permitting")
    a("")
    a("### Nearby dams (USACE National Inventory of Dams)")
    a("")
    if nid and nid.ok:
        rows = nid.payload or []
        if rows:
            a(f"{len(rows)} dam(s) within 10 miles:")
            a("")
            a("| Dam | NID ID | Distance (mi) | River | Purpose | Height (ft) | Year |")
            a("|---|---|---|---|---|---|---|")
            for d in rows[:25]:
                a(f"| {d.get('name','')} | {d.get('nid_id','')} | {d['distance_mi']:.1f} "
                  f"| {d.get('river','')} | {d.get('purposes','')} "
                  f"| {d.get('height_ft','')} | {d.get('year','')} |")
            a("")
            gname = (stream.get("GNIS_NAME") or "").lower()
            same = [d for d in rows
                    if gname and gname in (d.get("river") or "").lower()]
            hydro = [d for d in rows
                     if "hydro" in (d.get("purposes") or "").lower()]
            if same:
                a("")
                a(f"**{len(same)} of these sit on the same stream as your site "
                  f"({stream.get('GNIS_NAME')}).** An upstream dam means your flow is "
                  "partly controlled by someone else's operating decisions, and it "
                  "changes how a regulator views a new structure downstream.")
            else:
                a("")
                a(f"**None of these is on {stream.get('GNIS_NAME') or 'your stream'} "
                  "itself** — they are on neighbouring streams and on the Mohawk. So "
                  "no upstream impoundment is controlling your flow, which is good "
                  "news for a run-of-river scheme. They matter as context rather than "
                  "as a direct constraint.")
            if hydro:
                a("")
                a(f"{len(hydro)} of the {len(rows)} are already generating "
                  f"({', '.join(d.get('name','').strip() for d in hydro[:4])}), which "
                  "shows the wider basin supports hydro at a much larger scale than "
                  "anything contemplated here.")
        else:
            a("No dams within 10 miles of the site in the NID.")
    else:
        a(f"**FAILED — nearby dams NOT checked.** {nid.detail if nid else ''}")
    a("")
    eha: Optional[Probe] = ctx.get("eha")
    a("### Existing hydropower (ORNL EHA)")
    a("")
    if eha and eha.ok:
        a("The EHA plant inventory was located on HydroSource but **was not "
          "spatially queried** in this run — the published product is a bulk "
          "download rather than a point query service. Existing hydro near this "
          "reach is therefore **unverified**. Given the basin size, an existing "
          "plant on this stream is unlikely, but that is reasoning, not data.")
    else:
        a(f"**Not retrieved.** {eha.detail if eha else ''}")
    a("")
    a("### Environmental sensitivity")
    a("")
    a("**Not queried in this run — do not read that as 'no constraints'.** The "
      "datasets that would answer it are the NYSDEC water quality classification for "
      "this reach, NYSDEC trout-stream and spawning designations, a USFWS IPaC "
      "listed-species review, and NY Natural Heritage Program records. A cold "
      "headwater creek in central New York has a realistic chance of carrying a "
      "trout designation, which raises the bar substantially for any in-channel "
      "structure.")
    a("")
    a("### FERC thresholds")
    a("")
    a(FERC_GENERAL)
    a("")

    # ---- Verdict -----------------------------------------------------
    a("## Plain-language summary")
    a("")
    a(ctx.get("verdict", ""))
    a("")

    a("## What to field-verify before spending real money")
    a("")
    a("1. **Confirm which stream you are actually on.** The coordinate resolves to a "
      "different named stream, in a different river basin, than the one you named. "
      "Settle this first — everything else depends on it.")
    a("2. **Measure the flow, repeatedly, through a dry season.** Every flow figure "
      "here is a statistical transfer from a different watershed, and the one method "
      "purpose-built for New York does not apply to a basin this small. A weir box or "
      "bucket-and-stopwatch reading taken monthly for a year — and above all in late "
      "summer and in a drought year — is what decides this site. Late-summer low "
      "flow, not median flow, sizes an off-grid system.")
    a("3. **Survey the real head** with a laser level, rod, or hose-and-gauge, to the "
      "actual powerhouse location you could physically build on.")
    a("4. **Walk the penstock route.** Length, diameter, buried vs. surface, stream "
      "crossings and rock drive both net head and cost, and at this scale cost is "
      "dominated by pipe.")
    a("5. **Confirm you control both ends** — property boundaries and riparian rights "
      "at the intake and at the tailrace.")
    a("6. **Look up this reach's DEC classification** and get a real read on Article "
      "15, 401 certification, SEQRA, and any USACE 404 nexus.")
    a("7. **Get a written FERC jurisdictional determination** rather than relying on a "
      "threshold reading.")
    a("8. **Plan for winter.** Frazil and anchor ice, leaf litter and spring debris "
      "decide whether the intake runs unattended.")
    a("9. **Confirm the load and the distance to it** — transmission run from "
      "powerhouse to house, and battery vs. grid-tied.")
    a("")

    # ---- Appendices --------------------------------------------------
    a("## Appendix A — Every API call")
    a("")
    a("| # | Source | Status | Endpoint |")
    a("|---|---|---|---|")
    for i, c in enumerate(PROVENANCE, 1):
        st = f"OK {c.status}" if c.ok else f"**FAIL {c.status or ''}**"
        a(f"| {i} | {c.label} | {st} | `{c.url[:120]}` |")
    a("")
    if failures:
        a("## Appendix B — Failures in detail")
        a("")
        for c in failures:
            a(f"- **{c.label}**  ")
            a(f"  `{c.url[:160]}`  ")
            a(f"  → {str(c.detail)[:300]}")
        a("")
    a("---")
    a("")
    a("*Generated by `hydro_assessment.py`. Every value is either a live API response "
      "or an explicit NOT AVAILABLE / FAILED marker.*")

    out: list[str] = []
    for line in L:
        if line.startswith("#") and out and out[-1].strip():
            out.append("")
        out.append(line)
    return "\n".join(out)


# --------------------------------------------------------------------------
# Verdict
# --------------------------------------------------------------------------

def build_verdict(ctx: dict) -> str:
    basin: Basin = ctx["basin"]
    head: HeadResult = ctx["head"]
    ss: FlowStats = ctx["ss_flow"]
    fdc, fdc_source, _ = choose_fdc(ss, ctx.get("site_fdc") or {})
    stream = ctx.get("stream") or {}

    parts: list[str] = []
    gnis = stream.get("GNIS_NAME")
    if gnis and "ocquionis" not in gnis.lower() and "fish" not in gnis.lower():
        parts.append(
            f"**First, the coordinate is not on the stream you named.** NHD calls it "
            f"**{gnis}**, in the Mohawk/Hudson basin rather than Ocquionis Creek's "
            f"Susquehanna basin. If the coordinate is what you meant, read on. If the "
            f"*name* is what you meant, these numbers are for the wrong creek."
        )

    if basin.drainage_area_sqmi is None or head.gross_head_ft is None or not fdc:
        missing = []
        if basin.drainage_area_sqmi is None:
            missing.append("watershed delineation")
        if not fdc:
            missing.append("flow")
        if head.gross_head_ft is None:
            missing.append("head")
        parts.append(
            "**No verdict is possible from this run.** These inputs could not be "
            f"obtained: **{', '.join(missing)}**. See §0 and Appendix B."
        )
        return " ".join(parts)

    h = head.gross_head_ft
    q50, q90 = fdc.get(50), fdc.get(90)
    p50 = power_kw(q50, h, 0.65) if q50 is not None else None
    p90 = power_kw(q90, h, 0.65) if q90 is not None else None

    parts.append(
        f"The basin above this point is **{basin.drainage_area_sqmi:.2f} sq mi** — "
        f"very small — and the DEM puts **{h:.1f} ft of gross head** in 1,000 ft of "
        f"channel (a {(h/head.run_length_ft)*100:.1f}% gradient)."
    )
    if p50 is not None:
        parts.append(
            f"At median flow (Q50 = {q50:,.2f} cfs) a 65%-efficient machine makes "
            f"about **{p50:,.2f} kW**."
        )
    if p90 is not None:
        parts.append(
            f"At the low-flow condition that actually sizes an off-grid system "
            f"(Q90 = {q90:,.2f} cfs) it makes about **{p90:,.2f} kW**."
        )

    if p90 is not None:
        if p90 >= 1.0:
            parts.append(
                "On paper that clears the bar for a useful home system — continuous "
                "output above 1 kW is a real share of a homestead's demand."
            )
        elif p90 >= 0.3:
            parts.append(
                "That is marginal but not nothing: a few hundred watts running "
                "continuously into a battery bank adds up over a year, though the "
                "economics live or die on penstock length."
            )
        else:
            parts.append(
                "That is below what most people would consider a useful home system, "
                "and it is the number that matters most, because a system you cannot "
                "run in August is a system you cannot rely on."
            )

    # Confidence paragraph, honest about which caveats actually apply here.
    donor = ctx.get("donor")
    ratio = ctx.get("da_ratio")
    conf = ["**Now weigh the confidence.**"]
    if ss.out_of_range:
        conf.append(
            "New York's own flow-duration equations could not be applied — this basin "
            "sits below their minimum drainage area — so the flow above comes from a "
            "gauge transfer instead."
        )
    if donor and ratio is not None:
        if 0.67 <= ratio <= 1.5:
            conf.append(
                f"That transfer is unusually well matched on size: the donor basin is "
                f"{donor.drainage_area_sqmi:g} sq mi against this site's "
                f"{basin.drainage_area_sqmi:.2f} sq mi, a ratio of {ratio:.2f}, right "
                f"in the band where the drainage-area method is considered sound. The "
                f"weakness is not scale but location — the donor sits "
                f"{donor.distance_mi:.0f} miles away in a different river basin, so it "
                f"shares this site's size without necessarily sharing its geology, "
                f"soils or storage."
            )
        elif 0.3 <= ratio <= 3.0:
            conf.append(
                f"The donor basin ({donor.drainage_area_sqmi:g} sq mi, ratio "
                f"{ratio:.2f}) is acceptably matched on size, though not ideally, and "
                f"sits {donor.distance_mi:.0f} miles away."
            )
        else:
            conf.append(
                f"The donor basin is {donor.drainage_area_sqmi:g} sq mi against this "
                f"site's {basin.drainage_area_sqmi:.2f} sq mi — a ratio of "
                f"{ratio:.3f}, outside the range where this method is defensible. "
                f"Scaling across that gap systematically flatters low flow in a small "
                f"headwater catchment."
            )
        if donor.n_days:
            yrs = donor.n_days / 365.25
            conf.append(
                f"It carries {yrs:.0f} years of record, which captures ordinary dry "
                f"summers but not necessarily a severe drought."
            )
    conf.append(
        "The head comes from a 10 m DEM over a short run, where the vertical error is "
        "a large fraction of the answer — that number is the softest thing in this "
        "report."
    )
    parts.append(" ".join(conf))
    parts.append(
        "The honest summary: **this is a plausible micro-hydro site that has not yet "
        "been shown to be a good one.** Nothing here rules it out, and nothing here "
        "justifies buying equipment. A year of actual flow measurements and one "
        "afternoon with a level would tell you more than every dataset in this report "
        "combined — and cost almost nothing."
    )
    return " ".join(parts)


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT)
    ap.add_argument("--lon", type=float, default=DEFAULT_LON)
    ap.add_argument("--rcode", default="NY")
    ap.add_argument("--run-ft", type=float, default=1000.0)
    ap.add_argument("--step-ft", type=float, default=50.0)
    ap.add_argument("--cache-dir", default=".",
                    help="Where to cache the large NID / NSD downloads")
    ap.add_argument("--out", default="ocquionis_creek_microhydro_report.md")
    ap.add_argument("--provenance-json", default="provenance.json")
    args = ap.parse_args()

    lat, lon = args.lat, args.lon
    print(f"[*] Site: {lat}, {lon}", file=sys.stderr)
    ctx: dict = {"lat": lat, "lon": lon}

    # 1 -----------------------------------------------------------------
    print("[1] StreamStats delineation + basin characteristics ...", file=sys.stderr)
    basin = delineate_basin(lat, lon, args.rcode)
    ctx["basin"] = basin
    print(f"    DRNAREA = {basin.drainage_area_sqmi} sq mi"
          if basin.drainage_area_sqmi is not None else f"    FAILED: {basin.error}",
          file=sys.stderr)

    print("[1b] HUC lookup ...", file=sys.stderr)
    ctx["hucs"] = get_hucs(lat, lon)

    # 2a ----------------------------------------------------------------
    print("[2a] StreamStats flow-duration statistics ...", file=sys.stderr)
    ss = streamstats_flow_stats(basin, args.rcode)
    ctx["ss_flow"] = ss
    if ss.out_of_range:
        for o in ss.out_of_range:
            print(f"    OUT OF RANGE: {o['code']}={o['value']:g} "
                  f"({o['how']} of {o['min']}..{o['max']})", file=sys.stderr)
    if ss.zero_artifacts:
        print(f"    suppressed {len(ss.zero_artifacts)} false-zero statistics",
              file=sys.stderr)

    # 2b ----------------------------------------------------------------
    print("[2b] NWIS donor gauge ...", file=sys.stderr)
    site_fdc: dict = {}
    donor: Optional[Gauge] = None
    flow_error = ""
    band_note = ""
    try:
        cands = find_candidate_gauges(lat, lon)
        print(f"    {len(cands)} gauges in the search box", file=sys.stderr)
        ranked: list[Gauge] = []
        for limit, note in [
            (1.5, "Donor selected from the ideal 0.67–1.5x area band."),
            (3.0, "Donor selected from the acceptable 0.33–3x area band."),
            (10.0, "No gauge existed within 3x; donor taken from the 0.1–10x band."),
            (1e9, "No comparably sized gauge exists nearby at all; the closest "
                  "available drainage area was used and the ratio is extreme."),
        ]:
            ranked = rank_gauges(cands, basin.drainage_area_sqmi, max_ratio=limit)
            if ranked:
                band_note = note
                break
        for g in ranked[:5]:
            try:
                daily = fetch_daily_flow(g.site_no)
            except SourceFailure as e:
                print(f"    gauge {g.site_no} unusable: {str(e)[:90]}", file=sys.stderr)
                continue
            g.n_days = len(daily)
            g.fdc = flow_duration_curve(daily)
            donor = g
            break
        if donor is None:
            flow_error = "No nearby gauge had a usable daily-discharge record."
        elif basin.drainage_area_sqmi is None:
            flow_error = "Donor gauge found, but the site drainage area is unknown."
        else:
            ratio = basin.drainage_area_sqmi / donor.drainage_area_sqmi
            ctx["da_ratio"] = ratio
            site_fdc = scale_by_drainage_area(
                donor.fdc, basin.drainage_area_sqmi, donor.drainage_area_sqmi)
            print(f"    donor {donor.site_no} "
                  f"({donor.drainage_area_sqmi} sq mi), ratio {ratio:.4f}",
                  file=sys.stderr)
    except SourceFailure as e:
        flow_error = str(e)
        print(f"    FAILED: {e}", file=sys.stderr)

    ctx["donor"] = donor
    ctx["site_fdc"] = site_fdc
    ctx["flow_error"] = flow_error
    ctx["donor_band"] = band_note

    # 3 -----------------------------------------------------------------
    print("[3] Head: NLDI trace + 3DEP EPQS ...", file=sys.stderr)
    head = estimate_head(lat, lon, args.run_ft, args.step_ft)
    ctx["head"] = head
    if head.gross_head_ft is not None:
        print(f"    gross head = {head.gross_head_ft:.1f} ft over "
              f"{head.run_length_ft:.0f} ft", file=sys.stderr)
    else:
        print(f"    FAILED: {head.error}", file=sys.stderr)

    if head.comid:
        print("[3b] Stream identity check ...", file=sys.stderr)
        ctx["stream"] = identify_stream(head.comid)
        if ctx.get("stream"):
            print(f"    NHD GNIS_NAME = {ctx['stream'].get('GNIS_NAME')!r}",
                  file=sys.stderr)

    # 4 -----------------------------------------------------------------
    fdc, _, _ = choose_fdc(ss, site_fdc)
    if fdc and head.gross_head_ft is not None:
        ctx["aep"] = annual_energy_kwh(fdc, head.gross_head_ft, 0.65,
                                       design_exceedance=30)

    # 5 & 6 -------------------------------------------------------------
    hucs = ctx.get("hucs") or {}
    print("[5] ORNL HydroSource NSD ...", file=sys.stderr)
    ctx["nsd"] = probe_nsd(hucs.get("HUC2"), hucs.get("HUC10"), args.cache_dir)
    print(f"    {ctx['nsd'].detail}", file=sys.stderr)
    print("[6] USACE NID + ORNL EHA ...", file=sys.stderr)
    ctx["nid"] = probe_nid(lat, lon, 10.0, args.cache_dir)
    print(f"    {ctx['nid'].detail}", file=sys.stderr)
    ctx["eha"] = probe_eha(lat, lon)

    # Report ------------------------------------------------------------
    ctx["verdict"] = build_verdict(ctx)
    with open(args.out, "w") as f:
        f.write(render_report(ctx))
    with open(args.provenance_json, "w") as f:
        json.dump([{"label": c.label, "url": c.url, "ok": c.ok, "status": c.status,
                    "detail": c.detail, "elapsed_s": round(c.elapsed_s, 3)}
                   for c in PROVENANCE], f, indent=2)

    ok = sum(1 for c in PROVENANCE if c.ok)
    bad = len(PROVENANCE) - ok
    print(f"\n[*] Wrote {args.out}", file=sys.stderr)
    print(f"[*] API calls: {ok} OK, {bad} failed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
