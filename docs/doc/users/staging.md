# Staging

The **staging** copies products from the [external data sources](external-data-sources.md) into RS-Python: it is
not a download to your computer. The system keeps its own copy of the data, for performance purposes and to manage
the access rights:

1. the assets (files) of the products are copied from the stations into the RS-Python object storage, in the bucket
   given by the [bucket configuration](https://github.com/RS-PYTHON/rs-documentation/blob/develop/docs/administration/update-rs-server.md#object-storage-buckets-and-data-lifecycle),
2. the STAC items are published in a collection of the [catalog](catalog.md), with their assets referencing the
   object storage.

The users are then granted direct access to the buckets by [OSAM](osam.md), according to their rights on the
catalog collections.

The **rs-server-staging** service follows the [OGC API - Processes](https://ogcapi.ogc.org/processes/) standard,
with a single process named `staging`, implemented with [pygeoapi](https://pygeoapi.io/). The copies are run in
parallel on a [Dask](https://www.dask.org/) cluster. Its implementation is described in
[Staging internals](../dev/staging-internals.md).

In practice, the staging is usually run by the [staging flows](https://github.com/RS-PYTHON/rs-client-libraries/blob/develop/docs/doc/flows/common-flows.md#staging-flows)
or by the processing flows, that search the products then call this service with the
[rs-client-libraries](https://github.com/RS-PYTHON/rs-client-libraries/blob/develop/docs/doc/index.md).

## Endpoints

| Method | Endpoint | Description | Role |
|---|---|---|---|
| `GET` | `/processes` | List the processes. | `rs_processes_staging_read` |
| `GET` | `/processes/staging` | Describe the staging process. | `rs_processes_staging_read` |
| `POST` | `/processes/staging/execution` | Start a staging job. Returns the job identifier. | `rs_processes_staging_execute`, and `rs_processes_staging_download_<station>` for each station |
| `GET` | `/jobs` | List the jobs. | `rs_processes_staging_read` |
| `GET` | `/jobs/{job_id}` | Get the status and progress of a job. | `rs_processes_staging_read` |
| `GET` | `/jobs/{job_id}/results` | Get the results of a job. | `rs_processes_staging_read` |
| `DELETE` | `/jobs/{job_id}` | Dismiss a job. | `rs_processes_staging_dismiss` |

## Start a staging job

The body of the `POST /processes/staging/execution` request contains:

- `collection`: the catalog collection where the items are published. It is created if it doesn't exist.
- `items`: the items to stage, either:
    - `{"value": <STAC Feature or FeatureCollection>}`, e.g. the result of a search on the external data sources,
    - or `{"href": "<URL>"}`, a URL that returns a STAC FeatureCollection, e.g. a search URL of the CADIP service.
- `asset_names` (optional): stage only these assets of the items.

```json
{
  "inputs": {
    "collection": "s3-cadip-session",
    "items": {
      "href": "https://rspy.ops.rs-python.eu/cadip/search?ids=S3A_20260807020505053186&collections=sgs"
    }
  }
}
```

The response contains the job identifier. Follow the job with `GET /jobs/{job_id}`:

```json
{
  "jobID": "556363bf-c74d-41cf-931d-1972fe8a7b87",
  "processID": "staging",
  "type": "process",
  "status": "running",
  "message": "Sending tasks to the dask cluster",
  "progress": 25,
  "created": "2026-02-17T09:02:06Z",
  "started": "2026-02-17T09:02:06Z",
  "updated": "2026-02-17T09:02:16Z"
}
```

The status goes from `accepted` to `running`, then `successful` or `failed`.

With Python:

```python
staging_client = rs_client.get_staging_client()
jobs = staging_client.run_staging(item_collection, "s3-cadip-session")  # one job per station
staging_client.wait_for_jobs(jobs)
```

## Behaviour

- The items that are already in the target collection, with all their assets, are not staged again. The items that
  have expired (see [Data lifecycle](data-model.md#data-lifecycle)) are staged again and published again.
- The assets are streamed directly from the stations to the object storage, without local copy. The stations are
  accessed with the credentials configured by the administrators, with an OAuth2 token refreshed automatically.
- The progress of the job is updated after each copied asset.
- If a copy fails, the job fails, and the assets already copied by this job are deleted.
- The items are published in the catalog only when all their assets have been copied.
