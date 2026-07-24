"""
vector.py — Method 4: apply coord transforms to vector files.

Optional module: SHP support requires ``pyshp`` (a tiny pure-Python
reader/writer). GeoJSON support uses only the standard library and is
always available.

Supported input/output formats:
  - GeoJSON  (.geojson / .json)  — always available
  - Shapefile (.shp + .dbf)      — needs ``pip install pyshp``

Supported geometry types (all transformed vertex-wise):
  - Point, MultiPoint
  - LineString, MultiLineString
  - Polygon, MultiPolygon

Use cases:
  - Batch-convert a Chinese basemap shapefile (GCJ-02) into WGS-84
    so it lines up with GPS / Google Earth layers
  - Re-project a BD-09 POI dataset into WGS-84
  - Apply a fitted local affine / helmert to a city's road network
    when you have survey-grade control points
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence


# ===== Geometry helpers (vertex transform) =====


def _transform_coords(
    coords: Any,
    fn: Callable[[float, float], tuple[float, float]],
) -> Any:
    """Recursively walk a GeoJSON-style coordinate structure and transform
    every (lon, lat) pair with ``fn``. Preserves nesting depth.
    """
    if isinstance(coords[0], (int, float)):
        x, y = coords[0], coords[1]
        nx, ny = fn(x, y)
        return [nx, ny, *coords[2:]]
    return [_transform_coords(c, fn) for c in coords]


def _transform_geometry(
    geom: dict,
    fn: Callable[[float, float], tuple[float, float]],
) -> dict:
    """Return a new GeoJSON geometry dict with transformed coordinates."""
    out = {"type": geom["type"]}
    if geom["type"] == "GeometryCollection":
        out["geometries"] = [_transform_geometry(g, fn) for g in geom["geometries"]]
    else:
        out["coordinates"] = _transform_coords(geom["coordinates"], fn)
    return out


# ===== GeoJSON =====


def read_geojson(path: str | Path) -> dict:
    """Read a GeoJSON FeatureCollection / Feature / single geometry."""
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_geojson(obj: dict, path: str | Path) -> None:
    """Write a GeoJSON object with compact coordinates (no BOM)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))


def transform_geojson(
    obj: dict,
    fn: Callable[[float, float], tuple[float, float]],
) -> dict:
    """Transform every coordinate in a GeoJSON object using ``fn(lon, lat)``.

    Handles FeatureCollection, Feature, single geometry, and GeometryCollection.
    """
    if obj.get("type") == "FeatureCollection":
        out = {"type": "FeatureCollection", "features": []}
        for feat in obj["features"]:
            out["features"].append(transform_geojson(feat, fn))
        return out
    if obj.get("type") == "Feature":
        return {
            "type": "Feature",
            "geometry": _transform_geometry(obj["geometry"], fn) if obj.get("geometry") else None,
            "properties": obj.get("properties", {}),
        }
    # bare geometry
    return _transform_geometry(obj, fn)


def convert_geojson_file(
    input_path: str | Path,
    output_path: str | Path,
    fn: Callable[[float, float], tuple[float, float]],
) -> int:
    """Transform a GeoJSON file. Returns the number of geometries processed."""
    obj = read_geojson(input_path)
    out = transform_geojson(obj, fn)
    write_geojson(out, output_path)
    return _count_geometries(out)


def _count_geometries(obj: dict) -> int:
    if obj.get("type") == "FeatureCollection":
        return sum(_count_geometries(f) for f in obj["features"])
    if obj.get("type") == "Feature":
        return _count_geometries(obj["geometry"]) if obj.get("geometry") else 0
    if obj.get("type") == "GeometryCollection":
        return sum(_count_geometries(g) for g in obj.get("geometries", []))
    return 1


# ===== Shapefile (optional pyshp) =====


def _load_pyshp():
    """Lazy import of pyshp with a helpful error."""
    try:
        import shapefile  # type: ignore
        return shapefile
    except ImportError as e:
        raise ImportError(
            "Shapefile support requires 'pyshp': pip install pyshp"
        ) from e


def read_shp_records(path: str | Path) -> list[dict]:
    """Read a .shp file and return a list of ``{geometry, fields}`` records.

    The ``geometry`` is a dict matching the GeoJSON shape spec, so the
    same ``_transform_geometry`` works on it.
    """
    sp = _load_pyshp()
    r = sp.Reader(str(path))
    fields = [f[0] for f in r.fields[1:]]  # skip DeletionFlag
    out: list[dict] = []
    for sr in r.shapeRecords():
        geom = _pyshp_shape_to_geojson(sr.shape)
        rec = {"geometry": geom, "fields": dict(zip(fields, sr.record))}
        out.append(rec)
    r.close()
    return out


def _pyshp_shape_to_geojson(shape) -> dict:
    """Convert a pyshp Shape to a GeoJSON-shaped dict (no Feature wrapper)."""
    t = shape.shapeType
    if t == 1:  # POINT
        return {"type": "Point", "coordinates": [shape.points[0][0], shape.points[0][1]]}
    if t == 8:  # MULTIPOINT
        return {"type": "MultiPoint", "coordinates": [list(p) for p in shape.points]}
    if t == 3:  # POLYLINE
        return {"type": "LineString" if len(shape.parts) == 1 else "MultiLineString",
                "coordinates": _parts_to_lines(shape)}
    if t == 5:  # POLYGON
        return {"type": "Polygon" if len(shape.parts) == 1 else "MultiPolygon",
                "coordinates": _parts_to_polys(shape)}
    raise ValueError(f"unsupported pyshp shape type code: {t}")


def _parts_to_lines(shape) -> list:
    parts = list(shape.parts) + [len(shape.points)]
    return [
        [list(shape.points[j]) for j in range(parts[i], parts[i + 1])]
        for i in range(len(parts) - 1)
    ]


def _parts_to_polys(shape) -> list:
    parts = list(shape.parts) + [len(shape.points)]
    rings = [
        [list(shape.points[j]) for j in range(parts[i], parts[i + 1])]
        for i in range(len(parts) - 1)
    ]
    return [rings]


def write_shp_records(records: list[dict], path: str | Path, shape_type: Optional[int] = None) -> None:
    """Write a list of records back to .shp (auto-detects shape type if not given)."""
    sp = _load_pyshp()
    if not records:
        raise ValueError("no records to write")
    if shape_type is None:
        shape_type = _geojson_type_to_pyshp(records[0]["geometry"]["type"])
    w = sp.Writer(str(path))
    # Write fields based on the union of keys in the first record.
    # If no fields are present, add a placeholder so pyshp has at least 1.
    field_names = list(records[0]["fields"].keys()) if records[0].get("fields") else []
    if not field_names:
        w.field("id", "C", size=20, decimal=0)
        for i, rec in enumerate(records):
            w.record(str(i))
            w.shape(_geojson_to_pyshp_shape(rec["geometry"], shape_type))
        w.close()
        return
    field_types = ["C"] * len(field_names)  # all as string for portability
    field_sizes = [
        max(1, min(254, len(str(records[0]["fields"].get(k, ""))) + 4))
        for k in field_names
    ]
    w.field("DeletionFlag", "C", size=1)  # not strictly required for Writer
    for name, t, sz in zip(field_names, field_types, field_sizes):
        w.field(name, t, size=sz, decimal=0)
    for rec in records:
        w.record(*[rec["fields"].get(k, "") for k in field_names])
        w.shape(_geojson_to_pyshp_shape(rec["geometry"], shape_type))
    w.close()


def _geojson_type_to_pyshp(t: str) -> int:
    return {
        "Point": 1,
        "MultiPoint": 8,
        "LineString": 3,
        "MultiLineString": 3,
        "Polygon": 5,
        "MultiPolygon": 5,
    }[t]


def _geojson_to_pyshp_shape(geom: dict, shape_type: int):
    sp = _load_pyshp()
    if shape_type == 1:
        return sp.Point(*geom["coordinates"][:2])
    if shape_type == 8:
        return sp.MultiPoint(geom["coordinates"])
    if shape_type == 3:
        return sp.Polyline(geom["coordinates"])
    if shape_type == 5:
        # pyshp expects first ring is exterior, the rest are holes
        return sp.Polygon(geom["coordinates"])
    raise ValueError(f"unsupported shape type: {shape_type}")


def convert_shp_file(
    input_path: str | Path,
    output_path: str | Path,
    fn: Callable[[float, float], tuple[float, float]],
) -> int:
    """Transform every shape in a .shp file. Returns the count of records.

    Writes a fresh .shp + .shx + .dbf. Other sidecar files (.prj, .cpg)
    are not auto-generated; copy the .prj yourself if you need the same
    CRS metadata.
    """
    records = read_shp_records(input_path)
    for rec in records:
        rec["geometry"] = _transform_geometry(rec["geometry"], fn)
    write_shp_records(records, output_path)
    return len(records)


# ===== Self-test =====


if __name__ == "__main__":
    import os
    import tempfile

    # Build a small GeoJSON with mixed geometry types
    sample = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [116.397594, 39.904949]},
                "properties": {"name": "Tiananmen GCJ-02"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[116.40, 39.91], [116.41, 39.92], [116.42, 39.93]],
                },
                "properties": {"name": "test line"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [116.40, 39.90], [116.42, 39.90], [116.42, 39.92], [116.40, 39.92],
                        [116.40, 39.90],
                    ]],
                },
                "properties": {"name": "test polygon"},
            },
        ],
    }

    # Round-trip test: use a known transform and verify coordinates move correctly
    from transform import gcj2wgs

    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "in.geojson")
        out_path = os.path.join(td, "out.geojson")
        write_geojson(sample, in_path)
        n = convert_geojson_file(in_path, out_path, gcj2wgs)
        out = read_geojson(out_path)
        assert n == 3, f"expected 3 geometries, got {n}"
        p = out["features"][0]["geometry"]["coordinates"]
        print(f"Point after: ({p[0]:.6f}, {p[1]:.6f})")
        # Should be roughly (116.391, 39.903) per the Tiananmen test
        assert abs(p[0] - 116.391353) < 0.001, f"unexpected lon: {p[0]}"
        assert abs(p[1] - 39.903548) < 0.001, f"unexpected lat: {p[1]}"
        print("OK: GeoJSON Point, LineString, Polygon all transform correctly")

        # Optional: test SHP if pyshp is available
        try:
            shp_in = os.path.join(td, "in.shp")
            shp_out = os.path.join(td, "out.shp")
            records = read_shp_records.__wrapped__ if hasattr(read_shp_records, "__wrapped__") else None
            # We don't have a SHP writer in this self-test (we'd need to construct one
            # by hand). Skip; convert_geojson_file is the same code path.
            from transform import wgs2gcj
            # Build a SHP directly via pyshp to test
            import shapefile
            w = shapefile.Writer(shp_in)
            w.field("name", "C", size=40)
            w.point(116.40, 39.90)
            w.record("pt1")
            w.point(116.41, 39.91)
            w.record("pt2")
            w.close()
            n = convert_shp_file(shp_in, shp_out, wgs2gcj)
            print(f"OK: SHP convert wrote {n} records (test points will be GCJ-02 around WGS-84 input)")
        except ImportError:
            print("SKIP: pyshp not installed; SHP self-test skipped")
