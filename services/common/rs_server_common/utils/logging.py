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

"""Logging utility."""

import logging
import logging.handlers
import os
from multiprocessing import Queue
from threading import Lock

import logging_loki
from rs_server_common import settings


class Logging:  # pylint: disable=too-few-public-methods
    """
    Logging utility.

    Attributes:
        lock: For code synchronization
        level: Minimal log level to use for all new logging instances.
    """

    lock = Lock()
    level = logging.DEBUG

    @classmethod
    def default(cls, name="rspy"):
        """
        Return a default Logger class instance.

        Args:
            name (str): Logger name. You can pass __name__ to use your current module name.
        """
        logger = logging.getLogger(name=name)

        with cls.lock:
            # Don't propagate to root logger
            logger.propagate = False

            # If we have already set the handlers for the logger with this name, do nothing more
            if logger.hasHandlers():
                return logger

            # Set the minimal log level to use for all new logging instances.
            logger.setLevel(cls.level)

            # Create console handler
            handler = logging.StreamHandler()
            handler.setFormatter(CustomFormatter())
            logger.addHandler(handler)

            # Export logs to Loki, see: https://pypi.org/project/python-logging-loki/
            # Note: on the cluster, this is not used. Promtail already forwards stdout to Loki.
            loki_endpoint = os.getenv("LOKI_ENDPOINT")
            if loki_endpoint and settings.SERVICE_NAME:
                handler = logging_loki.LokiQueueHandler(
                    Queue(-1),
                    url=loki_endpoint,
                    tags={"service": settings.SERVICE_NAME},
                    # auth=("username", "password"),
                    version="1",
                )
                handler.setFormatter(CustomFormatter())
                logger.addHandler(handler)

            return logger


class CustomFormatter(logging.Formatter):
    """
    Custom logging formatter with colored text.
    See: https://stackoverflow.com/a/56944256
    """

    _RED = "\x1b[31m"
    _BOLD_RED = "\x1b[31;1m"
    _GREEN = "\x1b[32m"
    _YELLOW = "\x1b[33m"
    _PURPLE = "\x1b[35m"
    _RESET = "\x1b[0m"

    _FORMAT = f"%(asctime)s.%(msecs)03d [{{color}}%(levelname)s{_RESET}] (%(name)s) %(message)s"
    _DATETIME = "%H:%M:%S"

    _FORMATS = {
        logging.NOTSET: _FORMAT.format(color=""),
        logging.DEBUG: _FORMAT.format(color=_PURPLE),
        logging.INFO: _FORMAT.format(color=_GREEN),
        logging.WARNING: _FORMAT.format(color=_YELLOW),
        logging.ERROR: _FORMAT.format(color=_BOLD_RED),
        logging.CRITICAL: _FORMAT.format(color=_RED),
    }

    def format(self, record):
        level_format = self._FORMATS.get(record.levelno)
        formatter = logging.Formatter(level_format, self._DATETIME)
        return formatter.format(record)
