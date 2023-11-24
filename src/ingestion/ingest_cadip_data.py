"""FIXME add a module description here."""

import json
import os

import dask
import requests
from prefect import flow, get_run_logger, task
from prefect_dask import DaskTaskRunner
from requests.exceptions import ConnectionError

dask.config.set({"distributed.worker.memory.terminate": False})

UNAUTHORIZED = 401


@task(name="Querry CADIP Files endpoint", task_run_name="querryFiles")
def querry_files(execution_unit):
    """Docstring to be added."""
    logger = get_run_logger()
    logger.info("Starting to querry files")
    endpoint = "Files"
    endpoint_args = f"$filter={execution_unit.ProductFilter} {execution_unit.ProductFilterValue}"
    end_route = f"{execution_unit.webserver}/{endpoint}?{endpoint_args}"
    logger.info(f"endpoint called {end_route}")
    data = execution_unit.session.get(end_route)  # , auth=(executionUnit.user, executionUnit.password))
    logger.info(f"webserver response {data.content}")
    execution_unit.filesQuerry = data.content
    logger.info("Finished files querry")
    return execution_unit


@task(name="Querry CADIP Sessions endpoint", task_run_name="querrySessions")
def querry_sessions(execution_unit):
    """Docstring to be added."""
    logger = get_run_logger()
    logger.info("Starting to querry sesions")
    endpoint = "Sessions"
    endpoint_args = f"$filter={execution_unit.SessionFilter} {execution_unit.SessionFilterValue}"
    end_route = f"{execution_unit.webserver}/{endpoint}?{endpoint_args}"
    data = execution_unit.session.get(end_route)
    logger.info(f"endpoint called {end_route}")
    logger.info(f"webserver response {data.content}")
    execution_unit.sessionQuerry = data.content
    logger.info("Finished session querry")
    return execution_unit


@task(name="Init CADIP data ingestion parameters")
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


@task(name="Download file from CADIP s3")  # , on_completion=[querryQualityInfo(executionUnit, response)])
def download_file(execution_unit, response=None):
    """Docstring to be added."""
    file_id = json.loads(response if response else execution_unit.filesQuerry)["Id"]
    file_name = json.loads(response if response else execution_unit.filesQuerry)["Name"]
    endpoint = f"Files({file_id})/$S3OS"
    end_route = f"{execution_unit.webserver}/{endpoint}"
    # data = requests.get(endRoute) #, auth=(executionUnit.user, executionUnit.password))
    filename = f"{execution_unit.OutputPath}/{file_name}"
    os.makedirs(execution_unit.OutputPath, exist_ok=True)
    with execution_unit.session.get(end_route, stream=True) as req:
        req.raise_for_status()
        with open(filename, "wb") as outfile:
            for chunk in req.iter_content(chunk_size=8192):
                outfile.write(chunk)
    execution_unit.succesfullDownload = True
    return execution_unit


@task(name="Download file from CADIP")  # , on_completion=[querryQualityInfo(executionUnit, response)])
def download_file_http(execution_unit, response=None):
    """Docstring to be added."""
    file_id = json.loads(response if response else execution_unit.filesQuerry)["Id"]
    file_name = json.loads(response if response else execution_unit.filesQuerry)["Name"]
    endpoint = f"Files({file_id})/$value"
    end_route = f"{execution_unit.webserver}/{endpoint}"
    # data = requests.get(endRoute) #, auth=(executionUnit.user, executionUnit.password))
    filename = f"{execution_unit.OutputPath}/{file_name}"
    os.makedirs(execution_unit.OutputPath, exist_ok=True)
    with execution_unit.session.get(end_route, stream=True) as req:
        req.raise_for_status()
        with open(filename, "wb") as outfile:
            for chunk in req.iter_content(chunk_size=8192):
                outfile.write(chunk)
    execution_unit.succesfullDownload = True
    return execution_unit


@task(name="Check CADIP quality info of download")
def querry_quality_info(execution_unit, response=None):
    """Docstring to be added."""
    logger = get_run_logger()
    logger.info("Starting to check quality info")
    session_id = json.loads(response)["Id"] if response else execution_unit.filesQuerry["Id"]
    end_point = f"Sessions({session_id})?expand=qualityInfo"
    end_route = f"{execution_unit.webserver}/{end_point}"
    data = execution_unit.session.get(end_route)
    logger.info(f"endpoint called {end_route}")
    logger.info(f"webserver response {json.loads(data.content)}")
    execution_unit.qualityResponse = json.loads(data.content)
    return execution_unit.qualityResponse["ErrorTFs"] == 0


@task(name="Check CADIP given credentials")
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


@task(name="Check CADIP webserver connection")
def check_connection(execution_unit) -> bool:
    """Docstring to be added."""
    try:
        requests.get(execution_unit.webserver)
    except ConnectionError:
        return False
    return True


def dummy_task(**kwargs):
    """Docstring to be added."""
    print("Dummy")


@flow(task_runner=DaskTaskRunner(), on_completion=[dummy_task])  # type: ignore
def execute_cadip_ingestion(ingestion_file, **kwargs):  # noqa: N802
    """Docstring to be added."""
    # Recover flow parameters from json file, and create dynamic object
    execution_unit = init_ingestion(ingestion_file, target="CADIP")
    # Check webserver
    if not check_connection(execution_unit):
        raise ValueError("Incorrect webserver address")
    # Verify credentials
    if not login(execution_unit):
        raise ValueError("Incorrect credentials")
    # Querry active sessions by filtering sattelite type to S1A
    execution_unit = querry_sessions(execution_unit, wait_for=init_ingestion)  # type: ignore
    # Send execution object and parameters to quarry files from cadip server
    execution_unit = querry_files(execution_unit, wait_for=querry_sessions)  # type: ignore
    process_status = True
    # iterate available files, download and check quality info
    if "responses" in json.loads(execution_unit.filesQuerry):
        for response in json.loads(execution_unit.filesQuerry)["responses"]:
            download_file_http.submit(execution_unit, response)
            #process_status = querry_quality_info.submit(execution_unit, response) or process_status
    else:
        download_file_http(execution_unit)
        #process_status = querry_quality_info(execution_unit) or process_status
    return process_status


if __name__ == "__main__":
    # realUsageTest()
    # sys.argv tbu
    execute_cadip_ingestion("src/ingestion/ingestionParameters.json")
    # pass
