# Copyright 2024 CS Group
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

"""This module is used to share common functions between apis endpoints"""

import os
import os.path as osp
import traceback
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from threading import Thread
from typing import Any

import yaml
from dateutil.parser import isoparse
from eodag import EOProduct
from fastapi import HTTPException, status
from rs_server_common.utils.logging import Logging

# pylint: disable=too-few-public-methods
logger = Logging.default(__name__)
LOCAL_PTYPE_MAPPING_FILE = (
    Path(osp.realpath(osp.dirname(__file__))).parent.parent / "config" / "product_type_mapping.yaml"
)
PTYPE_MAPPING_FILE = Path(os.environ.get("PTYPE_MAPPING_CONFIG", LOCAL_PTYPE_MAPPING_FILE))
with PTYPE_MAPPING_FILE.open("r", encoding="utf-8") as f:
    product_type_data = yaml.safe_load(f)["types"]


def validate_str_list(parameter: str) -> list | str:
    """
    Validates and parses a parameter that can be either a string or a comma-separated list of strings.

    The function processes the input parameter to:
    - Strip whitespace from each item in a comma-separated list.
    - Return a single string if the list has only one item.
    - Return a list of strings if the input contains multiple valid items.

    Examples:
        - Input: 'S1A'
          Output: 'S1A' (str)

        - Input: 'S1A, S2B'
          Output: ['S1A', 'S2B'] (list of str)

          # Test case bgfx, when input contains ',' but not a validd value, output should not be ['S1A', '']
        - Input: 'S1A,'
          Output: 'S1A' (str)

        - Input: 'S1A, S2B, '
          Output: ['S1A', 'S2B'] (list of str)
    """
    if parameter and "," in parameter:
        items = [item.strip() for item in parameter.split(",") if item.strip()]
        return items if len(items) > 1 else items[0]
    return parameter


def validate_inputs_format(
    date_time: str,
    raise_errors: bool = True,
) -> tuple[datetime | None, datetime | None, datetime | None]:
    """
    Validate the format and content of a time interval string.

    This function checks whether the provided time interval string is in a valid format and
    whether the start and stop dates conform to the ISO 8601 standard. It supports a variety
    of interval formats, including open-ended intervals.

    Args:
        date_time (str): The time interval string to validate. Supported formats include:
            - "2024-01-01T00:00:00Z/2024-01-02T23:59:59Z" (closed interval)
            - "../2024-01-02T23:59:59Z" (open start interval)
            - "2024-01-01T00:00:00Z/.." (open end interval)
            - "2024-01-01T00:00:00Z" (fixed date)
        raise_errors (bool): If True, raises an exception for invalid input.
            If False, returns [None, None, None] for invalid input.

    Returns:
        List[Union[datetime, None]]: A list containing three elements:
            - fixed_date (datetime or None): The single fixed date if applicable.
            - start_date (datetime or None): The start date of the interval.
            - stop_date (datetime or None): The stop date of the interval.
            Returns [None, None, None] if the input is invalid or empty.

    Raises:
        HTTPException: If `raise_errors` is True and the input is invalid, an HTTP 400 or 422
            error is raised.

    Note:
        - The input interval should use the ISO 8601 format for dates and times.
        - If using an open-ended interval, one side of the interval can be omitted
          (e.g., "../2024-01-02T23:59:59Z").
    """
    fixed_date, start_date, stop_date = "", "", ""
    if not date_time:
        return None, None, None
    try:
        if "/" in date_time:
            # Open/Closed interval, ../2018-02-12T23:20:50Z or 2018-02-12T23:20:50Z/..
            start_date, stop_date = date_time.split("/")
        else:
            fixed_date = date_time
    except ValueError as exc:
        logger.error("Missing start or stop in endpoint call!")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Missing start/stop") from exc

    def is_valid_date(date: str) -> bool:
        """Check if the string can be converted to a valid datetime."""
        try:
            isoparse(date)
            return True
        except ValueError:
            return False

    for date in [fixed_date, start_date, stop_date]:
        if date.strip("'\".") and not is_valid_date(date):
            message: str = f"Invalid date: {date}"
            logger.warning(message)
            if raise_errors:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)
            return None, None, None

    def to_dt(dates: list[str]) -> list[datetime | None]:
        """Converts a list of date strings to datetime objects or None if the conversion fails."""
        return [isoparse(date) if is_valid_date(date) else None for date in dates]

    fixed_date_dt, start_date_dt, stop_date_dt = to_dt([fixed_date, start_date, stop_date])

    # if fixed_date_dt and "." not in fixed_date:
    #     # If miliseconds are not defined, don't set to .000Z create a timeinterval, to gather all products
    #     # from that milisecond
    #     start_date_dt = fixed_date_dt.replace(microsecond=0)  # type: ignore
    #     stop_date_dt = fixed_date_dt.replace(microsecond=999999)  # type: ignore
    #     fixed_date_dt = None
    #     return fixed_date_dt, start_date_dt, stop_date_dt
    # if stop_date_dt and "." not in stop_date:
    #     # If stop_date interval miliseconds value is not defined, set it to 999
    #     stop_date_dt = stop_date_dt.replace(microsecond=999999)  # type: ignore

    return fixed_date_dt, start_date_dt, stop_date_dt


@lru_cache
def map_stac_platform() -> dict:
    """Function used to read and interpret from constellation.yaml"""
    with open(Path(__file__).parent.parent.parent / "config" / "constellation.yaml", encoding="utf-8") as cf:
        return yaml.safe_load(cf)


def map_auxip_prip_mission(platform: str, constellation: str) -> tuple[str | None, str | None]:
    """
    Custom function for ADGS/PRIP, to read constellation mapper and return propper
    values for platform and serial.
    Eodag maps this values to platformShortName, platformSerialIdentifier

    Input: platform = sentinel-1a       Output: sentinel-1, A
    Input: platform = sentinel-5P       Output: sentinel-5p, None
    Input: constellation = sentinel-1   Output: sentinel-1, None
    """
    data = map_stac_platform()
    platform_short_name: str | None = None
    platform_serial_identifier: str | None = None
    try:
        if platform:
            config = next(satellite[platform] for satellite in data["satellites"] if platform in satellite)
            platform_short_name = config.get("constellation", None)
            platform_serial_identifier = config.get("serialid", None)
        if constellation:
            if platform_short_name and platform_short_name != constellation:
                # Inconsistent combination of platform / constellation case
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Invalid combination of platform-constellation",
                )
            if any(
                satellite[list(satellite.keys())[0]]["constellation"] == constellation
                for satellite in data["satellites"]
            ):
                platform_short_name = constellation
                platform_serial_identifier = None
            else:
                raise KeyError
    except (KeyError, IndexError, StopIteration) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot map platform/constellation",
        ) from exc
    return platform_short_name, platform_serial_identifier


def reverse_adgs_prip_map_mission(
    platform: str | None,
    constellation: str | None,
) -> tuple[str | None, str | None]:
    """Function used to re-map platform and constellation based on satellite value."""
    if not (constellation or platform):
        return None, None

    if constellation:
        constellation = constellation.lower()  # type: ignore

    for satellite in map_stac_platform()["satellites"]:
        for key, info in satellite.items():
            # Check for matching serialid and constellation
            if info.get("serialid") == platform and info.get("constellation").lower() == constellation:
                return key, info.get("constellation")
    return None, None


def odata_to_stac(
    feature_template: dict,
    odata_dict: dict,
    odata_stac_mapper: dict,
    collection_provider: Callable[[dict], str | None] | None = None,
) -> dict:
    """
    Maps OData values to a given STAC template.

    Args:
        feature_template (dict): The STAC feature template to be populated.
        odata_dict (dict): The dictionary containing OData values.
        odata_stac_mapper (dict): The mapping dictionary for converting OData keys to STAC properties.
        collection_provider (Callable[[dict], str | None]): optional function that determines STAC collection
                                                            for a given OData entity

    Returns:
        dict: The populated STAC feature template.

    Raises:
        ValueError: If the provided STAC feature template is invalid.
    """
    if not all(item in feature_template.keys() for item in ["properties", "id", "assets"]):
        raise ValueError("Invalid stac feature template")
    for stac_key, eodag_key in odata_stac_mapper.items():
        if eodag_key not in odata_dict:
            if stac_key in feature_template["properties"]:
                feature_template["properties"].pop(stac_key, None)
            continue
        value = odata_dict[eodag_key]
        if stac_key in feature_template["properties"]:
            feature_template["properties"][stac_key] = [value] if stac_key == "instruments" else value
            continue
        if stac_key == "id":
            feature_template["id"] = value
            continue
        if stac_key == "geometry":
            feature_template["geometry"] = value
            feature_template["bbox"] = _bbox_from_geometry(feature_template["geometry"])
            continue
        if stac_key in feature_template["assets"]["file"]:
            feature_template["assets"]["file"][stac_key] = value

    _apply_product_facets(feature_template, odata_dict)

    # to pass pydantic validation, make sure we don't have a single timerange value
    check_and_fix_timerange(feature_template)
    # determine item collection
    if collection_provider:
        feature_template["collection"] = collection_provider(odata_dict)
        if not feature_template["collection"]:
            logger.warning(f"Unable to determine collection for {odata_dict}")
    return feature_template


def _bbox_from_geometry(geom: dict) -> list[float]:
    """Compute [minLon, minLat, maxLon, maxLat] from GeoJSON Polygon."""
    t = (geom.get("type") or "").lower()

    def _extrema(points):
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return [min(xs), min(ys), max(xs), max(ys)]

    if t == "polygon":
        ring = (geom.get("coordinates") or [[]])[0] or []
        return _extrema(ring) if ring else []
    return []


def check_and_fix_timerange(item: dict):
    """This function ensures the item does not have a single timerange value"""
    properties = item.get("properties", {})

    start_dt = properties.get("start_datetime")
    end_dt = properties.get("end_datetime")
    dt = properties.get("datetime")

    if start_dt and not end_dt:
        properties["end_datetime"] = max(start_dt, dt) if dt else start_dt
        logger.warning(f"Forced end_datetime property in {item}")
    elif end_dt and not start_dt:
        properties.pop("end_datetime", None)
        logger.warning(f"Removed end_datetime property from {item}")


def extract_eo_product(eo_product: EOProduct, mapper: dict) -> dict:
    """This function is creating key:value pairs from an EOProduct properties"""
    eo_product.properties.update(
        {item.get("Name", None): item.get("Value", None) for item in eo_product.properties.get("attrs", [])},
    )
    return {key: value for key, value in eo_product.properties.items() if key in mapper.values()}


def _apply_product_facets(feature: dict, _odata: dict) -> None:
    """Sets product:type, processing:level - temporary hardcoded until RSPY-760 is DONE"""
    props: dict[str, str] = feature["properties"]
    if not (
        all(k in props for k in ("product:type", "processing:level"))
        and any(k in props for k in ("sar:instrument_mode", "eopf:instrument_mode", "instrument_mode"))
    ):
        return
    legacy_type: dict[str, str] = next(
        (item for item in product_type_data if item.get("legacyType") == props["product:type"]),
        {},
    )
    props["product:type"] = legacy_type["productType"]
    props["processing:level"] = legacy_type["processingLevel"]

    instrument_mode_key = "eopf:instrument_mode" if legacy_type["mission"] == "S2" else "sar:instrument_mode"

    # Remove any previous/generic instrument_mode keys, then set the selected one
    for k in ("instrument_mode", "sar:instrument_mode", "eopf:instrument_mode"):
        props.pop(k, None)

    props[instrument_mode_key] = legacy_type["instrumentMode"]


def validate_sort_input(sortby: str):
    """Used to transform stac sort parameter to odata type.
    -datetime = startTimeFromAscendingNode DESC.
    """
    sortby = sortby.strip("'\"").lower().replace("properties.", "")
    return [(sortby[1:] if sortby[0] in ["-", "+"] else sortby, "DESC" if sortby[0] == "-" else "ASC")]


def strftime_millis(date: datetime):
    """Format datetime with milliseconds precision"""
    return date.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def run_threads(threads: Iterable[Thread]) -> None:
    """Start all threads, then join them."""
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def run_in_threads(
    func: Callable[..., Any],
    args_list: Sequence[tuple],
    max_workers: int | None = None,
) -> list[Any]:
    """
    Executes a function in parallel using threads, and returns the list of non-None results.

    Each thread runs `func` with the corresponding arguments provided in `args_list`.

    Args:
        func (Callable[..., Any]): The function to be executed concurrently.
        args_list (Sequence[tuple]): A sequence of argument tuples for each thread.
        max_workers (int | None): The maximum number of threads to use.

    Returns:
        list[Any]: A list of results, one per thread, excluding any result that is None, in the same order as args_list.
    """
    results: list[Any] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for future in [executor.submit(func, *args) for args in args_list]:
            try:
                if (result := future.result()) is not None:
                    results.append(result)
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(traceback.format_exc())
                results.append(e)
    return results
