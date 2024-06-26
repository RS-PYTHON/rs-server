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
