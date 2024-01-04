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

            # Create console handler
            handler = logging.StreamHandler()
            handler.setFormatter(CustomFormatter())
            logger.addHandler(handler)

            return logger


class CustomFormatter(logging.Formatter):
    """
    Custom logging formatter with colored text.
    See: https://stackoverflow.com/a/56944256
    """

    RED = "\x1b[31m"
    BOLD_RED = "\x1b[31;1m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    PURPLE = "\x1b[35m"
    RESET = "\x1b[0m"

    FORMAT = f"%(asctime)s.%(msecs)03d [{{color}}%(levelname)s{RESET}] (%(name)s) %(message)s"
    DATETIME = "%H:%M:%S"

    FORMATS = {
        logging.NOTSET: FORMAT.format(color=""),
        logging.DEBUG: FORMAT.format(color=PURPLE),
        logging.INFO: FORMAT.format(color=GREEN),
        logging.WARNING: FORMAT.format(color=YELLOW),
        logging.ERROR: FORMAT.format(color=BOLD_RED),
        logging.CRITICAL: FORMAT.format(color=RED),
    }

    def format(self, record):
        format = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(format, self.DATETIME)
        return formatter.format(record)
