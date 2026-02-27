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

"""Tests endpoint for patching collections or items in catalog"""

import copy
import json

import fastapi


def test_patch_collection(client):
    """
    Test endpoint PATCH /catalog/collections/owner:collection_id.

    Test procedure:
    - Create new minimal collection
    - Test that collection is created with proper fields
    - Patch "description" value of collection
    - Test that the same collection has the same values except for the description
    """
    minimal_collection = {
        "id": "test_collection_for_patch",
        "type": "Collection",
        "description": "test_description",
        "stac_version": "1.1.0",
        "owner": "test_owner",
        "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
        "license": "public-domain",
        "extent": {
            "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
            "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
        },
    }
    response = client.post("/catalog/collections", json=minimal_collection)
    # Check that collection status code is 201 or 409 (if it already exists)
    assert response.status_code in (fastapi.status.HTTP_201_CREATED, fastapi.status.HTTP_409_CONFLICT)

    # Test that /catalog/collection GET endpoint returns the correct collection id
    response = client.get("/catalog/collections/test_owner:test_collection_for_patch")
    assert response.status_code == fastapi.status.HTTP_200_OK
    response_content = json.loads(response.content)
    # Check that values are correctly written in catalogDB
    assert response_content["id"] == minimal_collection["id"]
    assert response_content["owner"] == minimal_collection["owner"]
    assert response_content["description"] == minimal_collection["description"]
    created_timestamp = response_content["created"]
    # TODO uncomment this line and the assert associated once the bug on the "updated"
    # timestamp being unpatchable is fixed
    # updated_timestamp = response_content["updated"]
    # We don't check every values because that's something that is already done in another test

    # Patch description
    patch_values = {"description": "new_test_description"}
    patch_response = client.patch("/catalog/collections/test_owner:test_collection_for_patch", json=patch_values)
    assert patch_response.status_code == fastapi.status.HTTP_200_OK

    # Test that /catalog/collection GET endpoint returns the correct collection id with updated description
    response = client.get("/catalog/collections/test_owner:test_collection_for_patch")
    assert response.status_code == fastapi.status.HTTP_200_OK
    response_content = json.loads(response.content)
    # Check that values are correctly written in catalogDB
    assert response_content["id"] == minimal_collection["id"]
    assert response_content["owner"] == minimal_collection["owner"]
    assert response_content["description"] == patch_values["description"]  # Check patched value
    assert response_content["created"] == created_timestamp  # Check that "created" date didn't change
    # assert response_content["updated"] > updated_timestamp # Check that "updated" date changed and is newer


def test_patch_feature(client, a_minimal_collection, a_correct_feature):  # pylint: disable=unused-argument
    """
    Test endpoint PATCH /catalog/collections/owner:collection_id/items/item_id.

    Test procedure:
    - Create new feature
    - Test that the feature is created with proper fields
    - Patch "height" and "width" values of the properties of the feature with PATCH request
    - Test that the feature was updated with a GET request and also check that the timestamps are correct
    - Patch geometry only (no bbox) and check bbox is recomputed and persisted
    - Patch bbox only with invalid SW/NE ordering and check it is rejected with HTTP 400
    """
    # Change correct feature collection id to match with minimal collection and post it
    feature = copy.deepcopy(a_correct_feature)
    feature["collection"] = "fixture_collection"
    feature_post_response = client.post(
        "/catalog/collections/fixture_owner:fixture_collection/items",
        json=feature,
    )
    assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED

    # Get feature using specific endpoint with featureID
    feature_id = feature["id"]
    created_feature_response = client.get(
        f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
    )
    assert created_feature_response.status_code == fastapi.status.HTTP_200_OK
    created_feature = json.loads(created_feature_response.content)
    # Test feature content
    assert created_feature["properties"]["owner"] == "fixture_owner"
    assert created_feature["properties"]["height"] == 2500
    assert created_feature["properties"]["width"] == 2500
    published_timestamp = created_feature["properties"]["published"]
    updated_timestamp = created_feature["properties"]["updated"]

    # Patch a property of the feature
    patch_values = {"properties": {"height": 3000, "width": 3000}}
    patch_response = client.patch(
        f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
        json=patch_values,
    )
    assert patch_response.status_code == fastapi.status.HTTP_200_OK

    # Get feature using specific endpoint with featureID
    patched_feature_response = client.get(
        f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
    )
    assert patched_feature_response.status_code == fastapi.status.HTTP_200_OK
    patched_feature = json.loads(patched_feature_response.content)
    # Test feature content
    assert patched_feature["properties"]["owner"] == "fixture_owner"
    assert patched_feature["properties"]["height"] == 3000  # Updated value
    assert patched_feature["properties"]["width"] == 3000  # Updated value
    assert patched_feature["properties"]["published"] == published_timestamp  # Check publication date didn't change
    assert patched_feature["properties"]["updated"] > updated_timestamp  # Check updated date changed

    # Patch geometry only: middleware must merge with current item and recompute bbox for consistency.
    ring: list[list[float]] = [
        [-94.6324839, 37.0585608],
        [-94.6324839, 37.0342547],
        [-94.6015249, 37.0342547],
        [-94.6015249, 37.0585608],
        [-94.6324839, 37.0585608],
    ]
    new_geometry = {"type": "Polygon", "coordinates": [ring]}
    lons = [pos[0] for pos in ring]
    lats = [pos[1] for pos in ring]
    expected_bbox = [min(lons), min(lats), max(lons), max(lats)]

    patch_response = client.patch(
        f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
        # Item PATCH payload must contain "properties" so the middleware can update the "updated" timestamp.
        json={"geometry": new_geometry, "properties": {}},
    )
    assert patch_response.status_code == fastapi.status.HTTP_200_OK

    patched_feature_response = client.get(
        f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
    )
    assert patched_feature_response.status_code == fastapi.status.HTTP_200_OK
    patched_feature = json.loads(patched_feature_response.content)
    assert patched_feature["geometry"] == new_geometry
    assert patched_feature["bbox"] == expected_bbox

    # Patch bbox only with invalid SW/NE ordering: must be rejected.
    invalid_bbox = [expected_bbox[2], expected_bbox[3], expected_bbox[0], expected_bbox[1]]
    patch_response = client.patch(
        f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
        # Item PATCH payload must contain "properties" so the middleware can update the "updated" timestamp.
        json={"bbox": invalid_bbox, "properties": {}},
    )
    assert patch_response.status_code == fastapi.status.HTTP_400_BAD_REQUEST
    assert (
        patch_response.json()["description"]
        == "Invalid bbox: expected southwesterly point followed by northeasterly point."
    )

    # Patch geometry and bbox to null: request middleware must inject internal defaults for pgstac persistence,
    # while the API response must still expose geometry/bbox as null (ESA behavior for sessions/items without extent).
    patch_response = client.patch(
        f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
        json={"geometry": None, "bbox": None, "properties": {}},
    )
    assert patch_response.status_code == fastapi.status.HTTP_200_OK

    patched_feature_response = client.get(
        f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
    )
    assert patched_feature_response.status_code == fastapi.status.HTTP_200_OK
    patched_feature = json.loads(patched_feature_response.content)
    assert patched_feature["geometry"] is None
    assert patched_feature["bbox"] is None

    # Delete feature
    assert (
        client.delete("/catalog/collections/fixture_owner:fixture_collection").status_code == fastapi.status.HTTP_200_OK
    )


def test_patch_feature_geometry_on_missing_item_returns_400(
    client,
    a_minimal_collection,
):  # pylint: disable=unused-argument
    """
    PATCHing geometry/bbox of a missing item must fail early with HTTP 400.

    This covers the request middleware branch that loads the current item for geometry/bbox patches.
    """
    patch_response = client.patch(
        "/catalog/collections/fixture_owner:fixture_collection/items/does-not-exist",
        json={"geometry": None},
    )
    assert patch_response.status_code == fastapi.status.HTTP_400_BAD_REQUEST
    assert patch_response.json()["description"] == "Item does-not-exist not found."
