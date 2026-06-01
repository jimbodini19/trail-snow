"""Geometry helpers: trail length and even-spaced sampling along a polyline."""

from __future__ import annotations

import math

R_EARTH_M = 6371008.8  # mean Earth radius in meters


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlam / 2) ** 2
    return 2 * R_EARTH_M * math.asin(math.sqrt(a))


def line_length_m(coords: list[list[float]]) -> float:
    total = 0.0
    for (a_lat, a_lon), (b_lat, b_lon) in zip(coords, coords[1:]):
        total += haversine_m(a_lat, a_lon, b_lat, b_lon)
    return total


def _interp(a_lat: float, a_lon: float, b_lat: float, b_lon: float, frac: float) -> tuple[float, float]:
    """Linear interp in lat/lon. Fine for short segments (< 1 km) at these scales."""
    return a_lat + (b_lat - a_lat) * frac, a_lon + (b_lon - a_lon) * frac


def sample_along(coords: list[list[float]], spacing_m: float = 300.0) -> list[tuple[float, float]]:
    """Return points evenly spaced along the polyline, including start and end.

    Spacing is approximate: each interior segment may differ slightly because we
    walk segment by segment. Good enough for SNODAS sampling at 1 km grid.
    """
    if len(coords) < 2:
        return [tuple(coords[0])] if coords else []

    samples: list[tuple[float, float]] = [(coords[0][0], coords[0][1])]
    carry = 0.0  # distance already accumulated past the last sample
    for (a_lat, a_lon), (b_lat, b_lon) in zip(coords, coords[1:]):
        seg = haversine_m(a_lat, a_lon, b_lat, b_lon)
        if seg == 0:
            continue
        dist_into_seg = spacing_m - carry
        while dist_into_seg <= seg:
            frac = dist_into_seg / seg
            samples.append(_interp(a_lat, a_lon, b_lat, b_lon, frac))
            dist_into_seg += spacing_m
        carry = seg - (dist_into_seg - spacing_m)

    # Make sure the trail end is represented.
    end = (coords[-1][0], coords[-1][1])
    if samples[-1] != end:
        samples.append(end)
    return samples


def cumulative_distances_m(points: list[tuple[float, float]]) -> list[float]:
    out = [0.0]
    for (a_lat, a_lon), (b_lat, b_lon) in zip(points, points[1:]):
        out.append(out[-1] + haversine_m(a_lat, a_lon, b_lat, b_lon))
    return out
