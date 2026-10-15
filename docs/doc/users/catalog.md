# Catalog

The **rs-server-catalog** service is a [STAC API](https://github.com/radiantearth/stac-api-spec) of the products
managed by RS-Python: raw data sessions, auxiliary files, Level-0, Level-1 and Level-2 products. It allows to
create, read, update and delete (CRUD) collections and items, and to search them with spatial, temporal and
metadata criteria.

It is implemented with [stac-fastapi-pgstac](https://github.com/stac-utils/stac-fastapi-pgstac), the metadata being
stored in a [PostgreSQL](https://www.postgresql.org/) database with the [pgstac](https://github.com/stac-utils/pgstac)
schema, and the assets in the S3 object storage. RS-Python adds on top of it:

- the **ownership** of the collections and the **authorisation** checks,
- the checks of the **assets** in the object storage, their checksums, and their **download** with temporary URLs,
- the **timestamps** and the **lifecycle** of the items, see [Catalog data model and lifecycle](data-model.md).

The main use cases are:

- controlling the user access to the STAC collections,
- uploading new datasets into the catalog, with their metadata and asset references (this is done by the
  [staging](staging.md) and by the processing flows),
- searching the data with spatial, temporal or thematic criteria,
- accessing and downloading the assets,
- managing and updating the metadata of existing items,
- visualising the data, with the catalog [STAC browser](https://github.com/RS-PYTHON/rs-documentation/blob/develop/docs/services/browse-products.md#stac-browsers)
  or any STAC-compatible application.

## Collections and ownership

Each collection belongs to an **owner**, a user of the platform. Its identifier in the API is
`<owner>:<collection>`, e.g. `copernicus:s3-l0`. When the owner is omitted, e.g. `s3-l0`, the owner is the
authenticated user (the user of the API key or of the OAuth2 session). The owner is also written in the `owner`
property of the collections and items ([ownership STAC extension](https://github.com/RS-PYTHON/ownership-stac-extension)).

The owner has all the rights on its collections. The other users need the
`rs_catalog_<owner>:<collection>_<read|write|download>` roles, see
[User rights](https://github.com/RS-PYTHON/rs-documentation/blob/develop/docs/getting-started/user-rights.md#catalog).

> **Note:** internally, the collections are stored in pgstac as `<owner>_<collection>`, because pgstac does not
> handle the ownership. This internal identifier is never returned by the API.

## Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/catalog/` | Landing page, with links to the collections you can read. |
| `GET` | `/catalog/conformance` | Conformance classes. |
| `GET` | `/catalog/collections` | List the collections you can read. |
| `POST` | `/catalog/collections` | Create a collection. |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/catalog/collections/{owner}:{collection}` | Read, replace, update or delete a collection (and its items). |
| `GET` | `/catalog/collections/{owner}:{collection}/items` | Search the items of a collection. |
| `POST` | `/catalog/collections/{owner}:{collection}/items` | Add an item (or an item collection). |
| `POST` | `/catalog/collections/{owner}:{collection}/bulk_items` | Add several items at once ([bulk transactions](https://stac-utils.github.io/stac-fastapi/)). |
| `GET`, `PUT`, `PATCH`, `DELETE` | `/catalog/collections/{owner}:{collection}/items/{item_id}` | Read, replace, update or delete an item. |
| `GET` | `/catalog/collections/{owner}:{collection}/items/{item_id}/download/{asset}` | Download an asset, see [Download](#download-the-assets). |
| `GET`, `POST` | `/catalog/search` | Search the items of all or some collections. |
| `GET` | `/catalog/queryables`, `/catalog/collections/{owner}:{collection}/queryables` | Properties that can be used in the filters. |

The search parameters (`collections`, `ids`, `datetime`, `bbox`, `filter`, `sortby`, `limit`...) are described in
[Browse products](https://github.com/RS-PYTHON/rs-documentation/blob/develop/docs/services/browse-products.md#search-parameters).
The detailed description of the endpoints is in the [Swagger page](https://rspy.ops.rs-python.eu/docs#/Catalog).

The STAC API extensions implemented by the catalog are:

| Extension | Usage |
|---|---|
| [Transaction](https://github.com/stac-api-extensions/transaction) and [Collection Transaction](https://github.com/stac-api-extensions/collection-transaction) | Create, update and delete the items and the collections (`POST`, `PUT`, `PATCH`, `DELETE`). |
| [Bulk Transaction](https://stac-utils.github.io/stac-fastapi/) | Efficient insertion of many items. |
| [Filter](https://github.com/stac-api-extensions/filter) | Search with [CQL2](https://docs.ogc.org/is/21-065r2/21-065r2.html) filters and queryables. Used e.g. to [select the auxiliary files](https://github.com/RS-PYTHON/rs-client-libraries/blob/develop/docs/doc/flows/tasktable-payload.md#auxiliary-data-selection-policies) needed by the processors. |
| [Sort](https://github.com/stac-api-extensions/sort) | Sort the search results, e.g. to select the most recent auxiliary file. |

## Examples

### Create a collection

```http
POST /catalog/collections
```

```json
{
  "id": "my-collection",
  "type": "Collection",
  "description": "My collection",
  "stac_version": "1.1.0",
  "license": "other",
  "extent": {
    "spatial": {"bbox": [[-180, -90, 180, 90]]},
    "temporal": {"interval": [["2026-01-01T00:00:00Z", null]]}
  },
  "links": []
}
```

The collection is created for the authenticated user. To create it for another owner, add an `"owner": "<owner>"`
field (you need the `write` right on it).

### Add an item

```http
POST /catalog/collections/my-collection/items
```

```json
{
  "type": "Feature",
  "stac_version": "1.1.0",
  "stac_extensions": ["https://stac-extensions.github.io/eopf/v1.0.0/schema.json"],
  "id": "S1SIWOCN_20220412T054447_0024_S139",
  "collection": "my-collection",
  "geometry": {"type": "Polygon", "coordinates": [[[-94.63, 37.06], [-94.63, 37.03], [-94.60, 37.03], [-94.60, 37.06], [-94.63, 37.06]]]},
  "bbox": [-94.63, 37.03, -94.60, 37.06],
  "properties": {
    "datetime": "2022-04-12T05:44:47Z",
    "product:type": "S01SIWOCN"
  },
  "assets": {
    "zarr": {
      "href": "s3://<bucket>/<owner>/my-collection/S1SIWOCN_20220412T054447_0024_S139.zarr",
      "roles": ["data"]
    }
  },
  "links": []
}
```

When an item is created or replaced:

- the `product:type` property is mandatory (`403 Forbidden` otherwise),
- the assets must exist in the object storage: the catalog checks them and computes their `file:checksum`,
- the catalog adds the `owner` property, the `created`, `updated`, `published` and `expires` timestamps, see
  [Catalog data model and lifecycle](data-model.md#data-lifecycle).

The assets are not copied by the catalog: they must already be written in the right bucket, which is what the
[staging](staging.md) and the processing flows do.

### Search

```http
GET /catalog/search?collections=copernicus:s3-l0&filter=platform='sentinel-3a'&sortby=-datetime&limit=10
```

## Download the assets

The `GET /catalog/collections/{owner}:{collection}/items/{item_id}/download/{asset}` endpoint checks that you have
the `download` right on the collection, then redirects you to a temporary
[presigned URL](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html) of the asset in the
object storage. The thumbnails of the items get an `alternate` link to this endpoint, so they can be displayed by
the STAC browsers.

You can also read the assets directly from the object storage with your own S3 credentials, see
[OSAM](osam.md) and [Download the assets](https://github.com/RS-PYTHON/rs-documentation/blob/develop/docs/services/browse-products.md#download-the-assets).

## Configuration

| Environment variable | Description |
|---|---|
| `RSPY_DATA_LIFECYCLE_PERIOD` | Period, in seconds, of the task that unpublishes the expired items (see [Data lifecycle](data-model.md#data-lifecycle)). Negative to deactivate it. |
| `RSPY_PRESIGNED_URL_EXPIRATION_TIME` | Lifespan, in seconds, of the presigned download URLs. |
| `RSPY_HOST_OSAM` | URL of the OSAM service, that provides the [bucket configuration](https://github.com/RS-PYTHON/rs-documentation/blob/develop/docs/administration/update-rs-server.md#object-storage-buckets-and-data-lifecycle). |

The other parameters of the deployment are described in the
[rs-server-catalog Helm chart](https://github.com/RS-PYTHON/rs-helm/blob/develop/charts/rs-server-catalog/README.md).
