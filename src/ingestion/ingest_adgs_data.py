"""Docstring to be added."""
import json
import os

import requests
from prefect import flow, get_run_logger, task
from prefect_dask import DaskTaskRunner

UNAUTHORIZED = 401


@task(name="Init data ingestion parameters")
def init_ingestion(file_location, **kwargs):
    """Docstring to be added."""
    if "logger" not in kwargs.keys():
        logger = get_run_logger()
    logger.info("Starting to ingest flow arguments")
    with open(file_location, "r") as file:
        # SimpleNamespace or metaclass? hmm
        # from types import SimpleNamespace
        # return json.loads(file.read(), object_hook=lambda d: SimpleNamespace(**d))
        if "target" in kwargs:
            data = json.loads(file.read())[kwargs["target"]]
        else:
            data = json.loads(file.read())
    object_exec = type("RSUnit", (object,), data)
    setattr(object_exec, "created", True)
    logger.info("Succesfuly created an execution unit!")
    return object_exec


@task(name="Check webserver connection")
def check_connection(execution_unit) -> bool:
    """Docstring to be added."""
    try:
        requests.get(execution_unit.webserver)
    except ConnectionError:
        return False
    return True


@task(name="Check given credentials")
def login(execution_unit, logger=None) -> bool:
    """Docstring to be added."""
    if not logger:
        logger = get_run_logger()
    logger.info("Starting to login to CADIP webserver")
    username = execution_unit.user
    password = execution_unit.password
    end_point = "/"
    end_route = f"{execution_unit.webserver}/{end_point}"
    session = requests.Session()
    data = session.get(end_route, auth=(username, password))
    if data.status_code == UNAUTHORIZED:
        logger.info("Wrong credentials!")
        setattr(execution_unit, "logged_in", False)
        return False
    logger.info("Succesfully authentificated!")
    # persist auth parameters to request session
    session.auth = (execution_unit.user, execution_unit.password)
    setattr(execution_unit, "session", session)
    return True


@task(name="Querry Files catalog", task_run_name="querryFiles")
def querry_files(execution_unit):
    """Docstring to be added."""
    logger = get_run_logger()
    logger.info("Starting to querry files")
    endpoint = "Products"
    endpoint_args = f"$filter={execution_unit.ProductFilter}{execution_unit.ProductFilterValue}"
    end_route = f"{execution_unit.webserver}/{endpoint}?{endpoint_args}"
    logger.info(f"endpoint called {end_route}")
    data = execution_unit.session.get(end_route)  # , auth=(executionUnit.user, executionUnit.password))
    logger.info(f"webserver response {data.content}")
    execution_unit.filesQuerry = json.loads(data.content)
    logger.info("Finished files querry")
    return execution_unit


@task(name="Download file from ADGS")  # , on_completion=[querryQualityInfo(executionUnit, response)])
def download_file(execution_unit, response=None):
    """Docstring to be added."""
    file_id = json.loads(response if response else execution_unit.filesQuerry)["Id"]
    file_name = json.loads(response if response else execution_unit.filesQuerry)["Name"]
    endpoint = f"Products({file_id})/$value"
    end_route = f"{execution_unit.webserver}/{endpoint}"
    # data = requests.get(endRoute) #, auth=(executionUnit.user, executionUnit.password))
    filename = f"{execution_unit.OutputPath}/{file_name}"
    os.makedirs(execution_unit.OutputPath, exist_ok=True)
    with execution_unit.session.get(end_route, stream=True) as req:
        # Can be removed if replaced with real download data.
        import random
        import time

        time.sleep(random.randint(5, 10))

        with open(filename, "wb") as outfile:
            outfile.write(req.raw.read())
    execution_unit.succesfullDownload = True
    return execution_unit


@task(name="Download file from ADGS using s3 storage")  # , on_completion=[querryQualityInfo(executionUnit, response)])
def download_file_s3(execution_unit, response=None):
    """Docstring to be added."""
    file_id = json.loads(response if response else execution_unit.filesQuerry)["Id"]
    file_name = json.loads(response if response else execution_unit.filesQuerry)["Name"]
    endpoint = f"Products({file_id})/$S3OS"
    end_route = f"{execution_unit.webserver}/{endpoint}"
    # data = requests.get(endRoute) #, auth=(executionUnit.user, executionUnit.password))
    filename = f"{execution_unit.OutputPath}/{file_name}"
    os.makedirs(execution_unit.OutputPath, exist_ok=True)
    with execution_unit.session.get(end_route, stream=True) as req:
        with open(filename, "wb") as outfile:
            outfile.write(req.raw.read())
    execution_unit.succesfullDownload = True
    return execution_unit


@flow(task_runner=DaskTaskRunner())
def execute_adgs_ingestion(ingestion_file, **kwargs):  # noqa: N802
    """Docstring to be added."""
    execution_unit = init_ingestion(ingestion_file, target="ADGS")
    if not check_connection(execution_unit):
        raise ValueError("Incorrect webserver address")
    # Verify credentials
    if not login(execution_unit):
        raise ValueError("Incorrect credentials")
    # Querry files catalog
    execution_unit = querry_files(execution_unit, wait_for=init_ingestion)
    # download
    if "responses" in execution_unit.filesQuerry:
        for response in execution_unit.filesQuerry["responses"]:
            download_file_s3.fn(execution_unit, json.dumps(response))
    return True


if __name__ == "__main__":
    execute_adgs_ingestion("src/ingestion/ingestionParameters.json")
