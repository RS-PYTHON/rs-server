"""Logging utility."""

import logging
from threading import Lock


class Logging:  # pylint: too-few-public-methods
    """
    Logging utility.

    Static variables:
    :param lock: For code synchronization
    :param level: Minimal log level to use for all new logging instances.
    """

    lock = Lock()
    level = logging.DEBUG

    @classmethod
    def default(cls, name="rspy"):
        """
        Return a default Logger class instance.

        :param str name: Logger name. You can pass __name__ to use your current module name.
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

            # Create handler
            handler = logging.StreamHandler()

            # Create formatter and add it to handler
            c_format = logging.Formatter("%(asctime)s.%(msecs)03d | %(levelname)s | %(name)s - %(message)s", "%H:%M:%S")
            handler.setFormatter(c_format)

            # Add handler to the logger
            logger.addHandler(handler)

            return logger
