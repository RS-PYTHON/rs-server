"""Logging utility."""

import logging
from threading import Lock


class Logging:  # pylint: disable=fixme, too-few-public-methods
    """Logging utility."""

    lock = Lock()

    @classmethod
    def default(cls, name="rspy"):
        """
        Return a default Logger class instance.

        :param str name: Logger name. You can pass __name__ to use your current module name.
        """
        logger = logging.getLogger(name=name)

        with cls.lock:
            # If we have already set the handlers for the logger with this name, do nothing more
            if not logger.hasHandlers():
                return logger

            # Don't propagate to root logger
            logger.propagate = False

            # TODO: how can the user restrict messages to e.g. WARNING ? I've tested
            # From python: logging.basicConfig(level="WARNING")
            # From pytest command line: --log-cli-level=WARNING
            # but it doesn't work.
            logger.setLevel(logging.DEBUG)

            # Create handler
            handler = logging.StreamHandler()

            # Create formatter and add it to handler
            c_format = logging.Formatter("%(asctime)s.%(msecs)03d | %(levelname)s | %(name)s - %(message)s", "%H:%M:%S")
            handler.setFormatter(c_format)

            # Add handler to the logger
            logger.addHandler(handler)

            return logger
