import json
import sys
from functools import reduce
from pathlib import Path

import requests
from requests import HTTPError


class BuildOpenapiFailed(BaseException):
    def __init__(self):
        super().__init__("Unable to generate REST documentation.")


def load_services_configuration(service_conf: Path) -> dict[str, dict]:
    try:
        with open(service_conf, "r") as file:
            return json.load(file)
    except IOError as e:
        raise IOError(f"File {service_conf} was not found.") from e
    except ValueError as e:
        raise IOError(f"File {service_conf} content is invalid.") from e


def load_openapi(service: str, retrieve_url: str) -> dict:
    try:
        response = requests.get(retrieve_url)
        response.raise_for_status()
        return json.loads(response.content)
    except HTTPError as e:
        # TODO check what kind of base exception is relevant here
        raise HTTPError(
            f"Unable to retrieve the openapi documentation for {service}.",
        ) from e
    except ValueError as e:
        raise ValueError(
            f"The openapi documentation for {service} service is invalid.",
        ) from e


def merge_dicts(current: dict, other: dict) -> dict:
    current.update(other)
    return current


class AggregatedOpenapi:
    def __init__(self, sub_openapis: dict[str, dict]):
        self.sub_openapis = sub_openapis

    def build_openapi(self) -> dict:
        return {
            "openapi": self.merge_openapi_versions(),
            "info": {"title": "RS-server", "version": self.merge_service_versions()},
            "paths": self.merge_paths(),
            "components": self.merge_components(),
        }

    def merge_openapi_versions(self) -> str:
        openapi_versions = sorted({sub["openapi"] for sub in self.sub_openapis.values()})
        if len(openapi_versions) > 1:
            versions = ", ".join(openapi_versions)
            raise ValueError(f"The openapi versions are not all the same : {versions}")
        return next(iter(openapi_versions))

    def merge_service_versions(self) -> str:
        services_versions = sorted({sub["info"]["version"] for sub in self.sub_openapis.values()})
        if len(services_versions) > 1:
            versions = ", ".join(services_versions)
            raise ValueError(f"The service versions are not all the same : {versions}")
        return next(iter(services_versions))

    def merge_paths(self) -> dict[str, dict]:
        paths = (sub["paths"] for sub in self.sub_openapis.values())
        return reduce(merge_dicts, paths)

    def merge_components(self) -> dict[str, dict]:
        schemas = (sub["components"]["schemas"] for sub in self.sub_openapis.values())
        security = (sub["components"].get("securitySchemes", {}) for sub in self.sub_openapis.values())
        return {
            "schemas": reduce(merge_dicts, schemas),
            "securitySchemes": reduce(merge_dicts, security),
        }


def write_openapi(openapi: dict, to_path: Path):
    try:
        with open(to_path, "w") as file:
            json.dump(openapi, file, indent=2)
    except IOError as e:
        raise IOError(f"Unable to write the aggregated openapi into {to_path}.") from e


def build_aggregated_openapi(services_file: Path, to_path: Path):
    try:
        openapis: dict[str, dict] = {
            service: load_openapi(service, f"{conf['root_url']}/{conf['doc_endpoint']}")
            for service, conf in load_services_configuration(services_file).items()
        }
        aggregated = AggregatedOpenapi(openapis).build_openapi()
        write_openapi(aggregated, to_path)
    except BaseException as e:
        raise BuildOpenapiFailed() from e


if __name__ == "__main__":
    build_aggregated_openapi(*sys.argv[1:])
