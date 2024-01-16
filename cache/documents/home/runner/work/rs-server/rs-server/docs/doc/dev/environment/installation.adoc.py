# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.7811806
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/dev/environment/installation.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/dev/environment/installation.adoc'
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
        __M_writer('= Install your environment\n\n== Pre requises\n\nThis tutorial assumes the developer has already basic knowledge\nand is using a ubuntu working station.\nThis tutorial lets the user uses its preferred IDE.\nYou could extend your environment with specific IDE integration.\n\n== Checkout the project\n\nThe source code is hosted on github.\nYou should configure your github token access before.\n\n* Create a project folder that will contain all useful files\n\n[source, bash]\n----\nRSPY_ROOT=~/projects/rspy\nmkidr -P $RSPY_ROOT\nmkdir $RSPY_ROOT/src/\ncd $RSPY_ROOT\n----\n\n* Checkout the project\n\n[source, bash]\n----\ncd $RSPY_ROOT/src\ngit clone --branch develop git@github.com:RS-PYTHON/rs-server.git\n----\n\n== Install Python\n\nrs-server is using python 3.11.\nYou should install a compatible python version on your working station.\n\nIt is recommended to use https://github.com/pyenv/pyenv[pyenv] to handle your python versions.\nPyenv provides you an easy way to switch between different python versions.\n\n[source, bash]\n----\ncd $RSPY_ROOT/src\npyenv install 3.11.3\npyenv local 3.11.3\n----\n\nNOTE: The python version is an example. You could use more recent versions.\n\nThese commands install python 3.11 on your workstation and enforces this version for rs-server only.\n\n== Install Poetry\n\nThe dependency management on rs-server is done with https://python-poetry.org/[Poetry].\n\nIs it recommended to use https://github.com/pypa/pipx[pipx] to install your python tools.\nPipx provides you with isolated environment for your python tools.\n\n[source, bash]\n----\ncd $RSPY_ROOT/src\npipx install poetry\n----\n\n== Setup the project\n\nThe project is managed by poetry.\n\nYou should first initialize the project locally\n[source, bash]\n----\ncd $RSPY_ROOT/src/rs-server\npoetry install --with dev\n----\nThis command initialize and activate a virtual environment for your project.\nIt installs in this environment the project dependencies\nand the develop dependencies (--with dev).\n\nNOTE: Your IDE can provide poetry integration.\n\n== Verify your local environment\n\nTo verify your environment is correctly installed,\nyou can run the unittests and verify that they run nominally\n\n[source, bash]\n----\ncd $RSPY_ROOT/src/rs-server\npytest tests -m "unit"\n----\n\n// TODO give the extract of the expected result\n\nNOTE: Your IDE can provide integration to run your unittests.\n\n== Install trivi\n\nlink:https://aquasecurity.github.io/trivy/v0.47/[trivy] is used to do some security and license checks on the repository, the generated wheel packages and the docker images.\n\ntrivi is run on the pre-commit and the CI\nto verify the repository compliance with common vulnerabilities, secrets and licenses.\n\nTo install trivy on your local environment,\nfollow link:https://aquasecurity.github.io/trivy/v0.47/getting-started/installation/[the official procedure].\n\n== Install pre-commit hooks\n\npre-commit is used to check basic rules before each commit.\nYou should activate them :\n\n[source, bash]\n----\ncd $RSPY_ROOT/src/rs-server\npoetry run pre-commit install\n----\n\nOnce installed, checks will be performed before each commit\nto ensure your code is compliant with project best practice :\n* assert no unresolved merge conflicts\n* fix end of file\n* fix trailing whitespace\n* check toml\n* run black formatter\n* run linters\n* run trivy repo checks\n\nNOTE: It is useful to configure your IDE to run black at each file saving\nso that you keep your code compliant with the project coding style.\n\n== Additional IDE configuration\n\nWe will not give specific IDE configurations.\nNevertheless, it is relevant to configure your IDE\nto run format and lint after each save\nto keep your code compliant with the coding style at any moment.\n\n\n== The next steps\n\nThe ')
        __M_writer(str(include("description.adoc")))
        __M_writer(' can provide you with more details about the environment.\nThe ')
        __M_writer(str(include("../background/workflow.adoc")))
        __M_writer(' describes the workflow followed by developers to implement stories.\nYou may also want to read the ')
        __M_writer(str(include("../code-style.adoc")))
        __M_writer('.\n')
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/dev/environment/installation.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/dev/environment/installation.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "25": 1, "26": 140, "27": 140, "28": 141, "29": 141, "30": 142, "31": 142, "37": 31}}
__M_END_METADATA
"""
