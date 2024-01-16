# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.7968092
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/dev/design/design.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/dev/design/design.adoc'
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
        __M_writer('= Design & concepts\n\nThe rs-servcer is divided into two main elements :\n\n* the rs-server frontend\n* the rs-server backend\n\nThe rs-server frontend is a facade for users that verify the user privileges before accessing to the services provided by the rs-server backend.\n\n:leveloffset: +1\n\ninclude::uac/design.adoc[]\n\ninclude::services/design.adoc[]\n\n:leveloffset: -1\n')
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/dev/design/design.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/dev/design/design.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "24": 1, "30": 24}}
__M_END_METADATA
"""
