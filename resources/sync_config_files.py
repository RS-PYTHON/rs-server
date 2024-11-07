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
from pathlib import Path

import yaml
from rs_server_common.utils.logging import Logging

logger = Logging.default(Path(__file__).name)

# Avoid yaml references, see: https://stackoverflow.com/a/30682604
yaml.Dumper.ignore_aliases = lambda *_: True

# The config files will be copied in rs-demo and rs-helm if these projects
# are checkout under the same directory than rs-server.
rs_server_dir = Path(__file__).parent.parent
rs_demo_dir = rs_server_dir.parent / "rs-demo"
rs_helm_dir = rs_server_dir.parent / "rs-helm"
if not rs_demo_dir.is_dir():
    logger.warning(f"No 'rs-demo' repository found under: '{rs_demo_dir!s}'")
if not rs_helm_dir.is_dir():
    logger.warning(f"No 'rs-helm' repository found under: '{rs_helm_dir!s}'")

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


def recursive_update(d, u):
    """Recursive dict update, taken from: https://stackoverflow.com/a/3233356"""
    for k, v in u.items():
        if isinstance(v, collections.abc.Mapping):
            d[k] = recursive_update(d.get(k) or {}, v)
        else:
            d[k] = v
    return d


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

    all_files = {}
    output_paths = set()
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
        with open(template_path, encoding="utf-8") as input_file:
            if is_json:
                file = json.loads(input_file.read())
            else:
                file = yaml.safe_load(input_file)

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
    output_path = output_paths.pop()
    with open(output_path, "w") as output_file:
        logger.info(f"Update: '{output_path!s}'")
        output_file.write(this_header)
        if is_json:
            json.dump(all_files, output_file, indent=2, sort_keys=False)
        else:
            yaml.dump(all_files, output_file, default_flow_style=False, sort_keys=False)


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
