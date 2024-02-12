import json

import pytest

from tests.conftest import add_collection


@pytest.mark.integration
def test_redirection(client, toto_s1_l1, toto_s2_l3, titi_s2_l1):
    add_collection(client, toto_s1_l1)
    add_collection(client, toto_s2_l3)
    add_collection(client, titi_s2_l1)

    response = client.get("/catalog/toto/collections")

    # The user endpoint is working
    assert response.status_code == 200

    collections = json.loads(response.content)["collections"]
    collection_ids = {collection["id"] for collection in collections}
    # Only toto collections are retrieved.
    assert collection_ids == {toto_s1_l1.name, toto_s2_l3.name}

    response = client.get("/user/titi/collections")

    # The user endpoint is working
    assert response.status_code == 200

    collections = json.loads(response.content)["collections"]
    collection_ids = {collection["id"] for collection in collections}
    # Only titi collections are retrieved.
    assert collection_ids == {titi_s2_l1.name}
