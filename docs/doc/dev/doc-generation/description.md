Introduction
============

The rs-server technical documentation is mainly written using
asciidoctor. Nevertheless, the python api and the rest api are handled
differently. The python api is built using sphinx functionalities. The
rest api is built using fastapi functionalities.

Therefore, the built procedure includes specific steps to handle these
elements. The technical documentation include links to open the python
api and rest api reference guides.

Technical documentation with multiple pages
===========================================

[asciidoxy](https://asciidoxy.org/index.html) is used to generate a
asciidoctor documentation with multiple pages and add links between
pages. asciidoxy is not compatible with the other dev dependencies. To
use it, a python sub-project dedicated to the generation of the
technical documentation has been added in the rs-server/docs folder.

Python api reference guide
==========================

The python api is generated using
[sphinx](https://www.sphinx-doc.org/en/master/) functionalities. It
enables us to generate a reference guide from python doc-strings.

A link to this reference guide is added in the technical documentation.
A fake asciidoc file is created with the same location as the generated
python api. A link to this file is added in the asciidoc technical
documentation. The generation asciidoc documentation generates a link to
this fake html file. The generation of the python api replaces the html
file with the true api reference guide.

It’s important to do the python api generation after the technical
documentation generation.

It’s important to verify this link in the generated documentation.

Rest api reference guide
========================

The REST API is provided by FastAPI on a dynamic way on the /docs
endpoint, using SwaggerUI functionalities. The technical documentation
should also be provided statically in the technical documentation.
FastAPI enables us to export the openapi specification in a json format.
Using Swagger UI functionalities, we can generate a static REST API
documentation.

It takes the form of an HTML index file using swagger for the rendering
and the exported openapi file for the content.

To provide a link to this REST API from the technical documentation, the
same trick is used than the one used for the python API.