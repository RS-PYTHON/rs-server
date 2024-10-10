All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

The RS-SERVER is delivered with a version using 2 digits
("major.minor"), following the [Version specifiers for
Python](https://packaging.python.org/en/latest/specifications/version-specifiers/#version-scheme).

[Unreleased]
==============

Added
-----
* initialize technical documentation
* initialize python project

Fixed
-----

None

Changed
-------

None

[0.2a5] - Sprint 15 - 2024-10-09
================================

## Added

- RSPY-60: Deploy to PyPi
- RSPY-63: Complete Python CI/CD chain with distribution to the Python registry
- RSPY-230: Deploy STAC browser
- RSPY-352: Implement authentication to external data sources (CADIP+AUXIP)
- RSPY-357: Simulated OAuth2 token endpoint in CADIP/AUXIP/LTA mockups
- RSPY-358: Update helm charts to deploy RSPY-352
- RSPY-424: Sprint 15 corrections of issues

## Fixed

- RSPY-155: Pydantic version conflict in rs-server catalog
- RSPY-411: The first collection is created twice from SWAGGER interface
- RSPY-419: [Rs-server] Errors with rs-server-staging
- RSPY-430: /catalog/{collectionId}/queryables is not included in the links of the collection

[0.2a4] - Sprint 14 - 2024-09-18
================================

## Added

- RSPY-396: Implement missing fields of virtual STAC collections
- RSPY-348: Implement STAC view of CADIP sessions (2/3: add root STAC endpoints)
- RSPY-359: Implement STAC view of CADIP sessions (3/3: add Queryables endpoints)
- RSPY-345: Access to RS-Catalog with OAuth2
- RSPY-280: Implement the STAC authentication extension in Catalog (2/2: OIDC, Oauth2+PKCE)
- RSPY-197: Update to stac-fastapi 3.0.0
- RSPY-336: Dask cluster use cases study

## Fixed

- RSPY-381: Error during cluster creation
- RSPY-382: Prometheus datasource not created
- RSPY-385: CloudNative PG Deployment failed due to syntax issue on limit/request
- RSPY-386: Grafana-Tempo deployment values don't match with apps.yaml
- RSPY-387: Missing credential secret creation for Github Repository
- RSPY-388: [Velero] First Deployment failed due to missing CRD
- RSPY-399: Impossible to create PV (quota reached)
- RSPY-405: uacCheckUrl or uacURL

[0.2a3] - Sprint 13 - 2024-08-28
================================

Added
-----

* RSPY-166: Use Keycloak to login into Wazuh
* RSPY-237: [stac-fastapi-pgstac] Upgrade to version 2.5.0
* RSPY-264: [Monitoring] Create Grafana datasources for PostgreSQL databases
* RSPY-266: [Monitoring] Create JupyterHub ServiceMonitor
* RSPY-293: Use Keycloak to login into Neuvector
* RSPY-295: STAC Queryables (Catalog software part)
* RSPY-302: Simplify Catalog: remove the concept of "user catalog"
* RSPY-312: Configure Prefect Server logging
* RSPY-318: Backup and restore Keycloak data
* RSPY-321: Implement skeleton of staging service
* RSPY-322: Implement STAC view of CADIP sessions (1/3: refactor)
* RSPY-327: [Catalog] add/update item : don't copy assets already in catalog bucket
* RSPY-335: Deploy dask gateway server
* RSPY-340: [API-Key Manager] merge rspy branch into main
* RSPY-341: Update to EODAG v3
* RSPY-346: Proof Of Concept / oauth2 with PKCE authorisation
* RSPY-351: Variabilize the bucket name
* RSPY-353: STAC validation error with auth scheme
* RSPY-354: Sprint 13 corrections of issues
* RSPY-356: Collection search endpoint should return http 404 error instead of empty list for missing collection
* RSPY-397: Adapt tests and code to support filenames as STAC asset keys

[0.2a2] - Sprint 12 - 2024-07-17
================================

Added
-----

* RSPY-40: Implement a LTA station mockup
* RSPY-105: Add collection-specific search endpoint
* RSPY-132: Implement secured inventory.yaml using Vault
* RSPY-223: Provide an Ansible playbook to deploy RS-Server
* RSPY-272: [Deployment] Node label not set (terraform error)
* RSPY-273: Implement the STAC authentication extension in Catalog (1/3: API key)
* RSPY-281: STAC extensions missing in the stac_extensions list
* RSPY-282: Document STAC catalog metadata (id, title, description)
* RSPY-297: [Deployment] Several pods have no affinity
* RSPY-299: EODAG library performs uncontrolled access to external STAC servers
* RSPY-305: DPR mockup returns STAC items with a single zarr asset
* RSPY-306: Internal error when adding catalog item with missing asset
* RSPY-307: Replace use of deprecated FastAPI code
* RSPY-308: Define resource requests and limits for all pods
* RSPY-317: Deploy VELERO component on the cluster.
* RSPY-333: Sprint 12 corrections of issues
* RSPY-334: A user is able to create a collection for another user

[0.2a1] - Sprint 11 - 2024-06-26
================================

Added
-----

* RSPY-141: Implement the STAC timestamps extension in Catalog
* RSPY-153: Implicit collection owner when calling catalog endpoints
* RSPY-161: Map CADIP session files as STAC assets for stations that support Expand=Files
* RSPY-186: Catalog application does crash properly during initialization
* RSPY-192: Update CADU search endpoint to search by session_id:
* RSPY-210: Deploy Grafana Tempo on K8S cluster:
* RSPY-254: [Safety] Errors displayed on Wazuh UI:
* RSPY-256: [rs-testmeans] document how to add mock data:
* RSPY-277: Missing probes in some RS-Server components:
* RSPY-286: STAC OpenAPI links not working:
* RSPY-288: Update CADIP/AUXIP mocks to support PVC:
* RSPY-292: API Key manager wipes IAM roles of existing keys:
* RSPY-294: Umbrella to collect all ISSUES points (sprint 11):
* RSPY-296: Simplify authentication to RS frontend:
* RSPY-300: Internal error when calling /cadip/{station}/session without params:
* RSPY-303: Catalog asset download links are invalid:
* RSPY-304: Response of catalog asset download is invalid

[0.1a10] - 2024-06-05
======================

Added
-----

* RSPY-112: Take into account feedback on generated documentation
* RSPY-116: Prepare and perform 0.1 delivery for ESA checkpoint
* RSPY-159: StacClient Class Python development
* RSPY-241: [Deployment] JupiterHub UI not reachable after deployment
* RSPY-245: [Deployment] Missing namespaces in kustomization.yaml
* RSPY-252: [Deployment] Namespace issue during installation of Neuvector crds
* RSPY-253: Deploy RS-Client libraries into JupiterLab instances
* RSPY-255: Infra bugfixing for CP 0.1
* RSPY-258: [Deployment] Grafana in CrashLoop when no plugin
* RSPY-259: [Deployment] Missing secret for Loki
* RSPY-260: [monitoring] Monitoring certificate secret name not match with deployment for grafana and prometheus
* RSPY-261: [Monitoring] No prometheus value retrieved for neuvector
* RSPY-263: [Monitoring] Prometheus GrafanaDatasource not created during prometheus deployment
* RSPY-267: [Security] No severity score on huge amount of CVE

[0.1a9] - 2024-05-15
======================

Added
-----

* RSPY-130: Deploy Grafana on K8S cluster
* RSPY-133: Deploy Prefect Workers on K8S cluster
* RSPY-148: CadipClient Class Python development
* RSPY-149: AuxipClient Class Python development
* RSPY-158: RsClient Class Python development
* RSPY-174: [EODAG] download in parallel on the same machine or container
* RSPY-181: Deployment: label not well set by deployment script
* RSPY-196: Platform deployment: error keycloak realm import
* RSPY-213: Improve error handling in catalog
* RSPY-218: Sprint 9 corrections of issues
* RSPY-220: Kubectl commands with kubectl OIDC not working
* RSPY-224: RS-Server: missing resources tag in yaml
* RSPY-225: RS-Server: No image version reference
* RSPY-227: Add missing unit tests for \* RSPY-120
* RSPY-228: Add missing configuration for promtail
* RSPY-229: Helm charts - Dynamic list based on values
* RSPY-239: [Deployment] No JupiterHub image reachable from Validation platform
* RSPY-240: [Deployment] No Secret Create during Wazuh Agent deployment

[0.1a8] - 2024-04-24
======================

Added
-----

* RSPY-69: Implement access control to the catalog (with UAC)
* RSPY-99: Deploy JupyterHub on K8S cluster
* RSPY-120: Implement a first S1L0 processing Prefect @flow
* RSPY-123: Create Jupyter notebook to launch Prefect chains
* RSPY-128: Deploy promtail and Grafana Loki on K8S cluster
* RSPY-162: Python modules for log & trace
* RSPY-167: New endpoint to get CADIP session information
* RSPY-170: Platform deployment and start-stop playbook failed due to missing credential
* RSPY-176: Platform deployment: first application deployment execution failed for the step cluster-issuer
* RSPY-177: Platform Deployment: Failed to deployed application due to missing parameter in group\_vars
* RSPY-179: Platform deployment: no cinder controller for PVC
* RSPY-180: Platform deployment: kubelet errors with cpu manager
* RSPY-182: Wazuh agent is being reinstalled when cluster is restarted
* RSPY-183: Prometheus is not accessible from the ingress
* RSPY-185: Sprint 8 corrections of infrastructure issues
* RSPY-186: Catalog application does crash properly during initialization
* RSPY-219: Improve AUXIP & CADIP mockups representativeness

[0.1a7] - 2024-04-03
======================

Added
-----

* RSPY-86: Deploy security stack on K8S cluster
* RSPY-122: Deploy RS-Server on K8S cluster
* RSPY-129: Deploy prometheus and node\_exporter on K8S cluster
* RSPY-135: Setup Swagger/OpenAPI documentation aggregation frontend
* RSPY-137: Link RS-Server frontend with Backend Catalog endpoints (Without UAC) - Part 3
* RSPY-152: Simplify Catalog endpoints with "ownerId:collectionId"
* RSPY-157: Update the datetimes STAC mapping for ADGS & CADIP
* RSPY-163: Implement access control to the CADIP stations (with UAC)
* RSPY-164: Implement access control to the ADGS center (with UAC)
* RSPY-169: Project versioning and naming
* RSPY-171: [URGENT] Replace Miniconda by Miniforge

[0.1a6] - 2024-03-14
======================

Added
-----

* RSPY-15: Setup UAC Manager
* RSPY-25: Override endpoint "publication of STAC item" to the Catalog backend server
* RSPY-49: Deploy Prefect Server on K8S cluster
* RSPY-85: Implement CADU ingestion Prefect @flow
* RSPY-100: Link RS-Server frontend with Backend Catalog endpoints (Without UAC) - Part 2
* RSPY-115: Implement ADGS ingestion Prefect @flow
* RSPY-125: Cluster configuration folder is hard-coded
* RSPY-139: Add endpoint to download product (without UAC)

[0.1a5] - 2024-02-21
======================

Added
-----

* RSPY-68: Configure OpenID Connect on K8S cluster
* RSPY-73: Link RS-Server frontend with CADIP backend endpoints (without UAC)
* RSPY-78: Link RS-Server frontend with Backend Catalog endpoints (Without UAC) - Part 1
* RSPY-81: Deploy keycloak on K8S cluster
* RSPY-91: Link RS-Server frontend with ADGS backend endpoints (without UAC)
* RSPY-94: Implement a DPR mockup
* RSPY-121: Setup Ingress Controller
* RSPY-126: Initialize RS-SERVER-Libraries repository
* RSPY-134: Setup Helm Chart Releaser to use Github Pages as Helm chart repository
* RSPY-138: Add public architecture documentation on GitHub

[0.1a4] - 2024-01-31
======================

Added
-----

* RSPY-29: Deploy Kubernetes
* RSPY-33: Generate CI/CD documentation from Github
* RSPY-87: Develop ADGS backend server with first endpoint "GET /adgs/aux/search"
* RSPY-88: Add endpoint GET "/adgs/aux" to ADGS backend server
* RSPY-90: Add endpoint GET "/adgs/aux/status" to ADGS backend server
* RSPY-117: Create a Jupyter demo for local target

[0.1a3] - 2024-01-16
======================

Added
-----

* RSPY-14: Add endpoint "download cadu" to CADIP backend server
* RSPY-16: Develop CADIP backend server with first endpoint "get cadu"
* RSPY-31: Initiate Developer Guide
* RSPY-39: Implement a CADIP station mockup
* RSPY-41: Implement an ADGS station mockup
* RSPY-53: Develop Catalog backend server
* RSPY-72: Add endpoint "CADU status" to CADIP backend server
