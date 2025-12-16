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

"""Extension to compute the operation parts of CQL2 filter embedded in "interval" fields."""

import logging
from datetime import datetime

ACCEPTED_DATETIME_TEMPLATES = ["%Y-%m-%dT%H:%M:%S.%fZ"]

ACCEPTED_OPERATORS = ["+", "-"]

logger = logging.getLogger(__name__)


def process_filter_extensions(cql2_filter: dict | list) -> dict | list:
    """
    Recursive function, to process a filter and compute any operation subfilter existing in an 'interval' field.
    This kind of operation is not supported in native CQL2, so it replaces the subfilters with actual
    computed values to get a regular CQL2 filter.

    Args:
        cql2_filter (dict|list): any CQL2 filter or subfilter

    Returns:
        dict|list: regular-CQL2 compatible filter

    Raises:
        Cql2FilterFormattingError: if the subfilter to be processed is faulty
    """
    # If the filter is a list: treat each of its elements being a dict as a subfilter, ignore the other ones
    if isinstance(cql2_filter, list):
        for i, val in enumerate(cql2_filter):
            if isinstance(val, dict):
                cql2_filter[i] = process_filter_extensions(val)

    # If the filter is a dict: look for the 'interval' value that can contain a subfilter to process.
    # Iterate in case of any other value that is a dict or a list
    elif isinstance(cql2_filter, dict):
        for field in cql2_filter:
            if field == "interval":
                cql2_filter[field] = process_interval_field(cql2_filter[field])
            elif isinstance(cql2_filter[field], (dict, list)):
                cql2_filter[field] = process_filter_extensions(cql2_filter[field])

    return cql2_filter


def process_interval_field(interval: list) -> list:
    """
    Processes any operation inside an 'interval' field of a filter.

    Args:
        interval (list): Content of the 'interval' field

    Returns:
        list: New content for the 'interval' field
    """
    for i, element in enumerate(interval):
        # If any element in the interval contains field 'op' it means it's an operation to compute.
        # Otherwise, just ignore it.
        if isinstance(element, dict) and "op" in element:
            interval[i] = process_operation(element)
    return interval


def process_operation(operation: dict) -> str:
    """
    Process the operation given in the format of a CQL2 filter with 'op' and 'args' fields.
    The operation must follow the expected format to be processed: either a '+' or '-' operator and
    exactly two arguments.

    Args:
        operation (dict): Operation to process as a CQL2 formatted dictionary

    Returns:
        str: Result of the operation, usually a datetime or a number

    Raises:
        Cql2FilterFormattingError: If the given dictionary doesn't have the expected format.
    """
    if ("op" and "args") not in operation:
        raise Cql2FilterFormattingError(f"Missing field 'op' or 'args' in operation filter: {operation}")

    if not isinstance(operation["args"], list) or len(operation["args"]) != 2:
        raise Cql2FilterFormattingError(f"Expected exactly two values in field 'args': {operation}")

    if not isinstance(operation["op"], str) or operation["op"] not in ACCEPTED_OPERATORS:
        raise Cql2FilterFormattingError(
            f"Unknown operator: {operation['op']}. Accepted operators are: {ACCEPTED_OPERATORS}.",
        )

    logger.debug(f"Processing following sub-filter: {operation}")
    return compute_values(operation["args"], operation["op"])


def compute_values(values: list[str | int | float], operator: str = "+") -> str:
    """Computes the values given using the operator given. Supports any datetime matching one of the
    accepted templates, and returns a datetime matching the same template if one is in the inputs.

    Args:
        values (list[str|int|float]): List of values to compute. Can be datetimes (as str)
            or numbers (as str, int or float).
        operator (str): Operator to use for the calculation. Currently supports "+" and "-"

    Returns:
        str: Result of the operation. Can be a datetime or a number, but always as an str for consistency.
    """
    # If any of the input values is a datetime the operation will return a new datetime
    return_datetime = False
    return_dateformat = ""
    logger.debug(f"Computing values {values} with operator '{operator}'")

    # All "datetime" values are converted into POSIX timestamps
    for i, val in enumerate(values):
        if isinstance(val, str):
            date, dateformat = parse_datetime(val)
            if date:
                return_datetime = True
                return_dateformat = dateformat
                values[i] = date.timestamp()
            else:
                try:
                    values[i] = float(val)
                except ValueError as exc:
                    raise Cql2FilterFormattingError(
                        f"Cannot process value {val}: only int, float or valid datetimes are allowed.",
                    ) from exc

    # Compute the result depending on the operator
    result = values[0]
    if operator == "+":
        for val in values[1:]:
            result = result + val  # type: ignore
    elif operator == "-":
        for val in values[1:]:
            result = result - val  # type: ignore

    # Convert again into a datetime if necessary
    if return_datetime:
        new_datetime = datetime.fromtimestamp(result).strftime(return_dateformat)  # type: ignore
        logger.debug(f"Computed new datetime: {new_datetime}.")
        return new_datetime
    logger.debug(f"Computed new value: {result}")
    return str(result)


def parse_datetime(value: str) -> tuple[datetime | None, str]:
    """Returns the given value as a 'datetime' object if it matches any of the accepted templates.

    Args:
        value (str): Value to parse

    Returns:
        tuple[datetime, str]: The parsed date as a datetime and the template matching the initial value if any.
            Empty values if the input doesn't match any template.
    """
    for template in ACCEPTED_DATETIME_TEMPLATES:
        try:
            date = datetime.strptime(value, template)
            return date, template
        except ValueError:
            continue
    logger.debug(f"Value {value} is not matching any datetime format.")
    return None, ""


class Cql2FilterFormattingError(Exception):
    """Thrown when a filter or subfilter is wrongly formatted."""
