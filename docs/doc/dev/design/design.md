The rs-server is divided into two main elements :

-   the rs-server frontend

-   the rs-server backend

The rs-server frontend is a facade for users that verify the user
privileges before accessing to the services provided by the rs-server
backend.

rs-server frontend
==================

TODO To Be Defined

rs-server backend
=================

The rs-server backend is divided in several services.

TODO insert a table of the service with short description and the list
of functionalities

Each service provides several functionalities as https endpoints. All
services are independent of others. Each service is provided as an
independent Docker image. Each service can be started in laptop or
cluster mode (see later for more details). Each service can handle
multiple requests in parallel in cluster mode. Services are stateless,
so they can easily be scaled and the activity be divided into the
multiple instances.

All services share some common structures and mechanisms. These common
elements are provided by the rs-server-common package.

Sources organisation
--------------------

TODO insert the service tree structure here

Each service has its own folder named with the service name. This folder
is a python project. It contains the sources, tests, configuration,… for
this service. It also contains a Dockerfile describing the service
output image. The sources of each layer are separated in a specific
package.

The shared elements are provided by the rs-server-common package. It is
handled as a python project as if it is a rs-server service.

Services
--------

Cadip service
-------------

The cadip service enables users to retrieve data from cadip stations.
Each instance of this service is started for a given station.

It provides 2 endpoints :

-   a search endpoint that enables to search files for a time period

-   a download endpoint that enables to download a file from its id and
    name

The processes are realized by a DataRetriever configured to use the
EODAG provider "CADIP".

### Configuration

This service uses several configurations elements :

-   the station to url mapping that defines the url of the cadip server
    for each station

-   the station handled by the instance

-   the eodag configuration used to interact with the cadip station =
    Frontend service

The frontend is a rs-service service. It only provides REST API
documentation. It contains : \* a /doc endpoint displaying the
aggregated openapi specification of all the rs-server services using
SwaggerUI \* a /openapi.json displaying the same openapi specification
on a json format

The openapi specification is provided by a json file. The location of
this file is configurable. It is given by an environment variable read
at the start of the service.

It contains no functional implementation of the rs-server services
endpoints. Nevertheless, the "Try it out" functionality from Swagger is
working since the rs-server is deployed with an ingres controller that
handles the redirection of the requests to the dedicated rs-server
service.

The content of the documentation is static. It is computed during the
frontend build procedure and then integrated statically in the frontend
service. Each time a service endpoint is updated, the frontend has to be
rebuilt also to provide an up-to-date documentation.

The openapi specification is built on the CI workflow that build the
frontend service executable. The procedure starts all the rs-server
services and retrieve the openapi specification of each service. Once
done, it creates an aggregated specification and store it in a file.
This file is then integrated in the docker image of the service.

The procedure uses a configuration file. this file describes all the
rs-server services that should be integrated in the aggregated openapi
specification. Each time a new service is added, its configuration has
to be added in this configuration file.
