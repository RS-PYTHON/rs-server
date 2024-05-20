This procedure is run automatically in the CI by the *generate
documentation* workflow. It can be executed locally to verify the
generated documentation (before publishing it for example).

See ${cross\_document\_ref("description.adoc")} for more details on the
process and technical stuff.

Prerequisites
=============

The local developer environment has been setup. The global python
project is setup. The python sub-project for doc generation is also
setup.

Generate the technical documentation
====================================

From the rs-server/docs folder, execute the command:

    poetry run asciidoxy --warnings-are-errors --base-dir doc --image-dir images --build-dir ../dist/doc/ --multipage doc/index.adoc

This command generates the html pages of all the technical documentation
and write them in the rs-server/dist/doc folder.

Generate the python api documentation
=====================================

From the root folder, run the following command :

    rm -rf docs/doc/api/python/generated/
    poetry run sphinx-apidoc -o docs/doc/api/python/generated/common services/common/rs_server_common/
    poetry run sphinx-apidoc -o docs/doc/api/python/generated/cadip services/cadip/rs_server_cadip/
    poetry run sphinx-apidoc -o docs/doc/api/python/generated/adgs services/adgs/rs_server_adgs/

It generates rst files from the python doc-strings and write them in a
generated folder (excluded of git conf).

Then, execute the following command :

    poetry run sphinx-build -M html docs/doc/api/python/ dist/doc/output/api/python/

It generates the html pages for the python api of the rs-server. The
generated api is accessible locally at *dist/doc/api/html/index.html*.

Generate the REST API documentation
===================================

From the root folder, run the following command :

    mkdir -p dist/doc/output/api/rest/
    cp docs/doc/api/rest/index.html dist/doc/output/api/rest/

The previous command copies the entry document of the REST API to the
folder in which the documentation is generated. It’s important to keep
it like that for integration with the technical documentation.

From the root folder, run the following command :

    poetry run python -m tests.openapi dist/doc/output/api/rest/

The previous command uses FastAPI to extract the openapi specification
of the rs-server CADIP service and write it on the expected folder. The
output folder is the one expected for integration with the main document
of the rest api previously copied.

This is a POC waiting for the frontend to be implemented. The documented
REST API will be the one of the frontend at the end.

Verify the generated documentation
==================================

The technical documentation is generated in the folder
"dist/doc/output/". The main page is the file "index.html" is this
folder. It can be open in a web browser for example.

The REST API can’t be opened like that since it needs to be served. You
can open the REST API locally starting the rs-server and connecting to
the /docs endpoint.

You can verify the generated documentation before publishing it.

Important elements to check :

-   the python api is accessible in the technical documentation

-   the python api is well formatted

-   the rest api is accessible in the technical documentation

-   the rest api is well formatted

-   …
