These are the coding style followed on the rs-server project.

Pre-commit checks
=================

[pre-commit](https://pre-commit.com/) rules are configured to perform
basic checks before each commit. You can install it on your workstation
when [installing your environment](environment/installation.md). It is
recommended to verify your code follows the project coding rules.

Python style
============

By default, the [pep8](https://peps.python.org/pep-0008/) is followed.

All python files are formatted by
[black](https://black.readthedocs.io/en/stable/). It is run in the
pre-commit hooks and can be run after each file save. The line length is
extended to 120 but keep lines as small and readable as possible.

The lint is performed by pylint and flake8 in the CI workflow.

The doc-strings are written using the reStructuredText because the
python api is generated using Sphinx.

The following file header should be added at the start of each python
file.

```python
# Copyright 2024 CS Group
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
```

Unit test style
===============

The unittests are written with pytest.

We use marks to categorize tests. The following marks are defined
currently.

    import pytest

    @pytest.mark.integration
    def a_fixture_for_integration_only():
        return None

    @pytest.mark.unit
    def test_a_unit_test():
        assert False

    @pytest.mark.integration
    def test_an_integration_test(a_fixture_for_integration_only):
        assert False

Commit style
============

The commit messages are written using the [conventional
commit](https://www.conventionalcommits.org/en/v1.0.0/).

The messages try to follow the [following best
practices](https://cbea.ms/git-commit/).

Changelog
=========

The project changelog is produced following
[keepchangelog](https://keepachangelog.com/) practices. Please keep the
[changelog](../../../CHANGELOG.md) up-to-date after each modification.

Documentation
=============

The documentation is written in
[mkdocs](https://www.mkdocs.org/)
following the [documentation system](https://documentation.divio.com/).
