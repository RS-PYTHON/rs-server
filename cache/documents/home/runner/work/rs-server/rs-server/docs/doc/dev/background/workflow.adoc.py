# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.7841232
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/dev/background/workflow.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/dev/background/workflow.adoc'
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
        __M_writer('= Team workflow\n\n== Git\n\nThe project is using the https://git-flow.readthedocs.io/fr/latest/presentation.html[gitflow].\n\nThe feature branches are named following the pattern "feat-<jira-id>/<short-description>"\nFor example : "feat-rspy31/init-tech-doc"\n\nSometimes, a branch can implement multiple stories.\nFor example : "feat-rspy36-37/read-write-storage"\n\n== JIRA tickets\n\nThe backlog is handled on a private JIRA instance.\n\nThe ticket is initially in the TODO state.\nWhen the implementation starts, the state becomes "IN PROGRESS"\nand the ticket is assigned to the responsible developer.\nWhen the implementation is completed, the state becomes "IMPLEMENTED".\n\n== development DoR\n\n* development team understands what is expected\n* test cases are writen and clear\n* identify the specific integration tests if needed\n* technical documentation to write is identified\n* user documentation to write is identified\n\n== development DoD\n\n* code written covers the functionality\n* new code is covered by unit tests\n* new code is covered by integration tests if any\n* new test cases have been automated\n* documentation has been updated\n* changelog has been updated\n* all unit tests are green\n* all integration tests are green\n* all acceptance tests are green\n* the best practices are followed\n** the design is followed\n** the CI checks have been run and are green\n** the sonarqube errors have been fixed\n* a code review with a team member has been made\n\n== Code review\n\nThe objectives of the code reviews are :\n\n* double-check the DoD completion\n* share knowledge accros development team\n* human feedback on written tests, code and documentation\n')
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/dev/background/workflow.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/dev/background/workflow.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "24": 1, "30": 24}}
__M_END_METADATA
"""
