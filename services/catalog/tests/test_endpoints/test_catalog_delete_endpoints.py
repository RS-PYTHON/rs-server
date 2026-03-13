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

"""Endpoints tests for deletions in catalog"""

# pylint: disable=unused-argument

import copy
import json

import fastapi


class TestCatalogDeleteEndpoints:
    """This class is used to group all tests for deleting a collection or an item"""

    def test_delete_a_created_collection(self, client):
        """
        Test that a created collection can be deleted
        Endpoint: DELETE /catalog/collections.
        """
        minimal_collection = {
            "id": "will_be_deleted_collection",
            "type": "Collection",
            "description": "will_be_deleted_description",
            "stac_version": "1.1.0",
            "owner": "will_be_deleted_owner",
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_201_CREATED

        # Check that collection is correctly published
        first_check_response = client.get("/catalog/collections/will_be_deleted_owner:will_be_deleted_collection")
        first_response_content = json.loads(first_check_response.content)
        assert first_response_content["description"] == minimal_collection["description"]

        # Delete the collection
        delete_response = client.delete("/catalog/collections/will_be_deleted_owner:will_be_deleted_collection")
        assert delete_response.status_code == fastapi.status.HTTP_200_OK

        # Check that collection is correctly deleted
        second_check_response = client.get("/catalog/collections/will_be_deleted_owner:will_be_deleted_collection")
        assert second_check_response.status_code == fastapi.status.HTTP_404_NOT_FOUND

    def test_delete_a_non_existent_collection(self, client):
        """
        Test DELETE collection endpoint on non existing collection
        """
        # Should call delete endpoint on a non existent collection id
        delete_response = client.delete("/catalog/collections/non_existent_owner:non_existent_collection")
        assert delete_response.status_code == fastapi.status.HTTP_404_NOT_FOUND

    def test_delete_a_foreign_collection(self, client):
        """Test DELETE collection endpoint, with a user that has no rights to remove an existing collection."""
        minimal_collection = {
            "id": "correctly_created_collection",
            "type": "Collection",
            "description": "will_be_deleted_description",
            "stac_version": "1.1.0",
            "owner": "owner_with_rights",
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_201_CREATED
        delete_response = client.delete("/catalog/collections/owner_with_no_rights:correctly_created_collection")
        # To be changed with 405 not allowed after UAC
        assert delete_response.status_code == fastapi.status.HTTP_404_NOT_FOUND

    def test_delete_non_empty_collection(self, init_buckets, client, a_minimal_collection, a_correct_feature):
        """
        Test that a collection than contain features can be successfully deleted.
        """
        first_get_collection_response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert first_get_collection_response.status_code == fastapi.status.HTTP_200_OK
        assert json.loads(first_get_collection_response.content)["numberReturned"] == 0
        # Post the feature to the collection
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["collection"] = "fixture_collection"
        post_collection_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=updated_feature_sent,
        )
        assert post_collection_response.status_code == fastapi.status.HTTP_201_CREATED
        # Test that the collection is not empty
        second_get_collection_response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert second_get_collection_response.status_code == fastapi.status.HTTP_200_OK
        assert json.loads(second_get_collection_response.content)["numberReturned"] > 0
        # Delete the collection
        delete_response = client.delete("/catalog/collections/fixture_owner:fixture_collection")
        assert delete_response.status_code == fastapi.status.HTTP_200_OK
        # Test that the collection is removed, the request raises a 404 exception
        response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND
