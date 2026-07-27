#!/usr/bin/env python3
"""
cli.py — command-line interface for china-coord-transform.

Subcommands:
  convert          Single point, prints the converted (lon, lat) on stdout
  batch            CSV in / CSV out (columns: lon, lat, plus any extras)
  fit              Read a control-point CSV, fit affine / helmert params
  vector           Apply transform to a GeoJSON or Shapefile (SHP needs pyshp)

Examples:
  # Method 1: public GCJ-02 formula
  python cli.py convert --from gcj02 --to wgs84 --lon 116.397594 --lat 39.904949
  python cli.py batch   --from bd09  --to wgs84 --input in.csv --output out.csv

  # Method 2: local affine from control points
  python cli.py fit     --controls controls.csv --output params.json
  python cli.py batch   --from gcj02 --to wgs84 --input in.csv --output out.csv \\
                       --params params.json

  # Method 3: 4-parameter Helmert on plane coordinates
  python cli.py fit     --controls plane_controls.csv --model helmert-4param \\
                       --output helmert.json
  python cli.py batch   --from custom --to wgs84 --input in.csv --output out.csv \\
                       --params helmert.json

  # Method 4: vector file (SHP needs `pip install pyshp`)
  python cli.py vector  --input in.geojson --output out.geojson \\
                       --from gcj02 --to wgs84
  python cli.py vector  --input in.shp --output out.shp \\
                       --from bd09 --to wgs84 --params params.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from transform import convert as convert_one, SUPPORTED_SYSTEMS

__version__ = "0.2.0"
USER_AGENT = f"china-coord-transform/{__version__}"


def write_qa_summary(qa_path, args, src_lon, src_lat, dst_lon, dst_lat, params_used):
    """Write a JSON run-summary sidecar to qa_path (Phase 5 optimization)."""
    qa = {
        "skill": "china-coord-transform",
        "command": "convert",
        "version": __version__,
        "user_agent": USER_AGENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "args": vars(args),
        "input": {"lon": src_lon, "lat": src_lat, "src_system": args.frm},
        "output": {"lon": dst_lon, "lat": dst_lat, "dst_system": args.to},
        "params_used": params_used,
    }
    qa_p = Path(qa_path)
    qa_p.parent.mkdir(parents=True, exist_ok=True)
    with open(qa_p, "w", encoding="utf-8") as f:
        json.dump(qa, f, ensure_ascii=False, indent=2, default=str)
from affine import (
    AffineParams,
    fit_affine,
    affine_residual_stats,
    fit_polynomial,
    apply_polynomial,
)
from helmert import (
    Helmert2D4,
    Helmert2D5,
    Helmert3D7,
    fit_helmert_2d_4param,
    helmert_2d_residual_stats,
    geodetic_to_ecef,
    ecef_to_geodetic,
    params_from_json as helmert_from_json,
)


# ===== subcommand: convert =====


def cmd_convert(args: argparse.Namespace) -> int:
    lon_out, lat_out = convert_one(args.lon, args.lat, args.frm, args.to)
    # Resolve output format: --format wins; fall back to legacy --json
    fmt = getattr(args, "fmt", "text")
    if getattr(args, "json", False):
        fmt = "json"
    if fmt == "json":
        print(json.dumps({
            "lon": lon_out,
            "lat": lat_out,
            "src": args.frm,
            "dst": args.to,
        }, ensure_ascii=False))
    else:
        print(f"{lon_out:.7f},{lat_out:.7f}")

    if getattr(args, "qa", None):
        params_used = getattr(args, "params", None)
        write_qa_summary(args.qa, args, args.lon, args.lat, lon_out, lat_out, params_used)
    return 0


def cmd_self_test(args: argparse.Namespace) -> int:
    """Run a small self-test with known reference values.

    These are well-known GCJ-02 ↔ WGS-84 test vectors published by Chinese
    mapping community; if any fail the install is broken.
    """
    # Each test is (src, dst, src_lon, src_lat, expected_lon, expected_lat, tol)
    tests = [
        # WGS-84 → GCJ-02 (Tiananmen Square)
        ("wgs84", "gcj02", 116.397428, 39.90923, 116.40349, 39.91515, 0.01),
        # GCJ-02 → WGS-84 (Tiananmen)
        ("gcj02", "wgs84", 116.40349, 39.91515, 116.397428, 39.90923, 0.01),
        # WGS-84 → BD-09 (Tiananmen)
        ("wgs84", "bd09", 116.397428, 39.90923, 116.40980, 39.92172, 0.01),
        # BD-09 → WGS-84
        ("bd09", "wgs84", 116.40980, 39.92172, 116.397428, 39.90923, 0.01),
        # GCJ-02 ↔ BD-09 round trip
        ("gcj02", "bd09", 116.40349, 39.91515, 116.40980, 39.92172, 0.01),
    ]
    print("china-coord-transform self-test")
    print("=" * 60)
    n_ok = 0
    for frm, to, slon, slat, elon, elat, tol in tests:
        olon, olat = convert_one(slon, slat, frm, to)
        ok = abs(olon - elon) < tol and abs(olat - elat) < tol
        n_ok += int(ok)
        print(f"  {'PASS' if ok else 'FAIL'} {frm}→{to} ({slon:.5f},{slat:.5f}) "
              f"-> got ({olon:.5f},{olat:.5f}) expected ({elon:.5f},{elat:.5f})")
    print(f"\n{n_ok}/{len(tests)} tests passed")
    return 0 if n_ok == len(tests) else 1


# ===== subcommand: batch =====


def _load_params(path: str | None):
    if path is None:
        return None
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    model = raw.get("model", "")
    if model == "affine":
        return ("affine", AffineParams.from_dict(raw["params"]))
    if model.startswith("helmert"):
        return ("helmert", helmert_from_json(raw))
    if model == "polynomial":
        return ("poly", raw)
    raise ValueError(f"unknown model: {model!r}")


def _apply_with_params(
    lon: float,
    lat: float,
    src: str,
    dst: str,
    loaded,
) -> tuple[float, float]:
    """Apply a high-precision local transform if available, else fall back to the
    public GCJ-02 formula. ``loaded`` is (kind, params) or None.
    """
    if loaded is not None and src == "gcj02" and dst == "wgs84":
        kind, params = loaded
        if kind == "affine":
            return params.apply(lon, lat)
        if kind == "poly":
            return apply_polynomial(params, lon, lat)
        if kind == "helmert":
            # 2D helmerts: assume the params were fitted on lat/lon degrees
            if isinstance(params, (Helmert2D4, Helmert2D5)):
                return params.apply(lon, lat)
            # 3D helmert: needs ECEF round-trip
            if isinstance(params, Helmert3D7):
                X, Y, Z = geodetic_to_ecef(lon, lat, 0.0)
                Xp, Yp, Zp = params.apply_ecef(X, Y, Z)
                return ecef_to_geodetic(Xp, Yp, Zp)[:2]
    return convert_one(lon, lat, src, dst)


def cmd_batch(args: argparse.Namespace) -> int:
    in_path = Path(args.input)
    out_path = Path(args.output)
    loaded = _load_params(getattr(args, "params", None))

    # Resolve format: explicit --format wins; otherwise infer from suffix
    fmt = getattr(args, "fmt", None)
    if fmt is None:
        fmt = "json" if out_path.suffix.lower() == ".json" else "csv"

    with in_path.open("r", encoding="utf-8-sig", newline="") as fin:
        reader = csv.DictReader(fin)
        if "lon" not in reader.fieldnames or "lat" not in reader.fieldnames:
            print("error: input CSV must have 'lon' and 'lat' columns", file=sys.stderr)
            return 2

        out_fields = list(reader.fieldnames)
        if "src_lon" not in out_fields:
            out_fields.extend(["src_lon", "src_lat", "src_system"])
        out_records = []
        n_ok = n_skip = 0
        for row in reader:
            try:
                lon = float(row["lon"])
                lat = float(row["lat"])
            except (ValueError, TypeError) as e:
                print(f"warning: skipping row with non-numeric lon/lat: {row} ({e})", file=sys.stderr)
                n_skip += 1
                continue

            new_lon, new_lat = _apply_with_params(lon, lat, args.frm, args.to, loaded)
            row["src_lon"] = row.get("lon")
            row["src_lat"] = row.get("lat")
            row["src_system"] = args.frm
            row["lon"] = f"{new_lon:.7f}"
            row["lat"] = f"{new_lat:.7f}"
            out_records.append(row)
            n_ok += 1

    # Emit output
    if fmt == "json":
        with out_path.open("w", encoding="utf-8") as fout:
            json.dump(out_records, fout, ensure_ascii=False, indent=2)
    else:
        with out_path.open("w", encoding="utf-8", newline="") as fout:
            writer = csv.DictWriter(fout, fieldnames=out_fields)
            writer.writeheader()
            writer.writerows(out_records)

    print(f"wrote {n_ok} converted rows to {out_path} (skipped {n_skip})", file=sys.stderr)

    if getattr(args, "qa", None):
        qa = {
            "skill": "china-coord-transform",
            "command": "batch",
            "version": __version__,
            "user_agent": USER_AGENT,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "args": vars(args),
            "rows_converted": n_ok,
            "rows_skipped": n_skip,
            "input": str(in_path),
            "output": str(out_path),
            "format": fmt,
        }
        qa_p = Path(args.qa)
        qa_p.parent.mkdir(parents=True, exist_ok=True)
        with open(qa_p, "w", encoding="utf-8") as f:
            json.dump(qa, f, ensure_ascii=False, indent=2, default=str)
    return 0


# ===== subcommand: fit =====


def _read_control_csv(path: str) -> list[tuple[float, float, float, float]]:
    """Read a control-point CSV (lon, lat, dst_lon, dst_lat order).

    Column aliases accepted (case-insensitive):
      src_lon, gcj_lon, from_lon
      src_lat, gcj_lat, from_lat
      dst_lon, wgs_lon, to_lon
      dst_lat, wgs_lat, to_lat
    """
    out: list[tuple[float, float, float, float]] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        lines = []
        for raw in f:
            stripped = raw.lstrip()
            if not stripped or stripped.startswith("#"):
                continue
            lines.append(raw)
        if not lines:
            raise ValueError(f"control file {path!r} is empty or all comments")
        reader = csv.DictReader(lines)
        sl = next((c for c in (reader.fieldnames or []) if c and c.lower() in ("src_lon", "gcj_lon", "from_lon")), None)
        sa = next((c for c in (reader.fieldnames or []) if c and c.lower() in ("src_lat", "gcj_lat", "from_lat")), None)
        dl = next((c for c in (reader.fieldnames or []) if c and c.lower() in ("dst_lon", "wgs_lon", "to_lon")), None)
        da = next((c for c in (reader.fieldnames or []) if c and c.lower() in ("dst_lat", "wgs_lat", "to_lat")), None)
        if not (sl and sa and dl and da):
            raise ValueError(
                "controls CSV needs src_lon/src_lat/dst_lon/dst_lat "
                "(aliases: gcj_lon/wgs_lon etc.)"
            )
        for row in reader:
            try:
                out.append((float(row[sl]), float(row[sa]), float(row[dl]), float(row[da])))
            except (KeyError, TypeError, ValueError):
                continue
    if len(out) < 2:
        raise ValueError(f"need at least 2 valid control rows in {path!r}, got {len(out)}")
    return out


def cmd_fit(args: argparse.Namespace) -> int:
    controls = _read_control_csv(args.controls)
    model = args.model

    if model == "affine":
        if len(controls) < 3:
            print(f"warning: affine needs >= 3 controls, got {len(controls)}", file=sys.stderr)
        params = fit_affine(controls)
        stats = affine_residual_stats(params, controls)
        out_obj = {"model": "affine", "params": params.to_dict(), "stats": stats}
    elif model == "polynomial":
        if len(controls) < 6:
            raise ValueError(f"polynomial needs >= 6 controls, got {len(controls)}")
        poly = fit_polynomial(controls)
        out_obj = {"model": "polynomial", "params": poly, "stats": {"count": len(controls)}}
    elif model == "helmert-4param":
        params = fit_helmert_2d_4param(controls)
        stats = helmert_2d_residual_stats(params, controls)
        out_obj = {"model": params.to_dict()["model"], "params": params.to_dict(), "stats": stats}
    else:
        raise ValueError(f"unsupported model: {model}")

    Path(args.output).write_text(json.dumps(out_obj, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {model} fit to {args.output} ({len(controls)} controls)", file=sys.stderr)
    if "max_dist" in out_obj["stats"]:
        s = out_obj["stats"]
        print(
            f"  residuals: max={s['max_dist']:.4f}, "
            f"mean={s['mean_dist']:.4f}, rms={s['rms_dist']:.4f}",
            file=sys.stderr,
        )
    return 0


# ===== subcommand: vector =====


def cmd_vector(args: argparse.Namespace) -> int:
    """Convert a vector file (geojson or shp) using either a coordinate
    system transform (--from / --to) or a fitted local params file
    (--params). Only one path applies.
    """
    from transform import convert as convert_one
    from vector import (
        convert_geojson_file,
        convert_shp_file,
    )

    in_path = Path(args.input)
    out_path = Path(args.output)
    loaded = _load_params(args.params)

    def _fn(lon: float, lat: float) -> tuple[float, float]:
        if args.params:
            return _apply_with_params(lon, lat, args.frm, args.to, loaded)
        return convert_one(lon, lat, args.frm, args.to)

    suffix = in_path.suffix.lower()
    if suffix in (".geojson", ".json"):
        n = convert_geojson_file(in_path, out_path, _fn)
        print(f"converted {n} geometries in {in_path.name} -> {out_path.name}", file=sys.stderr)
        return 0
    if suffix == ".shp":
        n = convert_shp_file(in_path, out_path, _fn)
        print(f"converted {n} records in {in_path.name} -> {out_path.name}", file=sys.stderr)
        return 0
    print(f"error: unsupported extension {suffix!r} (expected .geojson, .json, or .shp)", file=sys.stderr)
    return 2


# ===== parser =====


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="china-coord-transform",
        description="Convert between WGS-84 / GCJ-02 / BD-09 (point, batch, vector).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("convert", help="convert a single (lon, lat)")
    pc.add_argument("--from", dest="frm", required=True, choices=SUPPORTED_SYSTEMS)
    pc.add_argument("--to", dest="to", required=True, choices=SUPPORTED_SYSTEMS)
    pc.add_argument("--lon", type=float, required=True)
    pc.add_argument("--lat", type=float, required=True)
    pc.add_argument("--format", dest="fmt", choices=["text", "json"], default="text",
                    help="Output format: text (CSV-style 'lon,lat') or json (default: text)")
    pc.add_argument("--json", action="store_true",
                    help="[deprecated] Shorthand for --format json (kept for backward compat)")
    pc.add_argument("--qa", metavar="PATH", default=None,
                    help="Write a JSON run-summary sidecar to PATH recording the conversion parameters")
    pc.set_defaults(func=cmd_convert)

    ps = sub.add_parser("self-test", help="run a built-in self-test with known values")
    ps.set_defaults(func=cmd_self_test)

    pb = sub.add_parser("batch", help="convert a CSV of points")
    pb.add_argument("--from", dest="frm", required=True, choices=SUPPORTED_SYSTEMS)
    pb.add_argument("--to", dest="to", required=True, choices=SUPPORTED_SYSTEMS)
    pb.add_argument("--input", required=True)
    pb.add_argument("--output", required=True)
    pb.add_argument("--format", dest="fmt", choices=["csv", "json"], default=None,
                    help="Output format: csv (default) or json. If omitted, inferred from --output suffix.")
    pb.add_argument("--params", help="affine / polynomial / helmert params JSON (from `fit`)")
    pb.add_argument("--qa", metavar="PATH", default=None,
                    help="Write a JSON run-summary sidecar to PATH recording the conversion parameters")
    pb.set_defaults(func=cmd_batch)

    pf = sub.add_parser("fit", help="fit a local transform from control points")
    pf.add_argument("--controls", required=True)
    pf.add_argument("--output", required=True)
    pf.add_argument("--model", default="affine",
                    choices=("affine", "polynomial", "helmert-4param"))
    pf.set_defaults(func=cmd_fit)

    pv = sub.add_parser("vector", help="convert a vector file (GeoJSON or SHP)")
    pv.add_argument("--input", required=True, help="input .geojson/.json or .shp")
    pv.add_argument("--output", required=True)
    pv.add_argument("--from", dest="frm", default="gcj02", choices=SUPPORTED_SYSTEMS,
                   help="input coord system (default: gcj02)")
    pv.add_argument("--to", dest="to", default="wgs84", choices=SUPPORTED_SYSTEMS,
                   help="output coord system (default: wgs84)")
    pv.add_argument("--params", help="optional local params JSON for high-precision")
    pv.set_defaults(func=cmd_vector)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
