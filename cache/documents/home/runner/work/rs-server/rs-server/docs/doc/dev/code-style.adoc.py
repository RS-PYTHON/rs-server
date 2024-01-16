# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.7855282
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/dev/code-style.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/dev/code-style.adoc'
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
        __M_writer('= Coding style\n\nThese are the coding style followed on the rs-server project.\n\n== Pre-commit checks\n\nhttps://pre-commit.com/[pre-commit] rules are configured to perform basic checks before each commit.\nYou can install it on your workstation when link:environment/installation.adoc[installing your environment].\nIt is recommended to verify your code follows the project coding rules.\n\n== Python style\n\nBy default, the https://peps.python.org/pep-0008/[pep8] is followed.\n\nAll python files are formatted by https://black.readthedocs.io/en/stable/[black].\nIt is run in the pre-commit hooks and can be run after each file save.\nThe line length is extended to 120\nbut keep lines as small and readable as possible.\n\nThe lint is performed by pylint and flake8 in the CI workflow.\n\nThe doc-strings are written using the reStructuredText\nbecause the python api is generated using Sphinx.\n\nThe following file header should be added at the start of each python file.\n[source, python]\n----\nTODO\n----\n\n== Unit test style\n\nThe unittests are written with pytest.\n\nWe use marks to categorize tests.\nThe following marks are defined currently.\n[source, python]\n----\nimport pytest\n\n@pytest.mark.integration\ndef a_fixture_for_integration_only():\n    return None\n\n@pytest.mark.unit\ndef test_a_unit_test():\n    assert False\n\n@pytest.mark.integration\ndef test_an_integration_test(a_fixture_for_integration_only):\n    assert False\n----\n\n== Commit style\n\nThe commit messages are written using the https://www.conventionalcommits.org/en/v1.0.0/[conventional commit].\n\nThe messages try to follow the https://cbea.ms/git-commit/[following best practices].\n\n\n== Changelog\n\nThe project changelog is produced following https://keepachangelog.com/[keepchangelog] practices.\nPlease keep the link:../../CHANGELOG.adoc[changelog] up-to-date after each modification.\n\n== Documentation\n\nThe documentation is written in https://asciidoctor.org/docs/asciidoc-writers-guide/[asciidoctor] following the https://documentation.divio.com/[documentation system].\n')
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/dev/code-style.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/dev/code-style.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "24": 1, "30": 24}}
__M_END_METADATA
"""
