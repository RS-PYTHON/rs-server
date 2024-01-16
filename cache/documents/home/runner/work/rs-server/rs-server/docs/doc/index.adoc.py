# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.778479
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/index.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/index.adoc'
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
        __M_writer("= RS server's technical documentation\n\n== User manual\n\nTODO TBD\n\n== Developer manual\n\nAll you want to know when you are a rs-server developer.\n\nThe documentation is organized in 4 sections :\n\n* Tutorials to help you start coding on rs-server :\n** ")
        __M_writer(str(include("dev/environment/installation.adoc")))
        __M_writer('\n\n* How to guides to provide practical common procedures\n** ')
        __M_writer(str(include("dev/doc-generation/how-to.adoc")))
        __M_writer('\n\n* Reference guides give you technical information about the code and software API :\n** ')
        __M_writer(str(include("dev/code-style.adoc")))
        __M_writer('\n** ')
        __M_writer(str(include("api/python/html/index.adoc")))
        __M_writer('\n** ')
        __M_writer(str(include("api/rest/index.adoc")))
        __M_writer('\n\nNOTE: TODO include a link to the python API\n\n* Additional information about the software, the team, the design,...\n\n** ')
        __M_writer(str(include("dev/background/tree-structure.adoc")))
        __M_writer('\n** ')
        __M_writer(str(include("dev/environment/description.adoc")))
        __M_writer('\n** ')
        __M_writer(str(include("dev/background/workflow.adoc")))
        __M_writer('\n** ')
        __M_writer(str(include("dev/background/ci.adoc")))
        __M_writer('\n** ')
        __M_writer(str(include("dev/design/design.adoc")))
        __M_writer('\n** ')
        __M_writer(str(include("dev/doc-generation/description.adoc")))
        __M_writer('\n')
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/index.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/index.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "25": 1, "26": 14, "27": 14, "28": 17, "29": 17, "30": 20, "31": 20, "32": 21, "33": 21, "34": 22, "35": 22, "36": 28, "37": 28, "38": 29, "39": 29, "40": 30, "41": 30, "42": 31, "43": 31, "44": 32, "45": 32, "46": 33, "47": 33, "53": 47}}
__M_END_METADATA
"""
