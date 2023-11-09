import json

import requests  # type: ignore
from prefect import flow, task, get_run_logger
from prefect_dask import DaskTaskRunner
import dask

dask.config.set({"distributed.worker.memory.terminate": False})


@task(name="Querry Files endpoint", task_run_name="querryFiles")
def querry_Files(executionUnit):
    logger = get_run_logger()
    logger.info("Starting to querry files")
    endpoint = "Files"
    endpointArgs = f"$filter={executionUnit.ProductFilter} {executionUnit.ProductFilterValue}"
    endRoute = f"{executionUnit.webserver}/{endpoint}?{endpointArgs}"
    logger.info(f"endpoint called {endRoute}")
    data = requests.get(endRoute)  # , auth=(executionUnit.user, executionUnit.password))
    logger.info(f"webserver response {json.loads(data.content)}")
    executionUnit.filesQuerry = json.loads(data.content)
    logger.info("Finished files querry")
    return executionUnit


@task(name="Querry Sessions endpoint", task_run_name="querrySessions")
def querry_Sessions(executionUnit):
    logger = get_run_logger()
    logger.info("Starting to querry sesions")
    endpoint = "Sessions"
    endpointArgs = f"$filter={executionUnit.SessionFilter} {executionUnit.SessionFilterValue}"
    endRoute = f"{executionUnit.webserver}/{endpoint}?{endpointArgs}"
    data = requests.get(endRoute)
    logger.info(f"endpoint called {endRoute}")
    logger.info(f"webserver response {json.loads(data.content)}")
    executionUnit.sessionQuerry = json.loads(data.content)
    logger.info("Finished session querry")
    return executionUnit


@task(name="Init data ingestion parameters")
def initIngestion(fileLocation):
    logger = get_run_logger()
    logger.info("Starting to ingest flow arguments")
    with open(fileLocation, "r") as file:
        # SimpleNamespace or metaclass? hmm
        # from types import SimpleNamespace
        # return json.loads(file.read(), object_hook=lambda d: SimpleNamespace(**d))
        data = json.loads(file.read())
        return type("RSUnit", (object,), data)


@task(name="Download file from CADIP")  # , on_completion=[querryQualityInfo(executionUnit, response)])
def downloadFile(executionUnit, response=None):
    fileId = json.loads(response if response else executionUnit.filesQuerry)["Id"]
    fileName = json.loads(response if response else executionUnit.filesQuerry)["Name"]
    endpoint = f"Files({fileId})/$value"
    endRoute = f"{executionUnit.webserver}/{endpoint}"
    # data = requests.get(endRoute) #, auth=(executionUnit.user, executionUnit.password))
    filename = f"{executionUnit.OutputPath}/{fileName}"
    with requests.get(endRoute, stream=True) as req:
        req.raise_for_status()
        import random
        import time
        time.sleep(random.randint(5, 10))
        with open(filename, "wb") as outfile:
            for chunk in req.iter_content(chunk_size=8192):
                outfile.write(chunk)
    executionUnit.succesfullDownload = True
    return executionUnit


@task(name="Check quality info of download")
def querryQualityInfo(executionUnit, response=None):
    logger = get_run_logger()
    logger.info("Starting to check quality info")
    sessionId = json.loads(response)["Id"] if response else executionUnit.filesQuerry["Id"]
    endPoint = f"Sessions({sessionId})?expand=qualityInfo"
    endRoute = f"{executionUnit.webserver}/{endPoint}"
    data = requests.get(endRoute)
    logger.info(f"endpoint called {endRoute}")
    logger.info(f"webserver response {json.loads(data.content)}")
    executionUnit.qualityResponse = json.loads(data.content)
    return executionUnit.qualityResponse["ErrorTFs"] == 0


def dummy_task(**kwargs):
    print("Dummy")


@flow(task_runner=DaskTaskRunner(), on_completion=[dummy_task])
def test_CADIP(ingestionFile):
    # Recover flow parameters from json file, and create dynamic object
    executionUnit = initIngestion(ingestionFile)
    # Querry active sessions by filtering sattelite type to S1A
    executionUnit = querry_Sessions(executionUnit, wait_for=initIngestion)  # tbd
    # Send execution object and parameters to quarry files from cadip server
    executionUnit = querry_Files(executionUnit, wait_for=querry_Sessions)
    process_status = True
    # iterate available files, download and check quality info
    if "responses" in executionUnit.filesQuerry:
        for response in executionUnit.filesQuerry["responses"]:
            downloadFile.submit(executionUnit, response)
            process_status = querryQualityInfo.submit(executionUnit, response) or process_status
    else:
        downloadFile(executionUnit)
        process_status = querryQualityInfo(executionUnit) or process_status
    return process_status


if __name__ == "__main__":
    # realUsageTest()
    test_CADIP("ingestionParameters.json")
