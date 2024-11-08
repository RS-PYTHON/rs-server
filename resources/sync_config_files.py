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

"""
Create rs-server configuration files from templates.
Copy them to rs-demo and rs-helm repositories.
"""

import collections.abc
import copy
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from rs_server_common.utils.logging import Logging
from yaml.representer import SafeRepresenter

# Avoid yaml references, see: https://stackoverflow.com/a/30682604
yaml.Dumper.ignore_aliases = lambda *_: True

logger = Logging.default(Path(__file__).name)


# Save the header for each config file. It is different between rs-demo, and rs-helm/infra
@dataclass
class Header:
    demo: str
    helm_infra: str


FILE_HEADERS: dict[Path, Header] = {}


class Stations:
    """Check a station name"""

    def __init__(self):
        self.value: str = ""
        self.adgs: bool = False
        self.cadip: bool = False
        self.lta: bool = False
        self.prip: bool = False

    def update(self, station: str):
        if any(station.startswith(s) for s in ("adgs", "auxip")):
            self.adgs = True
            self.value = station
        elif any(station.startswith(s) for s in ("cadip", "ins", "mps", "mti", "nsg", "sgs")):
            self.cadip = True
            self.value = station
        elif any(station == s for s in ("lta",)):
            self.lta = True
            self.value = station
        elif any(station == s for s in ("s1a", "s2a")):
            self.prip = True
            self.value = station


def recursive_update(old, new):
    """Recursive dict update, taken from: https://stackoverflow.com/a/3233356"""
    for key, value in new.items():
        if isinstance(value, collections.abc.Mapping):
            old[key] = recursive_update(old.get(key) or {}, value)
        else:
            old[key] = value
    return old


# To print literal yaml strings with |
# See: https://stackoverflow.com/a/20863889
class literal_str(str):
    pass


def change_yaml_style(style, representer):
    def new_representer(dumper, data):
        scalar = representer(dumper, data)
        scalar.style = style
        return scalar

    return new_representer


represent_literal_str = change_yaml_style("|", SafeRepresenter.represent_str)
yaml.add_representer(literal_str, represent_literal_str)


# Used to replace local urls like http(s)://(127.0.0.1|localhost):5xxx
REGEX_URL = re.compile(r"(https?://)(127.0.0.1|localhost):5\d+")

DCB_OPEN = "DOUBLE_CURLY_BRACES_OPEN"
DCB_CLOSE = "DOUBLE_CURLY_BRACES_CLOSE"

# The config files will be copied in rs-demo and rs-helm if these projects
# are checkout under the same directory than rs-server.
rs_server_dir = Path(__file__).parent.parent
rs_demo_dir = rs_server_dir.parent / "rs-demo"
rs_helm_dir = rs_server_dir.parent / "rs-helm"
rs_infra_dir = rs_server_dir.parent / "rs-infrastructure"
if not rs_demo_dir.is_dir():
    logger.warning(f"No 'rs-demo' repository found under: '{rs_demo_dir!s}'")
if not rs_helm_dir.is_dir():
    logger.warning(f"No 'rs-helm' repository found under: '{rs_helm_dir!s}'")
if not rs_infra_dir.is_dir():
    logger.warning(f"No 'rs-infrastructure' repository found under: '{rs_infra_dir!s}'")

# Extract the header from this current file. It will be added to yaml files modified from a template.
header = ""
with open(__file__, "r") as this_script:
    for line in this_script:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            header += line + "\n"
        else:
            break


def create_from_template(template_paths: list[str]):
    """
    Create a configuration file from one or several template paths.
    Paths are given from the rs-server root dir.
    """

    # Add a warning message to the header
    sep = "\n#  - rs-server/"
    header_paths = sep + sep.join(template_paths + [os.path.relpath(__file__, rs_server_dir)])
    this_header = (
        header + f"\n# THIS FILE WAS AUTOMATICALLY CREATED FROM:{header_paths}\n# DON'T MODIFY IT DIRECTLY !\n\n"
    )

    # Header for rs-helm and rs-infrastructure
    helm_infra_header = header + f"\n# NOTE: THIS FILE WAS PARTLY CREATED FROM:{header_paths}\n\n"

    all_files: dict = {}
    output_paths: set[Path] = set()
    for template_path in template_paths:
        template_path = rs_server_dir / template_path

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

    # Write back the templated file
    assert len(output_paths) == 1  # we should have a single output file
    output_path: Path = output_paths.pop()
    FILE_HEADERS[output_path] = Header(this_header, helm_infra_header)
    with open(output_path, "w") as opened:
        logger.info(f"Update: '{output_path!s}'")
        opened.write(this_header)
        if is_json:
            json.dump(all_files, opened, indent=2, sort_keys=False)
        else:
            yaml.dump(all_files, opened, default_flow_style=False, sort_keys=False)


def copy_to_demo(input_path_relative: str):
    """
    Copy a configuration file from rs-server to rs-demo.
    Path is given from the rs-server root dir.
    """
    if not rs_demo_dir.is_dir():
        return

    # Copy the file, keep the same name
    input_path = rs_server_dir / input_path_relative
    config_path = rs_demo_dir / "local-mode/config" / input_path.name
    shutil.copyfile(input_path, config_path)

    # Open the output file.
    # There are only yaml files for now
    assert config_path.suffix.lower() in (".yml", ".yaml")
    with open(config_path, encoding="utf-8") as opened:
        file = yaml.safe_load(opened)

    def update_all_values(parent_key: str, config: dict, stations: Stations = Stations()):
        """
        Recursive function to update values from the config file.
        """
        assert isinstance(config, dict)

        # Check station name from parent key
        stations = copy.deepcopy(stations)  # save the instance so the previous recursive calls are not impacted
        stations.update(parent_key)

        def update_single_value(value: str) -> str:
            """Return a single updated url value."""
            assert isinstance(value, str)
            if stations.adgs:
                return re.sub(REGEX_URL, r"\g<1>adgs-station:5000", value)
            elif stations.cadip:
                return re.sub(REGEX_URL, r"\g<1>cadip-station:5000", value)
            elif stations.lta:
                return re.sub(REGEX_URL, r"\g<1>lta-station:5000", value)
            elif stations.prip:
                return re.sub(REGEX_URL, r"\g<1>prip-station:5000", value)
            else:
                return value

        # Apply regex recursively
        for key, value in config.items():

            # Recursive calls on dicts
            if isinstance(value, collections.abc.Mapping):
                update_all_values(key, value, stations)

            # Update string value
            elif isinstance(value, str):
                config[key] = update_single_value(value)

            # Recursive calls on lists...
            elif isinstance(value, collections.abc.Iterable):
                for i, subvalue in enumerate(value):

                    # ... on list dicts
                    if isinstance(subvalue, collections.abc.Mapping):
                        update_all_values(key, subvalue, stations)

                    # ... or on list string values
                    elif isinstance(subvalue, str):
                        value[i] = update_single_value(subvalue)

    update_all_values("", file)

    # Write the modified output file
    with open(config_path, "w") as opened:
        logger.info(f"Update: '{config_path!s}'")
        opened.write(FILE_HEADERS[input_path].demo)
        yaml.dump(file, opened, default_flow_style=False, sort_keys=False)


def copy_to_helm_infra(
    input_path_relative: str,
    input_roots: list[str],
    output_path: Path,
    output_roots: list[str],
    output_doc_index: int = 0,  # indexes start at 0
):
    """
    Copy and update a configuration file that contains multiple yaml documents
    from rs-server to rs-helm or rs-infrastructure.
    Input path is given from the rs-server root dir.
    """
    # There are only yaml files for now
    input_path = rs_server_dir / input_path_relative
    assert input_path.suffix.lower() in (".yml", ".yaml")

    # Open the input file
    with open(input_path, encoding="utf-8") as opened:
        input_config = yaml.safe_load(opened)

    # Open the output file if it exists.
    # Python yaml cannot open files with k8s values like {{ some.thing }}
    # so we need to hack the file first to replace these values with sed.
    if output_path.is_file():
        with open(output_path, encoding="utf-8") as opened:
            plain_file = opened.read()
            plain_file = plain_file.replace("{{", DCB_OPEN)
            plain_file = plain_file.replace("}}", DCB_CLOSE)
            output_configs = list(yaml.safe_load_all(plain_file)) or [{}]

    # Else just start from an empty dict
    else:
        output_configs = [{}]

    # Check that the document exists in the output file
    if output_doc_index > len(output_configs):
        raise RuntimeError(f"Document index #{output_doc_index} not found in: {output_path!r}")

    # Call the sub-function on a single doc
    copy_to_helm_infra_single_doc(input_config, input_roots, output_configs[output_doc_index], output_roots)

    # Some k8s files have yaml dicts encoded as strings. We want to dump them using literal blocks.
    for output_config in output_configs:
        data = output_config.get("data", {})
        for key, value in data.items():
            if isinstance(value, str):
                data[key] = literal_str(value)

    # Write the modified output file. Restore the double curly braces.
    # Use width=... so we don't split long lines.
    with open(output_path, "w") as opened:
        logger.info(f"Update: '{output_path!s}'")
        opened.write(FILE_HEADERS[input_path].helm_infra)
        yaml_contents = yaml.dump_all(output_configs, default_flow_style=False, sort_keys=False, width=1000)
        yaml_contents = yaml_contents.replace(DCB_OPEN, "{{")
        yaml_contents = yaml_contents.replace(DCB_CLOSE, "}}")
        opened.write(yaml_contents)

    # Remove the quotes we added above around k8s values like {{ some.thing }}
    subprocess.run(["sed", "-i", r"s|'\({{.*}}\)'|\1|g", output_path])


def copy_to_helm_infra_single_doc(
    input_config: dict,
    input_roots: list[str],
    output_config: Path,
    output_roots: list[str],
):
    """
    Copy and update a single yaml document from rs-server to rs-helm or rs-infrastructure.
    """

    # Start from the input and output root tag(s)
    for tag in input_roots:
        input_config = input_config[tag]  # input tags must exist
    last_output_parent = None
    for tag in output_roots:
        if tag not in output_config:  # output tags are optional
            output_config[tag] = {}
            logger.warning(f"Tag does not exist in output file: {tag!r}")
        last_output_parent = output_config
        output_config = output_config[tag]

    # If the output config is a string from a k8s file, load it as a yaml
    as_string = False
    if isinstance(output_config, str):
        output_config = yaml.safe_load(output_config)
        as_string = True

    def update_all_values(parent_key: str, input_config: dict, output_config: dict, stations: Stations = Stations()):
        """
        Recursive function to copy and adapt values from input into output config.
        """
        assert isinstance(input_config, dict)
        assert isinstance(output_config, dict)

        # Check station name from parent key
        stations = copy.deepcopy(stations)  # save the instance so the previous recursive calls are not impacted
        stations.update(parent_key)

        def update_single_value(input_value: Any, output_value: str) -> str:
            """Return a single updated value."""
            assert isinstance(output_value, str)

            # If the output value is like {{ some.thing }}, it's a k8s value, we don't change it.
            if (DCB_OPEN in output_value) and (DCB_CLOSE in output_value):
                return output_value

            # Else try to update url in the input value
            if stations.adgs:
                return re.sub(
                    REGEX_URL,
                    rf"\g<1>mockup-station-{stations.value}-svc.processing.svc.cluster.local:8080",
                    input_value,
                )
            elif stations.cadip:
                return re.sub(
                    REGEX_URL,
                    rf"\g<1>mockup-station-cadip-{stations.value}-svc.processing.svc.cluster.local:8080",
                    input_value,
                )
            elif stations.lta:
                return re.sub(
                    REGEX_URL,
                    rf"\g<1>mockup-lta-{stations.value}-svc.processing.svc.cluster.local:8080",
                    input_value,
                )
            elif stations.prip:
                return re.sub(
                    REGEX_URL,
                    rf"\g<1>mockup-prip-{stations.value}-svc.processing.svc.cluster.local:8080",
                    input_value,
                )
            else:
                return input_value

        # Copy values recursively from input to output
        for key, input_value in input_config.items():

            if key not in output_config:
                output_config[key] = input_value

            # Recursive calls on dicts
            output_value = output_config[key]
            if isinstance(output_value, collections.abc.Mapping):
                update_all_values(key, input_value, output_value, stations)

            # Update string value
            elif isinstance(output_value, str):
                assert isinstance(input_value, str)
                output_config[key] = update_single_value(input_value, output_value)

            # Recursive calls on lists...
            elif isinstance(output_value, collections.abc.Iterable):
                assert isinstance(input_value, collections.abc.Iterable)
                assert len(input_value) == len(output_value)
                for i, output_subvalue in enumerate(output_value):
                    input_subvalue = input_value[i]

                    # ... on list dicts
                    if isinstance(output_subvalue, collections.abc.Mapping):
                        update_all_values(key, input_subvalue, output_subvalue, stations)

                    # ... or on list string values
                    elif isinstance(output_subvalue, str):
                        output_value[i] = update_single_value(input_subvalue, output_subvalue)

    update_all_values("", input_config, output_config)

    # Convert back the yaml dict into a string and update the last parent dict.
    # We don't handle the case of a string at the root of the document
    if as_string:
        assert last_output_parent
        last_output_parent[output_roots[-1]] = yaml.dump(
            output_config,
            default_flow_style=False,
            sort_keys=False,
            width=1000,
        )


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
):
    create_from_template(templates)


# # Copy resulting files to rs-demo
# for config_path in (
#     "services/common/config/rs-server.yaml",
#     "services/adgs/config/adgs_ws_config_token_module.yaml",
#     "services/cadip/config/cadip_ws_config_token_module.yaml",
# ):
#     copy_to_demo(config_path)

# #
# # Copy resulting files to rs-helm and rs-infrastructure

# input = ["services/common/config/rs-server.yaml", ["external_data_sources"]]
# copy_to_helm_infra(*input, rs_helm_dir / "charts/rs-server-station-secrets/values.yaml", ["app", "stations"])
# copy_to_helm_infra(*input, rs_infra_dir / "rs-server/rs-server-station-secrets/values.yaml", ["app", "stations"])

# Use the first station values for all other stations
copy_to_helm_infra(
    "services/adgs/config/adgs_ws_config.yaml",
    ["adgs"],
    rs_helm_dir / "charts/rs-server-adgs/templates/configmap.yaml",
    [
        "data",
        f"{DCB_OPEN} .Values.app.eodagConfigFile {DCB_CLOSE}",
        f"{DCB_OPEN}- range $k, $v := .Values.app.station {DCB_CLOSE}",
        f"{DCB_OPEN} $k {DCB_CLOSE}",
    ],
    0,
)

copy_to_helm_infra(
    "services/adgs/config/adgs_search_config.yaml",
    [],
    rs_helm_dir / "charts/rs-server-adgs/templates/configmap.yaml",
    ["data", f"{DCB_OPEN} .Values.app.adgsSearchConfigFile {DCB_CLOSE}"],
    2,
)
# copy_to_helm_infra(*input, rs_infra_dir / "rs-server/rs-server-station-secrets/values.yaml", ["app", "stations"])
