
# What are the .yml templates in rs-client staging wrappers used for ?

<p>
In order to validate the  format of the inputs and outputs of the different endpoint wrappers contained in
the StagingClient class, we used OGC standards: the OGC process documentation (https://ogcapi.ogc.org/processes) precisely describes what should be the formats of these endpoints inputs and outputs thanks to yaml schemas.

All yaml schemas have been downloaded from this link:
https://github.com/opengeospatial/ogcapi-processes/tree/1.0-draft.6.metanorma/core/openapi/schemas

You can also find some examples of valid data samples to provide for each endpoint in this link:
https://developer.ogc.org/api/processes/index.html#tag/Capabilities/operation/getLandingPage


# staging_body.json

This json file is the base structure to create the body of the staging /execute endpoint.
