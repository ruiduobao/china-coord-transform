"""
transform.py — China coord transforms via the public GCJ-02 obfuscation.

Supported directions (all 6 pairwise conversions):
  - wgs84 <-> gcj02
  - gcj02 <-> bd09
  - wgs84 <-> bd09 (composed)

Reference:
  - GCJ-02 obfuscation algorithm published by ANRC (国家测绘局), 2002
  - Krasovsky 1940 ellipsoid: a = 6378245.0, f = 1/298.3
  - BD-09 extension: z + 0.00002*sin(3θ), theta + 0.000003*cos(3θ), then +0.0065/+0.006
  - Original QGIS plugin: qgis-geohey-toolbox (GeoHey, sshuair@gmail.com)
"""
from __future__ import annotations

import math
from math import sin, cos, sqrt, atan2, fabs, pi as PI

# ===== Krasovsky 1940 ellipsoid =====
A = 6378245.0            # 长半轴
F = 1.0 / 298.3          # 扁率
EE = 1.0 - (1.0 - F) ** 2   # 第一偏心率平方

# ===== China bounding box (rough) =====
# 公式法只对中国大陆点有意义，越界点直接原样返回
LON_MIN, LON_MAX = 72.004, 137.8347
LAT_MIN, LAT_MAX = 0.8293, 55.8271


def out_of_china(lon: float, lat: float) -> bool:
    """Return True if the point is outside mainland China."""
    return not (LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX)


def _transform_lat(x: float, y: float) -> float:
    """Lat offset polynomial (clamped abs to keep sqrt safe)."""
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * sqrt(fabs(x))
    ret += (20.0 * sin(6.0 * x * PI) + 20.0 * sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * sin(y * PI) + 40.0 * sin(y / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * sin(y / 12.0 * PI) + 320.0 * sin(y * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    """Lon offset polynomial (clamped abs to keep sqrt safe)."""
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * sqrt(fabs(x))
    ret += (20.0 * sin(6.0 * x * PI) + 20.0 * sin(2.0 * x * PI)) * 2.0 / 3.0
    ret += (20.0 * sin(x * PI) + 40.0 * sin(x / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * sin(x / 12.0 * PI) + 300.0 * sin(x * PI / 30.0)) * 2.0 / 3.0
    return ret


def wgs2gcj(lon: float, lat: float) -> tuple[float, float]:
    """WGS-84 → GCJ-02 (火星坐标系). Returns (lon, lat)."""
    if out_of_china(lon, lat):
        return lon, lat
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlng = _transform_lng(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = sin(radlat)
    magic = 1 - EE * magic * magic
    sqrt_magic = sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrt_magic) * PI)
    dlng = (dlng * 180.0) / (A / sqrt_magic * cos(radlat) * PI)
    return (lon + dlng, lat + dlat)


def gcj2wgs(lon: float, lat: float, tol: float = 1e-6, max_iter: int = 10) -> tuple[float, float]:
    """GCJ-02 → WGS-84 by fixed-point iteration. Stops when delta < tol (degrees)."""
    g0 = (lon, lat)
    w0 = g0
    for _ in range(max_iter):
        w1_lon, w1_lat = wgs2gcj(w0[0], w0[1])
        # Newton-style correction: w1 = w0 - (wgs2gcj(w0) - g0)
        w1 = (w0[0] - (w1_lon - g0[0]), w0[1] - (w1_lat - g0[1]))
        if abs(w1[0] - w0[0]) < tol and abs(w1[1] - w0[1]) < tol:
            return w1
        w0 = w1
    return w0


def gcj2bd(lon: float, lat: float) -> tuple[float, float]:
    """GCJ-02 → BD-09 (百度坐标系)."""
    z = sqrt(lon * lon + lat * lat) + 0.00002 * sin(lat * PI * 3000.0 / 180.0)
    theta = atan2(lat, lon) + 0.000003 * cos(lon * PI * 3000.0 / 180.0)
    return (z * cos(theta) + 0.0065, z * sin(theta) + 0.006)


def bd2gcj(lon: float, lat: float) -> tuple[float, float]:
    """BD-09 → GCJ-02."""
    x = lon - 0.0065
    y = lat - 0.006
    z = sqrt(x * x + y * y) - 0.00002 * sin(y * PI * 3000.0 / 180.0)
    theta = atan2(y, x) - 0.000003 * cos(x * PI * 3000.0 / 180.0)
    return (z * cos(theta), z * sin(theta))


def wgs2bd(lon: float, lat: float) -> tuple[float, float]:
    """WGS-84 → BD-09 (composed)."""
    return gcj2bd(*wgs2gcj(lon, lat))


def bd2wgs(lon: float, lat: float) -> tuple[float, float]:
    """BD-09 → WGS-84 (composed)."""
    return gcj2wgs(*bd2gcj(lon, lat))


# ===== Convenience dispatch =====
CONVERTERS = {
    ("wgs84", "gcj02"): wgs2gcj,
    ("gcj02", "wgs84"): gcj2wgs,
    ("gcj02", "bd09"):  gcj2bd,
    ("bd09",  "gcj02"): bd2gcj,
    ("wgs84", "bd09"):  wgs2bd,
    ("bd09",  "wgs84"): bd2wgs,
}

SUPPORTED_SYSTEMS = ("wgs84", "gcj02", "bd09")


def convert(x: float, y: float, src: str, dst: str) -> tuple[float, float]:
    """Generic dispatcher. ``src``/``dst`` are case-insensitive."""
    src_l = src.lower()
    dst_l = dst.lower()
    if src_l == dst_l:
        return x, y
    if src_l not in SUPPORTED_SYSTEMS or dst_l not in SUPPORTED_SYSTEMS:
        raise ValueError(
            f"unsupported coord system pair: {src!r} -> {dst!r}; "
            f"supported: {', '.join(SUPPORTED_SYSTEMS)}"
        )
    fn = CONVERTERS[(src_l, dst_l)]
    return fn(x, y)


if __name__ == "__main__":
    # Self-test with the Tiananmen fixture from the project README
    print("== Tiananmen (高德 → WGS-84) ==")
    gcj_lon, gcj_lat = 116.397594, 39.904949
    wgs_lon, wgs_lat = gcj2wgs(gcj_lon, gcj_lat)
    print(f"GCJ-02 : {gcj_lon}, {gcj_lat}")
    print(f"WGS-84 : {wgs_lon:.6f}, {wgs_lat:.6f}")
    # Google Earth reference
    ref_lon, ref_lat = 116.391222, 39.903468
    print(f"Ref    : {ref_lon}, {ref_lat}")

    # Haversine
    def haversine(lon1, lat1, lon2, lat2):
        R = 6371008.8
        rl1, rl2 = lat1 * PI / 180, lat2 * PI / 180
        dlat = (lat2 - lat1) * PI / 180
        dlon = (lon2 - lon1) * PI / 180
        a = sin(dlat / 2) ** 2 + cos(rl1) * cos(rl2) * sin(dlon / 2) ** 2
        return 2 * R * atan2(sqrt(a), sqrt(1 - a))

    d_after = haversine(gcj_lon, gcj_lat, wgs_lon, wgs_lat)
    d_ref = haversine(ref_lon, ref_lat, wgs_lon, wgs_lat)
    print(f"distance (GCJ→converted): {d_after:.2f} m")
    print(f"distance (Google→converted): {d_ref:.2f} m  (should be < 20m)")
