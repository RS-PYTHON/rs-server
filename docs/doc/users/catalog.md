
Catalog
-------

The following section groups all the endpoints used to
interact with a [STAC](https://stacspec.org/)-compatible catalog of Sentinel products, auxiliary files and CADU chunks.

---

### STAC Item

A STAC Item represents a single geospatial
asset or dataset. Items are built upon community [extensions](https://stac-extensions.github.io/) including the eo, eopf, sar, sat, processing, proj and
timestamps extensions. It encapsulates metadata describing the asset,
including its spatial and temporal extent, properties, and links to
associated data files. STAC Items provide a standardized way to
describe individual geospatial datasets, making it easier to discover,
access, and use such data across different platforms and tools.

---

### STAC Collection

A STAC Collection is a logical grouping of related STAC Features. It
serves as a container for organizing and categorizing similar datasets
based on common characteristics, themes, or purposes. Collections can
represent various geospatial data themes such as satellite imagery,
aerial photography, or land cover classifications. They provide a
structured framework for managing and querying multiple related datasets
collectively, simplifying data organization and access workflows.

---

Using the endpoints described below, a user shall be able to:

-   Create / Read / Update / Delete a STAC item.

-   Create / Read / Update / Delete a collection of STAC items.

-   Search details of existing items and collections.

### Create a collection

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

### Get a collection

This endpoint returns a collection details based on parameters given in
request. The `ownerId` parameter is optional. If this is missing from the endpoint, a default
user is used with the following priority:
* the user found in the `apikey security` in the case when the process is running on `cluster`
* the current user in the case when the process is running in `local mode`

    GET /catalog/collections/{[ownerId:]collectionId}

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

### Update a collection

This endpoint updates a collection from STAC if it exists and request
body json data is STAC compatible. The `ownerId` parameter is optional. If this is missing from the endpoint,
a default user is used with the following priority:
* the user found in the `apikey security` in the case when the process is running on `cluster`
* the current user in the case when the process is running in `local mode`

    PUT /catalog/collections/{[ownerId:]collectionId}

    {
        "id": "test_collection",
        "type": "Collection",
        "description": "Updated collection description",
        "stac_version": "1.0.0",
        "owner": "test_owner"
    }

### Delete a collection

This endpoint deletes a collection from STAC if it exists and owner has
right to perform this action. The `ownerId` parameter is optional. If this is missing from the endpoint, a default
user is used with the following priority:
* the user found in the `apikey security` in the case when the process is running on `cluster`
* the current user in the case when the process is running in `local mode`

    DELETE /catalog/collections/{[ownerId:]collectionId}

### Add an Item

This endpoint converts a request with a correct JSON body feature
descriptor to a database entry. RS-Server Backend also move assets
between s3 storages and updates hypertext reference of each STAC Feature
with s3 locations. The `ownerId` parameter is optional. If this is missing from the endpoint, a default
user is used with the following priority:
* the user found in the `apikey security` in the case when the process is running on `cluster`
* the current user in the case when the process is running in `local mode`

    POST /catalog/collections/{[ownerId:]collectionId}/items

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

### Get an Item

This endpoint returns a feature details based on parameters given in
request. The `ownerId` parameter is optional. If this is missing from the endpoint, a default
user is used with the following priority:
* the user found in the `apikey security` in the case when the process is running on `cluster`
* the current user in the case when the process is running in `local mode`

    GET /catalog/collections/{[ownerId:]collectionId}/items/{featureID}

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

### Update an Item

This endpoint updates content of a feature is request JSON data is
completely STAC-compatible. The `ownerId` parameter is optional. If this is missing from the endpoint, a default
user is used with the following priority:
* the user found in the `apikey security` in the case when the process is running on `cluster`
* the current user in the case when the process is running in `local mode`

    PUT /catalog/collections/{[ownerId:]collectionId}/items/{featureID}


### Download an Item

This endpoint returns a S3 presigned url that can directly download the file when accessed. The `ownerId` parameter is
optional. If this is missing from the endpoint, a default user is used with the following priority:
* the user found in the `apikey security` in the case when the process is running on `cluster`
* the current user in the case when the process is running in `local mode`

    GET /catalog/collections/{[ownerId:]collectionId}/items/{featureID}/download/{assetId}
