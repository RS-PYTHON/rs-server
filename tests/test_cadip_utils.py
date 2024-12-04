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

"""Unit tests for the CADIP utilities."""

import json
import os.path as osp
from datetime import datetime, timezone
from pathlib import Path

from rs_server_cadip.cadip_utils import link_assets_to_session
from stac_pydantic import Item, ItemCollection, ItemProperties
from stac_pydantic.links import Links

CADIP_CONFIG = Path(osp.realpath(osp.dirname(__file__))).parent / "services/cadip/config"


def test_link_assets_to_session_no_start_no_end():
    """start_datetime not set, end_datetime not set"""
    do_test_link_assets_to_session(False, False)


def test_link_assets_to_session_no_start_but_end():
    """start_datetime not set, end_datetime set"""
    do_test_link_assets_to_session(False, True)


def test_link_assets_to_session_start_no_end():
    """start_datetime set, end_datetime not set"""
    do_test_link_assets_to_session(True, False)


def test_link_assets_to_session_start_and_end():
    """start_datetime set, end_datetime set"""
    do_test_link_assets_to_session(True, True)


def do_test_link_assets_to_session(start: bool, end: bool):
    """checks correct behaviour of link_assets_to_session for timerange properties"""
    with open(CADIP_CONFIG / "cadip_stac_mapper.json", encoding="utf-8") as mapper:
        item: Item = Item(
            type="Feature",
            stac_version="1.0.0",
            id="S1A_20241202183845056817",
            properties=ItemProperties(
                datetime=datetime.fromisoformat("2024-12-02T18:38:45").replace(tzinfo=timezone.utc),
                start_datetime=(
                    datetime.fromisoformat("2024-12-02T18:00:00").replace(tzinfo=timezone.utc) if start else None
                ),
                end_datetime=(
                    datetime.fromisoformat("2024-12-02T18:00:00").replace(tzinfo=timezone.utc) if start else None
                ),
                gsd=None,
            ),
            geometry=None,
            assets={},
            links=Links([]),
        )
        session_data = ItemCollection(features=[item], type="FeatureCollection")
        assets: list[dict] = (
            [
                {
                    "Name": "chunk_1.tgz",
                    "SessionId": "S1A_20241202183845056817",
                    "PublicationDate": "2024-12-02T18:49:55Z",
                    "href": "https://localhost/chunk_1.tgz",
                },
            ]
            if end
            else []
        )

        link_assets_to_session(session_data, assets, json.loads(mapper.read()))

        assert item.properties.datetime == datetime(  # pylint: disable=no-member
            2024,
            12,
            2,
            18,
            38,
            45,
            tzinfo=timezone.utc,
        )  # pylint: disable=no-member
        if start and end:
            assert item.properties.start_datetime == datetime(  # pylint: disable=no-member
                2024,
                12,
                2,
                18,
                0,
                0,
                tzinfo=timezone.utc,
            )
            assert item.properties.end_datetime == datetime(  # pylint: disable=no-member
                2024,
                12,
                2,
                18,
                49,
                55,
                tzinfo=timezone.utc,
            )
        else:
            assert item.properties.start_datetime is None  # pylint: disable=no-member
            assert item.properties.end_datetime is None  # pylint: disable=no-member
