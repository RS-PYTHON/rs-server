# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.78258
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/dev/environment/description.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/dev/environment/description.adoc'
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
        __M_writer('= Development environment description\n\nThe following table describes the development technical stack\nand explains briefly the choices that have been made.\n\n[cols=3,options=header]\n|===\n|Need\n|Chosen techno\n|Rational elements\n\n|language\n|python\n|the language commonly used by the final users\n\n|language version\n|python 3.11\n|python 3.12 is too recent to be chosen\n\n|dependency management\n|poetry\n|easy to use, good dependency management\n\n|code formatting\n|black\n|the current standard\n\n|unittests\n|pytest\n|standard\n\n|lint\n|pylint, flake8\n|standard\n\n|type check\n|mypy\n|commonly used by the team\n\n|quality check\n|sonarqube\n|commonly used by the team\n\n|commit check\n|pre-commit\n|commonly used by the team\n\n|security check\n|trivi\n|used in the previous phase\n\n|technical documentation\n|asciidoctor\n|good standard, simple syntax, good feedback from a team member\n\n|===\n')
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/dev/environment/description.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/dev/environment/description.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "24": 1, "30": 24}}
__M_END_METADATA
"""
