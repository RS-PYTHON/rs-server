"""File docstring to be added."""  # noqa: N999
import json
import os
import shutil

import pytest

import src.ingestion.ingest_cadip_data as ingestion_flow


# TC-001: Create a Prefect workflow that calls this task with publication date filters. Check that the task returns the
# expected result
@pytest.mark.unit
@pytest.mark.parametrize(
    "ingestion_file",
    [
        ("tests/data/correct_ingestionParameters.json")
    ]
)
def test_flow(ingestion_file):
    """Docstring to be added."""
    ingestion = json.loads(open(ingestion_file).read())
    if not os.path.exists(ingestion['OutputPath']):
        os.mkdir(ingestion['OutputPath'])
    initial_files = os.listdir(ingestion['OutputPath'])
    # check that flow didn't failed.
    assert ingestion_flow.execute(ingestion_file)
    current_files = os.listdir(ingestion['OutputPath'])
    shutil.rmtree(ingestion['OutputPath'])
    # Check that some files were downloaded.
    assert current_files != initial_files

#TC-002: Create a Prefect workflow that calls this task with invalid service root URI. Check that the error is displayed
#  in Prefect UI but that credentials are not logged.
@pytest.mark.unit
@pytest.mark.parametrize(
    "ingestion_file",
    [
        ("tests/data/incorrect_ingestionParameters.json")
    ]
)
def test_incorrect_credentials(ingestion_file):
    """Docstring to be added."""
    assert not ingestion_flow.execute(ingestion_file)

#TC-003: Create a Prefect workflow that calls this task with invalid credentials. Check that the error is displayed in 
# Prefect UI but that credentials are not logged.
@pytest.mark.unit
@pytest.mark.parametrize(
    "ingestion_file",
    [
        ("tests/data/incorrectWS_ingestionParameters.json")
    ]
)
def test_incorrect_webserver(ingestion_file):
    """Docstring to be added."""
    assert not ingestion_flow.execute(ingestion_file)