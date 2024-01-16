# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.7886152
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/dev/doc-generation/description.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/dev/doc-generation/description.adoc'
_source_encoding = 'utf-8'
import sys
sys.path.insert(1, "/home/runner/work/rs-server/rs-server/docs/doc")
del sys
_exports = []


def render_body(context,**pageargs):
    __M_caller = context.caller_stack._push_frame()
    try:
        __M_locals = __M_dict_builtin(pageargs=pageargs)
        __M_writer = context.writer()
        __M_writer("= Documentation generation process\n\n== Introduction\n\nThe rs-server technical documentation is mainly written using asciidoctor.\nNevertheless, the python api and the rest api are handled differently.\nThe python api is built using sphinx functionalities.\nThe rest api is built using fastapi functionalities.\n\nTherefore, the built procedure includes specific steps to handle these elements.\nThe technical documentation include links to open the python api and rest api reference guides.\n\n== Technical documentation with multiple pages\n\nlink:https://asciidoxy.org/index.html[asciidoxy] is used to generate a asciidoctor documentation with multiple pages and add links between pages.\nasciidoxy is not compatible with the other dev dependencies.\nTo use it, we added a python project dedicated to the generation of the technical documentation in the rs-server/docs folder.\n\n== Python api reference guide\n\nThe python api is generated using link:https://www.sphinx-doc.org/en/master/[sphinx] functionalities.\nIt enables us to generate a reference guide from python doc-strings.\n\nA link to this reference guide is added in the technical documentation.\nA fake asciidoc file is created with the same location as the generated python api.\nA link to this file is added in the asciidoc technical documentation.\nThe generation asciidoc documentation generates a link to this fake html file.\nThe generation of the python api replaces the html file with the true api reference guide.\n\nNOTE: It's important to do the python api generation after the technical documentation generation.\n\nNOTE: It's important to verify this link in the generated documentation.\n\n== Rest api reference guide\n\nThe REST API is provided by FastAPI on a dynamic way on the /docs endpoint,  using SwaggerUI functionalities.\nWe also want to provide it on a static way in the technical documentation.\nFastAPI enables us to export the openapi specification in a json format.\nUsing Swagger UI functionalities, we can generate a static REST API documentation.\n\nIt takes the form of an HTML index file using swagger for the rendering\nand the exported openapi file for the content.\n\nTo provide a link to this REST API from the technical documentation,\nthe same trick is used than the one used for the python API.\n")
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/dev/doc-generation/description.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/dev/doc-generation/description.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "24": 1, "30": 24}}
__M_END_METADATA
"""
