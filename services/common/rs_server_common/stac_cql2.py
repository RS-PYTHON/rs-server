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

"""Module to parse CQL2 filter expressions, adapted from pgstac.sql,
see https://github.com/stac-utils/pgstac/blob/main/src/pgstac/pgstac.sql"""

import json
import re
from datetime import datetime, timedelta, timezone

from .utils.utils import strftime_millis

temporal_operations = {
    "t_before": "lh < rl",
    "t_after": "ll > rh",
    "t_meets": "lh = rl",
    "t_metby": "ll = rh",
    "t_overlaps": "ll < rl and rl < lh and lh < rh",
    "t_overlappedby": "rl < ll and ll < rh and lh > rh",
    "t_starts": "ll = rl and lh < rh",
    "t_startedby": "ll = rl and lh > rh",
    "t_during": "ll > rl and lh < rh",
    "t_contains": "ll < rl and lh > rh",
    "t_finishes": "ll > rl and lh = rh",
    "t_finishedby": "ll < rl and lh = rh",
    "t_equals": "ll = rl and lh = rh",
    "t_disjoint": "not (ll <= rh and lh >= rl)",
    "t_intersects": "ll <= rh and lh >= rl",
}


def parse_dtrange(  # noqa: C901 # pylint: disable=too-many-branches
    _indate: str | dict | list,
    relative_base: datetime | None = None,
) -> tuple[datetime, datetime]:
    """parse datetime range"""
    if relative_base is None:
        relative_base = datetime.now(timezone.utc)

    if isinstance(_indate, str):
        try:
            _indate = json.loads(_indate)
        except json.JSONDecodeError:
            _indate = [_indate]

    if isinstance(_indate, dict):
        if "timestamp" in _indate:
            timestrs = [_indate["timestamp"]]
        elif "interval" in _indate:
            timestrs = _indate["interval"] if isinstance(_indate["interval"], list) else [_indate["interval"]]
        else:
            timestrs = re.split(r"/", _indate.get("0", ""))
    elif isinstance(_indate, list):
        timestrs = _indate
    else:
        raise ValueError(f"Invalid input format: {_indate}")

    if len(timestrs) == 1:
        if timestrs[0].upper().startswith("P"):
            delta = parse_interval(timestrs[0])
            return (relative_base - delta, relative_base)
        s = datetime.fromisoformat(timestrs[0])
        return (s, s)

    if len(timestrs) != 2:
        raise ValueError(f"Timestamp cannot have more than 2 values: {timestrs}")

    if timestrs[0] in ["..", ""]:
        s = datetime.min
        e = datetime.fromisoformat(timestrs[1])
    elif timestrs[1] in ["..", ""]:
        s = datetime.fromisoformat(timestrs[0])
        e = datetime.max
    elif timestrs[0].upper().startswith("P") and not timestrs[1].upper().startswith("P"):
        e = datetime.fromisoformat(timestrs[1])
        s = e - parse_interval(timestrs[0])
    elif timestrs[1].upper().startswith("P") and not timestrs[0].upper().startswith("P"):
        s = datetime.fromisoformat(timestrs[0])
        e = s + parse_interval(timestrs[1])
    else:
        s = datetime.fromisoformat(timestrs[0])
        e = datetime.fromisoformat(timestrs[1])

    return (s, e)


def parse_interval(interval: str) -> timedelta:
    """parse interval"""
    match = re.match(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", interval.upper())
    if match:
        days, hours, minutes, seconds = (int(v) if v else 0 for v in match.groups())
        return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    raise ValueError(f"Invalid interval format: {interval}")


def temporal_op_query(op: str, args: list[dict], temporal_mapping: dict[str, str]) -> str:
    """temporal operation query"""
    if op.lower() not in temporal_operations:
        raise ValueError(f"Invalid temporal operator: {op}")
    if not temporal_mapping:
        raise ValueError("Undefined temporal property mapping")

    props: list[dict] = args[0]["interval"] if "interval" in args[0].keys() else [args[0]]
    rrange = parse_dtrange(args[1])
    outq = (
        temporal_operations[op.lower()]
        .replace("ll", temporal_mapping[props[0]["property"]])
        .replace("lh", temporal_mapping[props[1 if len(props) > 1 else 0]["property"]])
        .replace("rl", strftime_millis(rrange[0]))
        .replace("rh", strftime_millis(rrange[1]))
        .replace("<=", "lte")
        .replace(">=", "gte")
        .replace("=", "eq")
        .replace("<", "lt")
        .replace(">", "gt")
    )
    return f"({outq})"
