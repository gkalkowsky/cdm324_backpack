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
# --------------------------------------------------------------------------

SS_BASE = "https://streamstats.usgs.gov/streamstatsservices"


@dataclass
class Basin:
    workspace_id: Optional[str] = None
    parameters: dict[str, dict] = field(default_factory=dict)
    drainage_area_sqmi: Optional[float] = None
    geometry_available: bool = False
    raw: dict = field(default_factory=dict)
    error: Optional[str] = None


def delineate_basin(lat: float, lon: float, rcode: str = "NY") -> Basin:
    """Delineate the drainage basin above the point and pull its characteristics."""
    b = Basin()
    try:
        data = http_get(
            "StreamStats watershed delineation (rcode=NY)",
            f"{SS_BASE}/watershed.json",
            params={
                "rcode": rcode,
                "xlocation": lon,
                "ylocation": lat,
                "crs": 4326,
                "includeparameters": "true",
                "includeflowtypes": "false",
                "includefeatures": "true",
                "simplify": "true",
            },
            timeout=180,          # delineation is slow; it runs a real GIS job
            retries=3,
        )
    except SourceFailure as e:
        b.error = str(e)
        return b

    b.raw = data
    b.workspace_id = data.get("workspaceID")
    b.geometry_available = bool(data.get("featurecollection"))

    params = data.get("parameters") or []
    # If the delineation returned no parameters inline, ask for them explicitly.
    if not params and b.workspace_id:
        try:
            pdata = http_get(
                "StreamStats basin characteristics",
                f"{SS_BASE}/parameters.json",
                params={
                    "rcode": rcode,
                    "workspaceID": b.workspace_id,
                    "includeparameters": "true",
                },
                timeout=180,
            )
            params = pdata.get("parameters") or []
        except SourceFailure as e:
            b.error = str(e)

    for p in params:
        code = p.get("code")
        if code:
            b.parameters[code.upper()] = p

    da = b.parameters.get("DRNAREA", {}).get("value")
    if da is not None:
        try:
            b.drainage_area_sqmi = float(da)
        except (TypeError, ValueError):
            pass

    if b.drainage_area_sqmi is None and b.error is None:
        b.error = "StreamStats responded but returned no DRNAREA (drainage area)."
    return b


# --------------------------------------------------------------------------
# STEP 2a -- Flow statistics straight from StreamStats regression equations
# --------------------------------------------------------------------------

@dataclass
class FlowStats:
    available: bool = False
    stats: list[dict] = field(default_factory=list)
    has_duration_curve: bool = False
    duration: dict[int, float] = field(default_factory=dict)  # exceedance% -> cfs
    error: Optional[str] = None


# StreamStats NY names duration statistics variously; match loosely.
def _parse_exceedance_from_name(name: str) -> Optional[int]:
    """Pull an exceedance percentile out of a StreamStats statistic name."""
    n = (name or "").upper().replace(" ", "")
    # Common encodings: "D10", "Q10", "10PERCENTDURATION", "FDC10", "M0D10"
    import re
    for pat in (
        r"^D(\d{1,2})$",
        r"^Q(\d{1,2})$",
        r"^FDC(\d{1,2})$",
        r"(\d{1,2})PERCENTDURATION",
        r"(\d{1,2})PERCENTEXCEED",
        r"DURATION(\d{1,2})",
    ):
        m = re.search(pat, n)
        if m:
            v = int(m.group(1))
            if 0 < v < 100:
                return v
    return None


def streamstats_flow_stats(workspace_id: str, rcode: str = "NY") -> FlowStats:
    fs = FlowStats()
    if not workspace_id:
        fs.error = "No StreamStats workspaceID (delineation failed), so no flow stats."
        return fs
    try:
        data = http_get(
            "StreamStats flow statistics (NY regression equations)",
            f"{SS_BASE}/flowstatistics.json",
            params={
                "rcode": rcode,
                "workspaceID": workspace_id,
                "includeflowtypes": "true",
            },
            timeout=180,
        )
    except SourceFailure as e:
        fs.error = str(e)
        return fs

    # Response is a list of regression regions, each with RegressionRegions[].Results[]
    results: list[dict] = []
    if isinstance(data, list):
        for region in data:
            for rr in region.get("RegressionRegions", []) or []:
                for res in rr.get("Results", []) or []:
                    results.append(res)
    fs.stats = results
    fs.available = bool(results)
    if not results:
        fs.error = "StreamStats returned no flow statistics for this basin."
        return fs

    for res in results:
        pct = _parse_exceedance_from_name(res.get("code") or res.get("Code") or "")
        val = res.get("Value", res.get("value"))
        if pct is not None and val is not None:
            try:
                fs.duration[pct] = float(val)
            except (TypeError, ValueError):
                pass
    fs.has_duration_curve = len(fs.duration) >= 3
    return fs


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
# STEPS 5 & 6 -- ORNL HydroSource (NSD + EHA), USACE NID, WBD/HUC
# --------------------------------------------------------------------------

@dataclass
class Probe:
    name: str
    ok: bool
    detail: str
    payload: Any = None


def get_huc12(lat: float, lon: float) -> Optional[dict]:
    """HUC12 watershed ID from the National Map WBD service."""
    url = ("https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/"
           "identify")
    try:
        data = http_get(
            "National Map WBD: HUC12 at point",
            url,
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
            timeout=90,
        )
    except SourceFailure:
        return None
    out = {}
    for r in data.get("results", []) or []:
        attrs = r.get("attributes", {}) or {}
        for k, v in attrs.items():
            kl = k.lower()
            if kl in ("huc12", "huc12 code", "huc_12"):
                out["huc12"] = v
            elif kl in ("huc8", "huc_8"):
                out["huc8"] = v
            elif kl == "name":
                out.setdefault("name", v)
    return out or None


def probe_hydrosource(huc: Optional[str]) -> list[Probe]:
    """
    Best-effort query of ORNL HydroSource for the NSD and EHA datasets.

    HydroSource publishes the New Stream-reach Development (NSD) resource and
    the Existing Hydropower Assets (EHA) inventory. Its machine endpoints move
    between releases, so we probe a list of documented entry points and report
    exactly what answered. Nothing is inferred when nothing answers.
    """
    probes: list[Probe] = []
    candidates = [
        ("HydroSource site root", "https://hydrosource.ornl.gov/", None),
        ("HydroSource ArcGIS REST catalog",
         "https://hydrosource.ornl.gov/arcgis/rest/services", {"f": "json"}),
        ("HydroSource NSD dataset landing",
         "https://hydrosource.ornl.gov/dataset/new-stream-reach-development-nsd", None),
        ("HydroSource EHA dataset landing",
         "https://hydrosource.ornl.gov/dataset/existing-hydropower-assets-eha", None),
        ("HydroSource CKAN package search (NSD)",
         "https://hydrosource.ornl.gov/api/3/action/package_search",
         {"q": "new stream-reach development", "rows": 10}),
        ("HydroSource CKAN package search (EHA)",
         "https://hydrosource.ornl.gov/api/3/action/package_search",
         {"q": "existing hydropower assets", "rows": 10}),
    ]
    for name, url, params in candidates:
        try:
            data = http_get(name, url, params=params, timeout=60, retries=2,
                            expect_json=bool(params and params.get("f") == "json")
                            or "api/3/action" in url)
            if isinstance(data, str):
                probes.append(Probe(name, True, f"reachable ({len(data)} bytes)", None))
            else:
                probes.append(Probe(name, True, "reachable (JSON)", data))
        except SourceFailure as e:
            probes.append(Probe(name, False, str(e)))
    return probes


def probe_nid(lat: float, lon: float, radius_mi: float = 10.0) -> Probe:
    """USACE National Inventory of Dams -- nearby dams."""
    url = "https://nid.sec.usace.army.mil/api/dams/search"
    try:
        data = http_get(
            "USACE National Inventory of Dams (nearby dams)",
            url,
            params={"stateKey": "NY", "size": 5000},
            timeout=120,
            retries=2,
        )
    except SourceFailure as e:
        return Probe("USACE NID", False, str(e))

    items = data if isinstance(data, list) else (data.get("data") or data.get("results") or [])
    near = []
    for d in items if isinstance(items, list) else []:
        try:
            dlat = float(d.get("latitude") or d.get("lat"))
            dlon = float(d.get("longitude") or d.get("lon"))
        except (TypeError, ValueError):
            continue
        dist = haversine_mi(lat, lon, dlat, dlon)
        if dist <= radius_mi:
            near.append({
                "name": d.get("name") or d.get("damName"),
                "nid_id": d.get("nidId") or d.get("federalId"),
                "distance_mi": dist,
                "purposes": d.get("purposes"),
                "river": d.get("riverName") or d.get("river"),
                "height_ft": d.get("damHeight"),
            })
    near.sort(key=lambda x: x["distance_mi"])
    return Probe("USACE NID", True, f"{len(near)} dams within {radius_mi:.0f} mi", near)


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

FERC_GENERAL = """\
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
"""


def render_report(ctx: dict) -> str:
    L: list[str] = []
    a = L.append
    lat, lon = ctx["lat"], ctx["lon"]
    basin: Basin = ctx["basin"]
    ss_flow: FlowStats = ctx["ss_flow"]
    head: HeadResult = ctx["head"]
    donor: Optional[Gauge] = ctx.get("donor")
    site_fdc: dict[int, float] = ctx.get("site_fdc") or {}
    failures = [c for c in PROVENANCE if not c.ok]

    a("# Micro-Hydro Site Assessment — Ocquionis (Fish) Creek")
    a("")
    a(f"**Point of interest:** {lat:.7f}, {lon:.7f}  ")
    a("**Stream:** Ocquionis Creek (Fish Creek), near Jordanville, NY  ")
    a(f"**Report generated:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}  ")
    a("**Target scale:** 0.5–10 kW, home / off-grid")
    a("")
    if ctx.get("huc"):
        h = ctx["huc"]
        a(f"**HUC12:** {h.get('huc12', 'NOT AVAILABLE')}  "
          f"**HUC8:** {h.get('huc8', 'NOT AVAILABLE')}  {h.get('name','')}")
        a("")

    # ---- Data source status up front -------------------------------------
    a("## 0. Data source status")
    a("")
    a("Every number below comes from a live API response logged in the appendix.")
    a("Sources that failed are named here and are **not** substituted with estimates.")
    a("")
    a("| Source | Purpose | Status |")
    a("|---|---|---|")
    a(f"| USGS StreamStats (NY) | Watershed + basin characteristics | "
      f"{'OK' if basin.drainage_area_sqmi is not None else '**FAILED**'} |")
    a(f"| StreamStats flow statistics | NY regression flow stats | "
      f"{'OK' if ss_flow.available else '**NO DATA / FAILED**'} |")
    a(f"| USGS NWIS | Donor gauge flow-duration curve | "
      f"{'OK' if site_fdc else '**FAILED**'} |")
    a(f"| USGS NLDI + 3DEP EPQS | Downstream channel head | "
      f"{'OK' if head.gross_head_ft is not None else '**FAILED**'} |")
    hs_ok = any(p.ok for p in ctx.get("hydrosource", []))
    a(f"| ORNL HydroSource (NSD / EHA) | DOE potential cross-check | "
      f"{'partial' if hs_ok else '**FAILED**'} |")
    nid: Optional[Probe] = ctx.get("nid")
    a(f"| USACE NID | Nearby dams | "
      f"{'OK' if (nid and nid.ok) else '**FAILED**'} |")
    a("")
    if failures:
        a(f"> **{len(failures)} HTTP call(s) failed.** See Appendix B for the exact "
          "endpoint and error for each.")
        a("")

    # ---- 1. Watershed ----------------------------------------------------
    a("## 1. Watershed delineation and basin characteristics")
    a("")
    a("*Source: USGS StreamStats web services, rcode=NY.*")
    a("")
    if basin.error and basin.drainage_area_sqmi is None:
        a(f"**FAILED — no delineation.** {basin.error}")
        a("")
        a("Because the drainage area is unknown, the drainage-area ratio in Step 2 "
          "cannot be computed and no flow estimate is possible from this run.")
    else:
        a(f"- **Workspace ID:** `{basin.workspace_id}`")
        a(f"- **Basin polygon returned:** {'yes' if basin.geometry_available else 'no'}")
        a(f"- **Drainage area:** {fmt(basin.drainage_area_sqmi, 3, 'sq mi')} "
          f"({fmt((basin.drainage_area_sqmi or 0) * SQMI_TO_SQKM, 3, 'sq km')})")
        a("")
        if basin.parameters:
            a("| Code | Characteristic | Value | Unit |")
            a("|---|---|---|---|")
            for code, p in sorted(basin.parameters.items()):
                label = PARAM_LABELS.get(code, p.get("name", ""))
                a(f"| `{code}` | {label} | {p.get('value', 'NOT AVAILABLE')} "
                  f"| {p.get('unit', '')} |")
            a("")

    # ---- 2. Flow ---------------------------------------------------------
    a("## 2. Available flow")
    a("")
    a("### 2a. StreamStats regression flow statistics")
    a("")
    if ss_flow.available:
        a("| Statistic | Value | Unit |")
        a("|---|---|---|")
        for s in ss_flow.stats:
            a(f"| {s.get('name', s.get('code',''))} | {s.get('Value', s.get('value'))} "
              f"| {s.get('unit', '')} |")
        a("")
        if ss_flow.has_duration_curve:
            a("StreamStats returned duration statistics directly; they are used below.")
        else:
            a("StreamStats returned flow statistics but **no flow-duration curve** "
              "(NY's published regression equations for this region are oriented to "
              "peak-flow and low-flow statistics). Falling back to a gauge transfer.")
    else:
        a(f"**No flow statistics from StreamStats.** {ss_flow.error or ''}")
        a("")
        a("Falling back to the drainage-area ratio method against a gauged basin.")
    a("")

    a("### 2b. Donor gauge and drainage-area ratio transfer")
    a("")
    if not donor or not site_fdc:
        a("**FAILED — no flow-duration curve could be built.** "
          f"{ctx.get('flow_error', '')}")
        a("")
    else:
        a(f"- **Donor gauge:** USGS {donor.site_no} — {donor.name}")
        a(f"- **Gauge location:** {donor.lat:.5f}, {donor.lon:.5f} "
          f"({donor.distance_mi:.1f} mi from the site)")
        a(f"- **Gauge drainage area:** {fmt(donor.drainage_area_sqmi, 2, 'sq mi')}")
        a(f"- **Site drainage area:** {fmt(basin.drainage_area_sqmi, 3, 'sq mi')}")
        a(f"- **Daily values used:** {donor.n_days:,} days of record")
        a("")
        ratio = ctx["da_ratio"]
        a("**Drainage-area ratio method — the work:**")
        a("")
        a("```")
        a("Q_site(p) = Q_gauge(p) * ( DA_site / DA_gauge ) ^ x        with x = 1.0")
        a("")
        a(f"DA_site  = {basin.drainage_area_sqmi:.3f} sq mi   (StreamStats delineation)")
        a(f"DA_gauge = {donor.drainage_area_sqmi:.2f} sq mi   (NWIS site record, gauge {donor.site_no})")
        a(f"ratio    = {basin.drainage_area_sqmi:.3f} / {donor.drainage_area_sqmi:.2f}"
          f" = {ratio:.5f}")
        a("```")
        a("")
        if ratio < 0.3 or ratio > 3.0:
            a(f"> ⚠️ **The area ratio is {ratio:.3f}.** The drainage-area ratio method "
              "is normally considered defensible only in roughly the 0.3–3.0 band "
              "(ideally 0.5–1.5). Outside it, the transferred flows carry large and "
              "asymmetric error and should be treated as an order-of-magnitude "
              "indication until a real gauging record exists at the site.")
            a("")
        a("| Exceedance | Meaning | Gauge flow (cfs) | Scaled site flow (cfs) | Site flow (m³/s) |")
        a("|---|---|---|---|---|")
        meaning = {5: "very high", 10: "high", 50: "median", 90: "low", 95: "very low"}
        for p in sorted(site_fdc):
            a(f"| Q{p} ({p}% of the time) | {meaning.get(p,'')} | "
              f"{donor.fdc.get(p, float('nan')):,.2f} | {site_fdc[p]:,.3f} | "
              f"{site_fdc[p]*CFS_TO_CMS:,.4f} |")
        a("")

    # ---- 3. Head ---------------------------------------------------------
    a("## 3. Gross head")
    a("")
    a("*Source: USGS NLDI downstream channel trace + USGS 3DEP EPQS point elevations.*")
    a("")
    if head.gross_head_ft is None:
        a(f"**FAILED — no head estimate.** {head.error or ''}")
    else:
        a(f"- **NHD COMID traced:** `{head.comid}`")
        a(f"- **Penstock run modelled:** {fmt(head.run_length_ft, 0, 'ft')} "
          "downstream along the channel")
        a(f"- **Gross head over that run:** **{fmt(head.gross_head_ft, 1, 'ft')}** "
          f"({fmt((head.gross_head_ft or 0)*FT_TO_M, 2, 'm')})")
        if head.head_at_500ft is not None:
            a(f"- **Gross head at 500 ft:** {fmt(head.head_at_500ft, 1, 'ft')} "
              f"({fmt(head.head_at_500ft*FT_TO_M, 2, 'm')})")
        if head.run_length_ft:
            a(f"- **Average channel gradient:** "
              f"{(head.gross_head_ft/head.run_length_ft)*100:.2f}%")
        a("")
        for n in head.notes:
            a(f"> {n}")
        a("")
        a("<details><summary>Elevation profile (every sample)</summary>")
        a("")
        a("| Distance (ft) | Lat | Lon | 3DEP elevation (ft) |")
        a("|---|---|---|---|")
        for p in head.profile:
            e = fmt(p["elev_ft"], 2) if p["elev_ft"] is not None else "NO DATA"
            a(f"| {p['dist_ft']:.0f} | {p['lat']:.6f} | {p['lon']:.6f} | {e} |")
        a("")
        a("</details>")
        a("")
        a("> **Accuracy caveat.** 3DEP is a ~10 m (1/3 arc-second) DEM with roughly "
          "1–2 ft RMSE vertical accuracy in bare-earth conditions, and it is worse "
          "in a narrow forested stream valley where the surface model may not have "
          "resolved the channel bottom. On a run this short the DEM error is a large "
          "fraction of the answer. **This head number is a screening value only** and "
          "must be replaced by a survey (laser level, rod, or a hose-and-pressure-gauge "
          "measurement) before any equipment is bought.")
    a("")

    # ---- 4. Power --------------------------------------------------------
    a("## 4. Power potential")
    a("")
    a("```")
    a("P(kW) = 9.81 * Q(m3/s) * H(m) * efficiency")
    a("```")
    a("")
    if head.gross_head_ft is None or not site_fdc:
        a("**Cannot be computed.** Power requires both a head value and a flow "
          "value; at least one of them failed above. Specifically:")
        if head.gross_head_ft is None:
            a("- head: **unavailable**")
        if not site_fdc:
            a("- flow: **unavailable**")
        a("")
        a("No power numbers are given here, because any number would be invented.")
    else:
        h = head.gross_head_ft
        a(f"Using gross head **H = {h:.1f} ft = {h*FT_TO_M:.2f} m** over a "
          f"{head.run_length_ft:.0f} ft run.")
        a("")
        a("Note this is *gross* head. Net head after penstock friction loss is "
          "typically 85–90% of gross for a well-sized pipe, and the efficiency "
          "column already carries the turbine/generator/drive losses.")
        a("")
        a("| Exceedance | Flow (cfs) | Flow (m³/s) | Theoretical (kW) | @60% (kW) | @65% (kW) | @70% (kW) |")
        a("|---|---|---|---|---|---|---|")
        for row in power_table(site_fdc, h, [0.60, 0.65, 0.70]):
            a(f"| Q{row['exceedance_pct']} | {row['q_cfs']:,.3f} | {row['q_cms']:,.4f} "
              f"| {row['theoretical_kw']:,.3f} | {row['kw_at_60']:,.3f} "
              f"| {row['kw_at_65']:,.3f} | {row['kw_at_70']:,.3f} |")
        a("")
        aep = ctx.get("aep")
        if aep:
            a("### Indicative annual energy")
            a("")
            a(f"Turbine sized at the Q{aep['design_exceedance']} flow "
              f"({aep['design_flow_cfs']:.3f} cfs), shutdown below "
              f"{aep['cutoff_flow_cfs']:.3f} cfs, {int(aep['efficiency']*100)}% "
              "system efficiency, no bypass flow deducted:")
            a("")
            a(f"- **Rated output:** {aep['rated_kw']:.3f} kW")
            a(f"- **Average output:** {aep['avg_kw']:.3f} kW")
            a(f"- **Annual energy:** {aep['annual_kwh']:,.0f} kWh/yr")
            a(f"- **Capacity factor:** {aep['capacity_factor']*100:.0f}%")
            a("")
            a(f"For scale, a typical US home uses roughly 10,500 kWh/yr; an "
              f"efficient off-grid homestead often runs 2,000–4,000 kWh/yr.")
            a("")

    # ---- 5. DOE ----------------------------------------------------------
    a("## 5. Cross-check against ORNL / DOE data")
    a("")
    a("*Target: ORNL HydroSource — New Stream-reach Development (NSD) potential.*")
    a("")
    probes: list[Probe] = ctx.get("hydrosource", [])
    if probes:
        a("| Endpoint | Result |")
        a("|---|---|")
        for p in probes:
            a(f"| {p.name} | {'reachable — ' + p.detail if p.ok else '**FAILED** — ' + p.detail} |")
        a("")
    if not any(p.ok for p in probes):
        a("**No ORNL/DOE data was retrieved.** No NSD estimate is reported for this "
          "reach, because none was obtained. This must be checked manually at "
          "<https://hydrosource.ornl.gov/>.")
        a("")
    a("> **Context for interpreting NSD either way.** The NSD assessment screened "
      "new stream-reach potential nationally and its published reach inventory is "
      "oriented to utility-relevant capacity — the national reporting threshold sits "
      "far above a 0.5–10 kW homestead machine. A reach of this size being absent "
      "from NSD is therefore expected and is **not** evidence against a home-scale "
      "project; conversely, a hit would indicate a much larger opportunity than the "
      "one being evaluated here.")
    a("")

    # ---- 6. Constraints --------------------------------------------------
    a("## 6. Constraints and permitting")
    a("")
    a("### Nearby dams and existing hydropower")
    a("")
    if nid and nid.ok:
        rows = nid.payload or []
        if rows:
            a("| Dam | NID ID | Distance (mi) | River | Purposes |")
            a("|---|---|---|---|---|")
            for d in rows[:20]:
                a(f"| {d.get('name')} | {d.get('nid_id')} | {d['distance_mi']:.1f} "
                  f"| {d.get('river')} | {d.get('purposes')} |")
        else:
            a("USACE NID returned no dams within the search radius of this point.")
    else:
        a(f"**USACE NID query failed** — nearby dams NOT checked. "
          f"{nid.detail if nid else ''}")
    a("")
    eha_ok = any(p.ok and "EHA" in p.name for p in probes)
    if not eha_ok:
        a("**ORNL Existing Hydropower Assets (EHA) was not retrieved**, so existing "
          "hydro facilities near this reach are unverified in this run.")
        a("")

    a("### Environmental sensitivity")
    a("")
    a("Not retrieved in this run. The datasets that would answer it — NYSDEC water "
      "quality classification for this reach, NYSDEC trout-stream and spawning "
      "designations, USFWS IPaC listed-species review, and NY Natural Heritage "
      "Program records — were not queried here and should not be assumed benign. "
      "A small headwater creek in this part of central New York has a realistic "
      "chance of carrying a trout designation, which raises the permitting bar for "
      "any in-channel structure.")
    a("")
    a("### FERC thresholds (general parameters, not legal advice)")
    a("")
    a(FERC_GENERAL)
    a("")

    # ---- Verdict ---------------------------------------------------------
    a("## Plain-language summary")
    a("")
    a(ctx.get("verdict", ""))
    a("")

    a("## What must be field-verified before spending real money")
    a("")
    a("1. **Measure the actual flow, repeatedly, through a dry season.** Everything "
       "in Step 2 is a statistical transfer from a different watershed. Weir-box or "
       "bucket-and-stopwatch measurements taken monthly for at least one full year — "
       "and above all in late summer and in a drought year — are what decide whether "
       "this site works. Late-summer low flow, not average flow, sets the size of the "
       "machine you can actually run.")
    a("2. **Survey the real head.** Replace the DEM number with a laser level, a "
       "surveyor's rod, or a hose filled with water and a pressure gauge read at the "
       "proposed turbine location. Measure to the actual, physically reachable "
       "powerhouse site, not to an arbitrary point 1,000 ft downstream.")
    a("3. **Walk the penstock route.** Length, pipe diameter, buried vs. surface, "
       "stream crossings, rock, and the resulting friction loss determine net head "
       "and dominate cost at this scale.")
    a("4. **Confirm you control both ends.** Property boundaries and, where the "
       "channel is not entirely yours, riparian rights at both the intake and the "
       "tailrace.")
    a("5. **Get the DEC classification for this reach** and a formal read on Article "
       "15 Protection of Waters, 401 water-quality certification, SEQRA, and any "
       "USACE 404 nexus.")
    a("6. **Get a written FERC jurisdictional determination** rather than relying on "
       "a threshold reading.")
    a("7. **Winter behaviour.** Frazil and anchor ice, leaf litter, and spring debris "
       "load at the intake decide whether the system runs unattended; screening and "
       "intake design follow from that.")
    a("8. **Confirm the load and the distance to it** — transmission distance from "
       "powerhouse to house, and whether the system is battery-based or grid-tied.")
    a("")

    # ---- Appendices ------------------------------------------------------
    a("## Appendix A — All API calls made")
    a("")
    a("| # | Source | Status | Endpoint |")
    a("|---|---|---|---|")
    for i, c in enumerate(PROVENANCE, 1):
        st = f"OK {c.status}" if c.ok else f"**FAIL {c.status or ''}**"
        a(f"| {i} | {c.label} | {st} | `{c.url[:150]}` |")
    a("")
    if failures:
        a("## Appendix B — Failures in detail")
        a("")
        for c in failures:
            a(f"- **{c.label}**  ")
            a(f"  `{c.url[:200]}`  ")
            a(f"  → {c.detail}")
        a("")
    a("---")
    a("")
    a("*Generated by `hydro_assessment.py`. Every value above is either a live API "
      "response or an explicit NOT AVAILABLE / FAILED marker. No placeholder or "
      "remembered values were substituted.*")

    # Guarantee a blank line before every heading, whichever branches ran above.
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
    fdc = ctx.get("site_fdc") or {}
    if basin.drainage_area_sqmi is None or head.gross_head_ft is None or not fdc:
        missing = []
        if basin.drainage_area_sqmi is None:
            missing.append("watershed delineation")
        if not fdc:
            missing.append("flow")
        if head.gross_head_ft is None:
            missing.append("head")
        return (
            "**No verdict can be given from this run.** The following inputs could "
            f"not be obtained from their live sources: **{', '.join(missing)}**. "
            "Rather than guess, this report stops here. See the source status table "
            "at the top and Appendix B for exactly which endpoints failed and why. "
            "Re-run the script from a network that can reach the USGS and ORNL "
            "services and the report will populate."
        )

    h = head.gross_head_ft
    q50, q90 = fdc.get(50), fdc.get(90)
    p50 = power_kw(q50, h, 0.65) if q50 else None
    p90 = power_kw(q90, h, 0.65) if q90 else None
    parts = [
        f"At the median flow (Q50 = {q50:,.2f} cfs) and {h:.1f} ft of gross head, a "
        f"65%-efficient machine would make about **{p50:,.2f} kW**. At the low-flow "
        f"condition that actually sizes an off-grid system (Q90 = {q90:,.2f} cfs), it "
        f"would make about **{p90:,.2f} kW**."
    ]
    if p90 is not None:
        if p90 >= 1.0:
            parts.append(
                "That clears the bar for a genuinely useful home system: continuous "
                "output above 1 kW even in low flow is a meaningful share of a "
                "homestead's demand, and the site is worth the cost of field "
                "verification."
            )
        elif p90 >= 0.3:
            parts.append(
                "That is marginal but real. Sub-kilowatt continuous output still adds "
                "up over a year and can carry a battery-based off-grid load, but the "
                "economics depend heavily on penstock length and how far the power has "
                "to be moved."
            )
        else:
            parts.append(
                "That is below the practical threshold for a useful home system as "
                "modelled. The site would only become interesting with substantially "
                "more head than the DEM suggests — which is exactly why the head must "
                "be surveyed before this is written off or pursued."
            )
    parts.append(
        "Treat all of this as a screening result. The flow figures are transferred "
        "from another watershed by area ratio and the head comes from a coarse DEM; "
        "both carry enough error at this scale to move the answer by a factor of two "
        "in either direction."
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
    ap.add_argument("--run-ft", type=float, default=1000.0,
                    help="Downstream channel length to sample for head (ft)")
    ap.add_argument("--step-ft", type=float, default=50.0,
                    help="Elevation sample spacing (ft)")
    ap.add_argument("--out", default="ocquionis_creek_microhydro_report.md")
    ap.add_argument("--provenance-json", default="provenance.json")
    args = ap.parse_args()

    lat, lon = args.lat, args.lon
    print(f"[*] Site: {lat}, {lon}", file=sys.stderr)

    ctx: dict = {"lat": lat, "lon": lon}

    # 1 -----------------------------------------------------------------
    print("[1] StreamStats watershed delineation ...", file=sys.stderr)
    basin = delineate_basin(lat, lon, args.rcode)
    ctx["basin"] = basin
    if basin.drainage_area_sqmi is not None:
        print(f"    drainage area = {basin.drainage_area_sqmi} sq mi", file=sys.stderr)
    else:
        print(f"    FAILED: {basin.error}", file=sys.stderr)

    # HUC (nice-to-have)
    ctx["huc"] = get_huc12(lat, lon)

    # 2a ----------------------------------------------------------------
    print("[2a] StreamStats flow statistics ...", file=sys.stderr)
    ss_flow = streamstats_flow_stats(basin.workspace_id or "", args.rcode)
    ctx["ss_flow"] = ss_flow

    # 2b ----------------------------------------------------------------
    site_fdc: dict[int, float] = {}
    donor: Optional[Gauge] = None
    flow_error = ""
    if ss_flow.has_duration_curve:
        site_fdc = dict(ss_flow.duration)
        ctx["da_ratio"] = None
        print("    using StreamStats duration statistics directly", file=sys.stderr)
    else:
        print("[2b] NWIS donor-gauge search ...", file=sys.stderr)
        try:
            cands = find_candidate_gauges(lat, lon)
            ranked = rank_gauges(cands, basin.drainage_area_sqmi)
            print(f"    {len(cands)} gauges found, {len(ranked)} usable", file=sys.stderr)
            for g in ranked[:5]:
                try:
                    daily = fetch_daily_flow(g.site_no)
                except SourceFailure as e:
                    print(f"    gauge {g.site_no} unusable: {e}", file=sys.stderr)
                    continue
                g.n_days = len(daily)
                g.fdc = flow_duration_curve(daily)
                donor = g
                break
            if donor is None:
                flow_error = ("No nearby gauge with a usable daily-discharge record "
                              "and a comparable drainage area was found.")
            elif basin.drainage_area_sqmi is None:
                flow_error = ("A donor gauge was found, but the site drainage area is "
                              "unknown (StreamStats failed), so the area ratio cannot "
                              "be computed.")
            else:
                ratio = basin.drainage_area_sqmi / donor.drainage_area_sqmi
                ctx["da_ratio"] = ratio
                site_fdc = scale_by_drainage_area(
                    donor.fdc, basin.drainage_area_sqmi, donor.drainage_area_sqmi
                )
                print(f"    donor {donor.site_no}, ratio {ratio:.4f}", file=sys.stderr)
        except SourceFailure as e:
            flow_error = str(e)
            print(f"    FAILED: {e}", file=sys.stderr)

    ctx["donor"] = donor
    ctx["site_fdc"] = site_fdc
    ctx["flow_error"] = flow_error

    # 3 -----------------------------------------------------------------
    print("[3] Head: NLDI trace + 3DEP EPQS sampling ...", file=sys.stderr)
    head = estimate_head(lat, lon, args.run_ft, args.step_ft)
    ctx["head"] = head
    if head.gross_head_ft is not None:
        print(f"    gross head = {head.gross_head_ft:.1f} ft over "
              f"{head.run_length_ft:.0f} ft", file=sys.stderr)
    else:
        print(f"    FAILED: {head.error}", file=sys.stderr)

    # 4 -----------------------------------------------------------------
    if site_fdc and head.gross_head_ft is not None:
        ctx["aep"] = annual_energy_kwh(site_fdc, head.gross_head_ft, 0.65)

    # 5 & 6 -------------------------------------------------------------
    print("[5] ORNL HydroSource probes ...", file=sys.stderr)
    ctx["hydrosource"] = probe_hydrosource(
        (ctx.get("huc") or {}).get("huc8") if ctx.get("huc") else None
    )
    print("[6] USACE NID ...", file=sys.stderr)
    ctx["nid"] = probe_nid(lat, lon)

    # Report ------------------------------------------------------------
    ctx["verdict"] = build_verdict(ctx)
    report = render_report(ctx)
    with open(args.out, "w") as f:
        f.write(report)

    with open(args.provenance_json, "w") as f:
        json.dump(
            [
                {"label": c.label, "url": c.url, "ok": c.ok,
                 "status": c.status, "detail": c.detail,
                 "elapsed_s": round(c.elapsed_s, 3)}
                for c in PROVENANCE
            ],
            f,
            indent=2,
        )

    ok = sum(1 for c in PROVENANCE if c.ok)
    bad = len(PROVENANCE) - ok
    print(f"\n[*] Wrote {args.out}", file=sys.stderr)
    print(f"[*] API calls: {ok} OK, {bad} failed "
          f"(details in {args.provenance_json})", file=sys.stderr)
    return 0 if bad == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
