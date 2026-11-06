# Copyright 2023-2026 Airbus, CS Group
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

"""Combine AUXIP/PRIP mission restrictions without losing constellation/serial associations.

For example, S1A and S2B must remain two pairs: splitting them into independent
constellation and serial lists would also allow S1B and S2A.
"""

from itertools import product

from fastapi import HTTPException
from rs_server_common.utils.utils import map_auxip_prip_mission

# Internal search field passed from the STAC layer to the EODAG provider.
MISSION_PAIRS = "mission_pairs"
# Each pair contains (platformShortName, platformSerialIdentifier), e.g. ("SENTINEL-1", "A").
Mission = tuple[str | None, str | None]
# Pairs are alternatives (OR). None means unrestricted; () means no match.
# A None component is a wildcard: ("SENTINEL-1", None) allows any Sentinel-1 serial.
MissionSelection = tuple[Mission, ...] | None


def _values(value: str | list[str]) -> list[str]:
    """Read a YAML list or comma-separated string, trimming and validating each entry.

    An empty list is valid and selects nothing; empty strings are rejected.
    """
    values = value.split(",") if isinstance(value, str) else value
    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
        raise HTTPException(422, "Mission restrictions must contain non-empty strings")
    return [v.strip() for v in values]


def normalize_missions(missions) -> tuple[Mission, ...]:
    """Uppercase and deduplicate complete pairs, sorting them for stable comparisons and filters."""
    pairs = {(c.upper() if c else None, s.upper() if s else None) for c, s in missions}
    return tuple(sorted(pairs, key=lambda pair: (pair[0] or "", pair[1] or "")))


def intersect_missions(left: MissionSelection, right: MissionSelection) -> MissionSelection:
    """Keep identities allowed by both selections, resolving wildcards to concrete values.

    For example, ("SENTINEL-1", None) intersected with ("SENTINEL-1", "A")
    yields ("SENTINEL-1", "A"). Conflicting constellations or serials cannot match.
    """
    if left is None:
        return right
    if right is None:
        return left
    # Combine only compatible pairs; an empty selection naturally produces no pairs.
    # lc/ls are the left pair's constellation/serial; rc/rs are the right pair's.
    # A None component is a wildcard, so keep the concrete value from either pair.
    return normalize_missions(
        (lc or rc, ls or rs)
        for (lc, ls), (rc, rs) in product(left, right)
        if (lc is None or rc is None or lc == rc) and (ls is None or rs is None or ls == rs)
    )


def extract_missions(query: dict) -> tuple[dict, MissionSelection]:
    """Return non-mission criteria and the intersection of all mission restrictions.

    Accept internal pairs, complete STAC platform names and legacy OData fields.
    The input dict is preserved; absent restrictions yield None, disjoint ones yield ().
    """
    remaining = query.copy()
    missions = remaining.pop(MISSION_PAIRS, None)
    if missions is not None:
        missions = normalize_missions(missions)

    if "platform" in remaining:
        # Complete names preserve the intended pairing, e.g. sentinel-2b -> (SENTINEL-2, B).
        platforms = _values(remaining.pop("platform"))
        configured = normalize_missions(map_auxip_prip_mission(p.lower(), None) for p in platforms)
        missions = intersect_missions(missions, configured)

    constellations = remaining.pop("platformShortName", None)
    serials = remaining.pop("platformSerialIdentifier", None)
    if constellations is not None or serials is not None:
        # Legacy fields constrain each attribute independently, so all combinations are allowed.
        # A missing field is a wildcard. Intersect with explicit pairs to retain their restrictions.
        legacy = normalize_missions(
            product(
                _values(constellations) if constellations is not None else [None],
                _values(serials) if serials is not None else [None],
            ),
        )
        missions = intersect_missions(missions, legacy)
    return remaining, missions


def matches_mission(entity: dict, missions: MissionSelection) -> bool:
    """Check an OData product's collection membership using the same pairs as station filtering."""
    # No mission restriction means every product is eligible.
    if missions is None:
        return True
    # Normalize product attributes to the same case as the configured pairs.
    constellation = str(entity.get("platformShortName") or "").strip().upper()
    serial = str(entity.get("platformSerialIdentifier") or "").strip().upper()
    # Both attributes must match within one pair; None accepts any value for that attribute.
    # Any matching pair is sufficient, while an empty selection matches no product.
    return any((c is None or c == constellation) and (s is None or s == serial) for c, s in missions)


def mission_search_params(missions: MissionSelection) -> dict:
    """Convert pairs to EODAG parameters while preserving their exact meaning.

    Independent attribute filters are sufficient for a full Cartesian product.
    Otherwise, return an internal OData fragment with OR between complete pairs.
    """
    if missions is None:
        return {}
    if not missions:
        return {"missionFilter": "false"}
    constellations = {c for c, _ in missions}
    serials = {s for _, s in missions}
    # Separate filters are safe only if recombining the attributes adds no new pairs: S1A/S1B is safe, S1A/S2B is not.
    # An attribute can be omitted only when it is a wildcard in every pair.
    if set(product(constellations, serials)) == set(missions) and all(
        None not in values or values == {None} for values in (constellations, serials)
    ):
        return {
            key: sorted(values)
            for key, values in (("platformShortName", constellations), ("platformSerialIdentifier", serials))
            if values != {None}
        }

    clauses = []
    # Build one AND group per pair, then join those groups with OR.
    for constellation, serial in missions:
        attributes = []
        for name, value in (("platformShortName", constellation), ("platformSerialIdentifier", serial)):
            # A wildcard adds no condition for this attribute.
            if value is not None:
                # OData string literals escape apostrophes by doubling them.
                literal = value.replace("'", "''")
                # The two attributes are separate entries, each requiring its own any(...).
                attributes.append(
                    f"Attributes/OData.CSC.StringAttribute/any(att:att/Name eq '{name}' "
                    f"and att/OData.CSC.StringAttribute/Value eq '{literal}')",
                )
        clauses.append("(" + " and ".join(attributes) + ")")
    # Group the entire OR so product, date and geometry filters can be ANDed with it.
    return {"missionFilter": "(" + " or ".join(clauses) + ")"}
