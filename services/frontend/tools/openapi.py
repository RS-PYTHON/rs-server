"""Build the aggregated openapi.json"""

from __future__ import annotations

import json
import sys
from functools import reduce
from pathlib import Path

import requests
from attr import dataclass
from requests import HTTPError
from requests.exceptions import ConnectionError
from rs_server_frontend import __version__


class BuildOpenapiFailed(BaseException):
    """Custom exception."""

    def __init__(self):
        super().__init__("Unable to build the aggregated openapi.json")


@dataclass
class ServiceConf:
    """
    Configuration of one service that is added to the aggregated openapi.json.

    Attributes:
        name (str): service name
        openapi_url (str): url to the service openapi.json file
        openapi_contents (dict): service openapi.json file contents
        change_tags (dict): changes to make to the path tags as key/value=old/new value.
        Regular expressions and captures can be used with \i=result.group(i) as in
        https://pynative.com/python-regex-capturing-groups/#h-example-to-capture-multiple-groups
    """

    name: str
    openapi_url: str
    openapi_contents: dict = {}  # set after class initialization
    change_tags: dict = {}  # optional

    @staticmethod
    def load_service_conf(conf_path: Path) -> dict[str, ServiceConf]:
        """
        Load a json file that contains services configuration,
        return a dict with key=service name, value=service configuration + openapi.json contents.
        """

        services = {}

        # Read the input configuration file
        try:
            with open(conf_path, "r") as file:
                conf_contents = json.load(file)
        except IOError as e:
            raise IOError(f"File {conf_path} was not found.") from e
        except ValueError as e:
            raise IOError(f"File {conf_path} content is invalid.") from e

        # For each service
        for service_name, service_json in conf_contents.items():

            # Init the conf instance
            service_conf = ServiceConf(name=service_name, **service_json)
            services[service_name] = service_conf

            # Read the openapi.json contents
            try:
                response = requests.get(service_json["openapi_url"])
                response.raise_for_status()
                service_conf.openapi_contents = json.loads(response.content)
            except (ConnectionError, HTTPError) as e:
                # TODO check what kind of base exception is relevant here
                raise type(e)(
                    f"Unable to retrieve the openapi documentation for {service_name}.",
                ) from e
            except ValueError as e:
                raise ValueError(
                    f"The openapi documentation for {service_name} service is invalid.",
                ) from e
        return services


def merge_dicts(current: dict, other: dict) -> dict:
    """Merge two dicts"""
    current.update(other)
    return current


class AggregatedOpenapi:
    """Build the aggregated openapi.json from a list of services."""

    def __init__(self, services: dict[str, ServiceConf]):
        """Constructor"""
        self.services = services
        self.all_openapi = [service.openapi_contents for service in self.services.values()]

    def build_openapi(self) -> dict:
        """Return the built openapi.json as a dict"""
        return {
            "openapi": self.merge_openapi_versions(),
            "info": {"title": "RS-server", "version": str(__version__)},
            "paths": self.merge_paths(),
            "components": self.merge_components(),
        }

    def merge_openapi_versions(self) -> str:
        """Merge two openapi.json versions"""
        openapi_versions = sorted(
            {sub["openapi"] for sub in self.all_openapi},
        )
        if len(openapi_versions) > 1:
            versions = ", ".join(openapi_versions)
            raise ValueError(f"The openapi versions are not all the same : {versions}")
        return next(iter(openapi_versions))

    def merge_paths(self) -> dict[str, dict]:
        """Merge two openapi.json paths"""
        paths = (sub["paths"] for sub in self.all_openapi)
        return reduce(merge_dicts, paths)

    def merge_components(self) -> dict[str, dict]:
        """Merge two openapi.json components"""
        schemas = (sub["components"]["schemas"] for sub in self.all_openapi)
        security = (sub["components"].get("securitySchemes", {}) for sub in self.all_openapi)
        return {
            "schemas": reduce(merge_dicts, schemas),
            "securitySchemes": reduce(merge_dicts, security),
        }


def build_aggregated_openapi(services_file: Path, to_path: Path):
    """Build the aggregated openapi.json from a json file that contains services configuration."""
    try:
        services = ServiceConf.load_service_conf(services_file)
        aggregated = AggregatedOpenapi(services).build_openapi()

        try:
            with open(to_path, "w") as file:
                json.dump(aggregated, file, indent=2)
                file.write("\n")
        except IOError as e:
            raise IOError(f"Unable to write the aggregated openapi into {to_path}.") from e
    except BaseException as e:
        raise BuildOpenapiFailed() from e


if __name__ == "__main__":
    build_aggregated_openapi(*sys.argv[1:])
