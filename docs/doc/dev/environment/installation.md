Prerequisites
=============

This tutorial assumes the developer has already basic knowledge and is
using a Ubuntu/macOS based computer. No specific IDE is recommended for the development process, user can extend
their environment with specific IDE integration.

Checkout the project
====================

The source code is hosted on GitHub. Personal Access Token (PAT) with specific rights on RS-Server repository should be configured before this process.

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

RS-Server is using Python 3.

Using `pyenv` (https://github.com/pyenv/pyenv) is recommended to manage Python versions. Pyenv offers a straightforward method to switch between various Python versions.

Follow instructions from https://github.com/pyenv/pyenv?tab=readme-ov-file#a-getting-pyenv to install pyenv, then:
```sh
# Install the python versions that are used in the project
pyenv install 3.11.7
pyenv install 3.13.9

# Go to the root folder of your rspy project, that contains all you local git repositories
# and use newest version in all this folder and subfolders
cd /path/to/parent/rspy
pyenv local 3.13.9
# Or if you prefer to use this version everywhere in your system, use: pyenv global 3.13.9
python -V # should display 3.13.9

# WARNING: in rs-dpr-service we still need the old version
cd rs-dpr-service
pyenv local 3.11.7
python -V # should display 3.11.7
```

Install Poetry
==============

The dependency management on RS-Server is done with
[Poetry](https://python-poetry.org/).

Is it recommended to use [pipx](https://github.com/pypa/pipx) to install Python tools. Pipx provides an isolated environment for any Python tool.

    cd $RSPY_ROOT/src
    pipx install poetry

Setup the project
=================

The project is managed by poetry, and should be initialized locally first.

    cd $RSPY_ROOT/src/rs-server
    poetry install --with dev
    poetry run opentelemetry-bootstrap -a install

This command initializes and activates a virtual environment for project.
It installs in this environment the project dependencies and
the develop dependencies (--with dev).

An IDE can provide poetry integration.

Verify your local environment
=============================

To verify if the local environment is correctly installed, all unittests should run normally using this command:

    cd $RSPY_ROOT/src/rs-server
    pytest tests -m "unit"

An IDE can provide integration to run unittests.

Install trivy
=============

[trivy](https://aquasecurity.github.io/trivy/latest/) is used to perform
security and license checks on the repository, the generated wheel
packages and the docker images.

trivy is run on the pre-commit and the CI to verify the repository
compliance with common vulnerabilities, secrets and licenses.

To install trivy on the local environment, follow [the official
procedure](https://aquasecurity.github.io/trivy/latest/getting-started/installation/).

Install pre-commit hooks
========================

pre-commit is used to check basic rules before each commit. Can be activated using:

    cd $RSPY_ROOT/src/rs-server
    poetry run pre-commit install

Once installed, checks will be performed before each commit to ensure
the code is compliant with project best practices :

-   assert no unresolved merge conflicts

-   fix end of file

-   fix trailing whitespace

-   check toml

-   run black formatter

-   run linters

-   run trivy repo checks

It is useful to configure an IDE to run [black](https://black.readthedocs.io/en/stable/) at each file saving so
that you keep your code compliant with the project coding style.

Additional IDE configuration
============================

We will not give specific IDE configurations. Nevertheless, it is
relevant to configure your IDE to run format and lint after each save to
keep your code compliant with the coding style at any moment.

The next steps
==============

The document titled [Development Technical Stack](description.md) provides additional details about the environment.
Additionally, the [Development Workflow](../background/workflow.md) document describes the workflow followed by developers to implement stories.
The [Code Style](../code-style.md) document may also be useful for review.
