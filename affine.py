"""
affine.py — Method 2: local affine / polynomial transform fitted from control points.

Pure-Python (no numpy / scipy) so the skill only needs the python interpreter.

Use when you need sub-meter accuracy in a small area, or when the public
GCJ-02 formula gives too much error for your data. Provide >= 3 control
points where you know both the GCJ-02 (or BD-09) and the WGS-84 coordinates,
and we solve a 2D affine transform:

    wgs_lon = a1 * src_lon + b1 * src_lat + c1
    wgs_lat = a2 * src_lon + b2 * src_lat + c2

The fit is least-squares; with N >= 6 well-spread points you typically get
< 1m residual in a 5-10 km box.

If you want a second-order (polynomial) fit to capture non-linear local
distortion, see ``fit_polynomial`` below. Most users only need affine.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Sequence


# ===== Pure-Python dense linear solver (Gauss-Jordan with partial pivoting) =====


def solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    """Solve Ax = b with Gauss-Jordan elimination. ``a`` is NxN, ``b`` is N.

    Raises ValueError if the system is singular or non-square.
    """
    n = len(a)
    if any(len(row) != n for row in a):
        raise ValueError("matrix A must be square")
    if len(b) != n:
        raise ValueError("vector b length must match matrix A")

    # Augment into a copy
    m = [row[:] + [b[i]] for i, row in enumerate(a)]

    for col in range(n):
        # Partial pivot
        pivot = col
        for r in range(col + 1, n):
            if abs(m[r][col]) > abs(m[pivot][col]):
                pivot = r
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError("singular matrix: cannot solve")
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]

        # Normalize pivot row
        pv = m[col][col]
        for j in range(col, n + 1):
            m[col][j] /= pv

        # Eliminate
        for r in range(n):
            if r == col:
                continue
            factor = m[r][col]
            if factor == 0.0:
                continue
            for j in range(col, n + 1):
                m[r][j] -= factor * m[col][j]

    return [m[i][n] for i in range(n)]


def lstsq_normal(A: list[list[float]], b: list[float]) -> list[float]:
    """Solve least-squares A x = b via the normal equations (A^T A) x = A^T b.

    Suitable for small (N <= ~12) dense systems — exactly our use case here
    (6 parameters for affine, 6 for polynomial). For ill-conditioned data
    you should pre-center and scale, but for a few km-scale box the raw
    numbers are fine.
    """
    n = len(A[0]) if A else 0
    if not A or any(len(row) != n for row in A):
        raise ValueError("A must be a non-empty matrix with uniform column count")
    m = len(A)
    if len(b) != m:
        raise ValueError("b length must match A row count")

    # A^T A (n x n)
    ata = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            s = 0.0
            for r in range(m):
                s += A[r][i] * A[r][j]
            ata[i][j] = s

    # A^T b (n)
    atb = [0.0] * n
    for i in range(n):
        s = 0.0
        for r in range(m):
            s += A[r][i] * b[r]
        atb[i] = s

    return solve_linear(ata, atb)


# ===== Affine model =====


@dataclass
class AffineParams:
    """2D affine parameters."""

    a1: float
    b1: float
    c1: float
    a2: float
    b2: float
    c2: float

    def apply(self, lon: float, lat: float) -> tuple[float, float]:
        return (
            self.a1 * lon + self.b1 * lat + self.c1,
            self.a2 * lon + self.b2 * lat + self.c2,
        )

    def to_dict(self) -> dict:
        return {
            "a1": self.a1, "b1": self.b1, "c1": self.c1,
            "a2": self.a2, "b2": self.b2, "c2": self.c2,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AffineParams":
        return cls(
            a1=d["a1"], b1=d["b1"], c1=d["c1"],
            a2=d["a2"], b2=d["b2"], c2=d["c2"],
        )


def fit_affine(controls: Sequence[tuple[float, float, float, float]]) -> AffineParams:
    """Fit a 2D affine from a list of (src_lon, src_lat, dst_lon, dst_lat).

    Each control point contributes 2 rows to the design matrix:
      [slon, slat, 1, 0,   0,   0  ] -> dlon
      [0,    0,    0, slon, slat, 1] -> dlat

    Raises ValueError if there are fewer than 3 controls or the system
    is singular.
    """
    if len(controls) < 3:
        raise ValueError(f"need at least 3 control points, got {len(controls)}")

    A: list[list[float]] = []
    b: list[float] = []
    for slon, slat, dlon, dlat in controls:
        A.append([slon, slat, 1.0, 0.0, 0.0, 0.0])
        A.append([0.0, 0.0, 0.0, slon, slat, 1.0])
        b.append(dlon)
        b.append(dlat)

    coeffs = lstsq_normal(A, b)
    a1, b1, c1, a2, b2, c2 = coeffs
    return AffineParams(a1, b1, c1, a2, b2, c2)


def affine_residual_stats(
    params: AffineParams,
    controls: Sequence[tuple[float, float, float, float]],
) -> dict:
    """Return per-point and aggregate residuals in degrees and meters.

    Distances use a flat-earth approximation at the mean latitude of the
    control set — accurate to < 1% over a 10 km box.
    """
    if not controls:
        return {"count": 0}

    dlon_diffs = []
    dlat_diffs = []
    dists = []
    mean_lat = sum(c[1] for c in controls) / len(controls)
    meters_per_deg_lat = 111_132.92
    meters_per_deg_lon = 111_412.84 * math.cos(math.radians(mean_lat))

    for slon, slat, dlon, dlat in controls:
        plon, plat = params.apply(slon, slat)
        dl = (plon - dlon) * meters_per_deg_lon
        dp = (plat - dlat) * meters_per_deg_lat
        dlon_diffs.append(plon - dlon)
        dlat_diffs.append(plat - dlat)
        dists.append(math.hypot(dl, dp))

    n = len(controls)
    return {
        "count": n,
        "mean_lon_residual_deg": sum(dlon_diffs) / n,
        "mean_lat_residual_deg": sum(dlat_diffs) / n,
        "max_dist_m": max(dists),
        "mean_dist_m": sum(dists) / n,
        "rms_dist_m": math.sqrt(sum(d * d for d in dists) / n),
        "meters_per_deg_lon": meters_per_deg_lon,
        "meters_per_deg_lat": meters_per_deg_lat,
    }


# ===== Quadratic polynomial (optional) =====


def fit_polynomial(
    controls: Sequence[tuple[float, float, float, float]],
) -> dict:
    """Fit a 2D quadratic polynomial. Returns a dict with keys ``lon_coef``
    and ``lat_coef``, each a length-6 list ordered as
    [1, x, y, x^2, y^2, xy].

    Use when residual of an affine fit is dominated by a trend. Need >= 6
    controls; avoid extrapolating outside the control bbox.
    """
    if len(controls) < 6:
        raise ValueError(f"need at least 6 control points for polynomial, got {len(controls)}")

    cols = 6
    A: list[list[float]] = []
    b: list[float] = []
    for slon, slat, dlon, dlat in controls:
        row = [1.0, slon, slat, slon * slon, slat * slat, slon * slat]
        A.append(row + [0.0] * cols)
        A.append([0.0] * cols + row)
        b.append(dlon)
        b.append(dlat)

    coeffs = lstsq_normal(A, b)
    return {
        "lon_coef": coeffs[:cols],
        "lat_coef": coeffs[cols:],
    }


def apply_polynomial(p: dict, lon: float, lat: float) -> tuple[float, float]:
    row = [1.0, lon, lat, lon * lon, lat * lat, lon * lat]
    out_lon = sum(c * r for c, r in zip(p["lon_coef"], row))
    out_lat = sum(c * r for c, r in zip(p["lat_coef"], row))
    return out_lon, out_lat


# ===== IO helpers =====


def params_to_json(params: AffineParams) -> str:
    return json.dumps(params.to_dict(), indent=2, ensure_ascii=False)


def params_from_json(s: str) -> AffineParams:
    return AffineParams.from_dict(json.loads(s))


if __name__ == "__main__":
    # Sanity: affine can recover an exact affine transform with 3+ points
    true = AffineParams(1.1, 0.05, 0.001, -0.04, 1.1, -0.002)
    import random
    random.seed(0)
    controls = []
    for _ in range(6):
        slon = 100 + random.random() * 5
        slat = 30 + random.random() * 5
        dlon, dlat = true.apply(slon, slat)
        controls.append((slon, slat, dlon, dlat))

    fit = fit_affine(controls)
    print("true  :", true)
    print("fitted:", fit)
    stats = affine_residual_stats(fit, controls)
    print("residuals:", stats)
    assert stats["max_dist_m"] < 1e-6, "affine fit should be exact on noiseless controls"
    print("OK: affine recovers the true transform exactly")
