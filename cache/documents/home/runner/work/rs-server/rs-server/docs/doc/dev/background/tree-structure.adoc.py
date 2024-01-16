# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.7931786
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/dev/background/tree-structure.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/dev/background/tree-structure.adoc'
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
        __M_writer('= Project tree structure\n\nThe rs-server repository tree structure is given in the following graph\n\n[plantuml, format=svg, opts="inline"]\n----\nskinparam Legend {\n\tBorderColor transparent\n}\n\nlegend\nrs-server\n|_ docs/\n|_ rs_server/\n|_ tests/\n|_ .gitignore\n|_ .pre-commit-config.yaml\n|_ CHANGELOG.adoc\n|_ LICENSE\n|_ poetry.lock\n|_ pyproject.toml\n|_ README.adoc\n\nend legend\n\n----\n\n* \'rs_server\' folder contains all the production code\n* \'tests\' folder contains all the unit and integration tests\n* \'docs\' folder contains all the technical documentation\n')
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/dev/background/tree-structure.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/dev/background/tree-structure.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "24": 1, "30": 24}}
__M_END_METADATA
"""
