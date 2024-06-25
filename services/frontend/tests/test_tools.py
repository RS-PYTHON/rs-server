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

"""Test the frontend generation tool."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest
import responses
import yaml
from requests import HTTPError
from tools.openapi import BuildOpenapiFailed, build_aggregated_openapi
from yaml.scanner import ScannerError

# pylint: disable=missing-class-docstring,missing-function-docstring,too-few-public-methods,redefined-outer-name


@pytest.fixture(scope="module")
def tools_test_path(resources_test_path) -> Path:
    """The root path for test resources."""
    return resources_test_path / "tools"


@dataclass
class ServicesConfiguration:
    """Service configuration yaml file and associated contents as a python dict."""

    config: dict
    file: Path

    def doc_endpoint_url(self, service: str) -> str:
        """Return a service url"""
        return f"{self.config[service]['openapi_url']}"


@pytest.fixture(scope="module")
def services_conf_file(tools_test_path) -> Path:
    return tools_test_path / "services.yml"


@pytest.fixture(scope="module")
def services_conf(services_conf_file) -> ServicesConfiguration:

    with open(services_conf_file, "r", encoding="utf-8") as file:
        return ServicesConfiguration(config=yaml.safe_load(file).get("services"), file=services_conf_file)


def a_openapi_path(service: str, response_type: str) -> dict:
    return {
        "get": {
            "tags": [],
            "summary": f"a summary {service}",
            "description": f"a description {service}",
            "operationId": f"operation_{service}",
            "parameters": [
                {
                    "name": "name",
                    "in": "query",
                    "required": True,
                    "schema": {
                        "type": "string",
                        "description": "name",
                        "title": "Name",
                    },
                    "description": "the name",
                },
            ],
            "responses": {
                "200": {
                    "description": "Successful Response",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": f"#/components/schemas/{response_type}"},
                        },
                    },
                },
                "422": {
                    "description": "Validation Error",
                    "content": {
                        "application/json": {
                            "schema": {
                                "$ref": "#/components/schemas/HTTPValidationError",
                            },
                        },
                    },
                },
            },
        },
    }


def an_openapi_component(component_name: str) -> dict:
    return {
        "properties": {"is_ok": {"type": "boolean", "title": "Started"}},
        "type": "object",
        "required": ["is_ok"],
        "title": component_name,
        "description": f"{component_name} description.",
    }


def a_service_openapi(
    service_name: str,
    openapi_version: str = "3.1.0",
    service_version: str = "0.1.0",
    common_difference: str = "",
) -> dict:
    return {
        "openapi": openapi_version,
        "info": {"title": f"RS server {service_name}", "version": service_version},
        "paths": {
            "/common": a_openapi_path("common", "CommonResponse"),
            f"/{service_name}": a_openapi_path(service_name, f"{service_name}Response"),
        },
        "components": {
            "schemas": {
                "CommonResponse": an_openapi_component(
                    f"CommonResponse_{common_difference}",
                ),
                f"{service_name}Response": an_openapi_component(
                    f"{service_name}Response",
                ),
            },
        },
    }


@pytest.fixture(scope="module")
def cadip_openapi(tools_test_path) -> dict:  # pylint: disable=unused-argument
    return a_service_openapi(service_name="cadip", common_difference="cadip")


@pytest.fixture(scope="module")
def adgs_openapi(tools_test_path) -> dict:  # pylint: disable=unused-argument
    return a_service_openapi(service_name="adgs", common_difference="adgs")


class TestGenerateAggregateRestDoc:
    @responses.activate
    def test_calls_doc_endpoint_of_each_configured_service(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,
        services_conf: ServicesConfiguration,
        tmp_path: Path,
    ):
        cadip_resp = responses.get(
            url=services_conf.doc_endpoint_url("cadip"),
            status=200,
            json=cadip_openapi,
        )
        adgs_resp = responses.get(
            url=services_conf.doc_endpoint_url("adgs"),
            status=200,
            json=adgs_openapi,
        )

        build_aggregated_openapi(services_conf.file, tmp_path / "output.json")

        assert cadip_resp.call_count == 1
        assert adgs_resp.call_count == 1

    @responses.activate
    def test_writes_the_aggregated_openapi_in_the_given_file(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,
        services_conf: ServicesConfiguration,
        tmp_path: Path,
    ):
        responses.get(
            url=services_conf.doc_endpoint_url("cadip"),
            status=200,
            json=cadip_openapi,
        )
        responses.get(
            url=services_conf.doc_endpoint_url("adgs"),
            status=200,
            json=adgs_openapi,
        )

        output_file = tmp_path / "output.json"
        build_aggregated_openapi(services_conf.file, output_file)

        assert output_file.is_file()


class TestGenerateAggregateRestDocFailsWhen:
    @pytest.mark.parametrize(
        ["conf_file", "message"],
        [
            pytest.param(
                "not_found.yml",
                "File .*/not_found.yml was not found.",
                id="file not found",
            ),
            pytest.param(
                "invalid.yml",
                "while scanning a simple key.*",
                id="file with bad format",
            ),
        ],
    )
    @responses.activate
    def test_the_list_of_service_cannot_be_initialized(
        self,
        conf_file: str,
        message: str,
        tools_test_path: Path,
        tmp_path: Path,
    ):
        with pytest.raises(BuildOpenapiFailed) as exc_info:
            build_aggregated_openapi(
                tools_test_path / conf_file,
                tmp_path / "output.json",
            )

        cause = exc_info.value.__cause__
        assert isinstance(cause, (OSError, ScannerError))
        p = re.compile(message)
        assert p.match(str(cause))

    @responses.activate
    def test_a_service_documentation_fails_to_be_retrieved(
        self,
        cadip_openapi: dict,
        services_conf: ServicesConfiguration,
        tmp_path: Path,
    ):
        responses.get(
            url=services_conf.doc_endpoint_url("cadip"),
            status=200,
            json=cadip_openapi,
        )
        responses.get(
            url=services_conf.doc_endpoint_url("adgs"),
            status=500,
            json={"detail": "ADGS not happy."},
        )

        with pytest.raises(BuildOpenapiFailed) as exc_info:
            build_aggregated_openapi(services_conf.file, tmp_path / "output.json")

        cause = exc_info.value.__cause__
        assert isinstance(cause, HTTPError)
        assert str(cause) == "Unable to retrieve the openapi documentation for adgs."

        assert isinstance(cause.__cause__, HTTPError)
        assert cause.__cause__.response.status_code == 500
        assert json.loads(cause.__cause__.response.content) == {
            "detail": "ADGS not happy.",
        }

    @responses.activate
    def test_the_documentation_of_a_service_is_invalid(
        self,
        cadip_openapi: dict,
        services_conf: ServicesConfiguration,
        tmp_path: Path,
    ):
        responses.get(
            url=services_conf.doc_endpoint_url("cadip"),
            status=200,
            json=cadip_openapi,
        )
        responses.get(
            url=services_conf.doc_endpoint_url("adgs"),
            status=200,
            body="{,}",
        )

        with pytest.raises(BuildOpenapiFailed) as exc_info:
            build_aggregated_openapi(services_conf.file, tmp_path / "output.json")

        cause = exc_info.value.__cause__
        assert isinstance(cause, ValueError)
        assert str(cause) == "The openapi documentation for adgs service is invalid."

    @responses.activate
    def test_the_merge_process_failed(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,  # pylint: disable=unused-argument
        services_conf: ServicesConfiguration,
        tmp_path: Path,
    ):
        responses.get(
            url=services_conf.doc_endpoint_url("cadip"),
            status=200,
            json=cadip_openapi,
        )
        responses.get(
            url=services_conf.doc_endpoint_url("adgs"),
            status=200,
            json=a_service_openapi(service_name="adgs", openapi_version="9.9.9"),
        )

        with pytest.raises(BuildOpenapiFailed):
            build_aggregated_openapi(services_conf.file, tmp_path / "output.json")

    @responses.activate
    def test_the_aggregated_documentation_cannot_be_written(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,
        services_conf: ServicesConfiguration,
        tmp_path: Path,
    ):
        responses.get(
            url=services_conf.doc_endpoint_url("cadip"),
            status=200,
            json=cadip_openapi,
        )
        responses.get(
            url=services_conf.doc_endpoint_url("adgs"),
            status=200,
            json=adgs_openapi,
        )

        output_file = tmp_path / "output.json"
        output_file.mkdir()

        with pytest.raises(BuildOpenapiFailed) as exc_info:
            build_aggregated_openapi(services_conf.file, output_file)

        cause = exc_info.value.__cause__
        assert isinstance(cause, IOError)
        assert str(cause) == f"Unable to write the aggregated openapi into {output_file}."


class TestTheMergedOpenapi:
    @pytest.fixture
    @responses.activate
    def the_merge_openapis(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,
        services_conf: ServicesConfiguration,
        tmp_path: Path,
    ) -> dict:
        responses.get(
            url=services_conf.doc_endpoint_url("cadip"),
            status=200,
            json=cadip_openapi,
        )
        responses.get(
            url=services_conf.doc_endpoint_url("adgs"),
            status=200,
            json=adgs_openapi,
        )

        output_file = tmp_path / "output.json"
        build_aggregated_openapi(services_conf.file, output_file)

        with open(output_file, "r", encoding="utf-8") as file:
            return json.load(file)

    @responses.activate
    def test_openapi_is_the_same_as_the_services(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,
        the_merge_openapis: dict,
    ):
        assert the_merge_openapis["openapi"] == cadip_openapi["openapi"]
        assert the_merge_openapis["openapi"] == adgs_openapi["openapi"]

    @responses.activate
    def test_title_is_rs_server(
        self,
        cadip_openapi: dict,  # pylint: disable=unused-argument
        adgs_openapi: dict,  # pylint: disable=unused-argument
        the_merge_openapis: dict,
    ):
        assert the_merge_openapis["info"]["title"] == "RS-Server"

    @responses.activate
    def test_keeps_the_paths_of_all_services(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,
        the_merge_openapis: dict,
    ):
        assert all(path in the_merge_openapis["paths"] for path in cadip_openapi["paths"])
        assert all(path in the_merge_openapis["paths"] for path in adgs_openapi["paths"])

    def test_keeps_the_paths_configuration_of_one_of_the_service(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,
        the_merge_openapis: dict,
    ):
        assert the_merge_openapis["paths"]["/common"] in (
            cadip_openapi["paths"]["/common"],
            adgs_openapi["paths"]["/common"],
        )

    @responses.activate
    def test_keeps_the_component_of_all_services(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,
        the_merge_openapis: dict,
    ):
        assert all(
            component in the_merge_openapis["components"]["schemas"]
            for component in cadip_openapi["components"]["schemas"]
        )
        assert all(
            component in the_merge_openapis["components"]["schemas"]
            for component in adgs_openapi["components"]["schemas"]
        )

    def test_keeps_the_component_configuration_of_one_of_the_service(
        self,
        cadip_openapi: dict,
        adgs_openapi: dict,
        the_merge_openapis: dict,
    ):
        assert the_merge_openapis["components"]["schemas"]["CommonResponse"] in (
            cadip_openapi["components"]["schemas"]["CommonResponse"],
            adgs_openapi["components"]["schemas"]["CommonResponse"],
        )


class TestTestMergeProcessFailedWhen:
    @responses.activate
    def test_all_services_have_not_the_same_openapi_version(
        self,
        cadip_openapi: dict,
        services_conf: ServicesConfiguration,
        tmp_path: Path,
    ):
        adgs_openapi = a_service_openapi(service_name="adgs", openapi_version="9.9.9")
        responses.get(
            url=services_conf.doc_endpoint_url("cadip"),
            status=200,
            json=cadip_openapi,
        )
        responses.get(
            url=services_conf.doc_endpoint_url("adgs"),
            status=200,
            json=adgs_openapi,
        )

        output_file = tmp_path / "output.json"
        with pytest.raises(BuildOpenapiFailed) as exc_info:
            build_aggregated_openapi(services_conf.file, output_file)

        cause = exc_info.value.__cause__
        assert isinstance(cause, ValueError)
        assert str(cause) == "The openapi versions are not all the same : 3.1.0, 9.9.9"
