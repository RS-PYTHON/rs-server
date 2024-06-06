
Service Structure
=================
The RS-Server architecture is composed of several modular services, each designed to offer distinct functionalities accessible via HTTPS endpoints. Here is a detailed overview of the key aspects of the RS-Server services:

1. Independence and Modularity:
    * Each service operates independently, encapsulated within its own Docker image. This isolation ensures that services can be developed, deployed, and scaled without interdependencies.
    * Services are designed to be stateless, which facilitates easy scaling and load distribution across multiple instances.

2. Deployment Modes:
    * **Laptop Mode**: Services can be initiated on a local machine, making it convenient for development and testing purposes.
    * **Cluster Mode**: For production environments, services can be deployed in a cluster setup , enhancing their ability to handle multiple concurrent requests. This mode supports parallel processing, thereby improving performance and reliability.

3. Cluster Management:
    * The cluster is governed by **Kubernetes**, which orchestrates the deployment, scaling, and management of the containerized services. Kubernetes ensures high availability, load balancing, and efficient resource utilization across the cluster.

4. Scalability:
    * Due to their stateless nature, services can be scaled horizontally. This means additional instances can be spawned to manage increased loads without any complex configuration.

The RS-Server's microservices architecture ensures robustness, scalability, and ease of management. By leveraging Docker for containerization and Kubernetes for orchestration, along with the rs-server-common package for shared functionalities, RS-Server offers a flexible and efficient solution for various deployment needs. This architecture supports both small-scale local deployments and large-scale production environments, providing the necessary tools and structures to handle a wide range of requests efficiently.

Main Services, Common Structures and Mechanisms
===============================================
There are currently 3 main services implemented:

1. CADIP service
It facilitates the search and download of files from a CADIP server to a S3 bucket. Each instance of this service is started for a given station and provides 3 endpoints:

    * A **search** endpoint that enables to search files for a time period
    * A **download** endpoint that enables to download a file using own its name
    * A **status** endpoint that enables the check of the current status for a downloading file.


2. ADGS service - Provides the same functionality as CADIP service, facilitates the search and download of files from an ADGS server to a S3 bucket
3. Catalog service - facilitates the use of the main RS-Server catalog in [PySTAC](https://pystac.readthedocs.io/en/stable/) format

To maintain consistency and streamline development, all services use shared components and mechanisms provided by the ```rs-server-common package```. This package includes:

* Standardized Data Structures: Ensuring uniformity in data handling across all services.
* Common Utilities: Functions and tools that are frequently used across different services, promoting code reuse and reducing redundancy.
* Configuration Management: Centralized configuration settings that can be applied uniformly to all services, simplifying deployment and maintenance.

Start coding
============

To start coding on RS-Server, you have to install it first:

-   [Installation](dev/environment/installation.md)

Code Style
==========

The following is the code style used in developing for RS-Server:

-   [Code style](dev/code-style.md)

RS-Server REST API Documentation
================================

The frontend of the RS-Server ecosystem is a specialized service that primarily provides [REST API](api/rest/index.md) documentation. Here’s a detailed overview of its features and functionality:
**Service Overview**

1. Purpose:
    * The frontend service is dedicated to displaying and managing the API documentation for all RS-Server services.
    * It does not implement any functional endpoints of the RS-Server itself but focuses on documentation.

2. Endpoints:
    * **/doc Endpoint**: This endpoint displays the aggregated OpenAPI specification of all RS-Server services using SwaggerUI, providing an interactive interface for users to explore the API.
    * **/openapi.json Endpoint**: This endpoint serves the same OpenAPI specification in JSON format, allowing programmatic access to the documentation.

**OpenAPI Specification**

1. Specification Source:
    * The OpenAPI specification is provided by a JSON file. The location of this file is configurable via an environment variable read at the service startup.
2. Configuration:
    * The environment variable determines the path to the JSON file containing the OpenAPI specification, allowing flexibility in deployment and updates.

**Static Documentation**

1. Build Procedure:
    * The content of the documentation is static. It is computed during the frontend build procedure and then integrated statically into the frontend service.
    * Whenever a RS-Server service endpoint is updated, the frontend service must be rebuilt to provide up-to-date documentation.

2. CI Workflow:
    * The OpenAPI specification is constructed as part of the continuous integration (CI) workflow that builds the frontend service executable.
    * This workflow starts all RS-Server services, retrieves their individual OpenAPI specifications, aggregates them, and stores the combined specification in a file.
    * This file is then integrated into the Docker image of the frontend service.

**Configuration Management**

1. Configuration File:
    * A configuration file defines all RS-Server services that should be included in the aggregated OpenAPI specification.
    * Each time a new service is added, its details must be included in this configuration file to ensure it is part of the aggregated documentation.

**Functionality**

1. Interactive Documentation:
    * Although the frontend does not implement the functional endpoints, the ```Try it out``` feature of SwaggerUI is functional. This is enabled by the deployment of RS-Server with an ingress controller that manages request redirection to the appropriate RS-Server services.

By maintaining a clear separation between documentation and functional implementation, the frontend service ensures that users have access to comprehensive and interactive API documentation, while also facilitating easy updates and integration of new services through a structured CI workflow.

Python API Library
==================
Please check the ```Python API Library``` link in the sidebar navigation to access the generated documentation directly from the source code.

Additional information
======================

Here are some additional information that may help you in finding the answer when coding on RS-Server:

-   [Tree structure](dev/background/tree-structure.md)

-   [Workflow](dev/background/workflow.md)

-   [CI](dev/background/ci.md)
