[![Quality Gate Status](https://sonarqube.ops-csc.com/api/project_badges/measure?branch=develop&project=RS-PYTHON_rs-server_AYw0m7ixvQv-JMsowILQ&metric=alert_status&token=sqb_c9241ef82ea91a8e9a9b604570f834f622dfed05)](https://sonarqube.ops-csc.com/dashboard?id=RS-PYTHON_rs-server_AYw0m7ixvQv-JMsowILQ&branch=develop)

# rs-server

The rs-server web services of [RS-Python](https://home.rs-python.eu/), the Copernicus Reference System Python:
[STAC](https://stacspec.org/) access to the Copernicus external data sources and to the RS-Python catalog, staging
of products into the catalog, and object storage access management, all of them with fine access control.

## Overview

rs-server is made of independent [FastAPI](https://fastapi.tiangolo.com/) web services, each one packaged in its
own Docker image:

| Service | Endpoints | Description |
|---|---|---|
| rs-server-cadip | `/cadip` | STAC API to search the sessions of the CADIP acquisition stations. |
| rs-server-adgs | `/auxip` | STAC API to search the auxiliary data of the AUXIP stations. |
| rs-server-prip | `/prip` | STAC API to search the products of the PRIP production services. |
| rs-server-catalog | `/catalog` | STAC API of the RS-Python catalog, with collections owned by the users. |
| rs-server-staging | `/processes`, `/jobs` | OGC API - Processes service that stages products from the stations into the catalog. |
| rs-server-osam | `/storage` | Object Storage Access Manager: S3 credentials and access rights of the users. |
| rs-server-frontend | `/docs` | Aggregated Swagger page of all the services. |

See the [rs-server documentation](docs/doc/index.md) for the details.

## Getting started

- Use the services from the Swagger page of your platform, e.g. <https://rspy.ops.rs-python.eu/docs> for the
  reference platform, from the [STAC browsers](https://github.com/RS-PYTHON/rs-documentation/blob/develop/docs/services/browse-products.md),
  or from Python code with the [rs-client-libraries](https://github.com/RS-PYTHON/rs-client-libraries).
- Run the services on your computer with the [local mode](https://github.com/RS-PYTHON/rs-demo/blob/develop/docs/local-mode.md)
  of rs-demo.
- Deploy them on a Kubernetes cluster with the [Helm charts](https://github.com/RS-PYTHON/rs-helm) and
  [rs-server-deployment](https://github.com/RS-PYTHON/rs-server-deployment).
- Develop on rs-server with the [developer manual](docs/doc/dev/developer_manual.md).

## Documentation

- User documentation: [overview](docs/doc/index.md), [external data sources](docs/doc/users/external-data-sources.md)
  and their [STAC mapping](docs/doc/users/stac-mapping.md), [catalog](docs/doc/users/catalog.md) and its
  [data model and lifecycle](docs/doc/users/data-model.md), [staging](docs/doc/users/staging.md),
  [OSAM](docs/doc/users/osam.md), [frontend](docs/doc/users/frontend.md).
- Developer documentation: [developer manual](docs/doc/dev/developer_manual.md),
  [staging internals](docs/doc/dev/staging-internals.md).
- Online documentation of the whole project: <https://home.rs-python.eu/rs-documentation/>
- [Changelog](CHANGELOG.md)

## Related repositories

| Repository | Relationship |
|---|---|
| [rs-client-libraries](https://github.com/RS-PYTHON/rs-client-libraries) | Python clients of the rs-server services, and Prefect flows that use them. |
| [rs-dpr-service](https://github.com/RS-PYTHON/rs-dpr-service) | The processing service, deployed alongside rs-server. |
| [rs-helm](https://github.com/RS-PYTHON/rs-helm), [rs-server-deployment](https://github.com/RS-PYTHON/rs-server-deployment) | Helm charts and deployment of the rs-server services. |
| [rs-testmeans](https://github.com/RS-PYTHON/rs-testmeans) | Mockups of the external stations used by the tests. |
| [rs-demo](https://github.com/RS-PYTHON/rs-demo) | Demo notebooks and local mode. |
| [rs-documentation](https://github.com/RS-PYTHON/rs-documentation) | Online documentation of the whole project. |

## Contributing

See the [contribution guidelines](https://github.com/RS-PYTHON/rs-documentation/blob/develop/docs/developers/contributing.md).
Report bugs in the [issue tracker](https://github.com/RS-PYTHON/rs-server/issues). In case of sensitive bugs like
security vulnerabilities, please contact <ops_coprs@airbus.com> directly instead of using the issue tracker.

## Licensing

The code in this project is licensed under the [Apache License, Version 2.0](https://www.apache.org/licenses/LICENSE-2.0).

---

![](https://raw.githubusercontent.com/RS-PYTHON/.github/refs/heads/main/profile/banner_logo.jpg)

This project is funded by the EU and ESA.
