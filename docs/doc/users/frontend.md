# Frontend

The **rs-server-frontend** service builds the unified [Swagger](https://swagger.io/tools/swagger-ui/) page of all
the RS-Python web services, e.g. <https://rspy.ops.rs-python.eu/docs> on the reference platform. It doesn't
implement any functional endpoint itself:

| Endpoint | Description |
|---|---|
| `/docs` | The Swagger page of the aggregated [OpenAPI](https://www.openapis.org/) specification. |
| `/openapi.json` | The aggregated OpenAPI specification, in JSON format. |

The usage of the Swagger page is described in
[Swagger](https://github.com/RS-PYTHON/rs-documentation/blob/develop/docs/services/swagger.md).

## How it works

The *Try it out* feature of the Swagger page calls the real services: all the services are exposed behind the same
domain name by the Envoy Gateway of the cluster, that routes each request to the right service according to its
path (`/cadip`, `/catalog`, `/processes`...).

The aggregated OpenAPI specification is static: it is computed by the CI that builds the rs-server Docker images,
with the [`build_aggregated_openapi.sh`](https://github.com/RS-PYTHON/rs-server/blob/develop/services/frontend/resources/build_aggregated_openapi.sh)
script, then embedded in the frontend Docker image:

1. the script starts all the services locally (with the databases and the rs-dpr-service image they need), only to
   get their OpenAPI specifications,
2. it downloads the specification of each service listed in
   [`services.yml`](https://github.com/RS-PYTHON/rs-server/blob/develop/services/frontend/resources/services.yml),
   renames their tags (e.g. `CADIP stations`) and merges them into a single `openapi.json` file, with the general
   description of the Swagger page (links to the documentation, the STAC browsers, the API Key Manager...),
3. the frontend service reads this file at startup (`RSPY_OPENAPI_FILE` environment variable) and serves it.

So, when an endpoint of a service is modified, the frontend image must be rebuilt to update the documentation.
When a new service is added, it must be added to `services.yml`.

The links of the general description, e.g. to the STAC browsers, are set at deployment time with environment
variables (`STAC_BROWSER_URL_CADIP`...), see the
[rs-server-frontend Helm chart](https://github.com/RS-PYTHON/rs-helm/blob/develop/charts/rs-server-frontend/README.md).
