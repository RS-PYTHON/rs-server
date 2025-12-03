#!/usr/bin/env bash
# Copyright 2025 CS Group
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

# LOCATIONS OF IMPORTANT FOLDERS
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
PROJECT_ROOT_DIR="$(realpath $SCRIPT_DIR/..)"
PYDOC_DIR="${PROJECT_ROOT_DIR}/docs/doc/pydoc"
MODULES_DIR="${PROJECT_ROOT_DIR}/services"
MKDOCS_FILE="${SCRIPT_DIR}/mkdocs.txt"
BASE_FOR_MKDOCS_LOCATIONS="rs-server/docs/doc/pydoc/"

# LIST OF MODULES IN THE PROJECT
# To add or remove one, make sure the lists are on the same order with the same number of elements
declare -a MODULE_LOCATIONS=("${MODULES_DIR}/adgs" "${MODULES_DIR}/cadip" "${MODULES_DIR}/catalog" "${MODULES_DIR}/common" "${MODULES_DIR}/edrs" "${MODULES_DIR}/frontend" "${MODULES_DIR}/prip" "${MODULES_DIR}/staging")
declare -a MODULE_NAMES=("rs_server_adgs" "rs_server_cadip" "rs_server_catalog" "rs_server_common" "rs_server_edrs" "rs_server_frontend" "rs_server_prip" "rs_server_staging")


create_md_file() {
    # Creates a md file in the mkdocs format for the given py file
    #
    # USAGE:
    # create_md_file PYTHON_FILE MODULE_NAME
    #
    # EXAMPLE:
    # create_md_file api/cadip_search.py rs_server_cadip

    # Retrieve input data: location of the python file (ex: subfolder/file.py), name of the python base module, and levels
    python_file=$1
    base_module=$2

    # === BUILD VARIABLES ===
    # Name of the md file: same as the source py file but with .md extension
    md_file=${base_module}"/"${python_file::-2}"md"
    # Name of the module: same as the name of the python file, but without the .py extension and replacing "/" to "." (to turn subfolders into submodules)
    pymodule=$(tr '/' '.' <<< "${base_module}.${python_file::-3}")
    # Subfolders to create: md file without the file name
    subfolder=${md_file%/*}
    # Location of the index file relative to the md file: replace the subfolder names with ".."
    index_location=$(printf '%s' "$python_file" | awk -F'/' '{for(i=1;i<NF;i++) printf "../"; print "index.md"}')

    # === CREATE AND POPULATE A MD FILE ===
    # Create subfolders and md file
    mkdir -p "$subfolder"
    touch $md_file
    # Fill the md file content
    echo "# "${md_file} > $md_file
    echo -e "\n[ << Back to index]("${index_location}")" >> $md_file
    echo -e "\n::: "${pymodule} >> $md_file
    echo -e "\n<!--- File generated automatically, do not modify it. -->" >> $md_file

    # Return name of the created md file
    echo "${python_file::-2}md"
}


create_documentation_for_module() {
    # Creates a comlete documentation folder for the given python module.
    # The documentation created follows mkdocs format and has the same structure as the given module.
    # Don't forget the / at the end of the module_location.
    #
    # USAGE:
    # create_documentation_for_module MODULE_NAME MODULE_LOCATION
    #
    # EXAMPLE:
    # create_documentation_for_module "rs_server_cadip" "/home/ecombelles/workspace/rs-server/services/cadip/rs_server_cadip/"

    module_name=$1
    module_location=$2

    # === BUILD VARIABLES ===
    # Files list: a complete list of everything inside the module's folder from where we keep only the .py files that are not init
    files_list=$(find $module_location -type f | grep ".*.\.py$" | grep -v "__init__")
    # Put the files in an array
    readarray -t files_list <<< "$files_list"

    # === CREATE AND POPULATE INDEX FILE ===
    index_file=$module_name/index.md
    mkdir -p "$module_name"
    touch $index_file
    echo "# Python documentation for $module_name" > $index_file
    echo -e "\n## List of modules\n" >> $index_file

    # === CREATE A MD FILE FOR EACH PY FILE ===
    for file in "${files_list[@]}"; do
        # Remove everything before the module location in the file name we are handling
        python_file=${file#${module_location}}

        # Create md file
        created_file=$(create_md_file $python_file $module_name)

        # Add info for created md file in the index
        echo "Created documentation file $created_file from file $python_file."
        echo "- ["${python_file}"]("${created_file}")" >> $index_file
    done

    echo -e "\n<!--- File generated automatically, do not modify it. -->" >> $index_file
}


create_documentation_for_rs_server() {
    # Main function to generate the documentation of rs_server with all the specified modules
    #
    # USAGE:
    # create_documentation_for_rs_server

    # Move to pydoc dir and remove all existing content
    mkdir -p "$PYDOC_DIR"
    cd $PYDOC_DIR
    rm -rf *

    # For each module: call create_documentation_for_module
    for i in "${!MODULE_NAMES[@]}"; do
        module_name=${MODULE_NAMES[i]}
        module_location=${MODULE_LOCATIONS[i]}

        create_documentation_for_module $module_name $module_location/$module_name/

        echo "✓ Documentation for module $module_name located at $module_location/$module_name/ succesfully built."
    done
}


mkdocs_for_folder() {
    # Generates recursively the mkdocs table of contents of one folder in the "pydoc" folder, with correct indentation
    #
    # USAGE:
    # mkdocs_for_folder FOLDER_NAME FOLDER_LEVEL PREVIOUS_FOLDER
    # (where FOLDER_LEVEL is the the level of the given folder relatively to the first folder given)
    #
    # EXAMPLE
    # mkdocs_for_folder rs_server_adgs/api/ 1 rs_server_adgs/

    folder_name=$1
    folder_level=$2
    previous_folders=$3

    # Compute indentation: 4 spaces as a base, then add two spaces for each folder level
    mkdocs_indent="    "
    for i in $(seq 1 $folder_level); do
        mkdocs_indent="${mkdocs_indent}  "
    done
    # Create line for folder name
    mkdocs="${mkdocs_indent}- ${folder_name::-1}:\n"

    cd $folder_name

    # For each file in the folder: add it as a line with a reference to the md file location
    files_list=$(ls -p | grep -v /)
    readarray -t files_list <<< "$files_list"
    for file in "${files_list[@]}"; do
        mkdocs="${mkdocs}${mkdocs_indent}  - ${file::-3}: ${BASE_FOR_MKDOCS_LOCATIONS}${previous_folders}${folder_name}${file}\n"
    done

    # For each folder in the folder: repeat the process to create a correct folders tree
    folders=$(ls -p | grep / )
    if [[ "$folders" ]]; then
        readarray -t folders_list <<< "$folders"
        for folder in "${folders_list[@]}"; do
            new_level=$((folder_level + 1))
            new_mkdocs=$(mkdocs_for_folder $folder $new_level "${previous_folders}${folder_name}")
            mkdocs="${mkdocs}${new_mkdocs}"
        done
    fi

    cd ..
    echo "${mkdocs}"
}


build_mkdocs_file() {
    # Generates complete mkdocs file, for everything in the module names list
    #
    # USAGE:
    # build_mkdocs_file
    rm $MKDOCS_FILE
    cd $PYDOC_DIR
    for module in "${MODULE_NAMES[@]}"; do
        module_mkdocs=$(mkdocs_for_folder "${module}/" 0 "")
        echo -e "${module_mkdocs}" >> $MKDOCS_FILE
    done

    echo "✓ Generated mkdocs table of contents at ${MKDOCS_FILE}."
}


create_documentation_for_rs_server
build_mkdocs_file
