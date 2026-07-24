"""
helmert.py — Method 3: 2D / 3D Helmert (Bursa-Wolf) transform.

For users with survey-grade control points (RTK, total station, CORS) and
a published parameter set, this is the standard way to convert between
datums. Pure-Python, no third-party deps.

Models supported:
  4-param (similarity, plane):   tx, ty, rotation, scale
  5-param (plane, anisotropic):  tx, ty, rotation, scale_x, scale_y
  6-param (affine, plane):       a, b, c, d, e, f   (already in affine.py)
  7-param (3D Helmert, geodetic): dx, dy, dz, rx, ry, rz, scale

The 7-parameter form is the standard for transforming between geodetic
datums (e.g. WGS-84 ↔ CGCS2000 ↔ local). It operates on geocentric
Cartesian (X, Y, Z) coordinates in meters, so the public `convert`
helpers in `transform.py` (lat/lon) should be used to first project
into ECEF if you want to use this directly.

The 4 / 5-parameter forms are typically used on projected plane
coordinates (e.g. UTM / Gauss-Krüger) where the local distortion is
small enough to be modeled as a similarity or affine transform.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

PI = math.pi


# ===== 2D: 4-parameter similarity (tx, ty, rotation, scale) =====


@dataclass
class Helmert2D4:
    """2D similarity transform: 4 parameters.

    [X]   [ tx ]   [ s -θ ] [x]
    [Y] = [ ty ] + [ θ  s ] [y]

    where s = 1 + scale, θ = rotation (radians, counter-clockwise).
    """
    tx: float
    ty: float
    rotation_rad: float
    scale: float  # dimensionless; e.g. 1e-6 = 1 ppm

    def apply(self, x: float, y: float) -> tuple[float, float]:
        s = 1.0 + self.scale
        c = math.cos(self.rotation_rad)
        si = math.sin(self.rotation_rad)
        return (
            self.tx + s * (x * c - y * si),
            self.ty + s * (x * si + y * c),
        )

    def to_dict(self) -> dict:
        return {
            "model": "helmert2d_4param",
            "tx": self.tx, "ty": self.ty,
            "rotation_deg": math.degrees(self.rotation_rad),
            "scale_ppm": self.scale * 1e6,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Helmert2D4":
        if "scale_ppm" in d:
            scale = d["scale_ppm"] * 1e-6
        else:
            scale = d.get("scale", 0.0)
        rot = math.radians(d.get("rotation_deg", d.get("rotation_rad", 0.0)))
        return cls(tx=d["tx"], ty=d["ty"], rotation_rad=rot, scale=scale)


# ===== 2D: 5-parameter plane (tx, ty, rotation, scale_x, scale_y) =====


@dataclass
class Helmert2D5:
    """2D plane transform with anisotropic scale: 5 parameters.

    [X]   [ tx ]   [ sx -θ ] [x]
    [Y] = [ ty ] + [ θ  sy ] [y]

    where sx = 1 + scale_x, sy = 1 + scale_y, θ = rotation.
    This is what Chinese surveying literature usually calls "五参数":
    2 translations + 1 rotation + 2 (per-axis) scales.
    """
    tx: float
    ty: float
    rotation_rad: float
    scale_x: float
    scale_y: float

    def apply(self, x: float, y: float) -> tuple[float, float]:
        sx = 1.0 + self.scale_x
        sy = 1.0 + self.scale_y
        c = math.cos(self.rotation_rad)
        si = math.sin(self.rotation_rad)
        return (
            self.tx + sx * (x * c) - sy * (y * si),
            self.ty + sx * (x * si) + sy * (y * c),
        )

    def to_dict(self) -> dict:
        return {
            "model": "helmert2d_5param",
            "tx": self.tx, "ty": self.ty,
            "rotation_deg": math.degrees(self.rotation_rad),
            "scale_x_ppm": self.scale_x * 1e6,
            "scale_y_ppm": self.scale_y * 1e6,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Helmert2D5":
        return cls(
            tx=d["tx"], ty=d["ty"],
            rotation_rad=math.radians(d.get("rotation_deg", 0.0)),
            scale_x=d.get("scale_x_ppm", d.get("scale_x", 0.0)) * (
                1e-6 if "scale_x_ppm" in d else 1.0
            ),
            scale_y=d.get("scale_y_ppm", d.get("scale_y", 0.0)) * (
                1e-6 if "scale_y_ppm" in d else 1.0
            ),
        )


# ===== 3D: 7-parameter Helmert (Bursa-Wolf) =====


# WGS-84 / CGCS2000 reference ellipsoid (used by 3D Helmert helpers)
A_WGS84 = 6378137.0
F_WGS84 = 1.0 / 298.257223563
E2_WGS84 = F_WGS84 * (2.0 - F_WGS84)


def geodetic_to_ecef(lon_deg: float, lat_deg: float, h: float = 0.0) -> tuple[float, float, float]:
    """Convert geodetic (lon, lat, h) on WGS-84 to ECEF (X, Y, Z), meters."""
    lon = math.radians(lon_deg)
    lat = math.radians(lat_deg)
    sinlat = math.sin(lat)
    coslat = math.cos(lat)
    sinlon = math.sin(lon)
    coslon = math.cos(lon)
    N = A_WGS84 / math.sqrt(1.0 - E2_WGS84 * sinlat * sinlat)
    X = (N + h) * coslat * coslon
    Y = (N + h) * coslat * sinlon
    Z = (N * (1.0 - E2_WGS84) + h) * sinlat
    return X, Y, Z


def ecef_to_geodetic(X: float, Y: float, Z: float) -> tuple[float, float, float]:
    """Convert ECEF (X, Y, Z) on WGS-84 to geodetic (lon, lat, h), meters."""
    lon = math.atan2(Y, X)
    p = math.hypot(X, Y)
    # Bowring's iterative formula
    lat = math.atan2(Z, p * (1.0 - E2_WGS84))
    for _ in range(8):
        sinlat = math.sin(lat)
        N = A_WGS84 / math.sqrt(1.0 - E2_WGS84 * sinlat * sinlat)
        h = p / math.cos(lat) - N
        lat = math.atan2(Z, p * (1.0 - E2_WGS84 * N / (N + h)))
    sinlat = math.sin(lat)
    coslat = math.cos(lat)
    N = A_WGS84 / math.sqrt(1.0 - E2_WGS84 * sinlat * sinlat)
    h = p / coslat - N
    return math.degrees(lon), math.degrees(lat), h


@dataclass
class Helmert3D7:
    """7-parameter Bursa-Wolf 3D transform.

    [X']   [dx]   [ 1   -rz  ry ] [X]
    [Y'] = [dy] + [ rz  1   -rx ] [Y]   (in radians; ppm scale)
    [Z']   [dz]   [-ry  rx  1   ] [Z]

    with all 7 params: dx, dy, dz (m), rx, ry, rz (arc-seconds), scale (ppm).
    """
    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0
    rx_arcsec: float = 0.0
    ry_arcsec: float = 0.0
    rz_arcsec: float = 0.0
    scale_ppm: float = 0.0

    def apply_ecef(self, X: float, Y: float, Z: float) -> tuple[float, float, float]:
        s = 1.0 + self.scale_ppm * 1e-6
        # Rotations in arc-seconds -> radians
        rx = math.radians(self.rx_arcsec / 3600.0)
        ry = math.radians(self.ry_arcsec / 3600.0)
        rz = math.radians(self.rz_arcsec / 3600.0)
        Xp = self.dx + s * (       X - rz * Y + ry * Z)
        Yp = self.dy + s * (rz *  X +        Y - rx * Z)
        Zp = self.dz + s * (-ry * X + rx * Y +        Z)
        return Xp, Yp, Zp

    def apply_geodetic(
        self, lon_deg: float, lat_deg: float, h: float = 0.0
    ) -> tuple[float, float, float]:
        X, Y, Z = geodetic_to_ecef(lon_deg, lat_deg, h)
        Xp, Yp, Zp = self.apply_ecef(X, Y, Z)
        return ecef_to_geodetic(Xp, Yp, Zp)

    def invert(self) -> "Helmert3D7":
        """Return a new Helmert3D7 representing the inverse transformation.

        Math: for the 3D similarity,
          M = T * s * R   (T = translation, s = scale, R = rotation)
        M^{-1} = R^T * (1/s) * T^{-1}
        Expanding and re-deriving in the same (dx, dy, dz, rx, ry, rz, scale)
        form gives a closed-form inverse.

        The new translation is in the original frame:
          new_dx = -(1/(1+s)) * (dx - rz*dy + ry*dz)
          new_dy = -(1/(1+s)) * (rz*dx + dy - rx*dz)
          new_dz = -(1/(1+s)) * (-ry*dx + rx*dy + dz)
        where s = self.scale_ppm * 1e-6, and rx/ry/rz in radians.
        """
        s = self.scale_ppm * 1e-6
        rx = math.radians(self.rx_arcsec / 3600.0)
        ry = math.radians(self.ry_arcsec / 3600.0)
        rz = math.radians(self.rz_arcsec / 3600.0)
        inv_s = 1.0 / (1.0 + s)
        new_dx = -inv_s * (        self.dx - rz * self.dy + ry * self.dz)
        new_dy = -inv_s * (rz  *   self.dx +        self.dy - rx * self.dz)
        new_dz = -inv_s * (-ry *   self.dx + rx *   self.dy +        self.dz)
        new_scale_ppm = -s / (1.0 + s) * 1e6
        # R is orthogonal, so R^{-1} = R^T -> negate all rotations
        return Helmert3D7(
            dx=new_dx, dy=new_dy, dz=new_dz,
            rx_arcsec=-self.rx_arcsec, ry_arcsec=-self.ry_arcsec, rz_arcsec=-self.rz_arcsec,
            scale_ppm=new_scale_ppm,
        )

    def to_dict(self) -> dict:
        return {
            "model": "helmert3d_7param",
            "dx": self.dx, "dy": self.dy, "dz": self.dz,
            "rx_arcsec": self.rx_arcsec, "ry_arcsec": self.ry_arcsec, "rz_arcsec": self.rz_arcsec,
            "scale_ppm": self.scale_ppm,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Helmert3D7":
        return cls(
            dx=d.get("dx", 0.0), dy=d.get("dy", 0.0), dz=d.get("dz", 0.0),
            rx_arcsec=d.get("rx_arcsec", 0.0),
            ry_arcsec=d.get("ry_arcsec", 0.0),
            rz_arcsec=d.get("rz_arcsec", 0.0),
            scale_ppm=d.get("scale_ppm", 0.0),
        )


def fit_helmert_3d_7param(
    controls: Sequence[tuple[float, float, float, float, float, float]],
) -> Helmert3D7:
    """Fit a 7-parameter Helmert from geodetic control points.

    Each control is ``(src_lon, src_lat, src_h, dst_lon, dst_lat, dst_h)``
    on the WGS-84 ellipsoid. Converts each side to ECEF, then solves the
    linearized 7-param system (small-angle + small-scale approximation,
    good for terrestrial-scale shifts).

    Need >= 3 controls; 4+ recommended. For the small-rotation / small-
    scale assumption to be valid, |rx|, |ry|, |rz| should be < a few
    arc-seconds and |scale| < a few ppm — i.e. between geodetic datums
    that are very similar. For WGS-84 ↔ CGCS2000 in mainland China the
    published params are well within this.
    """
    if len(controls) < 3:
        raise ValueError(f"need >= 3 controls for 7-param fit, got {len(controls)}")

    # Linearized 7-param system (small angles, small scale).
    # X' = dx + (1+s) * (X - rz*Y + ry*Z)
    # Y' = dy + (1+s) * (rz*X + Y - rx*Z)
    # Z' = dz + (1+s) * (-ry*X + rx*Y + Z)
    # Re-arranged: unknowns are (dx, dy, dz, s, -s*rz, s*ry, s*rx, -s*rx, s*rz)
    # We use a closed form: linearize around s=1, theta=0, then the
    # design matrix is:
    #   [1 0 0   X  0  Z -Y]
    #   [0 1 0   Y -Z  0  X]
    #   [0 0 1   Z  Y -X  0]
    # where the 4th column is for s, and 5-7 for s*rx, s*ry, s*rz.
    # After the LSQ solve, we extract s from the 4th unknown, and
    # rx/ry/rz from 5/6/7 divided by s.
    a_mat: list[list[float]] = []
    b_vec: list[float] = []
    for slon, slat, sh, dlon, dlat, dh in controls:
        X1, Y1, Z1 = geodetic_to_ecef(slon, slat, sh)
        X2, Y2, Z2 = geodetic_to_ecef(dlon, dlat, dh)
        a_mat.append([1.0, 0.0, 0.0,   X1,  0.0,  Z1, -Y1])
        a_mat.append([0.0, 1.0, 0.0,   Y1, -Z1,  0.0,  X1])
        a_mat.append([0.0, 0.0, 1.0,   Z1,  Y1, -X1,  0.0])
        b_vec.append(X2)
        b_vec.append(Y2)
        b_vec.append(Z2)

    from affine import lstsq_normal
    coeffs = lstsq_normal(a_mat, b_vec)
    dx, dy, dz, s_total, Dx, Dy, Dz = coeffs
    # s_total is the total scale factor (≈ 1 + scale_ppm*1e-6). coeffs[4:7]
    # are the rotation params Dx/Dy/Dz already in radians.
    scale_ppm = (s_total - 1.0) * 1e6
    return Helmert3D7(
        dx=dx, dy=dy, dz=dz,
        rx_arcsec=math.degrees(Dx) * 3600.0,
        ry_arcsec=math.degrees(Dy) * 3600.0,
        rz_arcsec=math.degrees(Dz) * 3600.0,
        scale_ppm=scale_ppm,
    )


def helmert_3d_residual_stats(
    params: Helmert3D7,
    controls: Sequence[tuple[float, float, float, float, float, float]],
) -> dict:
    """Residuals after applying params to controls, in meters.

    Each control is ``(src_lon, src_lat, src_h, dst_lon, dst_lat, dst_h)``.
    """
    if not controls:
        return {"count": 0}
    dists = []
    for slon, slat, sh, dlon, dlat, dh in controls:
        lon2, lat2, h2 = params.apply_geodetic(slon, slat, sh)
        # Convert residual in (lat, lon, h) to local meters
        # Approximate: 1° lat ~ 111 km, 1° lon ~ 111 km * cos(lat)
        dlat_m = (lat2 - dlat) * 111132.92
        dlon_m = (lon2 - dlon) * 111412.84 * math.cos(math.radians(dlat))
        dh_m = h2 - dh
        dists.append(math.sqrt(dlat_m * dlat_m + dlon_m * dlon_m + dh_m * dh_m))
    n = len(controls)
    return {
        "count": n,
        "max_dist_m": max(dists),
        "mean_dist_m": sum(dists) / n,
        "rms_dist_m": math.sqrt(sum(d * d for d in dists) / n),
    }


# ===== Fitting helpers (least-squares from control points) =====


def fit_helmert_2d_4param(
    controls: Sequence[tuple[float, float, float, float]],
) -> Helmert2D4:
    """Fit a 4-param similarity from (src_x, src_y, dst_x, dst_y) controls.

    Linear in (tx, ty, a, b) where a = s·cosθ, b = s·sinθ; we recover
    (s, θ) from (a, b) after the LSQ solve. Need >= 2 controls; 3+ is
    strongly preferred for redundancy / residual checks.
    """
    if len(controls) < 2:
        raise ValueError(f"need >= 2 controls for 4-param fit, got {len(controls)}")

    # Linear system: 2N equations, 4 unknowns (tx, ty, a, b)
    # [X_i]   [tx]   [a  -b] [x_i]
    # [Y_i] = [ty] + [b   a] [y_i]
    # Per row: X_i = tx + a·x_i - b·y_i
    #          Y_i = ty + b·x_i + a·y_i
    a_mat: list[list[float]] = []
    b_vec: list[float] = []
    for sx, sy, dx, dy in controls:
        a_mat.append([1.0, 0.0,  sx, -sy])
        a_mat.append([0.0, 1.0,  sy,  sx])
        b_vec.append(dx)
        b_vec.append(dy)

    from affine import lstsq_normal
    coeffs = lstsq_normal(a_mat, b_vec)
    tx, ty, a, b = coeffs
    s = math.hypot(a, b)
    theta = math.atan2(b, a)
    return Helmert2D4(tx=tx, ty=ty, rotation_rad=theta, scale=s - 1.0)


def helmert_2d_residual_stats(
    params,  # Helmert2D4 or Helmert2D5
    controls: Sequence[tuple[float, float, float, float]],
) -> dict:
    """Residuals after applying params to controls (in plane units)."""
    if not controls:
        return {"count": 0}
    dists = []
    for sx, sy, dx, dy in controls:
        X, Y = params.apply(sx, sy)
        dists.append(math.hypot(X - dx, Y - dy))
    n = len(controls)
    return {
        "count": n,
        "max_dist": max(dists),
        "mean_dist": sum(dists) / n,
        "rms_dist": math.sqrt(sum(d * d for d in dists) / n),
    }


# ===== JSON IO =====


def params_to_json(params) -> str:
    """Serialize any helmert param dataclass to JSON."""
    import json
    return json.dumps(params.to_dict(), indent=2, ensure_ascii=False)


def params_from_json(s: str):
    """Deserialize a JSON params dict back to the right dataclass."""
    import json
    d = json.loads(s)
    model = d.get("model", "")
    if model == "helmert2d_4param":
        return Helmert2D4.from_dict(d)
    if model == "helmert2d_5param":
        return Helmert2D5.from_dict(d)
    if model == "helmert3d_7param":
        return Helmert3D7.from_dict(d)
    raise ValueError(f"unknown helmert model: {model!r}")


# ===== Self-test =====


if __name__ == "__main__":
    import random
    # 4-param: exact recovery
    random.seed(42)
    true4 = Helmert2D4(tx=1234.5, ty=-678.9, rotation_rad=0.001234, scale=-5e-6)
    controls = []
    for _ in range(8):
        sx = 500000 + random.random() * 1000
        sy = 4500000 + random.random() * 1000
        dx, dy = true4.apply(sx, sy)
        # Add small noise to make it realistic
        dx += random.gauss(0, 0.01)
        dy += random.gauss(0, 0.01)
        controls.append((sx, sy, dx, dy))

    fit = fit_helmert_2d_4param(controls)
    stats = helmert_2d_residual_stats(fit, controls)
    print("4-param true :", true4.to_dict())
    print("4-param fit  :", fit.to_dict())
    print("residuals    :", stats)
    assert stats["max_dist"] < 0.05, f"expected < 5cm, got {stats['max_dist']}"
    print("OK: 4-param fit recovered within 5cm on noisy controls")

    # 7-param 3D: round-trip via ECEF (using the new .invert() method)
    h7 = Helmert3D7(dx=10.0, dy=-20.0, dz=5.0, rx_arcsec=0.5, ry_arcsec=-0.3, rz_arcsec=0.1, scale_ppm=2.0)
    # Beijing
    lon, lat, h = 116.391222, 39.903468, 50.0
    X, Y, Z = geodetic_to_ecef(lon, lat, h)
    Xp, Yp, Zp = h7.apply_ecef(X, Y, Z)
    lon2, lat2, h2 = ecef_to_geodetic(Xp, Yp, Zp)
    print(f"\n7-param 3D forward (WGS-84 near Beijing):")
    print(f"  before: lon={lon}, lat={lat}, h={h}")
    print(f"  after : lon={lon2:.9f}, lat={lat2:.9f}, h={h2:.6f}")
    # Then invert using the proper closed-form inverse
    inv = h7.invert()
    Xr, Yr, Zr = inv.apply_ecef(Xp, Yp, Zp)
    lon3, lat3, h3 = ecef_to_geodetic(Xr, Yr, Zr)
    print(f"  invert: lon={lon3:.9f}, lat={lat3:.9f}, h={h3:.6f}")
    assert abs(lon3 - lon) < 1e-9 and abs(lat3 - lat) < 1e-9, f"inversion round-trip: {lon3} vs {lon}"
    print("OK: 7-param ECEF forward + invert round-trips to < 1e-9 deg")

    # 7-param 3D: fit from control points and recover
    print("\n7-param 3D fit from synthetic control points:")
    true = Helmert3D7(dx=2.0, dy=-3.0, dz=1.5, rx_arcsec=0.2, ry_arcsec=-0.15, rz_arcsec=0.05, scale_ppm=0.8)
    src_controls = [
        (116.391222, 39.903468, 50.0),
        (121.473701, 31.230416, 30.0),
        (113.264385, 23.129110, 25.0),
        (108.939800, 34.341660, 400.0),
        (102.832892, 24.880095, 1900.0),
    ]
    geodetic_controls = []
    for slon, slat, sh in src_controls:
        dlon, dlat, dh = true.apply_geodetic(slon, slat, sh)
        geodetic_controls.append((slon, slat, sh, dlon, dlat, dh))
    fit = fit_helmert_3d_7param(geodetic_controls)
    stats = helmert_3d_residual_stats(fit, geodetic_controls)
    print(f"  true  : dx={true.dx}, dy={true.dy}, dz={true.dz}, rx={true.rx_arcsec}, ry={true.ry_arcsec}, rz={true.rz_arcsec}, scale_ppm={true.scale_ppm}")
    print(f"  fit   : dx={fit.dx:.4f}, dy={fit.dy:.4f}, dz={fit.dz:.4f}, rx={fit.rx_arcsec:.5f}, ry={fit.ry_arcsec:.5f}, rz={fit.rz_arcsec:.5f}, scale_ppm={fit.scale_ppm:.5f}")
    print(f"  stats : {stats}")
    assert stats["max_dist_m"] < 1.0, f"expected < 1m residual, got {stats['max_dist_m']}"
    print("OK: 7-param fit recovers the true transform on noiseless controls to < 1m")
