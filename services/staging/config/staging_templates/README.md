
# What are the .yml templates in rs-client staging wrappers used for ?

<p>
In order to validate the  format of the inputs and outputs of the different endpoints of the staging, we used OGC standards: the OGC process documentation (https://ogcapi.ogc.org/processes) precisely describes what should be the input and output formats of these endpoints thanks to yaml schemas.

All yaml schemas have been downloaded from this link:
https://github.com/opengeospatial/ogcapi-processes/tree/1.0-draft.6.metanorma/core/openapi/schemas

You can also find some examples of valid data samples to provide for each endpoint in this link:
https://developer.ogc.org/api/processes/index.html#tag/Capabilities/operation/getLandingPage


# CAUTION

Yaml schemas can be updated regularly: check the repo (https://github.com/opengeospatial/ogcapi-processes) regularly to see if new versions of these templates have been released.
