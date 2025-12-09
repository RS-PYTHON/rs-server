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
