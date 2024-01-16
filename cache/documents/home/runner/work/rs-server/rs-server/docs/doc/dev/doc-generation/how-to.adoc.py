# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.7872338
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/dev/doc-generation/how-to.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/dev/doc-generation/how-to.adoc'
_source_encoding = 'utf-8'
import sys
sys.path.insert(1, "/home/runner/work/rs-server/rs-server/docs/doc")
del sys
_exports = []


def render_body(context,**pageargs):
    __M_caller = context.caller_stack._push_frame()
    try:
        __M_locals = __M_dict_builtin(pageargs=pageargs)
        include = context.get('include', UNDEFINED)
        __M_writer = context.writer()
        __M_writer("= Generate rs-server technical documentation\n\nThis procedure is run automatically in the CI by the 'generate documentation' workflow.\nIt can be executed locally to verify the generated documentation (before publishing it for example).\n\nSee ")
        __M_writer(str(include("description.adoc")))
        __M_writer(" for more details on the process and technical stuff.\n\n. Pre-requises\n\nThe local developer environment has been setup.\nThe global python project is setup.\nThe python sub-project for doc generation is also setup.\n\n. Generate the technical documentation\n\nFrom the rs-server/docs folder, execute the command:\n[source, bash, indent=0]\n----\ninclude::../../../../.github/workflows/generate-documentation.yml[tag=asciidoxy-cmd]\n----\n\nThis command generates the html pages of all the technical documentation\nand write them in the rs-server/dist/doc folder.\n\n. Generate the python api documentation\n\nFrom the root folder, run the following command :\n[source, bash, indent=0]\n----\ninclude::../../../../.github/workflows/generate-documentation.yml[tag=sphinx-apidoc-cmd]\n----\nIt generates rst files from the python doc-strings\nand write them in a generated folder (excluded of git conf).\n\nThen, execute the following command :\n[source, bash, indent=0]\n----\ninclude::../../../../.github/workflows/generate-documentation.yml[tag=sphinx-build-cmd]\n----\nIt generates the html pages for the python api of the rs-server.\nThe generated api is accessible locally at 'dist/doc/api/html/index.html'.\n\n. Generate the REST API documentation\n\nFrom the root folder, run the following command :\n[source, bash, indent=0]\n----\ninclude::../../../../.github/workflows/generate-documentation.yml[tag=rest-api-root-cmd]\n----\n\nThe previous command copies the entry document of the REST API\nto the folder in which the documentation is generated.\nIt's important to keep it like that for integration with the technical documentation.\n\nFrom the root folder, run the following command :\n\n[source, bash, indent=0]\n----\ninclude::../../../../.github/workflows/generate-documentation.yml[tag=rest-openapi-cmd]\n----\n\nThe previous command uses FastAPI to extract the openapi specification of the rs-server CADIP service and write it on the expected folder.\nThe output folder is the one expected for integration with the main document of the rest api previously copied.\n\nNOTE: This is a POC waiting for the frontend to be implemented.\nThe documented REST API will be the one of the frontend at the end.\n\n. Verify the generated documentation\n\nThe main page of the technical documentation is accessible\nhttp://localhost:63342/rs-server/dist/doc/output/index.html[locally].\nYou can verify the generated documentation before publishing it.\n\nImportant elements to check :\n\n* the python api is accessible in the technical documentation\n* the python api is well formatted\n* the rest api is accessible in the technical documentation\n* the rest api is well formatted\n* ...\n")
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/dev/doc-generation/how-to.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/dev/doc-generation/how-to.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "25": 1, "26": 6, "27": 6, "33": 27}}
__M_END_METADATA
"""
