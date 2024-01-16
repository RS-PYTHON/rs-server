# -*- coding:utf-8 -*-
from mako import runtime, filters, cache
UNDEFINED = runtime.UNDEFINED
STOP_RENDERING = runtime.STOP_RENDERING
__M_dict_builtin = dict
__M_locals_builtin = locals
_magic_number = 10
_modified_time = 1705399186.7955065
_enable_loop = True
_template_filename = '/home/runner/work/rs-server/rs-server/docs/doc/dev/background/ci.adoc'
_template_uri = '/home/runner/work/rs-server/rs-server/docs/doc/dev/background/ci.adoc'
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
        __M_writer('= CI/CD workflows\n\nThe CI/CD (Continuous Integration and Delivery) is implemented using GitHub Actions yaml scripts.\n\nImplemented workflows are:\n\n* Check code quality\n* Publish wheels and Docker images\n* Generate documentation\n\n== *Check code quality* workflow\n\nThis workflow is run either automatically after each `git push` command on each branch and pull request, or manually.\n\nIt runs the following jobs:\n\n* Check format (pre-commit, black, isort)\n    ** This job checks that you have run `pre-commit run --all-files` in your local git repository before committing. The `pre-commit` runs `black` and `isort` to auto-format your source code and facilitate reviewing differences and merging between git branches.\n\n* Check linting (pylint, flake8)\n    ** These linters analyse your code without actually running it. They check for errors, enforce a coding standard, look for code smells, and can make suggestions about how the code could be refactored.\n\n* Check typing (mypy)\n    ** Add type annotations to your Python programs, and use mypy to type check them.\n\n* Check security (bandit, safety, trivy)\n    ** Bandit is a tool designed to find common security issues in Python code.\n    ** Safety checks Python dependencies for known security vulnerabilities and suggests the proper remediations for vulnerabilities detected.\n    ** Trivy is a comprehensive and versatile security scanner that looks for security issues, and targets where it can find those issues. The scan results are updated into the GitHub Security tab: https://github.com/RS-PYTHON/rs-server/security/code-scanning\n\n* Run unit tests (pytest)\n* Run integration tests (pytest)\n    ** Test source code and determine if it is fit to use.\n    ** Unit tests are faster than integration tests and use mockup servers. Integration tests are run on the production infrastructure (to be confirmed).\n    ** They also calculate code coverage i.e. percentage measure of the degree to which the source code is executed when the tests are run. Only the unit tests coverage is shown in sonarqube.\n\n* Quality report (sonarqube)\n    ** SonarQube is a platform for continuous inspection of code quality to perform automatic reviews with static analysis of code to detect bugs and code smells. It offers reports on duplicated code, coding standards, unit tests, code coverage, code complexity, comments, bugs, and security recommendations.\n    ** It renders the reports from pylint, flake8, bandit and code coverage in a more graphical way.\n    ** Reports are displayed at: https://sonarqube.ops-csc.com/dashboard?branch=develop&id=RS-PYTHON_rs-server_AYw0m7ixvQv-JMsowILQ\n\n== *Publish wheels and Docker images* workflow\n\nThis workflow is run either automatically after adding a git tag to a commit, or manually. It:\n\n* Builds source code into Python wheel packages.\n    ** Upload them into the Python registry.\n    ** Make them available for manual download as GitHub Actions artifacts.\n\n* Builds the project Docker images (that use the Python wheel packages).\n    ** Scan them with Trivy for security issues and update results into the GitHub Security tab: https://github.com/RS-PYTHON/rs-server/security/code-scanning\n    ** Upload them into the ghcr.io GitHub package registry: https://github.com/orgs/RS-PYTHON/packages\n\nThe git tag name must conform to the following syntax examples:\n\n* `v2.0` is a version for a release with at least major updates.\n* `v2.1` is a version for a release without any major updates.\n* `v2.1rc1` is the version for the first 2.1 release-candidate.\n* `v1.0a3` is the version for sprint 3 features integration.\n* `v1.0a3+dev9afcfc1` is dev commit version during the sprint 3.\n\nThe `Poetry dynamic versioning` python plugin is then used to determine automatically the wheels and Docker images version name. Note that it is slighty different from the git tag name:\n\n* `v` is removed.\n* For Docker images, `+` is replaced by `.`\n\nSo we have e.g. the wheel filenames:\n\n* `rs_server-2.0-py3-none-any.whl`\n* `rs_server-2.1-py3-none-any.whl`\n* `rs_server-2.1rc1-py3-none-any.whl`\n* `rs_server-1.0a3-py3-none-any.whl`\n* `rs_server-1.0a3+dev9afcfc1-py3-none-any.whl`\n\nAnd the Docker images:\n\n* `ghcr.io/rs-python/rs-server:2.0`\n* `ghcr.io/rs-python/rs-server:2.1`\n* `ghcr.io/rs-python/rs-server:2.1rc1`\n* `ghcr.io/rs-python/rs-server:1.0a3`\n* `ghcr.io/rs-python/rs-server:1.0a3.dev9afcfc1`\n\nWhen running manually the workflow, the version name is determined automatically as:\n\n* `0.0.0.post1.dev0+<short-hash-commit>` for the wheels.\n* `0.0.0.post1.dev0.<short-hash-commit>` for the Docker images.\n\ne.g. `0.0.0.post1.dev0+216f7fa` and `0.0.0.post1.dev0.216f7fa`.\n\nBut running manually the workflow is discouraged, it is preferred to generate the wheels and Docker images by creating a new git tag (to be discussed).\n\n== *Generate documentation* workflow\n\nThis workflow is run either automatically after adding a git tag to a commit, or manually.\n\nIt builds the documentation using the command :\n[,console,indent=0]\n----\ninclude::../../../../.github/workflows/generate-documentation.yml[tag=adoc-cmd]\n----\n\nAnd then publishes the results to the GitHub Pages: https://rs-python.github.io/rs-server\n')
        return ''
    finally:
        context.caller_stack._pop_frame()


"""
__M_BEGIN_METADATA
{"filename": "/home/runner/work/rs-server/rs-server/docs/doc/dev/background/ci.adoc", "uri": "/home/runner/work/rs-server/rs-server/docs/doc/dev/background/ci.adoc", "source_encoding": "utf-8", "line_map": {"19": 0, "24": 1, "30": 24}}
__M_END_METADATA
"""
