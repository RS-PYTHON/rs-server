CADIP
=====

The CADU Interface delivery Point (CADIP) is a pick-up point for
Sentinel CADU data. The CADIP allows clients to straightforwardly
discover and retrieve available data files through a standard OData
RESTful API. The following endpoints have been implemented in RS-Server
to interact with CADIP RESTful API

Search Endpoint
---------------

This endpoint retrieves a list of products from the CADU system for a
specified station within a given time range and return a STAC compatible
FeatureCollection response.

### API Reference

`/cadip/{station}/cadu/search`

### Parameters

-   `station` (str): Identifier for the CADIP station (e.g., MTI, SGS,
    MPU, INU, etc).

-   `datetime` (str): Interval of date for time series filter joined by
    a slash (*/*). (format:
    "YYYY-MM-DDThh:mm:sssZ**/**YYYY-MM-DDThh:mm:sssZ").

-   `limit` (int, optional): Maximum number of products to return,
    default set to 1000.

-   `sortby` (str, optional): Sorting criteria. +/-fieldName indicates
    ascending/descending order and field name (e.g. sortby=+datetime)
    Default no sorting is applied.

### Request example

    GET /cadip/station123/cadu/search?datetime=2023-01-01T00:00:00Z/2023-01-02T23:59:59Z&limit=50&sortby=-datetime

### Return

    {
        "stac_version": "1.0.0",
        "stac_extensions": ["https://stac-extensions.github.io/file/v2.1.0/schema.json"],
        "type": "Feature",
        "id": "DCS_01_S1A_20170501121534062343_ch1_DSDB_00001.raw",
        "geometry": null,
        "properties": {
            "datetime": "2019-02-16T12:00:00.000Z",
            "eviction_datetime": "2019-12-16T12:00:00.000Z",
            "cadip:id": "2b17b57d-fff4-4645-b539-91f305c27c69",
            "cadip:retransfer": false,
            "cadip:final_block": true,
            "cadip:block_number": 1,
            "cadip:channel": 2,
            "cadip:session_id": "S1A_20170501121534062343",
        },
        "links": [],
        "assets": {
            "file": {
                "file:size": 32553
            }
        },
    }

Session search Endpoint
-----------------------

This endpoint retrieves a list of sessions from the CADU system for a
specified station within a given parameter and/or time range and return
a STAC compatible FeatureCollection response.

### API Reference

`/cadip/{station}/session`

### Parameters

-   `station` (str): Identifier for the CADIP station (e.g., MTI, SGS,
    MPU, INU, etc).

-   `id` (str, list\[str\], optional): DSIB SessionId value. Can be used
    with coma-separated values (e.g., S1A\_20170501121534062343).

-   `platform` (str, list\[str\], optional): Platform / Satellite
    identifier. Can be used with coma-separated values (e.g: platform =
    S1A or platform=S1A, S2B).

-   `start_date` (str, optional): Start time of session
    (PublicationTime). (format: YYYY-MM-DDThh:mm:sssZ).

-   `stop_date` (str, optional): Stop time of session (PublicationTime).
    (format: YYYY-MM-DDThh:mm:sssZ).

### Note

A valid session search request must contain at least a value for either
**id** or **platform** or time interval (**start\_date** and
**stop\_date** correctly defined).

### Request example

    GET /cadip/station123/session?id=S1A_20170501121534062343,S1A_20240328185208053186

    GET /cadip/station123/session?start_date=2020-02-16T12:00:00Z&stop_date=2023-02-16T12:00:00Z&platform=S1A

### Return

    {
        "type": "FeatureCollection",
        "numberMatched": 3,
        "numberReturned": 3,
        "features": [
            {
                "stac_version": "1.0.0",
                "stac_extensions": [
                    "https://stac-extensions.github.io/timestamps/v1.1.0/schema.json"
                ],
                "type": "Feature",
                "id": "S1A_20240328185208053186",
                "geometry": null,
                "properties": {
                    "start_datetime": "2024-03-28T18:52:08.000Z",
                    "datetime": "2024-03-28T18:52:08.000Z",
                    "end_datetime": "2024-03-28T19:00:52.000Z",
                    "published": "2024-03-28T18:52:26Z",
                    "platform": "S1A",
                    "cadip:id": "726f387b-ad2d-3538-8834-95e3cf8894c6",
                    "cadip:num_channels": 2,
                    "cadip:station_unit_id": "01",
                    "cadip:downlink_orbit": 53186,
                    "cadip:acquisition_id": 531861,
                    "cadip:antenna_id": "MSP21",
                    "cadip:front_end_id": "01",
                    "cadip:retransfer": false,
                    "cadip:antenna_status_ok": true,
                    "cadip:front_end_status_ok": true,
                    "cadip:planned_data_start": "2024-03-28T18:52:08.336Z",
                    "cadip:planned_data_stop": "2024-03-28T19:00:51.075Z",
                    "cadip:downlink_status_ok": true,
                    "cadip:delivery_push_ok": true
                },
                "links": [],
                "assets": {}
            },
            {
                "stac_version": "1.0.0",
                "stac_extensions": [
                    "https://stac-extensions.github.io/timestamps/v1.1.0/schema.json"
                ],
                "type": "Feature",
                "id": "S1A_20240328185208053186",
                "geometry": null,
                "properties": {
                    "start_datetime": "2024-03-28T18:52:08.000Z",
                    "datetime": "2024-03-28T18:52:08.000Z",
                    "end_datetime": "2024-03-28T19:00:52.000Z",
                    "published": "2024-03-28T18:52:26Z",
                    "platform": "S1A",
                    "cadip:id": "726f387b-ad2d-3538-8834-95e3cf8894c6",
                    "cadip:num_channels": 2,
                    "cadip:station_unit_id": "01",
                    "cadip:downlink_orbit": 53186,
                    "cadip:acquisition_id": 531861,
                    "cadip:antenna_id": "MSP21",
                    "cadip:front_end_id": "01",
                    "cadip:retransfer": false,
                    "cadip:antenna_status_ok": true,
                    "cadip:front_end_status_ok": true,
                    "cadip:planned_data_start": "2024-03-28T18:52:08.336Z",
                    "cadip:planned_data_stop": "2024-03-28T19:00:51.075Z",
                    "cadip:downlink_status_ok": true,
                    "cadip:delivery_push_ok": true
                },
                "links": [],
                "assets": {}
            },
            {
                "stac_version": "1.0.0",
                "stac_extensions": [
                    "https://stac-extensions.github.io/timestamps/v1.1.0/schema.json"
                ],
                "type": "Feature",
                "id": "S1A_20240329083700053194",
                "geometry": null,
                "properties": {
                    "start_datetime": "2024-03-28T18:52:08.000Z",
                    "datetime": "2024-03-28T18:52:08.000Z",
                    "end_datetime": "2024-03-28T19:00:52.000Z",
                    "published": "2024-03-29T08:37:22Z",
                    "platform": "S2B",
                    "cadip:id": "726f387b-ad2d-3538-8834-95e3cf8894c6",
                    "cadip:num_channels": 2,
                    "cadip:station_unit_id": "01",
                    "cadip:downlink_orbit": 53186,
                    "cadip:acquisition_id": 531861,
                    "cadip:antenna_id": "MSP21",
                    "cadip:front_end_id": "01",
                    "cadip:retransfer": false,
                    "cadip:antenna_status_ok": true,
                    "cadip:front_end_status_ok": true,
                    "cadip:planned_data_start": "2024-03-28T18:52:08.336Z",
                    "cadip:planned_data_stop": "2024-03-28T19:00:51.075Z",
                    "cadip:downlink_status_ok": true,
                    "cadip:delivery_push_ok": true
                },
                "links": [],
                "assets": {}
            }
        ]
    }

Download Endpoint
-----------------

This endpoint initiates an asynchronous download process for a CADU
product using EODAG. If specific parameters are provided, endpoint also
upload the file to an S3 bucket.

### API Reference

`/cadip/{station}/cadu`

### Parameters

-   `station` (str): The EODAG station identifier (e.g., MTI, SGS, MPU,
    INU, etc).

-   `name` (str): The name of the CADU product to be downloaded.

-   `local` (str, optional): The local path where the CADU product will
    be downloaded.

-   `obs` (str, optional): S3 storage path where the CADU file will be
    uploaded. (e.g. s3://bucket/path/to/file.tif). Connection to S3
    bucket is required, and should be written in the environmental
    variables, **S3\_ACCESSKEY**, **S3\_SECRETKEY**, **S3\_ENDPOINT**
    and **S3\_REGION**.

### Returns

-   `dict`: A dictionary indicating whether the download process has
    started.

### Request example

    GET /cadip/station123/cadu?name=DCS_04_S1A_20231121072204051312_ch1_DSDB_00001.raw

    GET /cadip/station123/cadu?name=DCS_04_S1A_20231121072204051312_ch1_DSDB_00001.raw&local=/tmp/file.raw

    GET /cadip/station123/cadu?name=DCS_04_S1A_20231121072204051312_ch1_DSDB_00001.raw&local=/tmp/file.raw&obs=s3://bucket/path/to/file.raw

### Response

    {
      "started": "true"
    }

Status Endpoint
---------------

This endpoint is used to query the download status of an CADU file.

### API Reference

`/cadip/{station}/cadu/status`

Parameters
----------

-   `station` (str): The EODAG station identifier (e.g., MTI, SGS, MPU,
    INU, etc).

-   `name` (str): The name of the CADU file to be queried from database.

### Request

    GET /cadip/{station}/cadu/status?name=DCS_04_S1A_20231121072204051312_ch1_DSDB_00001.raw

### Response

    {
      "product_id": "2b17b57d-fff4-4645-b539-91f305c27c69",
      "name": "DCS_04_S1A_20231121072204051312_ch1_DSDB_00001.raw",
      "available_at_station": "2019-02-16T12:00:00.000Z",
      "db_id": 1,
      "download_start": "2023-02-16T12:00:00.000Z",
      "download_stop": null,
      "status": "IN_PROGRESS",
      "status_fail_message": null
    }

ADGS
====

The Auxiliary Data Gathering Service (ADGS) is a pick-up point for
Sentinel auxiliary files. This service allows clients to discover and
retrieve available auxiliary data files through a standard OData RESTful
API. The following endpoints have been implemented in RS-Server to
interact with ADGS RESTful API.

Search Endpoint
---------------

This endpoint handles the search for products in the AUX station within
a specified time interval and return a STAC compatible FeatureCollection
response.

### API Reference

`/adgs/aux/search`

### Parameters

-   `datetime` (str): Interval of date for time series filter joined by
    a slash (*/*). (format:
    "YYYY-MM-DDThh:mm:sssZ**/**YYYY-MM-DDThh:mm:sssZ").

-   `limit` (int, optional): Maximum number of products to return,
    default set to 1000.

-   `sortby` (str, optional): Sorting criteria. +/-fieldName indicates
    ascending/descending order and field name (e.g. sortby=+datetime)
    Default no sorting is applied.

### Request Example

    GET /adgs/aux/search?datetime=2018-01-01T00:00:00Z/2023-01-02T23:59:59Z&limit=10&sortby=+properties.adgs:id

### Response

    {
        "stac_version": "1.0.0",
        "stac_extensions": ["https://stac-extensions.github.io/file/v2.1.0/schema.json"],
        "type": "Feature",
        "id": "DCS_01_S1A_20170501121534062343_ch1_DSDB_00001.raw",
        "geometry": null,
        "properties": {
            "adgs:id": "2b17b57d-fff4-4645-b539-91f305c27c69",
            "datetime": "2019-02-16T12:00:00.000Z",
            "start_datetime": "2019-02-16T11:59:58.000Z",
            "end_datetime": "2019-02-16T12:00:00.000Z",
        },
        "links": [],
        "assets": {
            "file": {
                "file:size": 29301
            }
        }
    }

Download Endpoint
-----------------

This endpoint initiates an asynchronous download process for an AUX
product using EODAG. If specific parameters are provided, endpoint also
upload the file to an S3 bucket.

### API Reference

`/adgs/aux`

### Parameters

-   `name` (str): The name of the AUX product to be downloaded

-   `local` (str, optional): The local path where the AUX product will
    be downloaded.

-   `obs` (str, optional): S3 storage path where the AUX file will be
    uploaded. (e.g. s3://bucket/path/to/file.tgz). Connection to S3
    bucket is required, and should be written in the environmental
    variables, **S3\_ACCESSKEY**, **S3\_SECRETKEY**, **S3\_ENDPOINT**
    and **S3\_REGION**.

### Returns

-   `dict`: A dictionary indicating whether the download process has
    started.

### Request Example

    GET /adgs/aux?name=S2__OPER_AUX_ECMWFD_PDMC_20190216T120000_V20190217T090000_20190217T210000.TGZ

    GET /adgs/aux?name=S2__OPER_AUX_ECMWFD_PDMC_20190216T120000_V20190217T090000_20190217T210000.TGZ&local=/tmp/aux.tar.gz

    GET /adgs/aux?name=S2__OPER_AUX_ECMWFD_PDMC_20190216T120000_V20190217T090000_20190217T210000.TGZ&local=/tmp/aux.tar.gz&obs=s3://bucket/path/to/aux.tar.gz

### Response

    {
      "started": "true"
    }

Status Endpoint
---------------

This endpoint is used to query the download status of an AUX file.

### Endpoint

`/adgs/aux/status`

### Parameters

-   `name` (str): The name of the AUX file to be queried from database.

### Request Example

    GET /adgs/aux/status?name=S2__OPER_AUX_ECMWFD_PDMC_20200216T120000_V20190217T090000_20190217T210000.TGZ

### Response

    {
      "product_id": "id2",
      "name": "S2__OPER_AUX_ECMWFD_PDMC_20200216T120000_V20190217T090000_20190217T210000.TGZ",
      "available_at_station": "2020-02-16T12:00:00",
      "db_id": 2,
      "download_start": "2023-02-16T12:00:00",
      "download_stop": "2023-02-16T12:01:00",
      "status": "DONE",
      "status_fail_message": null
    }

Catalog
=======

The following section groups all the endpoints a user can use to
interact with a STAC-compatible database system.

--- === STAC Feature: A STAC Feature represents a single geospatial
asset or dataset. It encapsulates metadata describing the asset,
including its spatial and temporal extent, properties, and links to
associated data files. STAC Features provide a standardized way to
describe individual geospatial datasets, making it easier to discover,
access, and use such data across different platforms and tools.

---

STAC Collection:
----------------

A STAC Collection is a logical grouping of related STAC Features. It
serves as a container for organizing and categorizing similar datasets
based on common characteristics, themes, or purposes. Collections can
represent various geospatial data themes such as satellite imagery,
aerial photography, or land cover classifications. They provide a
structured framework for managing and querying multiple related datasets
collectively, simplifying data organization and access workflows.

---

Using the endpoints described below, a user shall be able to:

-   Create / Read / Update / Delete a STAC feature.

-   Create / Read / Update / Delete a collection of STAC features.

-   Search details of existing catalogs, features and collections.

Create a collection
-------------------

This endpoint converts a request with a correct JSON body collection
descriptor to a database entry.

    POST /catalog/collections

    {
        "id": "test_collection",
        "type": "Collection",
        "description": "Collection description",
        "stac_version": "1.0.0",
        "owner": "test_owner"
    }

Get a collection
----------------

This endpoint returns a collection details based on parameters given in
request.

    GET /catalog/collections/{ownerId:collectionId}

    {
      "collections": [
        {
          "id": "test_collection",
          "type": "Collection",
          "owner": "test_owner",
          "description": "Collection description",
          "stac_version": "1.0.0",
          "links": [
            {
              "rel": "items",
              "type": "application/geo+json",
              "href": "http://testserver/catalog/test_owner/collections/test_collection/items"
            },
            {
              "rel": "parent",
              "type": "application/json",
              "href": "http://testserver/catalog/test_owner"
            },
            {
              "rel": "root",
              "type": "application/json",
              "href": "http://testserver/catalog/test_owner"
            },
            {
              "rel": "self",
              "type": "application/json",
              "href": "http://testserver/catalog/test_owner/collections/test_collection"
            }
          ]
        }
      ],
      "links": [
        {
          "rel": "root",
          "type": "application/json",
          "href": "http://testserver/catalog/test_owner"
        },
        {
          "rel": "parent",
          "type": "application/json",
          "href": "http://testserver/catalog/test_owner"
        },
        {
          "rel": "self",
          "type": "application/json",
          "href": "http://testserver/catalog/test_owner/collections"
        }
      ]
    }

Update a collection
-------------------

This endpoint updates a collection from STAC if it exists and request
body json data is STAC compatible.

    PUT /catalog/collections/{ownerId:collectionId}

    {
        "id": "test_collection",
        "type": "Collection",
        "description": "Updated collection description",
        "stac_version": "1.0.0",
        "owner": "test_owner"
    }

Delete a collection
-------------------

This endpoint deletes a collection from STAC if it exists and owner has
right to perform this action.

    DELETE /catalog/collections/{ownerId:collectionId}

Create a Feature
----------------

This endpoint converts a request with a correct JSON body feature
descriptor to a database entry. RS-Server Backend also move assets
between s3 storages and updates hypertext reference of each STAC Feature
with s3 locations.

    POST /catalog/collections/{ownerId:collectionId}/items

    {
      "collection": "S1_L2",
      "assets": {
        "zarr": {
          "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T717.zarr.zip",
          "roles": [
            "data"
          ]
        },
        "cog": {
          "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T420.cog.zip",
          "roles": [
            "data"
          ]
        },
        "ncdf": {
          "href": "s3://temp-bucket/S1SIWOCN_20220412T054447_0024_S139_T902.nc",
          "roles": [
            "data"
          ]
        }
      },
      "bbox": [0],
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [[-94.6334839, 37.0595608],
            [-94.6334839, 37.0332547],
            [-94.6005249, 37.0332547],
            [-94.6005249, 37.0595608],
            [-94.6334839, 37.0595608]]
        ]
      },
      "id": "S1SIWOCN_20220412T054447_0024_S139",
      "links": [
        {
          "href": "./.zattrs.json",
          "rel": "self",
          "type": "application/json"
        }
      ],
      "other_metadata": {},
      "properties": {
        "gsd": 0.5971642834779395,
        "width": 2500,
        "height": 2500,
        "datetime": "2000-02-02T00:00:00Z",
        "proj:epsg": 3857,
        "orientation": "nadir"
      },
      "stac_extensions": [
        "https://stac-extensions.github.io/eopf/v1.0.0/schema.json"
      ],
      "stac_version": "1.0.0",
      "type": "Feature"
    }

Get a Feature
-------------

This endpoint returns a feature details based on parameters given in
request.

    GET /catalog/collections/{ownerId:collectionId}/items/{featureID}

    {
      "id": "S1SIWOCN_20220412T054447_0024_S139",
      "bbox": [0],
      "type": "Feature",
      "links": [
        {
          "rel": "collection",
          "type": "application/json",
          "href": "http://testserver/catalog/fixture_owner/collections/fixture_collection"
        },
        {
          "rel": "parent",
          "type": "application/json",
          "href": "http://testserver/catalog/fixture_owner/collections/fixture_collection"
        },
        {
          "rel": "root",
          "type": "application/json",
          "href": "http://testserver/catalog/fixture_owner"
        },
        {
          "rel": "self",
          "type": "application/geo+json",
          "href": "http://testserver/catalog/fixture_owner/collections/fixture_collection/items/new_feature_id"
        }
      ],
      "assets": {
        "cog": {
          "href": "https://rs-server/catalog/fixture_owner/collections/fixture_collection/items/some_file.cog.zip/download/cog",
          "roles": [
            "data"
          ],
          "alternate": {
            "s3": {
              "href": "s3://catalog-bucket/correct_location/some_file.cog.zip"
            }
          }
        },
        "ncdf": {
          "href": "https://rs-server/catalog/fixture_owner/collections/fixture_collection/items/some_file.ncdf.zip/download/ncdf",
          "roles": [
            "data"
          ],
          "alternate": {
            "s3": {
              "href": "s3://catalog-bucket/correct_location/some_file.ncdf.zip"
            }
          }
        },
        "zarr": {
          "href": "https://rs-server/catalog/fixture_owner/collections/fixture_collection/items/some_file.zarr.zip/download/zarr",
          "roles": [
            "data"
          ],
          "alternate": {
            "s3": {
              "href": "s3://catalog-bucket/correct_location/some_file.zarr.zip"
            }
          }
        }
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [[-94.6334839, 37.0595608],
            [-94.6334839, 37.0332547],
            [-94.6005249, 37.0332547],
            [-94.6005249, 37.0595608],
            [-94.6334839, 37.0595608]]
        ]
      },
      "collection": "fixture_collection",
      "properties": {
        "gsd": 0.5971642834779395,
        "owner": "fixture_owner",
        "width": 2500,
        "height": 2500,
        "datetime": "2000-02-02T00:00:00Z",
        "proj:epsg": 3857,
        "orientation": "nadir"
      },
      "stac_version": "1.0.0",
      "stac_extensions": [
        "https://stac-extensions.github.io/eopf/v1.0.0/schema.json"
      ]
    }

Update a Feature
----------------

This endpoint updates content of a feature is request JSON data is
completely STAC-compatible.

    PUT /catalog/collections/{ownerId:collectionId}/items/{featureID}
