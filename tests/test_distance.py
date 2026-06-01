"""Sanity tests for the haversine distance and trail length calculations.

No network, no fixtures, fast. Run with: python -m pytest tests/ -q
"""
from trailsnow.snotel import _haversine_km
from trailsnow.v1 import _trail_length_km


def test_haversine_zero():
    assert _haversine_km(46.78, -121.74, 46.78, -121.74) == 0.0


def test_haversine_known_pair():
    # Paradise SNOTEL to Skyline centroid, hand-computed ~1.2 km
    d = _haversine_km(46.78266, -121.74767, 46.7825, -121.7300)
    assert 1.0 < d < 1.5


def test_haversine_long():
    # Seattle to Portland is ~233 km great-circle
    d = _haversine_km(47.6062, -122.3321, 45.5152, -122.6784)
    assert 230 < d < 240


def test_trail_length_straight_segment():
    # A roughly 1 km segment east-west at 47 N is about 0.0132 degrees of lon
    coords = [[47.0, -121.0], [47.0, -121.0132]]
    km = _trail_length_km(coords)
    assert 0.95 < km < 1.05
