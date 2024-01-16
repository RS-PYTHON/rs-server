# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.7919786
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/api/rest/index.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/api/rest/index.adoc'
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
        __M_writer('= REST reference api\n\nThis is a fake documentation used by asciidoxy to generate a link to this url.\nIt is replaced by the real REST API during the documentation generation.\n\nIf you see this page, there is an error during documentation generation process.\nPlease contact the developer team.\n')
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/api/rest/index.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/api/rest/index.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "24": 1, "30": 24}}
__M_END_METADATA
"""
