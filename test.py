"""
test.py — 10+ test cases covering all 4 methods of china-coord-transform.

Run with: python test.py

Each test prints PASS/FAIL with a one-line summary. Exits non-zero on any
failure so CI can detect regressions.
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import traceback
from pathlib import Path

# Make sibling modules importable when run from the skill directory
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


# ===== Result tracking =====


_PASSED: list[str] = []
_FAILED: list[tuple[str, str]] = []


def _check(condition: bool, name: str, detail: str = "") -> bool:
    if condition:
        _PASSED.append(name)
        print(f"  PASS  {name}" + (f"  ({detail})" if detail else ""))
        return True
    _FAILED.append((name, detail))
    print(f"  FAIL  {name}  -- {detail}")
    return False


def _approx(a: float, b: float, tol: float, msg: str = "") -> bool:
    if abs(a - b) <= tol:
        return True
    raise AssertionError(f"{msg}: expected |{a} - {b}| <= {tol}, got {abs(a - b):.6g}")


def _haversine(lon1, lat1, lon2, lat2) -> float:
    R = 6371008.8
    rl1, rl2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rl1) * math.cos(rl2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ===== Test 1: Method 1 single-point (the canonical Tiananmen case) =====


def test_1_method1_tiananmen():
    print("\n[Test 1] Method 1: GCJ-02 -> WGS-84 (Tiananmen)")
    from transform import gcj2wgs
    # Input: Amap coordinate-pick result
    gcj_lon, gcj_lat = 116.397594, 39.904949
    wgs_lon, wgs_lat = gcj2wgs(gcj_lon, gcj_lat)
    ref_lon, ref_lat = 116.391222, 39.903468
    d = _haversine(ref_lon, ref_lat, wgs_lon, wgs_lat)
    _check(
        d < 20.0,
        "1.1 Tiananmen within 20m of Google Earth",
        f"dist = {d:.2f} m",
    )


# ===== Test 2: Method 1 boundary - outside China passes through unchanged =====


def test_2_method1_outside_china():
    print("\n[Test 2] Method 1: outside-China coordinates pass through unchanged")
    from transform import wgs2gcj, gcj2wgs
    # Tokyo
    lon, lat = 139.6917, 35.6895
    out = wgs2gcj(lon, lat)
    _check(
        out == (lon, lat),
        "2.1 Tokyo wgs2gcj is identity",
        f"out = {out}",
    )
    # New York
    lon, lat = -74.0060, 40.7128
    out = gcj2wgs(lon, lat)
    _check(
        out == (lon, lat),
        "2.2 NYC gcj2wgs is identity",
        f"out = {out}",
    )
    # Just outside the bounding box
    out = wgs2gcj(60.0, 30.0)
    _check(
        out == (60.0, 30.0),
        "2.3 just-outside wgs2gcj is identity",
        f"out = {out}",
    )


# ===== Test 3: Method 1 round-trip WGS -> GCJ -> WGS is lossy but bounded =====


def test_3_method1_roundtrip():
    print("\n[Test 3] Method 1: round-trip wgs -> gcj -> wgs is lossy but bounded")
    from transform import wgs2gcj, gcj2wgs
    # Spot-check across China
    cases = [
        (116.391222, 39.903468, "Beijing"),
        (121.473701, 31.230416, "Shanghai"),
        (113.264385, 23.129110, "Guangzhou"),
        (108.939800, 34.341660, "Xian"),
        (102.832892, 24.880095, "Kunming"),
        (87.616823, 43.792560, "Urumqi"),
    ]
    max_err = 0.0
    for wgs_lon, wgs_lat, name in cases:
        gcj = wgs2gcj(wgs_lon, wgs_lat)
        back = gcj2wgs(*gcj)
        d = _haversine(wgs_lon, wgs_lat, back[0], back[1])
        max_err = max(max_err, d)
    _check(
        max_err < 5.0,
        "3.1 round-trip within 5m everywhere (for WGS in China)",
        f"max_err = {max_err:.3f} m",
    )


# ===== Test 4: Method 1 dispatcher & all 6 direction combos =====


def test_4_method1_dispatcher():
    print("\n[Test 4] Method 1: dispatcher & 6 direction combos")
    from transform import convert, SUPPORTED_SYSTEMS
    _check(
        len(SUPPORTED_SYSTEMS) == 3,
        "4.1 supported systems = {wgs84, gcj02, bd09}",
        f"got {SUPPORTED_SYSTEMS}",
    )
    # Direct direction: wgs84 -> gcj02 should move the point
    a = convert(116.391222, 39.903468, "wgs84", "gcj02")
    _check(
        abs(a[0] - 116.391222) > 1e-4 and abs(a[1] - 39.903468) > 1e-4,
        "4.2 wgs84 -> gcj02 moves the point",
        f"got {a}",
    )
    # Idempotent: same src/dst is identity
    c = convert(116.4, 39.9, "gcj02", "gcj02")
    _check(
        c == (116.4, 39.9),
        "4.3 same src/dst is identity",
        f"got {c}",
    )
    # Unknown system raises
    raised = False
    try:
        convert(1.0, 2.0, "bogus", "wgs84")
    except ValueError:
        raised = True
    _check(
        raised,
        "4.4 unknown src system raises ValueError",
    )
    # Case insensitive
    a = convert(116.4, 39.9, "GCJ02", "WGS84")
    _check(
        isinstance(a, tuple) and len(a) == 2,
        "4.5 case-insensitive system names",
        f"got {a}",
    )
    # Same for dst typo
    raised = False
    try:
        convert(1.0, 2.0, "wgs84", "bogus")
    except ValueError:
        raised = True
    _check(raised, "4.6 unknown dst system raises ValueError")


# ===== Test 5: Method 2 affine with minimum (3) controls =====


def test_5_method2_affine_minimum():
    print("\n[Test 5] Method 2: affine fit with minimum 3 controls")
    from affine import fit_affine
    # 3 points, perfect affine
    a1, b1, c1, a2, b2, c2 = 1.0, 0.0, 0.0, 0.0, 1.0, 0.0  # identity
    controls = []
    for slon, slat in [(100.0, 30.0), (101.0, 30.0), (100.0, 31.0)]:
        dlon = a1 * slon + b1 * slat + c1
        dlat = a2 * slon + b2 * slat + c2
        controls.append((slon, slat, dlon, dlat))
    p = fit_affine(controls)
    _check(
        abs(p.a1 - 1.0) < 1e-9 and abs(p.b1) < 1e-9 and abs(p.a2) < 1e-9 and abs(p.b2 - 1.0) < 1e-9,
        "5.1 identity fit recovered exactly",
        f"a1={p.a1}, b1={p.b1}, a2={p.a2}, b2={p.b2}",
    )
    # Should raise on < 3
    raised = False
    try:
        fit_affine([(1, 1, 2, 2)])
    except ValueError:
        raised = True
    _check(raised, "5.2 < 3 controls raises")


# ===== Test 6: Method 3 2D Helmert round-trip with realistic params =====


def test_6_method3_helmert_2d():
    print("\n[Test 6] Method 3: 2D Helmert 4-param round-trip")
    from helmert import Helmert2D4
    p = Helmert2D4(tx=1000.0, ty=2000.0, rotation_rad=math.radians(0.5), scale=-1e-5)
    srcs = [(500000.0, 4500000.0), (500500.0, 4500500.0), (501000.0, 4501000.0)]
    outs = [p.apply(x, y) for x, y in srcs]
    # Round-trip via apply again with inverse params
    inv = Helmert2D4(tx=-p.tx, ty=-p.ty, rotation_rad=-p.rotation_rad, scale=-p.scale / (1 + p.scale))
    # Note: exact inverse for similarity: s' = 1/s - 1, theta' = -theta
    inv2 = Helmert2D4(
        tx=-(p.tx * math.cos(p.rotation_rad) + p.ty * math.sin(p.rotation_rad)) / (1 + p.scale),
        ty=-(-p.tx * math.sin(p.rotation_rad) + p.ty * math.cos(p.rotation_rad)) / (1 + p.scale),
        rotation_rad=-p.rotation_rad,
        scale=-p.scale / (1 + p.scale),
    )
    for (x, y), (X, Y) in zip(srcs, outs):
        rx, ry = inv2.apply(X, Y)
        _approx(rx, x, 1e-6, f"round-trip lon at ({x}, {y})")
        _approx(ry, y, 1e-6, f"round-trip lat at ({x}, {y})")
    _check(True, "6.1 2D Helmert round-trip preserves coords to < 1µm")


# ===== Test 7: Method 3 3D 7-param geodetic round-trip =====


def test_7_method3_helmert_3d():
    print("\n[Test 7] Method 3: 3D Helmert 7-param (Bursa-Wolf) geodetic round-trip")
    from helmert import Helmert3D7
    p = Helmert3D7(dx=10.0, dy=-20.0, dz=5.0, rx_arcsec=0.5, ry_arcsec=-0.3, rz_arcsec=0.1, scale_ppm=2.0)
    inv = p.invert()
    for lon, lat, h in [(116.391222, 39.903468, 50.0), (-74.0, 40.7, 0.0), (139.69, 35.69, 100.0)]:
        lon2, lat2, h2 = p.apply_geodetic(lon, lat, h)
        lon3, lat3, h3 = inv.apply_geodetic(lon2, lat2, h2)
        _approx(lon3, lon, 1e-9, f"3D round-trip lon at ({lon}, {lat})")
        _approx(lat3, lat, 1e-9, f"3D round-trip lat at ({lon}, {lat})")
        # h round-trip is limited by the Bowring geodetic iteration (~0.1mm)
        _approx(h3, h, 1e-3, f"3D round-trip h at ({lon}, {lat})")
    _check(True, "7.1 3D Helmert round-trip preserves geodetic (h < 1mm) via .invert()")

    # Bonus: round-trip without h
    lon2, lat2, _ = p.apply_geodetic(116.0, 30.0, 0.0)
    lon3, lat3, _ = inv.apply_geodetic(lon2, lat2, 0.0)
    _approx(lon3, 116.0, 1e-9, "round-trip lon h=0")
    _approx(lat3, 30.0, 1e-9, "round-trip lat h=0")

    # 7-param fit from control points (noisy, then noiseless)
    from helmert import fit_helmert_3d_7param, helmert_3d_residual_stats
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
    _check(
        stats["max_dist_m"] < 1e-3,
        "7.2 7-param fit recovers true transform on noiseless controls to < 1mm",
        f"max={stats['max_dist_m']*1000:.3f}mm",
    )


# ===== Test 8: Method 4 GeoJSON all geometry types =====


def test_8_method4_geojson():
    print("\n[Test 8] Method 4: GeoJSON Point/LineString/Polygon/Multi/MultiPolygon")
    from vector import (
        convert_geojson_file, read_geojson, _count_geometries,
    )
    from transform import gcj2wgs
    sample = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [116.397594, 39.904949]},
             "properties": {"name": "Tiananmen"}},
            {"type": "Feature",
             "geometry": {"type": "MultiPoint",
                          "coordinates": [[116.40, 39.90], [116.41, 39.91]]},
             "properties": {"name": "multi-pt"}},
            {"type": "Feature",
             "geometry": {"type": "LineString",
                          "coordinates": [[116.40, 39.91], [116.42, 39.93]]},
             "properties": {"name": "line"}},
            {"type": "Feature",
             "geometry": {"type": "MultiLineString",
                          "coordinates": [[[116.40, 39.91], [116.42, 39.93]],
                                          [[116.50, 39.95], [116.52, 39.97]]]},
             "properties": {"name": "multi-line"}},
            {"type": "Feature",
             "geometry": {"type": "Polygon",
                          "coordinates": [[[116.40, 39.90], [116.42, 39.90],
                                          [116.42, 39.92], [116.40, 39.92],
                                          [116.40, 39.90]]]},
             "properties": {"name": "poly"}},
            {"type": "Feature",
             "geometry": {"type": "MultiPolygon",
                          "coordinates": [
                              [[  # Polygon 1, ring 1
                                  [116.40, 39.90], [116.41, 39.90],
                                  [116.41, 39.91], [116.40, 39.91],
                                  [116.40, 39.90],
                              ]],
                              [[  # Polygon 2, ring 1
                                  [116.50, 39.95], [116.51, 39.95],
                                  [116.51, 39.96], [116.50, 39.96],
                                  [116.50, 39.95],
                              ]],
                          ]},
             "properties": {"name": "multi-poly"}},
        ],
    }
    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "in.geojson")
        out_path = os.path.join(td, "out.geojson")
        from vector import write_geojson
        write_geojson(sample, in_path)
        n = convert_geojson_file(in_path, out_path, gcj2wgs)
        out = read_geojson(out_path)
        _check(n == 6, "8.1 counted 6 geometries", f"got {n}")
        _check(_count_geometries(out) == 6, "8.2 round-trip counts match")
        # Spot-check a coord was moved
        first = out["features"][0]["geometry"]["coordinates"]
        expected_lon, expected_lat = gcj2wgs(116.397594, 39.904949)
        _approx(first[0], expected_lon, 1e-6, "Tiananmen lon")
        _approx(first[1], expected_lat, 1e-6, "Tiananmen lat")


# ===== Test 9: Method 4 Shapefile (only if pyshp is available) =====


def test_9_method4_shp():
    print("\n[Test 9] Method 4: Shapefile round-trip (skipped if pyshp missing)")
    try:
        import shapefile  # noqa
    except ImportError:
        print("  SKIP  pyshp not installed")
        return
    from vector import convert_shp_file
    from transform import wgs2gcj
    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "in.shp")
        out_path = os.path.join(td, "out.shp")
        # Write a small SHP directly
        w = shapefile.Writer(in_path)
        w.field("name", "C", size=40)
        w.point(116.40, 39.90)
        w.record("pt1")
        w.point(116.41, 39.91)
        w.record("pt2")
        w.point(116.42, 39.92)
        w.record("pt3")
        w.close()
        n = convert_shp_file(in_path, out_path, wgs2gcj)
        _check(n == 3, "9.1 SHP 3 points converted", f"got {n}")
        # Read back
        from vector import read_shp_records
        out = read_shp_records(out_path)
        _check(len(out) == 3, "9.2 SHP round-trip count = 3")
        # The first point's coordinates should be GCJ-02 (moved) not WGS-84
        first = out[0]["geometry"]["coordinates"]
        _check(
            first[0] > 116.40 and first[0] < 116.42,
            "9.3 SHP point 1 lon is in expected GCJ-02 range",
            f"got {first}",
        )


# ===== Test 10: CLI end-to-end batch + fit + vector =====


def test_10_cli_end_to_end():
    print("\n[Test 10] CLI: batch / fit / vector end-to-end")
    import subprocess
    py = sys.executable
    skill_dir = str(HERE)
    with tempfile.TemporaryDirectory() as td:
        in_csv = os.path.join(td, "in.csv")
        out_csv = os.path.join(td, "out.csv")
        params_json = os.path.join(td, "params.json")
        # 3-point CSV
        Path(in_csv).write_text(
            "name,lon,lat\nA,116.40,39.90\nB,116.41,39.91\nC,116.42,39.92\n",
            encoding="utf-8",
        )
        # 3-point control CSV (non-collinear)
        controls_csv = os.path.join(td, "controls.csv")
        Path(controls_csv).write_text(
            "src_lon,src_lat,dst_lon,dst_lat\n"
            "116.40,39.90,116.40,39.90\n"
            "116.42,39.90,116.42,39.90\n"
            "116.40,39.92,116.40,39.92\n",
            encoding="utf-8",
        )
        # batch with no params
        r = subprocess.run(
            [py, os.path.join(skill_dir, "cli.py"), "batch",
             "--from", "gcj02", "--to", "wgs84",
             "--input", in_csv, "--output", out_csv],
            capture_output=True, text=True, timeout=30,
        )
        _check(r.returncode == 0, "10.1 cli batch (no params) exits 0", r.stderr)
        out_lines = Path(out_csv).read_text(encoding="utf-8").strip().splitlines()
        _check(len(out_lines) == 4, "10.2 batch wrote 3 rows + header", f"got {len(out_lines)}")
        # fit affine
        r = subprocess.run(
            [py, os.path.join(skill_dir, "cli.py"), "fit",
             "--controls", controls_csv,
             "--model", "affine",
             "--output", params_json],
            capture_output=True, text=True, timeout=30,
        )
        _check(r.returncode == 0, "10.3 cli fit affine exits 0", r.stderr)
        params_data = Path(params_json).read_text(encoding="utf-8")
        _check('"model": "affine"' in params_data, "10.4 fit wrote affine JSON")
        # batch with params
        out_csv2 = os.path.join(td, "out2.csv")
        r = subprocess.run(
            [py, os.path.join(skill_dir, "cli.py"), "batch",
             "--from", "gcj02", "--to", "wgs84",
             "--input", in_csv, "--output", out_csv2,
             "--params", params_json],
            capture_output=True, text=True, timeout=30,
        )
        _check(r.returncode == 0, "10.5 cli batch with params exits 0", r.stderr)
        # vector on a small geojson
        in_geo = os.path.join(td, "in.geojson")
        out_geo = os.path.join(td, "out.geojson")
        Path(in_geo).write_text(
            '{"type":"FeatureCollection","features":['
            '{"type":"Feature","geometry":{"type":"Point","coordinates":[116.40,39.90]},'
            '"properties":{"name":"A"}}]}',
            encoding="utf-8",
        )
        r = subprocess.run(
            [py, os.path.join(skill_dir, "cli.py"), "vector",
             "--input", in_geo, "--output", out_geo,
             "--from", "gcj02", "--to", "wgs84"],
            capture_output=True, text=True, timeout=30,
        )
        _check(r.returncode == 0, "10.6 cli vector exits 0", r.stderr)
        out_geo_data = Path(out_geo).read_text(encoding="utf-8")
        _check("FeatureCollection" in out_geo_data, "10.7 vector wrote geojson")


# ===== Test 11: Performance / scale - 1k points =====


def test_11_perf_batch():
    print("\n[Test 11] Performance: 1000 points batch")
    import time
    from transform import gcj2wgs
    pts = []
    for i in range(1000):
        lon = 100 + (i % 50) * 0.1
        lat = 30 + (i // 50) * 0.1
        pts.append((lon, lat))
    t0 = time.perf_counter()
    out = [gcj2wgs(lon, lat) for lon, lat in pts]
    dt = time.perf_counter() - t0
    _check(
        dt < 2.0,
        "11.1 1000-point batch < 2s",
        f"{dt*1000:.0f} ms",
    )
    _check(
        all(isinstance(p, tuple) and len(p) == 2 for p in out),
        "11.2 all 1000 results are 2-tuples",
    )


# ===== Test 12: Adversarial inputs - corrupt / empty / missing =====


def test_12_adversarial():
    print("\n[Test 12] Adversarial: corrupt / empty / wrong-shape inputs")
    from transform import convert
    # NaN (use math.isnan since NaN != NaN by IEEE 754)
    out = convert(float("nan"), float("nan"), "gcj02", "wgs84")
    _check(
        math.isnan(out[0]) and math.isnan(out[1]),
        "12.1 NaN passes through (NaN in -> NaN out)",
        f"got {out}",
    )
    # Inf
    out = convert(float("inf"), float("inf"), "wgs84", "gcj02")
    _check(
        math.isinf(out[0]) and math.isinf(out[1]),
        "12.2 Inf passes through (not in China box)",
        f"got {out}",
    )
    # Outside the China box but in mainland coords (should be identity)
    out = convert(60.0, 30.0, "wgs84", "gcj02")
    _check(
        out == (60.0, 30.0),
        "12.3 outside-China is identity (lat=30 in India is outside box)",
        f"got {out}",
    )
    # Vector: empty FeatureCollection
    from vector import write_geojson, convert_geojson_file, read_geojson
    with tempfile.TemporaryDirectory() as td:
        ip = os.path.join(td, "in.geojson")
        op = os.path.join(td, "out.geojson")
        write_geojson({"type": "FeatureCollection", "features": []}, ip)
        n = convert_geojson_file(ip, op, lambda x, y: (x, y))
        _check(n == 0, "12.4 empty FeatureCollection -> 0 geometries", f"got {n}")
        out_obj = read_geojson(op)
        _check(out_obj["features"] == [], "12.5 empty input -> empty output")


# ===== Test 13: CSV with BOM and Chinese chars =====


def test_13_csv_bom_chinese():
    print("\n[Test 13] Robustness: CSV with UTF-8 BOM and Chinese headers")
    import subprocess
    py = sys.executable
    with tempfile.TemporaryDirectory() as td:
        in_csv = os.path.join(td, "in.csv")
        # Write with BOM
        with open(in_csv, "wb") as f:
            f.write(b'\xef\xbb\xbfname,lon,lat\n')
            f.write("地点,116.40,39.90\n".encode("utf-8"))
        out_csv = os.path.join(td, "out.csv")
        r = subprocess.run(
            [py, str(HERE / "cli.py"), "batch",
             "--from", "gcj02", "--to", "wgs84",
             "--input", in_csv, "--output", out_csv],
            capture_output=True, text=True, timeout=30,
        )
        _check(r.returncode == 0, "13.1 cli handles BOM CSV", r.stderr)
        out_text = Path(out_csv).read_text(encoding="utf-8")
        _check("地点" in out_text, "13.2 Chinese name preserved", f"out={out_text!r}")


# ===== Test 14: Cross-method composition (vector with local affine params) =====


def test_14_vector_with_affine():
    print("\n[Test 14] Vector + local affine: GeoJSON transformed with fitted params")
    from affine import fit_affine
    from vector import write_geojson, convert_geojson_file, read_geojson
    # Generate a synthetic affine "ground truth" with non-collinear points
    a, b, c, d, e, f = 1.0001, 0.0, -0.0001, 0.0, 1.0001, -0.0001
    # Triangle of non-collinear src pts
    src_pts = [(116.40, 39.90), (116.50, 39.90), (116.40, 40.00), (116.50, 40.00)]
    controls = []
    for s_lon, s_lat in src_pts:
        d_lon = a * s_lon + b * s_lat + c
        d_lat = d * s_lon + e * s_lat + f
        controls.append((s_lon, s_lat, d_lon, d_lat))
    affine = fit_affine(controls)

    # Build a small geojson with the dst coords; transform with affine; expect to recover src
    sample = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": list(affine.apply(116.40, 39.90))},
             "properties": {}},
        ],
    }
    with tempfile.TemporaryDirectory() as td:
        ip = os.path.join(td, "in.geojson")
        op = os.path.join(td, "out.geojson")
        write_geojson(sample, ip)
        # Build the inverse manually
        from affine import AffineParams
        det = a * e - b * d
        inv = AffineParams(
            a1= e / det,
            b1=-b / det,
            c1= (b * f - e * c) / det,
            a2=-d / det,
            b2= a / det,
            c2= (d * c - a * f) / det,
        )
        n = convert_geojson_file(ip, op, inv.apply)
        _check(n == 1, "14.1 vector with affine applied", f"got {n}")
        out = read_geojson(op)
        back = out["features"][0]["geometry"]["coordinates"]
        _approx(back[0], 116.40, 1e-6, "vector+affine round-trip lon")
        _approx(back[1], 39.90, 1e-6, "vector+affine round-trip lat")


# ===== Test 15: BD-09 vs GCJ-02 vs WGS-84 composition =====


def test_15_bd_gcj_wgs_chain():
    print("\n[Test 15] Method 1: BD-09 -> GCJ-02 -> WGS-84 vs BD-09 -> WGS-84")
    from transform import bd2gcj, gcj2wgs, bd2wgs
    # Tiananmen BD-09 (Amap value + BD-09 offset)
    bd_lon, bd_lat = 116.403839, 39.915406
    chain = gcj2wgs(*bd2gcj(bd_lon, bd_lat))
    direct = bd2wgs(bd_lon, bd_lat)
    d = _haversine(chain[0], chain[1], direct[0], direct[1])
    _check(
        d < 1.0,
        "15.1 chain (BD->GCJ->WGS) matches direct (BD->WGS)",
        f"chain-drift = {d:.6f} m",
    )


# ===== Runner =====


ALL_TESTS = [
    test_1_method1_tiananmen,
    test_2_method1_outside_china,
    test_3_method1_roundtrip,
    test_4_method1_dispatcher,
    test_5_method2_affine_minimum,
    test_6_method3_helmert_2d,
    test_7_method3_helmert_3d,
    test_8_method4_geojson,
    test_9_method4_shp,
    test_10_cli_end_to_end,
    test_11_perf_batch,
    test_12_adversarial,
    test_13_csv_bom_chinese,
    test_14_vector_with_affine,
    test_15_bd_gcj_wgs_chain,
]


def main():
    for t in ALL_TESTS:
        try:
            t()
        except Exception as e:
            tb = traceback.format_exc().splitlines()[-3:]
            _FAILED.append((t.__name__, f"{type(e).__name__}: {e}"))
            print(f"  EXCEPTION in {t.__name__}: {e}")
            for line in tb:
                print(f"    {line}")

    print("\n" + "=" * 60)
    print(f"Results: {len(_PASSED)} passed, {len(_FAILED)} failed")
    if _FAILED:
        print("\nFAILURES:")
        for name, detail in _FAILED:
            print(f"  - {name}: {detail}")
    print("=" * 60)
    return 0 if not _FAILED else 1


if __name__ == "__main__":
    raise SystemExit(main())
