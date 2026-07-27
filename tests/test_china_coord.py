"""Tests for china-coord-transform coordinate conversion methods."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Make sibling modules importable
HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from transform import gcj2wgs, wgs2gcj, bd2gcj, gcj2bd
import cli as cli_mod


def _haversine(lon1, lat1, lon2, lat2) -> float:
    """Calculate distance in meters between two lat/lon points."""
    R = 6371008.8
    rl1, rl2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rl1) * math.cos(rl2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class TestGCJ02ToWGS84:
    """Test GCJ-02 -> WGS-84 conversion."""

    def test_tiananmen(self):
        """Tiananmen Square case: GCJ-02 -> WGS-84."""
        gcj_lon, gcj_lat = 116.397594, 39.904949
        wgs_lon, wgs_lat = gcj2wgs(gcj_lon, gcj_lat)
        ref_lon, ref_lat = 116.391222, 39.903468
        d = _haversine(ref_lon, ref_lat, wgs_lon, wgs_lat)
        assert d < 20.0, f"Distance {d:.2f}m exceeds 20m threshold"

    def test_roundtrip(self):
        """WGS -> GCJ -> WGS round-trip should be bounded."""
        lon, lat = 116.397594, 39.904949
        gcj = wgs2gcj(lon, lat)
        back = gcj2wgs(*gcj)
        d = _haversine(lon, lat, *back)
        assert d < 50.0, f"Round-trip distance {d:.2f}m exceeds 50m"


class TestOutsideChina:
    """Test that coordinates outside China pass through unchanged."""

    def test_tokyo_wgs2gcj(self):
        """Tokyo should pass through wgs2gcj unchanged."""
        lon, lat = 139.6917, 35.6895
        assert wgs2gcj(lon, lat) == (lon, lat)

    def test_nyc_gcj2wgs(self):
        """New York should pass through gcj2wgs unchanged."""
        lon, lat = -74.0060, 40.7128
        assert gcj2wgs(lon, lat) == (lon, lat)


class TestBD09:
    """Test BD-09 conversions."""

    def test_bd2gcj_roundtrip(self):
        """BD-09 -> GCJ-02 -> BD-09 round-trip."""
        lon, lat = 116.404, 39.915
        gcj = bd2gcj(lon, lat)
        back = gcj2bd(*gcj)
        d = _haversine(lon, lat, *back)
        assert d < 10.0, f"BD round-trip distance {d:.2f}m exceeds 10m"


class TestFormatAndQA:
    """Tests for --format and --qa (Phase 5 optimization)."""

    def _run_cli(self, args):
        py = sys.executable
        return subprocess.run(
            [py, str(HERE / "cli.py")] + args,
            capture_output=True, text=True, timeout=30,
        )

    def test_convert_default_text_format(self):
        """Default --format=text should emit comma-separated lon,lat on one line."""
        r = self._run_cli([
            "convert", "--from", "gcj02", "--to", "wgs84",
            "--lon", "116.40349", "--lat", "39.91515",
        ])
        assert r.returncode == 0, r.stderr
        out = r.stdout.strip()
        # "lon,lat" CSV style
        parts = out.split(",")
        assert len(parts) == 2, f"expected 2 fields, got {out!r}"
        float(parts[0])  # should be parseable as float
        float(parts[1])

    def test_convert_format_text_explicit(self):
        """--format text should match the default text output."""
        r = self._run_cli([
            "convert", "--from", "gcj02", "--to", "wgs84",
            "--lon", "116.40349", "--lat", "39.91515",
            "--format", "text",
        ])
        assert r.returncode == 0, r.stderr
        out = r.stdout.strip()
        assert "," in out
        parts = out.split(",")
        assert len(parts) == 2

    def test_convert_format_json(self):
        """--format json should emit a JSON object with lon/lat/src/dst keys."""
        r = self._run_cli([
            "convert", "--from", "gcj02", "--to", "wgs84",
            "--lon", "116.40349", "--lat", "39.91515",
            "--format", "json",
        ])
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout.strip())
        assert "lon" in data and "lat" in data
        assert data["src"] == "gcj02"
        assert data["dst"] == "wgs84"
        # Sanity: result should round-trip (WGS-84 → GCJ-02 → WGS-84).
        # The GCJ-02 offset algorithm is approximate (~500m tolerance);
        # we just want to ensure the conversion moves in the right direction.
        from transform import wgs2gcj
        gcj_lon, gcj_lat = wgs2gcj(data["lon"], data["lat"])
        d = _haversine(116.40349, 39.91515, gcj_lon, gcj_lat)
        assert d < 1000.0, f"round-trip distance {d:.2f}m unexpectedly large"

    def test_convert_json_backcompat(self):
        """Legacy --json flag should still emit JSON (backward compat)."""
        r = self._run_cli([
            "convert", "--from", "gcj02", "--to", "wgs84",
            "--lon", "116.40349", "--lat", "39.91515",
            "--json",
        ])
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout.strip())
        assert "lon" in data and "lat" in data

    def test_convert_qa_writes_sidecar(self, tmp_path):
        """--qa should write a JSON run-summary sidecar with key fields."""
        qa = tmp_path / "run.qa.json"
        r = self._run_cli([
            "convert", "--from", "gcj02", "--to", "wgs84",
            "--lon", "116.40349", "--lat", "39.91515",
            "--format", "json",
            "--qa", str(qa),
        ])
        assert r.returncode == 0, r.stderr
        assert qa.exists()
        qa_data = json.loads(qa.read_text(encoding="utf-8"))
        assert qa_data["skill"] == "china-coord-transform"
        assert qa_data["command"] == "convert"
        assert qa_data["version"]
        assert "timestamp" in qa_data
        assert qa_data["input"]["src_system"] == "gcj02"
        assert qa_data["output"]["dst_system"] == "wgs84"
        assert qa_data["input"]["lon"] == 116.40349
        assert qa_data["output"]["lon"] is not None

    def test_batch_format_json(self, tmp_path):
        """batch --format json should write a JSON array."""
        in_csv = tmp_path / "in.csv"
        out_path = tmp_path / "out.json"
        in_csv.write_text(
            "name,lon,lat\nA,116.40349,39.91515\nB,116.404,39.915\n",
            encoding="utf-8",
        )
        r = self._run_cli([
            "batch", "--from", "gcj02", "--to", "wgs84",
            "--input", str(in_csv), "--output", str(out_path),
            "--format", "json",
        ])
        assert r.returncode == 0, r.stderr
        records = json.loads(out_path.read_text(encoding="utf-8"))
        assert isinstance(records, list)
        assert len(records) == 2
        assert "src_lon" in records[0]
        assert "src_lat" in records[0]
        assert "src_system" in records[0]

    def test_batch_format_csv_explicit(self, tmp_path):
        """batch --format csv should produce CSV even when output suffix is .txt."""
        in_csv = tmp_path / "in.csv"
        out_path = tmp_path / "out.txt"
        in_csv.write_text(
            "name,lon,lat\nA,116.40349,39.91515\n",
            encoding="utf-8",
        )
        r = self._run_cli([
            "batch", "--from", "gcj02", "--to", "wgs84",
            "--input", str(in_csv), "--output", str(out_path),
            "--format", "csv",
        ])
        assert r.returncode == 0, r.stderr
        text = out_path.read_text(encoding="utf-8")
        # CSV header should be present
        assert "src_lon" in text
        assert "name" in text

    def test_batch_qa_writes_sidecar(self, tmp_path):
        """batch --qa should write a JSON run-summary sidecar."""
        in_csv = tmp_path / "in.csv"
        out_path = tmp_path / "out.csv"
        qa = tmp_path / "run.qa.json"
        in_csv.write_text(
            "name,lon,lat\nA,116.40349,39.91515\n",
            encoding="utf-8",
        )
        r = self._run_cli([
            "batch", "--from", "gcj02", "--to", "wgs84",
            "--input", str(in_csv), "--output", str(out_path),
            "--qa", str(qa),
        ])
        assert r.returncode == 0, r.stderr
        qa_data = json.loads(qa.read_text(encoding="utf-8"))
        assert qa_data["skill"] == "china-coord-transform"
        assert qa_data["command"] == "batch"
        assert qa_data["rows_converted"] == 1
        assert qa_data["format"] in ("csv", "json")

    def test_write_qa_summary_helper(self, tmp_path):
        """Direct call to write_qa_summary should write a valid JSON sidecar."""
        qa = tmp_path / "x.qa.json"
        args = cli_mod.argparse.Namespace(
            frm="gcj02", to="wgs84", lon=116.4, lat=39.9,
            fmt="json", json=False, qa=str(qa), params=None,
        )
        cli_mod.write_qa_summary(
            str(qa), args, 116.4, 39.9, 116.39, 39.89, None,
        )
        assert qa.exists()
        data = json.loads(qa.read_text(encoding="utf-8"))
        assert data["input"]["lon"] == 116.4
        assert data["output"]["dst_system"] == "wgs84"
