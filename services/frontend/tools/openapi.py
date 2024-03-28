"""Build the aggregated openapi.json"""

from __future__ import annotations

import json
import sys
from functools import reduce
from pathlib import Path

import requests
from attr import dataclass
from requests import HTTPError
from requests.exceptions import ConnectionError  # pylint: disable=redefined-builtin
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
            with open(conf_path, "r", encoding="utf-8") as file:
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
                response = requests.get(service_json["openapi_url"], timeout=30)
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
        self.services: dict[str, ServiceConf] = services
        self.all_openapi: list[dict] = [service.openapi_contents for service in self.services.values()]

    def build_openapi(self) -> dict:
        """Return the built openapi.json as a dict"""
        return {
            "openapi": self.merge_openapi_versions(),
            "info": {"title": "RS-Server", "version": str(__version__)},
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

        # All paths of all services
        all_paths = []

        # Get each service paths
        for service in self.services.values():
            service_paths = service.openapi_contents["paths"]
            all_paths.append(service_paths)

            # For each path method (get, post, ...)
            for path in [path for methods in service_paths.values() for path in methods.values()]:

                # Get the path tags or a default one
                if ("tags" in path) and (len(path["tags"]) > 0):
                    tags = path["tags"]
                    default_tag = False
                else:
                    tags = [""]
                    default_tag = True

                # Change tags value
                for i_tag, tag in enumerate(tags):
                    for replace_what, replace_by in service.change_tags.items():
                        if tag == replace_what:
                            tags[i_tag] = replace_by

                # Save the modified tag. Don't save unmodified default tags.
                if not (default_tag and tags == [""]):
                    path["tags"] = tags

        # Merge all services paths
        return reduce(merge_dicts, all_paths)

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
            with open(to_path, "w", encoding="utf-8") as file:
                json.dump(aggregated, file, indent=2)
                file.write("\n")
        except IOError as e:
            raise IOError(f"Unable to write the aggregated openapi into {to_path}.") from e
    except BaseException as e:
        raise BuildOpenapiFailed() from e


if __name__ == "__main__":
    build_aggregated_openapi(*[Path(path) for path in sys.argv[1:]])
