# Copyright 2025 CS Group
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

"""Integration tests for user_catalog module."""

import json
import os

import fastapi


def test_status_code_200_docs_if_good_endpoints(client):  # pylint: disable=missing-function-docstring
    response = client.get("/catalog/api.html")
    assert response.status_code == fastapi.status.HTTP_200_OK
    print(f"Response vaut: {response}")


def test_update_stac_catalog_metadata(client):
    """
    Test the update of the stac catalog metadata when the `/catalog/ endpoint is called
    """
    default_txt = "stac-fastapi"
    id_txt = "rs-python"
    title_txt = "RS-PYTHON STAC Catalog"
    description_txt = "STAC catalog of Copernicus Reference System Python"

    response = client.get("/catalog/")
    assert response.status_code == fastapi.status.HTTP_200_OK
    resp_dict = json.loads(response.content)
    assert resp_dict["id"] == default_txt
    assert resp_dict["title"] == default_txt
    assert resp_dict["description"] == default_txt

    os.environ["CATALOG_METADATA_ID"] = id_txt
    response = client.get("/catalog/")
    assert response.status_code == fastapi.status.HTTP_200_OK
    resp_dict = json.loads(response.content)
    assert resp_dict["id"] == id_txt
    assert resp_dict["title"] == default_txt
    assert resp_dict["description"] == default_txt

    os.environ["CATALOG_METADATA_TITLE"] = title_txt
    os.environ["CATALOG_METADATA_DESCRIPTION"] = description_txt
    response = client.get("/catalog/")
    assert response.status_code == fastapi.status.HTTP_200_OK
    resp_dict = json.loads(response.content)
    assert resp_dict["id"] == id_txt
    assert resp_dict["title"] == title_txt
    assert resp_dict["description"] == description_txt


def test_queryables(client):
    """
    Test Queryables feature endpoint.s
    """
    response = client.get("/catalog/queryables")
    assert response.status_code == fastapi.status.HTTP_200_OK


def test_catalog_catalogs_owner_id_is_disabled(client):
    """
    Test that the endpoint /catalog/catalogs/{owner_id} is no longer working as expected.
    """

    response = client.get("/catalog/catalogs/toto")
    assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST


def test_queryables_with_empty_catalog(client_with_empty_catalog):
    """
    Test Queryables feature endpoint when catalog has no collections in it
    """
    response_empty = client_with_empty_catalog.get("/catalog/queryables")

    assert response_empty.status_code == fastapi.status.HTTP_200_OK
    expected_response = {
        "$id": f"{client_with_empty_catalog.base_url}/queryables",
        "type": "object",
        "title": "STAC Queryables.",
        "$schema": "https://json-schema.org/draft-07/schema#",
        "properties": {},
        "additionalProperties": True,
    }
    assert response_empty.json() == expected_response  # JSON Content Check
