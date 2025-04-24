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

"""Endpoint tests for publishing feature in catalog without beucket transfer"""

# pylint: disable=unused-argument

import copy
import json
import time

import fastapi


class TestCatalogPublishFeatureWithoutBucketTransferEndpoint:
    """Class used to group tests that publish a collection and move assets between buckets."""

    def test_create_new_minimal_feature(self, client, a_minimal_collection, a_correct_feature):
        """Test that a feature is correctly published into catalogDB
        ENDPOINT: POST /catalog/collections/{user:collection}/items
        ENDPOINT: GET /catalog/collections/{user:collection}/items
        ENDPOINT: GET /catalog/collections/{user:collection}/items/{featureID}"""
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED
        # Check if the future is correctly posted to catalog
        check_features_response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert check_features_response.status_code == fastapi.status.HTTP_200_OK
        # Test if query returns only one feature for this collection
        returned_features = json.loads(check_features_response.content)
        assert returned_features["numberReturned"] == 1
        # Test feature content
        assert returned_features["features"][0]["id"] == a_correct_feature["id"]
        assert returned_features["features"][0]["geometry"] == a_correct_feature["geometry"]
        assert returned_features["features"][0]["properties"]["owner"] == "fixture_owner"
        # Get feature using specific endpoint with featureID
        feature_id = a_correct_feature["id"]
        specific_feature_response = client.get(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{feature_id}",
        )
        assert specific_feature_response.status_code == fastapi.status.HTTP_200_OK
        specific_feature = json.loads(check_features_response.content)
        # Check that specific feature is exactly match for previous one
        assert specific_feature["features"][0] == returned_features["features"][0]
        assert (
            client.delete("/catalog/collections/fixture_owner:fixture_collection").status_code
            == fastapi.status.HTTP_200_OK
        )

    def test_get_non_existent_feature(self, client, a_minimal_collection):
        """
        Testing GET feature endpoint with a non-existent feature ID.
        """
        # Try to get a non-existent feature from a non-existing collection
        feature_post_response = client.get("/catalog/collections/non_owner:non_collection/items/non_feature_id")
        assert feature_post_response.status_code == fastapi.status.HTTP_404_NOT_FOUND
        # Try to get a non-existent feature from an existing collection
        feature_post_response = client.get(
            "/catalog/collections/fixture_owner:fixture_collection/items/incorrect_feature_id",
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_404_NOT_FOUND
        assert (
            client.delete("/catalog/collections/fixture_owner:fixture_collection").status_code
            == fastapi.status.HTTP_200_OK
        )

    def test_update_with_a_correct_feature(self, client, a_minimal_collection, a_correct_feature):
        """
        ENDPOINT: PUT: /catalog/collections/{user:collection}/items/{featureID}
        """
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED
        # Update the feature and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = [-180.0, -90.0, 180.0, 90.0]
        del updated_feature_sent["collection"]

        feature_put_response = client.put(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
            json=updated_feature_sent,
        )
        assert feature_put_response.status_code == fastapi.status.HTTP_200_OK
        # Test the updated feature from catalog
        updated_feature = client.get(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
        )
        assert updated_feature.status_code == fastapi.status.HTTP_200_OK
        updated_feature = json.loads(updated_feature.content)
        # Test that ID has changed, but other arbitrary field not
        assert updated_feature["bbox"] == updated_feature_sent["bbox"]
        assert updated_feature["geometry"] == a_correct_feature["geometry"]
        assert (
            client.delete("/catalog/collections/fixture_owner:fixture_collection").status_code
            == fastapi.status.HTTP_200_OK
        )

    def test_update_timestamp_feature(  # pylint: disable=too-many-locals
        self,
        client,
        a_minimal_collection,
        a_correct_feature,
    ):
        """
        ENDPOINT: PUT: /catalog/collections/{user:collection}/items/{featureID}
        """
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )

        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED

        content = json.loads(feature_post_response.content)
        first_published_date = content["properties"]["published"]
        first_expires_date = content["properties"]["expires"]
        # Update the feature and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = [-180.0, -90.0, 180.0, 90.0]
        del updated_feature_sent["collection"]

        # Test that updated field is correctly updated.
        updated_timestamp = json.loads(feature_post_response.content)["properties"]["updated"]
        time.sleep(1)

        feature_put_response = client.put(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
            json=updated_feature_sent,
        )
        content = json.loads(feature_put_response.content)

        new_updated_timestamp = content["properties"]["updated"]

        # Test that "updated" field is correctly updated.
        assert updated_timestamp != new_updated_timestamp

        # Test that "published" and "expires" field are inchanged after the update.
        assert content["properties"]["published"] == first_published_date
        assert content["properties"]["expires"] == first_expires_date

        assert feature_put_response.status_code == fastapi.status.HTTP_200_OK
        # client.delete("/catalog/collections/fixture_owner:fixture_collection")
        deletion = client.delete("/catalog/collections/fixture_owner:fixture_collection")
        assert deletion.status_code == fastapi.status.HTTP_200_OK

    def test_update_timestamp_feature_fails_with_unfound_item(
        self,
        client,
        a_minimal_collection,
        a_correct_feature,
    ):
        """
        ENDPOINT: PUT: /catalog/collections/{user:collection}/items/{featureID}
        """
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )

        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED

        # Update the feature and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = [77]
        del updated_feature_sent["collection"]

        path = "/catalog/collections/fixture_owner:fixture_collection/items/NOT_FOUND_ITEM"
        feature_put_response = client.put(
            path,
            json=updated_feature_sent,
        )
        assert feature_put_response.status_code == fastapi.status.HTTP_400_BAD_REQUEST

    def test_update_feature_in_non_existing_collection_fails(
        self,
        client,
        a_minimal_collection,
        a_correct_feature,
    ):
        """
        ENDPOINT: PUT: /catalog/collections/{user:collection}/items/{featureID}
        with collection as non existing collection
        """
        # Change correct feature collection id to match with minimal collection
        a_correct_feature["collection"] = "fixture_collection"
        # Put feature in non existing collection
        non_existing_collection = "NON_EXISTING_FIXTURE_COLLECTION"
        feature_put_response = client.put(
            f"/catalog/collections/fixture_owner:{non_existing_collection}/items/{a_correct_feature['id']}",
            json=a_correct_feature,
        )

        assert feature_put_response.status_code == fastapi.status.HTTP_404_NOT_FOUND
        assert feature_put_response.json() == f"Collection {non_existing_collection} does not exist."

    def test_add_feature_in_non_existing_collection_fails(
        self,
        client,
        a_minimal_collection,
        a_correct_feature,
    ):
        """
        ENDPOINT: POST: /catalog/collections/{user:collection}/items/
        with collection as non existing collection
        """
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        non_existing_collection = "NON_EXISTING_FIXTURE_COLLECTION"
        feature_post_response = client.post(
            f"/catalog/collections/fixture_owner:{non_existing_collection}/items",
            json=a_correct_feature,
        )

        assert feature_post_response.status_code == fastapi.status.HTTP_404_NOT_FOUND
        assert feature_post_response.json() == f"Collection {non_existing_collection} does not exist."

    def test_update_with_an_incorrect_feature(self, client, a_minimal_collection, a_correct_feature):
        """Testing POST feature endpoint with a wrong-formatted field (BBOX)."""
        # Change correct feature collection id to match with minimal collection and post it
        a_correct_feature["collection"] = "fixture_collection"
        # Post the correct feature to catalog
        get_response = client.get(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
        )

        if get_response.status_code == fastapi.status.HTTP_200_OK:
            client.delete(f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}")

        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED
        # Update the feature with an incorrect value and PUT it into catalogDB
        updated_feature_sent = copy.deepcopy(a_correct_feature)
        updated_feature_sent["bbox"] = "Incorrect_bbox_value"
        del updated_feature_sent["collection"]

        response = client.put(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
            json=updated_feature_sent,
        )
        assert response.status_code == fastapi.status.HTTP_400_BAD_REQUEST

    def test_delete_a_correct_feature(self, client, a_minimal_collection, a_correct_feature):
        """
        ENDPOINT: DELETE: /catalog/collections/{user:collection}/items/{featureID}
        """
        a_correct_feature["collection"] = "fixture_collection"

        get_response = client.get(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
        )

        if get_response.status_code == fastapi.status.HTTP_200_OK:
            client.delete(f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}")

        # Post the correct feature to catalog
        feature_post_response = client.post(
            "/catalog/collections/fixture_owner:fixture_collection/items",
            json=a_correct_feature,
        )
        assert feature_post_response.status_code == fastapi.status.HTTP_201_CREATED
        # Delete the feature from catalogDB
        delete_response = client.delete(
            f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}",
        )
        assert delete_response.status_code == fastapi.status.HTTP_200_OK
        # Test that feature was correctly removed from catalogDB

        response = client.get(f"/catalog/collections/fixture_owner:fixture_collection/items/{a_correct_feature['id']}")
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND

        # Test that collection is now empty
        collection_content_response = client.get("/catalog/collections/fixture_owner:fixture_collection/items")
        assert collection_content_response.status_code == fastapi.status.HTTP_200_OK
        collection_content_response = json.loads(collection_content_response.content)
        assert collection_content_response["numberReturned"] == 0
        assert (
            client.delete("/catalog/collections/fixture_owner:fixture_collection").status_code
            == fastapi.status.HTTP_200_OK
        )

    def test_delete_a_non_existing_feature(self, client, a_minimal_collection):
        """
        Test DELETE feature endpoint on non-existing feature.
        """
        response = client.delete("/catalog/collections/fixture_owner:fixture_collection/items/non_existent_feature")
        assert response.status_code == fastapi.status.HTTP_404_NOT_FOUND
