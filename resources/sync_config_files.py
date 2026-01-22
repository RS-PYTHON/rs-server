# Copyright 2023-2025 Airbus, CS Group
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

"""
Create rs-server configuration files from templates.
Copy them to rs-demo, rs-helm and rs-server-deployment repositories.
"""

import collections.abc
import copy
import json
import logging
import numbers
import os
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from yaml.representer import SafeRepresenter

# Avoid yaml references, see: https://stackoverflow.com/a/30682604
yaml.Dumper.ignore_aliases = lambda *_: True  # type: ignore

logger = logging.getLogger(__name__)

#
# Class definition


class Stations:  # pylint: disable=too-few-public-methods
    """Check a station name"""

    def __init__(self):
        self.value: str = ""
        self.adgs: bool = False
        self.cadip: bool = False
        self.edrs: bool = False
        self.lta: bool = False
        self.prip: bool = False

    def update(self, station: str):
        """Update the station name from a string."""
        if any(station.startswith(s) for s in ("adgs", "auxip")):
            self.adgs = True
            self.value = station
        elif any(station.startswith(s) for s in ("cadip", "ins", "mps", "mti", "nsg", "sgs")):
            self.cadip = True
            self.value = station
        elif any(station == s for s in ("pedc", "bedc")):
            self.edrs = True
            self.value = station
        elif any(station == s for s in ("lta",)):
            self.lta = True
            self.value = station
        elif any(station == s for s in ("s1a", "s2b")):
            self.prip = True
            self.value = station


@dataclass
class HelmOrInfraParams:
    """
    Parameters to copy a single configuration file to rs-helm or rs-server-deployment.

    Attributes:
        input_path_relative: input configuration file path, relative to the rs-server root dir
        input_root_tags: root yaml tags from where the input values must be read
        output_root_tags: root yaml tags where the output values must be written
        output_doc_index: output document index (start at 0) to write (only for yaml files with multiple documents)
        post_processing: function to execute on the output configuration under output_root_tags
    """

    input_path_relative: str
    input_root_tags: list[str]
    output_root_tags: list[str]
    output_doc_index: int
    post_processing: Callable[[dict], None] | None = None


#
# Utility functions


def recursive_update(old, new):
    """Recursive dict update, taken from: https://stackoverflow.com/a/3233356"""
    for key, value in new.items():
        if isinstance(value, collections.abc.Mapping):
            old[key] = recursive_update(old.get(key) or {}, value)
        else:
            old[key] = value
    return old


def strip_edrs_placeholders(value: str) -> str:
    """Remove quotes around EDRS placeholders in literal strings."""
    for placeholder in ("URL", "PORT", "USER", "PASS"):
        for quote in ("'", '"'):
            value = value.replace(f"{quote}{{{placeholder}}}{quote}", f"{{{placeholder}}}")
    return value


class LiteralStr(str):
    """
    To print literal yaml strings with |
    See: https://stackoverflow.com/a/20863889
    """


class QuotedStr(str):
    """To print quoted yaml strings with single quotes."""


def change_yaml_style(style, representer):
    """Goes with LiteralStr above"""

    def new_representer(dumper, data):
        scalar = representer(dumper, data)
        scalar.style = style
        return scalar

    return new_representer


#
# Init global variables


represent_literal_str = change_yaml_style("|", SafeRepresenter.represent_str)
yaml.add_representer(LiteralStr, represent_literal_str)
represent_quoted_str = change_yaml_style("'", SafeRepresenter.represent_str)
yaml.add_representer(QuotedStr, represent_quoted_str)


# Replace local urls like http(s)://(127.0.0.1|localhost):5xxx
REGEX_URL = re.compile(r"(https?://)(127.0.0.1|localhost):5\d+")
REGEX_DOMAIN = re.compile(r"mockup-.+.processing.svc.cluster.local")

# Replace k8s values
REGEX_RANGE_START = r"({{-?\s*range\s.*-?}})"
REGEX_RANGE_END = r"({{-?\s*end\s.*-?}})"

DCB_OPEN = "DOUBLE_CURLY_BRACES_OPEN"
DCB_CLOSE = "DOUBLE_CURLY_BRACES_CLOSE"

# The config files will be copied in rs-demo, rs-helm and rs-server-deployment if these projects
# are checkout under the same directory than rs-server.
rs_server_dir = Path(__file__).parent.parent
rs_demo_dir = rs_server_dir.parent / "rs-demo"
rs_helm_dir = rs_server_dir.parent / "rs-helm"
rs_deploy_dir = rs_server_dir.parent / "rs-server-deployment"
if not rs_demo_dir.is_dir():
    logger.warning(f"No 'rs-demo' repository found under: '{rs_demo_dir!s}'")
if not rs_helm_dir.is_dir():
    logger.warning(f"No 'rs-helm' repository found under: '{rs_helm_dir!s}'")
if not rs_deploy_dir.is_dir():
    logger.warning(f"No 'rs-server-deployment' repository found under: '{rs_deploy_dir!s}'")

# Extract the copyright header from this current file. It will be added to yaml files modified from a template.
COPYRIGHT_HEADER = ""
with open(__file__, encoding="utf-8") as this_script:
    for line in this_script:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            COPYRIGHT_HEADER += line + "\n"
        else:
            break

# Save the template file paths that were used to create each final configuration file.
# Key=final file, values=template files.
TEMPLATE_PATHS: dict[Path, list[str]] = {}

#
# Implement main features


def get_header(template_paths: list[str] | None = None, final_paths: Iterable[Path] | None = None):
    """
    Return header for configuration file created from template files.

    Args:
        template_paths: template file paths, relative to the rs-server root dir.
        final_paths: final configuration file absolute paths
    """
    if template_paths is None:
        template_paths = []
    if final_paths is None:
        final_paths = []

    # Get the template files used to create the final files
    for path in final_paths:
        if path in TEMPLATE_PATHS:
            template_paths += TEMPLATE_PATHS[path]
        else:
            logger.warning(f"Missing template mapping for: '{path!s}'")

    sep = "\n#  - rs-server/"
    header_paths = sep + sep.join(sorted(template_paths) + [os.path.relpath(__file__, rs_server_dir)])
    return (
        COPYRIGHT_HEADER
        + f"\n# THIS FILE WAS AUTOMATICALLY CREATED FROM:{header_paths}\n# DON'T MODIFY IT DIRECTLY !\n\n"
    )


def create_from_template(
    template_paths: list[str],
):  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
    """
    Create a configuration file from one or several template paths.

    Args:
        template_paths: template file paths, relative to the rs-server root dir.
    """
    all_files: dict = {}
    output_paths: set[Path] = set()
    for relative_path in template_paths:
        template_path: Path = rs_server_dir / relative_path

        is_json = template_path.suffix.lower() == ".json"
        is_yaml = template_path.suffix.lower() in (".yml", ".yaml")
        if not (is_json or is_yaml):
            raise RuntimeError(f"Unexpected file extension: '{template_path.absolute()!s}'")

        # The output path is the same than the template file witout the ".template*" extension.
        template_ext = ".template"
        suffixes = template_path.suffixes
        for i, suffix in enumerate(suffixes):
            if template_ext in suffix:
                suffixes.pop(i)  # remove .template* from the suffixes
                break
        if suffixes == template_path.suffixes:
            raise RuntimeError(f"'{template_ext}*' is missing from filename: '{template_path.absolute()!s}'")
        output_paths.add(
            template_path.parent
            / template_path.name.replace(
                "".join(template_path.suffixes),
                "".join(suffixes),
            ),
        )
        if len(output_paths) > 1:
            raise RuntimeError(f"Incoherent output files: {output_paths}")

        # Read the yaml or json file
        with open(template_path, encoding="utf-8") as opened:
            if is_json:
                file = json.loads(opened.read())
            else:
                file = yaml.safe_load(opened)

        # A template should defined at the top of the file and be applied to each file node
        template = file.pop("template")

        # If the file contains a single node, we guess that it is a root title.
        # We apply the template to its children.
        nodes = file
        if len(file) == 1:
            nodes = next(iter(file.values()))

        if isinstance(nodes, list):
            for i, node in enumerate(nodes):
                nodes[i] = recursive_update(copy.deepcopy(template), node)
        elif isinstance(nodes, dict):
            for key, node in nodes.items():
                nodes[key] = recursive_update(copy.deepcopy(template), node)
        else:
            raise RuntimeError(f"Unrecognized data structure for: '{template_path.absolute()!s}'")

        all_files.update(file)

    # We should have a single output file
    if len(output_paths) != 1:
        raise RuntimeError(f"Not a single output file: {output_paths}")
    output_path: Path = output_paths.pop()
    logger.info(f"Update: '{output_path!s}'")

    # Save the template file paths that were used to create each final configuration file.
    TEMPLATE_PATHS[output_path] = template_paths

    # Specific post-processing for files that must keep literal block style
    def post_process(file_path: Path, content: dict):
        """Apply file-specific tweaks after template rendering."""
        if file_path.name == "edrs_stations.yaml" and isinstance(content, dict) and "stations" in content:
            stations_yaml = yaml.dump(content["stations"], default_flow_style=False, sort_keys=False)
            stations_yaml = strip_edrs_placeholders(stations_yaml)
            lines = stations_yaml.splitlines()
            formatted_lines = []
            first_station = True
            for station_line in lines:
                is_station_key = station_line and (station_line.lstrip() == station_line) and station_line.endswith(":")
                if is_station_key:
                    if not first_station:
                        formatted_lines.append("")
                    first_station = False
                formatted_lines.append(station_line)
            content["stations"] = LiteralStr("\n".join(formatted_lines) + "\n")

    post_process(output_path, all_files)

    # Write back the templated file
    with open(output_path, "w", encoding="utf-8") as opened:
        opened.write(get_header(template_paths))
        if is_json:
            json.dump(all_files, opened, indent=2, sort_keys=False)
        else:
            yaml.dump(all_files, opened, default_flow_style=False, sort_keys=False)


#
# rs-demo


def extract_structure(value: Any) -> Any:
    """Return a structure-only representation of the input value."""
    if isinstance(value, dict):
        return {key: extract_structure(subvalue) for key, subvalue in value.items()}
    if isinstance(value, list):
        return [extract_structure(subvalue) for subvalue in value]
    return None


def get_structure(file_contents: dict | None) -> Any:
    """Return structure-only representation, parsing embedded stations yaml if needed."""
    if not isinstance(file_contents, dict):
        return None
    stations_value = file_contents.get("stations")
    if isinstance(stations_value, str):
        # Normalize placeholders so template vs. local values compare equal.
        stations_value = re.sub(r"\{[A-Z0-9_]+\}", "PLACEHOLDER", stations_value)
        try:
            stations_value = yaml.safe_load(stations_value)
        except yaml.YAMLError:
            # Keep as string if stations content is not valid YAML.
            stations_value = stations_value
        file_contents = dict(file_contents)
        file_contents["stations"] = stations_value
    return extract_structure(file_contents)


def should_skip_demo_edrs_update(config_path: Path, input_path: Path) -> bool:
    """Return True when existing and input configs share the same structure."""
    try:
        with open(config_path, encoding="utf-8") as opened:
            existing_config = yaml.safe_load(opened)
        with open(input_path, encoding="utf-8") as opened:
            input_config = yaml.safe_load(opened)
        return get_structure(existing_config) == get_structure(input_config)
    except Exception:  # pylint: disable=broad-exception-caught
        return False


def update_demo_values(parent_key: str, config: dict, station: Stations | None = None):
    """
    Recursive function to update values from the config file.

    Args:
        parent_key: parent yaml tag name
        config: current yaml block
        station: is the current yaml block implementing an adgs station, or cadip station, or ...
    """
    if not isinstance(config, dict):
        raise RuntimeError(f"Invalid argument: {config}")

    if station is None:
        station = Stations()

    # Check station name from parent key
    station = copy.deepcopy(station)  # save the instance so the previous recursive calls are not impacted
    station.update(parent_key)

    def update_single_value(value: str) -> str:
        """Return a single updated url value."""
        if not isinstance(value, str):
            raise RuntimeError(f"Invalid argument: {value}")
        if station.adgs:
            return re.sub(REGEX_DOMAIN, "adgs-station", re.sub(REGEX_URL, r"\g<1>adgs-station:5000", value))
        if station.cadip:
            return re.sub(REGEX_DOMAIN, "cadip-station", re.sub(REGEX_URL, r"\g<1>cadip-station:5000", value))
        if station.edrs:
            return re.sub(REGEX_DOMAIN, "edrs-station", re.sub(REGEX_URL, r"\g<1>edrs-station:5000", value))
        if station.lta:
            return re.sub(REGEX_DOMAIN, "lta-station", re.sub(REGEX_URL, r"\g<1>lta-station:5000", value))
        if station.prip:
            return re.sub(REGEX_DOMAIN, "prip-station", re.sub(REGEX_URL, r"\g<1>prip-station:5000", value))
        # No modification
        return value

    # Apply regex recursively
    for key, value in config.items():

        # Recursive calls on dicts
        if isinstance(value, dict):
            update_demo_values(key, value, station)

        # Update string value
        elif isinstance(value, str):
            config[key] = update_single_value(value)

        # Recursive calls on lists...
        elif isinstance(value, list):
            for i, subvalue in enumerate(value):

                # ... on list dicts
                if isinstance(subvalue, dict):
                    update_demo_values(key, subvalue, station)

                # ... or on list string values
                elif isinstance(subvalue, str):
                    value[i] = update_single_value(subvalue)


def copy_to_demo(input_path_relative: str):
    """
    Copy and update a configuration file from rs-server to rs-demo.

    Args:
        input_path_relative: input configuration file path, relative to the rs-server root dir
    """
    if not rs_demo_dir.is_dir():
        return

    # Copy the file, keep the same name
    input_path = rs_server_dir / input_path_relative
    config_path = rs_demo_dir / "local-mode/config" / input_path.name
    if input_path.name == "edrs_stations.yaml" and config_path.is_file():
        # Same structure: keep local credentials untouched.
        if should_skip_demo_edrs_update(config_path, input_path):
            logger.info(f"Skip update: '{config_path!s}' (same structure)")
            return
    logger.info(f"Update: '{config_path!s}'")
    shutil.copyfile(input_path, config_path)

    # Open the output file.
    # There are only yaml files for now
    if config_path.suffix.lower() not in (".yml", ".yaml"):
        raise RuntimeError(f"File type not supported: {config_path}")
    with open(config_path, encoding="utf-8") as opened:
        file = yaml.safe_load(opened)

    update_demo_values("", file)

    if (
        input_path.name == "edrs_stations.yaml"
        and isinstance(file, dict)
        and isinstance(file.get("stations"), str)
        and "\n" in file["stations"]
    ):
        stations_value = strip_edrs_placeholders(file["stations"])
        if not stations_value.endswith("\n"):
            stations_value += "\n"
        file["stations"] = LiteralStr(stations_value)

    # Write the modified output file
    with open(config_path, "w", encoding="utf-8") as opened:
        opened.write(get_header(final_paths=[input_path]))
        yaml.dump(file, opened, default_flow_style=False, sort_keys=False)


#
# rs-helm and rs-server-deployment


def copy_to_helm_or_infra(
    all_params: list[HelmOrInfraParams],
    output_path: Path,
):
    """
    Copy and update a configuration file from rs-server to rs-helm or rs-server-deployment.

    Args:
        all_params: parameters to copy each configuration file
        output_path: output configuration absolute path
    """
    logger.info(f"Update: '{output_path!s}'")

    # The k8s configmap files contain strings that contain yaml contents.
    yaml_as_string = output_path.name == "configmap.yaml"

    # Open the output file if it exists.
    output_configs = None
    if output_path.is_file():
        with open(output_path, encoding="utf-8") as opened:
            output_configs = read_helm_or_infra(opened.read(), yaml_as_string)

    # Else just start from empty dicts
    if not output_configs:
        output_configs = [{}] * len(all_params)

    # For each input configuration file
    for params in all_params:

        # Check that the document exists in the output file
        if params.output_doc_index > len(output_configs):
            raise RuntimeError(f"Document index #{params.output_doc_index} not found in: {output_path!r}")

        # Call the sub-function on a single doc
        try:
            copy_to_helm_or_infra_single_doc(params, output_configs[params.output_doc_index])
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.error("Failed to update single infra doc: %s", params, exc_info=e)

    # Get the file header from the list of input configuration files
    input_paths = {rs_server_dir / param.input_path_relative for param in all_params}
    header = get_header(final_paths=input_paths)

    # Write the modified output file into a string
    yaml_contents = write_helm_or_infra(output_configs, yaml_as_string)
    if output_path == rs_helm_dir / "charts/rs-server-station-secrets/values.yaml":
        yaml_contents = re.sub(
            r"(^\s+-----END (?:CERTIFICATE|RSA PRIVATE KEY)-----\n)(?!\n)",
            r"\1\n",
            yaml_contents,
            flags=re.MULTILINE,
        )
        yaml_contents = re.sub(r"\n(?:[ \t]*\n)+\Z", "\n", yaml_contents)
    with open(output_path, "w", encoding="utf-8") as opened:
        opened.write(header)
        opened.write(yaml_contents)


def read_helm_or_infra(yaml_contents: str, yaml_as_string: bool) -> list[dict]:
    """
    Read Kubernetes configuration files that contain not yaml-compliant values and need special care.

    Args:
        yaml_contents: yaml contents as a string
        yaml_as_string: should configmap.yaml string values be converted to yaml dict ?

    Returns:
        list of yaml dicts = one per document
    """
    if not isinstance(yaml_contents, str):
        raise RuntimeError(f"Invalid argument: {yaml_contents}")

    # Python yaml cannot open the {{- range ... }}' and '{{- end }}' tags
    # that do not contain a : at the end, so we add the : here
    yaml_contents = re.sub(re.compile(REGEX_RANGE_START), r"\g<1>:", yaml_contents)
    yaml_contents = re.sub(re.compile(REGEX_RANGE_END), r"\g<1>:", yaml_contents)

    # Python yaml cannot open files with k8s values like {{ some.thing }}
    # so we replace them with any other strings.
    yaml_contents = yaml_contents.replace("{{", DCB_OPEN)
    yaml_contents = yaml_contents.replace("}}", DCB_CLOSE)

    # Read the configuration file as a multidoc file (with docs separated by '---')
    output_configs = list(yaml.safe_load_all(yaml_contents)) or []

    # Parse strings that contain yaml values
    if yaml_as_string:
        for output_config in output_configs:
            data = output_config.get("data", {})
            for key, value in data.items():
                if key == f"{DCB_OPEN} .Values.app.edrsStations {DCB_CLOSE}":
                    continue
                if isinstance(value, str):
                    data[key] = yaml.safe_load(value)

    return output_configs


def write_helm_or_infra(output_configs: list[dict], yaml_as_string: bool) -> str:
    """
    Write Kubernetes configuration files that contain not yaml-compliant values and need special care.

    Args:
        output_configs: list of yaml dicts = one per document
        yaml_as_string: should configmap.yaml string values be converted from yaml dict ?

    Returns:
        String contents.
    """
    if not isinstance(output_configs, list):
        raise RuntimeError(f"Invalid argument: {output_configs}")

    # Use a large width so we don't split long lines
    witdh = 1000

    # Unparse yaml contents into literal strings (indented with |)
    if yaml_as_string:

        def format_config_value(config_key: str, config_value: Any) -> Any:
            """Format configmap values that embed yaml."""
            if isinstance(config_value, dict):
                if config_key == f"{DCB_OPEN} .Values.app.edrsStations {DCB_CLOSE}" and "stations" in config_value:
                    config_value["stations"] = LiteralStr("\n")
                stations_value = config_value.get("stations")
                if isinstance(stations_value, str) and "\n" in stations_value:
                    stations_value = strip_edrs_placeholders(stations_value)
                    if not stations_value.endswith("\n"):
                        stations_value += "\n"
                    config_value["stations"] = LiteralStr(stations_value)
                return LiteralStr(yaml.dump(config_value, default_flow_style=False, sort_keys=False, width=witdh))
            if isinstance(config_value, str) and "\n" in config_value:
                if config_key == f"{DCB_OPEN} .Values.app.edrsStations {DCB_CLOSE}":
                    config_value = re.sub(r"stations: \|\n\s*\n", "stations: |\n", config_value, count=1)
                return LiteralStr(config_value if config_value.endswith("\n") else config_value + "\n")
            return config_value

        for output_config in output_configs:
            data = output_config.get("data", {})
            for key, value in data.items():
                data[key] = format_config_value(key, value)

    # Write the configuration file as a multidoc file (with docs separated by '---')
    yaml_contents = yaml.dump_all(output_configs, default_flow_style=False, sort_keys=False, width=witdh)

    # Restore the double curly braces
    yaml_contents = yaml_contents.replace(DCB_OPEN, "{{")
    yaml_contents = yaml_contents.replace(DCB_CLOSE, "}}")

    # Remove the added : after the k8s values
    suffix = r":(\s*null)?"  # yaml parsing added ': null' after the tag
    yaml_contents = re.sub(re.compile(REGEX_RANGE_START + suffix), r"\g<1>", yaml_contents)
    yaml_contents = re.sub(re.compile(REGEX_RANGE_END + suffix), r"\g<1>", yaml_contents)

    # Normalize edrsStations literal block to avoid "|2+" formatting
    yaml_contents = re.sub(
        re.compile(
            r"(^\s*\{\{\s*\.Values\.app\.edrsStations\s*\}\}: \|\n\s+stations: )\|\d\+",
            re.MULTILINE,
        ),
        r"\1|",
        yaml_contents,
    )

    return yaml_contents


def copy_to_helm_or_infra_single_doc(  # pylint: disable=too-many-statements
    params: HelmOrInfraParams,
    output_config: dict,
):
    """
    Copy and update a single yaml document from rs-server to rs-helm or rs-server-deployment.

    Args:
        params parameters to copy a single configuration file
        output_config: current output yaml block
    """

    # There are only yaml files for now
    input_path = rs_server_dir / params.input_path_relative
    if input_path.suffix.lower() not in (".yml", ".yaml"):
        raise RuntimeError(f"File type not supported: {input_path}")

    # Open the input file
    with open(input_path, encoding="utf-8") as opened:
        input_config = yaml.safe_load(opened)

    # Start from the input and output root tag(s)
    for tag in params.input_root_tags:
        input_config = input_config[tag]  # input tags must exist
    for tag in params.output_root_tags:
        if tag not in output_config:  # output tags are optional
            output_config[tag] = {}
            logger.warning(f"Tag does not exist in output file: {tag!r}")
        output_config = output_config[tag]

    def update_all_values(  # pylint: disable=too-many-branches
        parent_keys: list[str],
        input_config: dict,
        output_config: dict,
        station: Stations = Stations(),
    ):
        """
        Recursive function to update values from the config file.

        Args:
            parent_keys: parent yaml tag names
            input_config: current input yaml block
            output_config: current output yaml block
            station: is the current yaml block implementing an adgs station, or cadip station, or ...
        """
        if not isinstance(input_config, dict):
            raise RuntimeError(f"Invalid input_config: {input_config}")
        if not isinstance(output_config, dict):
            raise RuntimeError(f"Invalid output_config: {output_config}")

        # Check station name from parent key
        station = copy.deepcopy(station)  # save the instance so the previous recursive calls are not impacted
        station.update(parent_keys[-1] if parent_keys else "")

        def update_single_value(input_value: Any, output_value: str) -> str:
            """Return a single updated value."""
            if not isinstance(output_value, str):
                raise RuntimeError(f"Invalid argument: {output_value}")

            # If the output value is like {{ some.thing }}, it's a k8s value, we don't change it.
            if (DCB_OPEN in output_value) and (DCB_CLOSE in output_value):
                return output_value

            # Else try to update url in the input value
            updated_value = input_value
            if station.adgs:
                updated_value = re.sub(
                    REGEX_URL,
                    rf"\g<1>mockup-station-{station.value}.processing.svc.cluster.local:8080",
                    input_value,
                )
            elif station.cadip:
                updated_value = re.sub(
                    REGEX_URL,
                    rf"\g<1>mockup-station-cadip-{station.value}.processing.svc.cluster.local:8080",
                    input_value,
                )
            elif station.edrs:
                updated_value = re.sub(
                    REGEX_URL,
                    rf"\g<1>mockup-station-{station.value}.processing.svc.cluster.local:21",
                    input_value,
                )
            elif station.lta:
                updated_value = re.sub(
                    REGEX_URL,
                    rf"\g<1>mockup-lta-{station.value}.processing.svc.cluster.local:8080",
                    input_value,
                )
            elif station.prip:
                updated_value = re.sub(
                    REGEX_URL,
                    rf"\g<1>mockup-prip-{station.value}.processing.svc.cluster.local:8080",
                    input_value,
                )
            return updated_value

        for key in output_config.keys():
            if key not in input_config.keys():
                logger.warning(f"Missing from rs-server: {'.'.join(parent_keys + [key])!r}")

        # Copy values recursively from input to output
        for key, input_value in input_config.items():

            if key not in output_config:
                output_config[key] = input_value

            # Recursive calls on dicts
            output_value = output_config[key]
            if isinstance(output_value, dict):
                if not isinstance(input_value, dict):
                    output_config[key] = input_value
                    continue
                update_all_values(parent_keys + [key], input_value, output_value, station)

            # Update string value
            elif isinstance(output_value, str):
                if isinstance(input_value, str):
                    output_config[key] = update_single_value(input_value, output_value)
                else:
                    output_config[key] = input_value

            # Update number values
            elif isinstance(output_value, numbers.Number):
                if not isinstance(input_value, numbers.Number):
                    raise RuntimeError(f"Invalid argument: {input_value}")
                output_config[key] = input_value

            # Recursive calls on lists...
            elif isinstance(output_value, list):

                # If the input value is not a list or does not have the same length,
                # I don't really know what to do, so just copy the input value.
                if (not isinstance(input_value, list)) or (len(input_value) != len(output_value)):
                    output_config[key] = input_value

                # Else, do a recursive call on each lists element ...
                else:
                    for i, output_subvalue in enumerate(output_value):
                        input_subvalue = input_value[i]

                        # ... on list dicts
                        if isinstance(output_subvalue, dict):
                            update_all_values(parent_keys + [key], input_subvalue, output_subvalue, station)

                        # ... or on list string values
                        elif isinstance(output_subvalue, str):
                            output_value[i] = update_single_value(input_subvalue, output_subvalue)

                        # ... or on list number values
                        elif isinstance(output_subvalue, numbers.Number):
                            output_value[i] = input_subvalue

    if isinstance(input_config, dict) and isinstance(output_config, dict):
        update_all_values([], input_config, output_config)
    else:
        logger.error(f"Cannot update values for {input_config} => {output_config}")

    # Call post-processing on output configuration
    if params.post_processing:
        params.post_processing(output_config)


if __name__ == "__main__":

    # Create configuration files from templates. Paths are given from the rs-server root dir.
    for templates in (
        ["services/common/config/rs-server.template.yaml"],
        ["services/adgs/config/adgs_search_config.template.yaml"],
        ["services/adgs/config/adgs_ws_config_token_module.template.yaml"],
        ["services/adgs/config/adgs_ws_config.template.yaml"],
        ["services/cadip/config/cadip_search_config.template.yaml"],
        [
            "services/cadip/config/cadip_ws_config_token_module.template.yaml",
            "services/cadip/config/cadip_ws_config_token_module.template_session.yaml",
        ],
        [
            "services/cadip/config/cadip_ws_config.template.yaml",
            "services/cadip/config/cadip_ws_config.template_session.yaml",
        ],
        ["services/edrs/config/edrs_search_config.template.yaml"],
        ["services/edrs/config/edrs_stations.template.yaml"],
        ["services/prip/config/prip_search_config.template.yaml"],
        ["services/prip/config/prip_ws_config_token_module.template.yaml"],
        ["services/prip/config/prip_ws_config.template.yaml"],
    ):
        create_from_template(templates)

    # Copy resulting files to rs-demo
    for config_path_relative in (
        "services/common/config/rs-server.yaml",
        "services/adgs/config/adgs_ws_config.yaml",
        "services/cadip/config/cadip_ws_config.yaml",
        "services/prip/config/prip_ws_config.yaml",
        "services/adgs/config/adgs_ws_config_token_module.yaml",
        "services/cadip/config/cadip_ws_config_token_module.yaml",
        "services/prip/config/prip_ws_config_token_module.yaml",
        "services/edrs/config/edrs_search_config.yaml",
        "services/edrs/config/edrs_stations.yaml",
    ):
        copy_to_demo(config_path_relative)

    #
    # Copy resulting files to rs-helm and rs-server-deployment

    def remove_session_stations(output_config: dict):
        """For this file, don't copy the cadip "_session" stations."""
        if not isinstance(output_config, dict):
            return
        for station in list(output_config.keys()):
            if station.endswith("_session"):
                output_config.pop(station)
        for station_name in ("pedc", "bedc"):
            station = output_config.get(station_name)
            if not isinstance(station, dict):
                continue
            authentication = station.get("authentication")
            if not isinstance(authentication, dict):
                continue
            for key in ("username", "password"):
                if key in authentication:
                    authentication[key] = QuotedStr(str(authentication[key]))
            for key in ("ca_crt", "client_crt", "client_key"):
                if key in authentication and authentication[key] is not None:
                    cert_value = str(authentication[key]).rstrip("\n")
                    authentication[key] = LiteralStr(cert_value)

    station_params = HelmOrInfraParams(
        "services/common/config/rs-server.yaml",
        ["external_data_sources"],
        ["app", "stations"],
        0,
        remove_session_stations,
    )
    copy_to_helm_or_infra([station_params], rs_helm_dir / "charts/rs-server-station-secrets/values.yaml")

    copy_to_helm_or_infra(
        [
            HelmOrInfraParams(
                "services/adgs/config/adgs_ws_config.yaml",
                ["adgs"],  # use the first input station values for all other stations
                [  # where to write in the output file
                    "data",
                    f"{DCB_OPEN} .Values.app.eodagConfigFile {DCB_CLOSE}",
                    f"{DCB_OPEN}- range $k, $v := .Values.app.station {DCB_CLOSE}",
                    f"{DCB_OPEN} $k {DCB_CLOSE}",
                ],
                0,  # output doc index
            ),
            HelmOrInfraParams(
                "services/adgs/config/adgs_ws_config_token_module.yaml",
                ["adgs"],  # use the first input station values for all other stations
                [  # where to write in the output file
                    "data",
                    f"{DCB_OPEN} .Values.app.eodagConfigFileTokenModule {DCB_CLOSE}",
                    f"{DCB_OPEN}- range $k, $v := .Values.app.station {DCB_CLOSE}",
                    f"{DCB_OPEN} $k {DCB_CLOSE}",
                ],
                1,
            ),
            HelmOrInfraParams(
                "services/adgs/config/adgs_search_config.yaml",
                [],
                ["data", f"{DCB_OPEN} .Values.app.adgsSearchConfigFile {DCB_CLOSE}"],
                2,
            ),
        ],
        rs_helm_dir / "charts/rs-server-adgs/templates/configmap.yaml",
    )

    copy_to_helm_or_infra(
        [
            HelmOrInfraParams(
                "services/edrs/config/edrs_search_config.yaml",
                [],
                ["data", f"{DCB_OPEN} .Values.app.edrsSearchConfigFile {DCB_CLOSE}"],
                0,
            ),
        ],
        rs_helm_dir / "charts/rs-server-edrs/templates/configmap.yaml",
    )

    copy_to_helm_or_infra(
        [
            HelmOrInfraParams(
                "services/cadip/config/cadip_ws_config.yaml",
                ["cadip"],  # use the first input station values for all other stations
                [  # where to write in the output file
                    "data",
                    f"{DCB_OPEN} .Values.app.eodagConfigFile {DCB_CLOSE}",
                    f"{DCB_OPEN}- range $k, $v := .Values.app.station {DCB_CLOSE}",
                    f"{DCB_OPEN} $k {DCB_CLOSE}",
                ],
                0,  # output doc index
            ),
            HelmOrInfraParams(  # same for _session stations
                "services/cadip/config/cadip_ws_config.yaml",
                ["cadip_session"],
                [
                    "data",
                    f"{DCB_OPEN} .Values.app.eodagConfigFile {DCB_CLOSE}",
                    f"{DCB_OPEN}- range $k, $v := .Values.app.station {DCB_CLOSE}",
                    f"{DCB_OPEN} $k {DCB_CLOSE}_session",
                ],
                0,  # output doc index
            ),
            HelmOrInfraParams(  # same for _token_module
                "services/cadip/config/cadip_ws_config_token_module.yaml",
                ["cadip"],
                [  # where to write in the output file
                    "data",
                    f"{DCB_OPEN} .Values.app.eodagConfigFileTokenModule {DCB_CLOSE}",
                    f"{DCB_OPEN}- range $k, $v := .Values.app.station {DCB_CLOSE}",
                    f"{DCB_OPEN} $k {DCB_CLOSE}",
                ],
                1,
            ),
            HelmOrInfraParams(  # same for _token_module and _session stations
                "services/cadip/config/cadip_ws_config_token_module.yaml",
                ["cadip_session"],
                [  # where to write in the output file
                    "data",
                    f"{DCB_OPEN} .Values.app.eodagConfigFileTokenModule {DCB_CLOSE}",
                    f"{DCB_OPEN}- range $k, $v := .Values.app.station {DCB_CLOSE}",
                    f"{DCB_OPEN} $k {DCB_CLOSE}_session",
                ],
                1,
            ),
            HelmOrInfraParams(
                "services/cadip/config/cadip_search_config.yaml",
                [],
                ["data", f"{DCB_OPEN} .Values.app.cadipSearchConfigFile {DCB_CLOSE}"],
                2,
            ),
        ],
        rs_helm_dir / "charts/rs-server-cadip/templates/configmap.yaml",
    )

    copy_to_helm_or_infra(
        [
            HelmOrInfraParams(
                "services/prip/config/prip_ws_config.yaml",
                ["s1a"],  # use the first input station values for all other stations
                [  # where to write in the output file
                    "data",
                    f"{DCB_OPEN} .Values.app.eodagConfigFile {DCB_CLOSE}",
                    f"{DCB_OPEN}- range $k, $v := .Values.app.station {DCB_CLOSE}",
                    f"{DCB_OPEN} $k {DCB_CLOSE}",
                ],
                0,  # output doc index
            ),
            HelmOrInfraParams(
                "services/prip/config/prip_ws_config_token_module.yaml",
                ["s1a"],  # use the first input station values for all other stations
                [  # where to write in the output file
                    "data",
                    f"{DCB_OPEN} .Values.app.eodagConfigFileTokenModule {DCB_CLOSE}",
                    f"{DCB_OPEN}- range $k, $v := .Values.app.station {DCB_CLOSE}",
                    f"{DCB_OPEN} $k {DCB_CLOSE}",
                ],
                1,
            ),
            HelmOrInfraParams(
                "services/prip/config/prip_search_config.yaml",
                [],
                ["data", f"{DCB_OPEN} .Values.app.pripSearchConfigFile {DCB_CLOSE}"],
                2,
            ),
        ],
        rs_helm_dir / "charts/rs-server-prip/templates/configmap.yaml",
    )
