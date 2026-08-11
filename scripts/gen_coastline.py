#!/usr/bin/env python3
"""Regenerate custom_components/accuweather/coastline.py.

    python3 scripts/gen_coastline.py

Downloads Natural Earth 1:50m (public domain), resamples every country ring at
a fixed spacing, and keeps only the points that sit on the real coastline, so
inland borders — China/Mongolia, India/Nepal — never end up in a table called
"coastal points". Vietnam is left out on purpose: const.VIETNAM_COAST names it
by province, which is the more useful answer for the people using this.

Needs no third-party packages, only network access.
"""
from __future__ import annotations

import json
import math
import urllib.request
from datetime import date
from pathlib import Path

BASE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson"
COUNTRIES_URL = f"{BASE}/ne_50m_admin_0_countries.geojson"
COASTLINE_URL = f"{BASE}/ne_50m_coastline.geojson"

OUT = Path(__file__).resolve().parent.parent / "custom_components/accuweather/coastline.py"

# The western North Pacific, the South China Sea and the Bay of Bengal: every
# basin whose storms can reach the people this integration is written for.
BOX = (-12.0, 52.0, 90.0, 155.0)  # lat_min, lat_max, lon_min, lon_max
STEP_KM = 40.0        # spacing along each ring
SEA_LIMIT_KM = 20.0   # how close to the real coastline a point must be to count

NAMES_VI = {
    "China": "Trung Quốc",
    "Japan": "Nhật Bản",
    "Philippines": "Philippines",
    "Taiwan": "Đài Loan",
    "South Korea": "Hàn Quốc",
    "North Korea": "Triều Tiên",
    "Thailand": "Thái Lan",
    "Cambodia": "Campuchia",
    "Laos": "Lào",
    "Malaysia": "Malaysia",
    "Singapore": "Singapore",
    "Brunei": "Brunei",
    "Indonesia": "Indonesia",
    "Timor-Leste": "Đông Timor",
    "Myanmar": "Myanmar",
    "Bangladesh": "Bangladesh",
    "India": "Ấn Độ",
    "Russia": "Nga",
    "Hong Kong": "Hồng Kông",
    "Papua New Guinea": "Papua New Guinea",
    "Australia": "Úc",
    "N. Mariana Is.": "Quần đảo Bắc Mariana",
    "Guam": "Guam",
    "Palau": "Palau",
    "Micronesia": "Micronesia",
}


def fetch(url: str) -> dict:
    print(f"  tải {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.loads(response.read())


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def rings(geom: dict) -> list[list[list[float]]]:
    if geom["type"] == "Polygon":
        return [geom["coordinates"][0]]
    return [polygon[0] for polygon in geom["coordinates"]]


def resample(ring: list[list[float]], step: float = STEP_KM) -> list[tuple[float, float]]:
    """Walk a ring, dropping a point every `step` kilometres."""
    out: list[tuple[float, float]] = []
    travelled = step
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:]):
        segment = distance_km(lat1, lon1, lat2, lon2)
        if segment <= 0:
            continue
        travelled += segment
        while travelled >= step:
            travelled -= step
            fraction = 1 - (travelled / segment)
            if 0 <= fraction <= 1:
                out.append((
                    round(lat1 + (lat2 - lat1) * fraction, 2),
                    round(lon1 + (lon2 - lon1) * fraction, 2),
                ))
    return out


def main() -> None:
    coastline = fetch(COASTLINE_URL)
    countries = fetch(COUNTRIES_URL)

    # The true coastline, bucketed by whole degree, to tell shore from border.
    shore: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for feature in coastline["features"]:
        geom = feature["geometry"]
        lines = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
        for line in lines:
            for lon, lat in line:
                if BOX[0] - 1 <= lat <= BOX[1] + 1 and BOX[2] - 1 <= lon <= BOX[3] + 1:
                    shore.setdefault((int(lat), int(lon)), []).append((lat, lon))

    def on_the_sea(lat: float, lon: float) -> bool:
        for d_lat in (-1, 0, 1):
            for d_lon in (-1, 0, 1):
                for s_lat, s_lon in shore.get((int(lat) + d_lat, int(lon) + d_lon), ()):
                    if distance_km(lat, lon, s_lat, s_lon) <= SEA_LIMIT_KM:
                        return True
        return False

    points: dict[str, list[tuple[float, float]]] = {}
    for feature in countries["features"]:
        vietnamese = NAMES_VI.get(feature["properties"].get("NAME"))
        if not vietnamese:
            continue
        kept = [
            (lat, lon)
            for ring in rings(feature["geometry"])
            for lat, lon in resample(ring)
            if BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3] and on_the_sea(lat, lon)
        ]
        if kept:
            points[vietnamese] = kept

    total = sum(len(v) for v in points.values())
    body = ",\n".join(
        '    "%s": "%s"' % (name, " ".join(f"{lat},{lon}" for lat, lon in pts))
        for name, pts in sorted(points.items())
    )

    OUT.write_text(
        f'''"""Coastal reference points for the storm basin this integration watches.

GENERATED FILE — do not edit by hand. Run scripts/gen_coastline.py instead.

Source: Natural Earth 1:50m admin_0 countries and coastline, public domain.
Generated on {date.today().isoformat()}.

Country rings are resampled every {STEP_KM:.0f} km and thinned to the points within
{SEA_LIMIT_KM:.0f} km of the real coastline, so inland borders are left out. Coverage is the
box {BOX[0]:.0f}..{BOX[1]:.0f} N, {BOX[2]:.0f}..{BOX[3]:.0f} E — the western North Pacific, the South China Sea
and the Bay of Bengal. A storm outside it gets no landfall estimate rather than
a made-up one.

Vietnam is not here on purpose: const.VIETNAM_COAST names it by province, which
is the more useful answer for the people using this integration.
"""
from __future__ import annotations

# Country name -> "lat,lon lat,lon ..." — a compact form, {total} points in all.
_POINTS: dict[str, str] = {{
{body},
}}

COASTAL_POINTS: tuple[tuple[str, float, float], ...] = tuple(
    (name, float(lat), float(lon))
    for name, blob in _POINTS.items()
    for lat, lon in (pair.split(",") for pair in blob.split())
)
''',
        encoding="utf-8",
    )

    print(f"đã ghi {OUT}")
    print(f"  {total} điểm, {len(points)} vùng đất, {OUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
