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

"""Authentication and token manipulation."""

import logging
import threading

from fastapi import HTTPException
from rs_server_common.authentication.authentication_to_external import (
    StationExternalAuthenticationConfig,
)
from rs_server_common.authentication.token_auth import (
    TokenDataNotFound,
    get_station_token,
)


class RefreshTokenData:  # pylint: disable=too-few-public-methods
    """
    Stores and manages authentication token refresh data for an external station.

    This class maintains authentication configuration details, a token dictionary,
    and a subscriber count to track whether the token should be refreshed.

    Attributes:
        config (StationExternalAuthenticationConfig): Authentication configuration for the station.
        padlock (threading.Lock): Lock to synchronize token updates.
        token_dict (dict): Dictionary containing authentication token details.
        subscribers (int): Number of active subscribers tracking the token refresh status.
    """

    def __init__(
        self,
        config: StationExternalAuthenticationConfig,
    ):
        """
        Initializes the `RefreshTokenData` instance with station authentication details.

        Args:
            config (StationExternalAuthenticationConfig): The authentication configuration for the station.
        """
        # NOTE: station_id has to be unique !
        self.config = config
        self.padlock = threading.Lock()
        self.token_dict: dict = {}
        self.subscribers = 1

    def station_id(self):
        """
        Retrieves the unique station identifier.

        Returns:
            str: The station ID.
        """
        return self.config.station_id

    def subscribe(self, logger):
        """
        Increments the subscriber count for token tracking.

        This method is thread-safe using a lock.

        Args:
            logger (logging.Logger): Logger instance for logging subscription events.
        """
        with self.padlock:
            self.subscribers += 1
            logger.debug(f"Subscribe to {self.station_id()}. Number of subscribers : {self.subscribers}")

    def unsubscribe(self, logger):
        """
        Decrements the subscriber count when a subscription ends.

        This method is thread-safe using a lock.

        Args:
            logger (logging.Logger): Logger instance for logging unsubscription events.
        """
        with self.padlock:
            self.subscribers -= 1
            logger.debug(f"Unsubscribe from station {self.station_id()}. Number of subscribers : {self.subscribers}")

    def update_dict_token(self, new_dict_token, logger):
        """
        Updates the authentication token dictionary with new token data.

        This method is NOT thread-safe ! The caller should use the padlock

        Args:
            new_dict_token (dict): The new token data to store.
            logger (logging.Logger): Logger instance for logging token update events.
        """
        logger.debug(f"Updating dictionary token with: {new_dict_token}")
        self.token_dict = new_dict_token.copy()

    def get_access_token(self):
        """
        Gets the access_token field from the dictionays

        This method is thread-safe using a lock.

        """
        with self.padlock:
            return self.token_dict["access_token"]


def update_station_token(auth_refresh_token: RefreshTokenData, logger: logging.Logger):
    """
    Refreshes the authentication token for an external station.

    This function retrieves the current authentication token from the shared variable,
    and refreshes it if necessary.

    Args:
        auth_refresh_token (RefreshTokenData): The authentication token data, with the dictionary that keeps the
            token.
        logger (logging.Logger): Logger instance for logging events.

    Returns:
        bool: `True` if the token was successfully refreshed, `False` if an error occurred.

    Raises:
        RuntimeError: If an unexpected error occurs during token retrieval or update.
    """
    try:
        if auth_refresh_token.subscribers == 0:
            logger.debug(f"No subscribers for {auth_refresh_token.station_id()}, so no token refreshment")
            return True
        logger.debug(f"Refreshing token for {auth_refresh_token.station_id()}")
        # Get/refresh the access token if necessary
        with auth_refresh_token.padlock:
            token_dict = get_station_token(auth_refresh_token.config, auth_refresh_token.token_dict)
            if auth_refresh_token.token_dict != token_dict:
                auth_refresh_token.update_dict_token(token_dict, logger)
    except (TokenDataNotFound, ValueError) as e:
        logger.exception(f"Token dictionary not valid: {e}")
        return False
    except HTTPException as http_exception:
        logger.exception(
            f"Failed to retrieve the token needed to connect to the external station: {http_exception}",
        )
        return False

    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.exception(f"Unhandled exception in update_station_token: {e}")
        return False
    logger.debug("Refreshing token finished.")
    return True
