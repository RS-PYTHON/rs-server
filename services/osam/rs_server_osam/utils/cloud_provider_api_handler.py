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
"""OVH Handler module"""
import logging
import os
import time

import ovh
from rs_server_common.utils.logging import Logging

logger = Logging.default(__name__)
logger.setLevel(logging.DEBUG)


class OVHApiHandler:
    """
    Handler for interacting with the OVH Cloud API for project users.

    This class manages the OVH API client, providing methods to create,
    retrieve, and delete users associated with a cloud project.
    """

    def __init__(self):
        """
        Initializes the OVH API client and retrieves the service name dynamically.
        """
        self.ovh_client = self.__open_ovh_connection()
        self.ovh_service_name = os.getenv("OVH_SERVICE")
        if not self.ovh_service_name:
            if not self.ovh_client.get("/cloud/project"):
                # protection
                raise RuntimeError("No cloud projects found in OVH account.")
            # get the first one
            self.ovh_service_name = self.ovh_client.get("/cloud/project")[0]
        logger.debug(f"self.ovh_service_name: {self.ovh_service_name}")

    def __open_ovh_connection(self) -> ovh.Client:
        """
        Establishes a connection to the OVH API using credentials from environment variables.

        Returns:
            ovh.Client: An authenticated OVH API client.

        Raises:
            RuntimeError: If the connection to the OVH API fails.
        """
        ovh_endpoint = os.environ["OVH_ENDPOINT"]
        ovh_application_key = os.environ["OVH_APPLICATION_KEY"]
        ovh_application_secret = os.environ["OVH_APPLICATION_SECRET"]
        ovh_consumer_key = os.environ["OVH_CONSUMER_KEY"]

        try:
            ovh_client = ovh.Client(
                endpoint=ovh_endpoint,
                application_key=ovh_application_key,
                application_secret=ovh_application_secret,
                consumer_key=ovh_consumer_key,
            )
        except ovh.APIError as error:
            raise RuntimeError(f"Error connecting with OVH to '{ovh_endpoint}'.") from error

        return ovh_client

    def get_all_users(self) -> list[dict]:
        """
        Retrieves a list of all users associated with the OVH cloud project.

        Returns:
            list[dict]: A list of user dictionaries.
        """
        return self.ovh_client.get(f"/cloud/project/{self.ovh_service_name}/user")

    def get_user(self, user_id: str) -> dict:
        """
        Retrieves details of a specific user by user ID.

        Args:
            user_id (str): The ID of the user to retrieve.

        Returns:
            dict: A dictionary containing user details.
        """
        return self.ovh_client.get(f"/cloud/project/{self.ovh_service_name}/user/{user_id}")

    def create_user(
        self,
        description: str | None = None,
        role=None,
        roles=None,
        timeout_seconds=60,
        poll_interval=2,
    ) -> dict:
        """
        Creates a new user in the OVH cloud project.

        Args:
            description (str | None): Optional description for the user.
            role: (deprecated) Optional legacy role specification.
            roles: Optional list of roles for the user.

        Returns:
            dict: The created user object as returned by the OVH API.
        """
        logger.debug(f"OVH endpoint to be called: /cloud/project/{self.ovh_service_name}/user")
        user = self.ovh_client.post(
            f"/cloud/project/{self.ovh_service_name}/user",
            description=description,
            role=role,
            roles=roles,
        )
        user_id = user["id"]
        # Step 2: Wait for status to become 'ok'
        start_time = time.time()
        logger.info("Waiting for the user's status to be ok")
        while time.time() - start_time < timeout_seconds:
            user_status = self.ovh_client.get(f"/cloud/project/{self.ovh_service_name}/user/{user_id}")
            status = user_status.get("status")
            if status == "ok":
                logger.info(
                    f"Exit from waiting, with status = {user_status.get('status')} "
                    f"in {time.time() - start_time} seconds",
                )
                return user
            time.sleep(poll_interval)

        raise TimeoutError(f"Timeout: OVH user '{user_id}' status did not become 'ok' within {timeout_seconds} seconds")

    def delete_user(self, user_id: str):
        """
        Deletes a user from the OVH cloud project.

        Args:
            user_id (str): The ID of the user to delete.

        Returns:
            Any: Response from the OVH API upon successful deletion.
        """
        return self.ovh_client.delete(f"/cloud/project/{self.ovh_service_name}/user/{user_id}")
