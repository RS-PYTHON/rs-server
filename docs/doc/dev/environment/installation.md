Prerequisites
=============

This tutorial assumes the developer has already basic knowledge and is
using a ubuntu working station. This tutorial lets the user uses their
preferred IDE. You could extend your environment with specific IDE
integration.

Checkout the project
====================

The source code is hosted on github. You should configure your github
token access before.

-   Create a project folder that will contain all useful files

<!-- -->

    RSPY_ROOT=~/projects/rspy
    mkidr -P $RSPY_ROOT
    mkdir $RSPY_ROOT/src/
    cd $RSPY_ROOT

-   Checkout the project

<!-- -->

    cd $RSPY_ROOT/src
    git clone --branch develop git@github.com:RS-PYTHON/rs-server.git

Install Python
==============

rs-server is using python 3.11. You should install a compatible python
version on your working station.

It is recommended to use [pyenv](https://github.com/pyenv/pyenv) to
handle your python versions. Pyenv provides you an easy way to switch
between different python versions.

    cd $RSPY_ROOT/src
    pyenv install 3.11.3
    pyenv local 3.11.3

The python version is an example. You could use more recent versions.

These commands install python 3.11 on your workstation and enforces this
version for rs-server only.

Install Poetry
==============

The dependency management on rs-server is done with
[Poetry](https://python-poetry.org/).

Is it recommended to use [pipx](https://github.com/pypa/pipx) to install
your python tools. Pipx provides you with isolated environment for your
python tools.

    cd $RSPY_ROOT/src
    pipx install poetry

Setup the project
=================

The project is managed by poetry.

You should first initialize the project locally

    cd $RSPY_ROOT/src/rs-server
    poetry install --with dev
    poetry run opentelemetry-bootstrap -a install

This command initializes and activates a virtual environment for your
project. It installs in this environment the project dependencies and
the develop dependencies (--with dev).

Your IDE can provide poetry integration.

Verify your local environment
=============================

To verify your environment is correctly installed, you can run the
unittests and verify that they run nominally

    cd $RSPY_ROOT/src/rs-server
    pytest tests -m "unit"

Your IDE can provide integration to run your unittests.

Install trivy
=============

[trivy](https://aquasecurity.github.io/trivy/latest/) is used to perform
security and license checks on the repository, the generated wheel
packages and the docker images.

trivy is run on the pre-commit and the CI to verify the repository
compliance with common vulnerabilities, secrets and licenses.

To install trivy on your local environment, follow [the official
procedure](https://aquasecurity.github.io/trivy/latest/getting-started/installation/).

Install pre-commit hooks
========================

pre-commit is used to check basic rules before each commit. You should
activate them :

    cd $RSPY_ROOT/src/rs-server
    poetry run pre-commit install

Once installed, checks will be performed before each commit to ensure
your code is compliant with project best practices :

-   assert no unresolved merge conflicts

-   fix end of file

-   fix trailing whitespace

-   check toml

-   run black formatter

-   run linters

-   run trivy repo checks

It is useful to configure your IDE to run black at each file saving so
that you keep your code compliant with the project coding style.

Additional IDE configuration
============================

We will not give specific IDE configurations. Nevertheless, it is
relevant to configure your IDE to run format and lint after each save to
keep your code compliant with the coding style at any moment.

The next steps
==============

The ${cross\_document\_ref("description.adoc")} can provide you with
more details about the environment. The
${cross\_document\_ref("../background/workflow.adoc")} describes the
workflow followed by developers to implement stories. You may also want
to read the ${cross\_document\_ref("../code-style.adoc")}.