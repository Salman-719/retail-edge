"""Polygon geometry helpers using Shapely."""
from shapely.geometry import Polygon


def polygons_overlap(points_a: list[list[float]], points_b: list[list[float]]) -> bool:
    """
    Return True if the two polygons have any area overlap.

    Touching edges / shared vertices are NOT considered overlap
    (uses intersection area > tiny epsilon rather than .intersects()).
    """
    poly_a = Polygon(points_a)
    poly_b = Polygon(points_b)

    if not poly_a.is_valid or not poly_b.is_valid:
        return False

    intersection = poly_a.intersection(poly_b)
    return intersection.area > 1e-9
