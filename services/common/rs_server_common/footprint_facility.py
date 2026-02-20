# Copyright 2023-2025 Airbus, CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# https://gitlab.com/be-prototypes/geofootprint-prototype

"""
Copyright 2024 - GAEL Systems

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

# mypy: ignore-errors
# type: ignore
# pylint: skip-file
# flake8: noqa
# NOSONAR

import inspect
import logging

import numpy as np
import shapely
from pyproj import Transformer
from shapely import Geometry, Point
from shapely.geometry.base import BaseMultipartGeometry
from shapely.geometry.polygon import Polygon
from shapely.ops import transform as sh_transform

"""
Checks the singularities in the footprints
 - longitude/antimeridian : when the footprint crosses ±180 meridian
 - polar : when the footprint contains polar area (also ±180 meridian)
"""

logger = logging.getLogger("footprint_facility")


class AlreadyReworkedPolygonError(Exception):
    pass


################################
# Prepare projection transformers
# Objective is to use metric projection centered on the concerned polar
# point to avoid polar discontinuity.
# Projection user: polar stereoscopic epsg:3031
wgs84_to_polar_north = Transformer.from_crs(
    "+proj=longlat +datum=WGS84 +no_defs",
    "+proj=stere +lat_0=90 +lat_ts=75",
).transform
wgs84_to_polar_south = Transformer.from_crs(
    "+proj=longlat +datum=WGS84 +no_defs",
    "+proj=stere +lat_0=-90 +lat_ts=-75",
).transform
north_pole_m = sh_transform(wgs84_to_polar_north, Point(float(0), float(90)))
south_pole_m = sh_transform(wgs84_to_polar_south, Point(float(0), float(-90)))


def check_cross_antimeridian(geometry: Geometry) -> bool:
    """
    Checks if the geometry pass over ±180 longitude position.
    The detection of antimeridian is performed according to the distance
    between longitudes positions between consecutive points of the geometry
    points. The distance shall be greater than 180 to avoid revert longitude
    signs around greenwich meridian 0.
    It is also considered crossing antimeridian when one of the polygon
    longitude is exactly to +-180 degrees.
    :parameter geometry: The geometry to be controlled.
    :return: True if the geometry pass over antimeridian, False otherwise.
    """
    # Case of Collection of geometries (i.e. Multipolygons)
    if hasattr(geometry, "geoms"):
        for geom in geometry.geoms:
            if check_cross_antimeridian(geom):
                return True

    # Path of points shall exist (Polygon or Linestring)
    boundary = np.array(shapely.get_coordinates(geometry))
    i = 0
    while i < boundary.shape[0] - 1:
        if boundary[i, 0] == 180 or boundary[i, 0] == -180 or abs(boundary[i + 1, 0] - boundary[i, 0]) > 180:
            return True
        i += 1
    return False


def _check_contains_north_pole(geometry: Geometry):
    """
    Check if the given geometry contains North Pole.
    Warning: the re-projection process does not work properly when coordinates
    of the geometry pass over antimeridian. This method cannot be used without
    applying the polar inclusive method as implemented in
    `rework_to_polygon_geometry`.

    See comment on globals variable for projection details.

    :parameter geometry: the complex reference geometry.
    :return: True if the given geometry contains North Pole
    """
    north = shapely.intersection(shapely.box(-180, 0, 180, 90), shapely.buffer(geometry, 0))

    geometry_m = sh_transform(wgs84_to_polar_north, north)
    # Use 1m larger as rounded to handle float values inaccuracies.
    geometry_m = geometry_m.buffer(1)

    return geometry_m.contains(north_pole_m)


def _check_contains_south_pole(geometry: Geometry):
    """
    Check if the given geometry contains South Pole.
    Warning: the re-projection process does not work properly when coordinates
    of the geometry pass over antimeridian. This method cannot be used without
    applying the polar inclusive method as implemented in
    `rework_to_polygon_geometry`.

    See comment on globals variable for projection details.

    :parameter geometry: the complex reference geometry.
    :return: True if the given geometry contains South Pole
    """

    south = shapely.intersection(shapely.box(-180, -90, 180, 0), shapely.buffer(geometry, 0))

    geometry_m = sh_transform(wgs84_to_polar_south, south)
    # Use 1m larger as rounded to handle float values inaccuracies.
    geometry_m = geometry_m.buffer(1)

    return geometry_m.contains(south_pole_m)


def _check_contains_pole(geometry: Geometry) -> bool:
    """
    Checks if the geometry pass over the North or South Pole.
    WARN: this method shall be used only once improved geometry with inclusion
    of polar point.
    :parameter geometry: the geometry to be controlled.
    :return: True if the geometry contains polar point, False otherwise.
    """
    return _check_contains_north_pole(geometry) or _check_contains_south_pole(geometry)


def _plus360(x):
    """
    Translate to +360 degrees the x longitude value when value is negative.

    Note: The translation is only applicable to longitude values with unit
    in degrees. It shall be efficient when previous coordinate longitude is
    180 degrees far from this point.

    :param x: the longitude to be translated
    :return:  the shifted longitude when required.
    """
    if x < 0:
        x = 180 + (x + 180)
    return x


def _moins360(x):
    """
    Translate to -360 degrees the x longitude value when value is negative.

    Note: The translation is only applicable to longitude values with unit
    in degrees. It shall be efficient when previous coordinate longitude is
    180 degrees far from this point.

    :param x: the longitude to be translated
    :return:  the shifted longitude when required.
    """
    if x > 180:
        x = (x - 180) - 180
    return x


def _polynom_coefficients(px1, py1, px2, py2):
    """
    Resolves the linear equation passing by given p1 and p2 coordinates.
    :return: Two values: first is the leading coefficient (m) second is the
    constant coefficient (b) that can be used as Y=m.X+b
    """
    if px2 - px1 == 0:
        raise AlreadyReworkedPolygonError("Points are aligned onto the antimeridian")
    # leading coefficient
    m = (py2 - py1) / (px2 - px1)
    # retrieves b
    b = py1 - m * px1
    return m, b


def _lat_cross_antimeridian(p1, p2):
    """
    Retrieves the latitude position in the line drawn by 2
    point parameters p1 and p2 and crossing ±180 longitude.
    """
    x1 = _plus360(p1[0])
    y1 = p1[1]

    x2 = _plus360(p2[0])
    y2 = p2[1]

    m, b = _polynom_coefficients(x1, y1, x2, y2)
    # resolve polynom with x=180
    return 180 * m + b


def _lon_cross_equator(p1, p2):
    """
    Retrieves the longitude position in the line drawn by 2
    point parameters p1 and p2 and crossing equator.
    """
    x1 = _plus360(p1[0])
    y1 = p1[1]

    x2 = _plus360(p2[0])
    y2 = p2[1]

    m, b = _polynom_coefficients(x1, y1, x2, y2)
    # resolve polynom with y=0 for (y=mx + b) -> x = -b/m
    return _moins360(-b / m)


def _split_polygon_to_antimeridian(geometry: Geometry):
    """
    This method splits geometry among the antimeridan area. It removes link
    to the pole if any.
    :param geometry: the geometry to split
    :return: polygon or multipolygon if the geometry requires to be split.
    """
    if not check_cross_antimeridian(geometry):
        return geometry

    boundaries = np.array(shapely.get_coordinates(geometry))

    left_antimeridian = []
    right_antimeridian = []
    polygons = [right_antimeridian, left_antimeridian]

    hsign = 0 if boundaries[0, 0] < 0 else 1
    for index, boundary in enumerate(boundaries):
        if index < boundaries.shape[0] - 1 and abs(boundaries[index + 1, 0] - boundaries[index, 0]) > 180:
            hsign = 0 if boundaries[index + 1, 0] < 0 else 1

        if (boundary[0] == -180 or boundary[0] == 180) and (boundary[1] == -90 or boundary[1] == 90):
            continue
        polygons[hsign].append(boundary)

    # Checks the empty list if any
    if not left_antimeridian and not right_antimeridian:
        raise ValueError("Footprint cannot be split across the antimeridian")
    elif not left_antimeridian:
        reworked = shapely.polygons(right_antimeridian)
    elif not right_antimeridian:
        reworked = shapely.polygons(left_antimeridian)
    else:
        reworked = shapely.multipolygons([shapely.polygons(left_antimeridian), shapely.polygons(right_antimeridian)])

    return reworked


def _num_cross_equator(geometry: Geometry):
    """Count the equator cross number."""
    boundaries = np.array(shapely.get_coordinates(geometry))
    previous = []
    count = 0
    for boundary in boundaries:
        if len(previous) == 2 and ((previous[1] > 0 > boundary[1]) or (previous[1] < 0 < boundary[1])):
            count += 1
        previous = boundary
    return count


def _to_polygons(geometries):
    for geometry in geometries:
        if isinstance(geometry, shapely.Polygon):
            yield geometry
        else:
            yield from geometry.geoms


def _split_polygon_to_equator(geometry: Geometry):
    """
    Split geometry among the equator: this is useful when the footprint cover
    both hemisphere and includes overlapping with antimeridian: In this case
    both poles are included into the shape of the footprint and intersection
    method fails.
    :param geometry:
    :return:
    """
    north = shapely.intersection(shapely.box(-180, 0, 180, 90), shapely.buffer(geometry, 0))
    south = shapely.intersection(shapely.box(-180, -90, 180, 0), shapely.buffer(geometry, 0))
    return shapely.MultiPolygon(_to_polygons([north, south]))


def _split_crude_polygon_to_latitude(geometry: Geometry, latitude):
    """
    Split geometry among the given latitude: The objective of this function
    is to cut the footprint horizontally at the given latitude.
    Originally fixed to cut at the equator with latitude=0, it can be also
    be used with different latitudes.
    The algorithm is based on following the shape path borders upon above
    and below the given latitude. Once separate, the set of points, they are
    re-arrange per polygons according to their position.
    :param geometry:
    :return:
    """
    boundaries = np.array(shapely.get_coordinates(geometry))
    north = []
    south = []
    north_list = []
    south_list = []
    i = 0
    point_number = boundaries.shape[0]
    while i < point_number:
        # North: lat>=0
        if boundaries[i, 1] >= latitude:
            north.append(boundaries[i])
            # Case of transition to the south hemisphere
            if i + 1 < point_number and boundaries[i + 1, 1] < latitude:
                equator_pts = np.array([_lon_cross_equator(boundaries[i + 1], boundaries[i]), latitude])
                north.append(equator_pts)
                north_list.append(north)
                north = []
                south.append(equator_pts)
        # South: lat<=0
        if boundaries[i, 1] <= latitude:
            south.append(boundaries[i])
            # Case of transition to the north hemisphere
            if i + 1 < point_number and boundaries[i + 1, 1] > latitude:
                equator_pts = np.array([_lon_cross_equator(boundaries[i + 1], boundaries[i]), latitude])
                south.append(equator_pts)
                south_list.append(south)
                south = []
                north.append(equator_pts)
        i += 1
    if len(north) > 0:
        north_list.append(north)
    if len(south) > 0:
        south_list.append(south)

    # Rebuild the polygons north/south split from the path list
    # When the trace start from north
    if boundaries[0, 1] > latitude:
        if len(north_list) == 2:
            north_list[0].extend(north_list[1])
            del north_list[1]
        if len(north_list) == 3:
            north_list[0].extend(north_list[2])
            del north_list[2]
            if len(south_list) == 2:
                south_list[0].extend(south_list[1])
                del south_list[1]
    # When the trace start from south
    if boundaries[0, 1] <= latitude:
        if len(south_list) == 2:
            south_list[0].extend(south_list[1])
            del south_list[1]
        if len(south_list) == 3:
            south_list[0].extend(south_list[2])
            del south_list[2]
            if len(north_list) == 2:
                north_list[0].extend(north_list[1])
                del north_list[1]

    return north_list, south_list


def _split_crude_polygon_to_equator(geometry: Geometry):
    """
    Split geometry among the equator: this is useful when the footprint covers
    both hemisphere and includes overlapping with antimeridian: In this case
    both poles are included into the shape of the footprint and intersection
    method fails. In the case of crude polygon, the shapely union function
    cannot be used.
    The algorithm is based on following the shape path borders upon north and
    south hemisphere. Once separate, the set of points, they are rearrange per
    polygons according to their position.
    :param geometry:
    :return:
    """
    north_list, south_list = _split_crude_polygon_to_latitude(geometry, 0)
    multi = []
    multi.extend([Polygon(x) for x in north_list])
    multi.extend([Polygon(x) for x in south_list])
    return shapely.MultiPolygon(multi)


def _merge_polygon_to_equator(geometry):
    """Merge set of geometries which are adjacent."""
    return shapely.union_all(geometry)


def _num_cross_antimeridian(geometry):
    """
    Computes the number of times the footprint crosses the antimeridian.
    It also checks if the antimeridian is crossed in north hemisphere only,
    south hemisphere only or mixed both hemispheres.
    :param geometry:
    :return:
    """
    boundaries = np.array(shapely.get_coordinates(geometry))
    i = 0
    count = 0
    previous = []
    crossing_latitudes = []
    mixed = False
    while i < boundaries.shape[0] - 1:
        if abs(boundaries[i + 1, 0] - boundaries[i, 0]) > 180:
            count += 1
            crossing_latitudes.append(boundaries[i, 1])
            if len(previous) > 0 and not mixed:
                p = previous[1]
                c = boundaries[i, 1]
                mixed = (p > 0 > c) or (p < 0 < c)
            previous = boundaries[i]
        i += 1
    return count, mixed, crossing_latitudes


# https://shapely.readthedocs.io/en/latest/reference/shapely.make_valid.html
# Added in version 2.1.0
_SHAPELY_SUPPORTS_NEW_MAKE_VALID = "method" in inspect.signature(shapely.make_valid).parameters


def rework_to_polygon_geometry(geometry: Geometry):
    """Rework the geometry to manage polar and antimeridian singularity.
    This process implements the **Polar inclusive algorithm**.
    The objective of this algorithm is to add the North/South Pole into
    the list of coordinates of geometry polygon at the antimeridian cross.

    When the geometry contains the pole the single polygon geometry including
    the pole in its border point list is properly interpreted by displays
    systems. When the geometry does not contain the pole, the geometry shall be
    split among the antimeridian line.

    :param geometry: the geometry crossing the antimeridian.
    :return: the modified geometry with the closest pole included at
     antimeridian crossing.
    """
    if not check_cross_antimeridian(geometry):
        return geometry

    count, mixed, latitudes = _num_cross_antimeridian(geometry)
    if mixed and count > 2:
        logger.debug(f"WARN: Crossing antimeridian {count} times ...")
        logger.debug(f" And crossing equator {_num_cross_equator(geometry)} times ...")
        logger.debug("Split footprint at equator to support polar inclusion")
        geometry = _split_crude_polygon_to_equator(geometry)
        rwrk = []
        for geom in geometry.geoms:
            reworked = rework_to_polygon_geometry(geom)
            if isinstance(reworked, BaseMultipartGeometry):
                for geo in reworked.geoms:
                    rwrk.append(geo)
            else:
                rwrk.append(reworked)
        rwrk = _merge_polygon_to_equator(rwrk)
        return rwrk

    # Manage case of multipolygon input
    if isinstance(geometry, shapely.geometry.MultiPolygon):
        rwrk = []
        for geom in geometry.geoms:
            reworked = rework_to_polygon_geometry(geom)
            if isinstance(reworked, BaseMultipartGeometry):
                raise AlreadyReworkedPolygonError("Algorithm not supported already reworked inputs.")
            rwrk.append(reworked)
        return shapely.geometry.MultiPolygon(rwrk)

    if not isinstance(geometry, shapely.geometry.Polygon):
        raise ValueError("Polygon and MultiPolygon features only are " f"supported ({type(geometry).__name__})")

    boundaries = np.array(shapely.get_coordinates(geometry))
    i = 0
    vertical_set = False
    vsign = 1
    while i < boundaries.shape[0] - 1:
        if abs(boundaries[i + 1, 0] - boundaries[i, 0]) > 180:
            if not vertical_set:
                vsign = -1 if boundaries[i, 1] < 0 else 1
                vertical_set = True
            hsign = -1 if boundaries[i, 0] < 0 else 1
            lat = _lat_cross_antimeridian(boundaries[i], boundaries[i + 1])
            boundaries = np.insert(
                boundaries,
                i + 1,
                [
                    [hsign * 180, lat],
                    [hsign * 180, vsign * 90],
                    [-hsign * 180, vsign * 90],
                    [-hsign * 180, lat],
                ],
                axis=0,
            )
            i += 5
        else:
            i += 1
    geometry_type = type(geometry)
    reworked = geometry_type(boundaries)

    # When the geometry does not contain pole: Cuts the geometry among the
    # antimeridian line.
    if not _check_contains_pole(reworked):
        reworked = _split_polygon_to_antimeridian(reworked)
    else:
        # Case of footprint crossing equator, antimeridian and polar zone
        # Split at the equator
        # Warn:
        if _num_cross_equator(reworked) > 1:
            reworked = _split_polygon_to_equator(reworked)
        # When footprint contains overlapping, it happens at polar location.
        # Polygon containing overlapping are considered invalid in shapely
        # library. It includes validity check and correction methods.
        # The shapely correction method extrude the overlap areas and fails
        # to generate patchwork of polygons at polar area. This is probably
        # due to the antimeridian crossing.
        # Shapely "buffer" method fixe"s the geometry merging overlapping
        # regions.
        if not shapely.is_valid(reworked):
            reworked = (
                shapely.make_valid(reworked, method="structure", keep_collapsed=False)
                if _SHAPELY_SUPPORTS_NEW_MAKE_VALID
                else shapely.make_valid(reworked)
            )

    return shapely.buffer(reworked, 0)
