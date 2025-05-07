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

from datetime import datetime
from typing import Any

from eodag import EOProduct
from fastapi import HTTPException, status
from rs_server_common.utils.logging import Logging

# pylint: disable=too-few-public-methods

logger = Logging.default(__name__)

# TODO: the value was set to 1.8s but it sometimes doesn't pass the CI in github.
DWN_THREAD_START_TIMEOUT = 5


def is_valid_date_format(date: str) -> bool:
    """Check if a string adheres to the expected date format "YYYY-MM-DDTHH:MM:SS[.sss]Z".

    Args:
        date (str): The string to be validated for the specified date format.

    Returns:
        bool: True if the input string adheres to the expected date format, otherwise False.

    """
    try:
        datetime.strptime(date, "%Y-%m-%dT%H:%M:%SZ")  # test without milliseconds
        return True
    except ValueError:
        try:
            datetime.strptime(date, "%Y-%m-%dT%H:%M:%S.%fZ")  # test with milliseconds
            return True
        except ValueError:
            pass
    return False


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
) -> Any:
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

    for date in [fixed_date, start_date, stop_date]:
        if date.strip("'\".") and not is_valid_date_format(date):
            logger.info("Invalid start/stop in endpoint call!")
            if raise_errors:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing start/stop")
            return None, None, None

    def to_dt(dates) -> list[Any]:
        """Converts a list of date strings to datetime objects or None if the conversion fails."""
        return [datetime.fromisoformat(date) if is_valid_date(date) else None for date in dates]

    def is_valid_date(date: str) -> bool:
        """Check if the string can be converted to a valid datetime."""
        try:
            datetime.fromisoformat(date)
            return True
        except ValueError:
            return False

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


def odata_to_stac(feature_template: dict, odata_dict: dict, odata_stac_mapper: dict) -> dict:
    """
    Maps OData values to a given STAC template.

    Args:
        feature_template (dict): The STAC feature template to be populated.
        odata_dict (dict): The dictionary containing OData values.
        odata_stac_mapper (dict): The mapping dictionary for converting OData keys to STAC properties.

    Returns:
        dict: The populated STAC feature template.

    Raises:
        ValueError: If the provided STAC feature template is invalid.
    """
    if not all(item in feature_template.keys() for item in ["properties", "id", "assets"]):
        raise ValueError("Invalid stac feature template")
    for stac_key, eodag_key in odata_stac_mapper.items():
        if eodag_key in odata_dict:
            if stac_key in feature_template["properties"]:
                feature_template["properties"][stac_key] = odata_dict[eodag_key]
            elif stac_key == "id":
                feature_template["id"] = odata_dict[eodag_key]
            elif stac_key in feature_template["assets"]["file"]:
                feature_template["assets"]["file"][stac_key] = odata_dict[eodag_key]
    # to pass pydantic validation, make sure we don't have a single timerange value
    check_and_fix_timerange(feature_template)
    return feature_template


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


def validate_sort_input(sortby: str):
    """Used to transform stac sort parameter to odata type.
    -datetime = startTimeFromAscendingNode DESC.
    """
    sortby = sortby.strip("'\"").lower().replace("properties.", "")
    return [(sortby[1:] if sortby[0] in ["-", "+"] else sortby, "DESC" if sortby[0] == "-" else "ASC")]


def strftime_millis(date: datetime):
    """Format datetime with milliseconds precision"""
    return date.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
