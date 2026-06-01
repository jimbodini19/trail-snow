"""Unit tests for the v2 modules: trail densifier + SNODAS pixel math."""

from trailsnow.geom import haversine_m, line_length_m, sample_along
from trailsnow.snodas import latlon_to_pixel, COLS, ROWS, MIN_LON, MAX_LON, MIN_LAT, MAX_LAT


def test_haversine_m_zero():
    assert haversine_m(46.78, -121.74, 46.78, -121.74) == 0.0


def test_haversine_m_about_a_km():
    d = haversine_m(47.0, -121.0, 47.0, -121.0132)
    assert 990 < d < 1010


def test_sample_along_two_km_at_300m():
    coords = [[47.0, -121.0], [47.0, -120.9737]]
    samples = sample_along(coords, spacing_m=300.0)
    assert len(samples) >= 7
    assert samples[0] == (47.0, -121.0)
    assert samples[-1] == (47.0, -120.9737)


def test_sample_along_multi_segment():
    coords = [[47.0, -121.0], [47.005, -121.0], [47.005, -120.99]]
    samples = sample_along(coords, spacing_m=200.0)
    assert samples[0] == (47.0, -121.0)
    assert samples[-1] == (47.005, -120.99)


def test_snodas_pixel_corners():
    r, c = latlon_to_pixel(MIN_LAT + 0.001, MIN_LON + 0.001)
    assert r == ROWS - 1
    assert c == 0
    r, c = latlon_to_pixel(MAX_LAT - 0.001, MAX_LON - 0.001)
    assert r == 0
    assert c == COLS - 1


def test_snodas_pixel_paradise():
    r, c = latlon_to_pixel(46.78266, -121.74767)
    assert 0 <= r < ROWS
    assert 0 <= c < COLS
