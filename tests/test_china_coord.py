"""Tests for china-coord-transform coordinate conversion methods."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

# Make sibling modules importable
HERE = Path(__file__).parent.parent
sys.path.insert(0, str(HERE))

from transform import gcj2wgs, wgs2gcj, bd2gcj, gcj2bd


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
