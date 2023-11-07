import json

import requests  # type: ignore
from prefect import flow, task
from prefect_dask import DaskTaskRunner


@task(name="Querry Files endpoint", task_run_name="querryFiles")
def querry_Files(executionUnit):
    endpoint = "Files"
    endpointArgs = f"$filter={executionUnit.ProductFilter} {executionUnit.ProductFilterValue}"
    endRoute = f"{executionUnit.webserver}/{endpoint}?{endpointArgs}"
    data = requests.get(endRoute)  # , auth=(executionUnit.user, executionUnit.password))
    executionUnit.filesQuerry = json.loads(data.content)
    return executionUnit


@task(name="Querry Sessions endpoint", task_run_name="querrySessions")
def querry_Sessions(executionUnit):
    # SessionsRoute = "Sessions"
    pass


@task(name="Init data ingestion parameters")
def initIngestion(fileLocation):
    with open(fileLocation, "r") as file:
        # SimpleNamespace or metaclass? hmm
        # from types import SimpleNamespace
        # return json.loads(file.read(), object_hook=lambda d: SimpleNamespace(**d))
        data = json.loads(file.read())
        return type("RSUnit", (object,), data)


@task(name="Download file from CADIP")
def downloadFile(executionUnit, response=None):
    if response:
        fileId = json.loads(response)["Id"]
    else:
        fileId = json.loads(executionUnit.filesQuerry)["Id"]
    endpoint = f"Files({fileId})/$value"
    endRoute = f"{executionUnit.webserver}/{endpoint}"
    # data = requests.get(endRoute) #, auth=(executionUnit.user, executionUnit.password))
    # TBD since you request download only by fileID, how to get filename? update mockup to send fileinfo response
    filename = f"{executionUnit.OutputPath}/{fileId}.raw"
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
    if response:
        sessionId = json.loads(response)["Id"]
    else:
        sessionId = executionUnit.filesQuerry["Id"]
    endPoint = f"Sessions({sessionId})?expand=qualityInfo"
    endRoute = f"{executionUnit.webserver}/{endPoint}"
    print(sessionId)
    print(endRoute)
    data = requests.get(endRoute)
    executionUnit.qualityResponse = json.loads(data.content)
    return executionUnit.qualityResponse["ErrorTFs"] == 0


@flow(task_runner=DaskTaskRunner())
def test_CADIP(ingestionFile):
    executionUnit = initIngestion(ingestionFile)
    querry_Sessions(executionUnit)  # tbd
    executionUnit = querry_Files(executionUnit)
    process_status = True
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
