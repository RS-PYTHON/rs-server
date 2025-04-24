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

"""Tests endpoint for publishing in catalog"""

import getpass
import json

import fastapi


# REWORKED TESTS
class TestCatalogPublishCollectionEndpoint:
    """This class is used to group all tests for publishing a collection into catalog DB."""

    def test_create_new_minimal_collection(self, client):
        """
        Test endpoint POST /catalog/collections.
        """
        minimal_collection = {
            "id": "test_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "test_owner",
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }
        response = client.post("/catalog/collections", json=minimal_collection)
        # Check that collection status code is 201
        assert response.status_code == fastapi.status.HTTP_201_CREATED
        # Check that internal collection id is set to owner_collection
        assert json.loads(response.content)["id"] == "test_collection"
        assert json.loads(response.content)["owner"] == "test_owner"

        # # Call search endpoint to verify presence of collection in catalog
        # test_params = {"collections": "test_collection", "filter-lang": "cql2-text", "filter": "owner='test_owner'"}
        # response = client.get("/catalog/search", params=test_params)
        # assert response.status_code == fastapi.status.HTTP_200_OK

        # Test that /catalog/collection GET endpoint returns the correct collection id
        response = client.get("/catalog/collections/test_owner:test_collection")
        assert response.status_code == fastapi.status.HTTP_200_OK
        response_content = json.loads(response.content)
        # Check that values are correctly written in catalogDB
        assert response_content["id"] == minimal_collection["id"]
        assert response_content["owner"] == minimal_collection["owner"]
        assert response_content["description"] == minimal_collection["description"]
        assert response_content["type"] == minimal_collection["type"]
        assert response_content["stac_version"] == minimal_collection["stac_version"]

    def test_create_new_minimal_collection_without_setting_user(self, client):
        """
        Test endpoint POST /catalog/collections.
        """
        minimal_collection = {
            "id": "test_collection_without_user",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }

        response = client.post("/catalog/collections", json=minimal_collection)
        # Check that collection status code is 201
        assert response.status_code == fastapi.status.HTTP_201_CREATED
        # Check that internal collection id is set to owner_collection
        assert json.loads(response.content)["id"] == "test_collection_without_user"
        assert json.loads(response.content)["owner"] == getpass.getuser()

        # # Call search endpoint to verify presence of collection in catalog
        # test_params = {"collections": "test_collection", "filter-lang": "cql2-text", "filter": "owner='test_owner'"}
        # response = client.get("/catalog/search", params=test_params)
        # assert response.status_code == fastapi.status.HTTP_200_OK

        # Test that /catalog/collection GET endpoint returns the correct collection id
        response = client.get("/catalog/collections/test_collection_without_user")
        assert response.status_code == fastapi.status.HTTP_200_OK
        response_content = json.loads(response.content)
        # Check that values are correctly written in catalogDB
        assert response_content["id"] == minimal_collection["id"]
        assert response_content["owner"] == getpass.getuser()
        assert response_content["description"] == minimal_collection["description"]
        assert response_content["type"] == minimal_collection["type"]
        assert response_content["stac_version"] == minimal_collection["stac_version"]

    def test_failure_to_create_collection(self, client):
        """
        Test endpoint POST /catalog/collections with incorrect collection.
        Endpoint: POST /catalog/collections
        """
        # This minimal collection is missing the id field
        minimal_incorrect_collection = {
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "test_incorrect_owner",
        }
        # Test that response is 400 BAD Request
        response = client.post("/catalog/collections", json=minimal_incorrect_collection)
        assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST
        # Check that owner from this collection is not written in catalogDB
        test_params = {"filter-lang": "cql2-text", "filter": "owner='test_incorrect_owner'"}
        response = client.get("/catalog/search", params=test_params)
        assert response.status_code == fastapi.status.HTTP_200_OK
        assert len(json.loads(response.content)["features"]) == 0

    def test_create_a_collection_already_created(self, client):
        """
        Test that endpoint POST /catalog/collections returns 409 Conflict if collection already exists.
        This action can be performed only by PUT or PATCH /catalog/collections.
        """
        minimal_collection = {
            "id": "duplicate_collection",
            "type": "Collection",
            "description": "test_description",
            "stac_version": "1.0.0",
            "owner": "duplicate_owner",
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }

        # Test that collection is correctly published
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_201_CREATED
        # Test that duplicate collection cannot be published
        response = client.post("/catalog/collections", json=minimal_collection)
        assert response.status_code == fastapi.status.HTTP_409_CONFLICT
        # Change values from collection, try to publish again
        minimal_collection["description"] = "test_description_updated"
        response = client.post("/catalog/collections", json=minimal_collection)
        # Test that is not allowed
        assert response.status_code == fastapi.status.HTTP_409_CONFLICT
        # Check into catalogDB that values are not updated
        response = client.get("/catalog/collections/duplicate_owner:duplicate_collection")
        response_content = json.loads(response.content)
        assert response_content["description"] == "test_description"

    def test_update_a_created_collection(self, client):
        """
        Test that endpoint PUT /catalog/collections updates a collection.
        Endpoint: PUT /catalog/collections.
        Endpoint: PUT /catalog/collections/owner:collection
        """
        minimal_collection = {
            "id": "second_test_collection",
            "type": "Collection",
            "description": "not_updated_test_description",
            "stac_version": "1.0.0",
            "owner": "second_test_owner",
            "links": [{"href": "./.zattrs.json", "rel": "self", "type": "application/json"}],
            "license": "public-domain",
            "extent": {
                "spatial": {"bbox": [[-94.6911621, 37.0332547, -94.402771, 37.1077651]]},
                "temporal": {"interval": [["2000-02-01T00:00:00Z", "2000-02-12T00:00:00Z"]]},
            },
        }
        # Post the collection
        post_collection_response = client.post("/catalog/collections", json=minimal_collection)
        assert post_collection_response.status_code == fastapi.status.HTTP_201_CREATED
        # test if is ok written in catalogDB
        get_collection_response = client.get("/catalog/collections/second_test_owner:second_test_collection")
        response_content = json.loads(get_collection_response.content)
        assert response_content["description"] == "not_updated_test_description"

        # Update the collection description and PUT
        minimal_collection["description"] = "the_updated_test_description"
        updated_collection_response = client.put(
            "/catalog/collections/second_test_owner:second_test_collection",
            json=minimal_collection,
        )
        assert updated_collection_response.status_code == fastapi.status.HTTP_200_OK

        # Check that collection is correctly updated
        get_check_collection_response = client.get("/catalog/collections/second_test_owner:second_test_collection")
        response_content = json.loads(get_check_collection_response.content)
        assert response_content["description"] == "the_updated_test_description"

        # cleanup
        client.delete("/catalog/collections/second_test_owner:second_test_collection")
