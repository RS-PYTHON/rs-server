The CI/CD (Continuous Integration and Delivery) is implemented using
GitHub Actions yaml scripts.

Implemented workflows are:

-   Check code quality

-   Publish wheels and Docker images

-   Generate documentation

**Check code quality** workflow
===============================

This workflow is run either automatically after each `git push` command
on each branch and pull request, or manually.

It runs the following jobs:

-   Check format (pre-commit, black, isort)

    -   This job checks that you have run `pre-commit run --all-files`
        in your local git repository before committing. The `pre-commit`
        runs `black` and `isort` to auto-format your source code and
        facilitate reviewing differences and merging between git
        branches.

-   Check linting (pylint, flake8)

    -   These linters analyse your code without actually running it.
        They check for errors, enforce a coding standard, look for code
        smells, and can make suggestions about how the code could be
        refactored.

-   Check typing (mypy)

    -   Add type annotations to your Python programs, and use mypy to
        type check them.

-   Check security (bandit, safety, trivy)

    -   Bandit is a tool designed to find common security issues in
        Python code.

    -   Safety checks Python dependencies for known security
        vulnerabilities and suggests the proper remediations for
        vulnerabilities detected.

    -   Trivy is a comprehensive and versatile security scanner that
        looks for security issues, and targets where it can find those
        issues. The scan results are updated into the GitHub Security
        tab:
        <https://github.com/RS-PYTHON/rs-server/security/code-scanning>

-   Run unit tests (pytest)

-   Run integration tests (pytest)

    -   Test source code and determine if it is fit to use.

    -   Unit tests are faster than integration tests and use mockup
        servers. Integration tests are run on the production
        infrastructure (to be confirmed).

    -   They also calculate code coverage i.e. percentage measure of the
        degree to which the source code is executed when the tests are
        run. Only the unit tests coverage is shown in sonarqube.

-   Quality report (sonarqube)

    -   SonarQube is a platform for continuous inspection of code
        quality to perform automatic reviews with static analysis of
        code to detect bugs and code smells. It offers reports on
        duplicated code, coding standards, unit tests, code coverage,
        code complexity, comments, bugs, and security recommendations.

    -   It renders the reports from pylint, flake8, bandit and code
        coverage in a more graphical way.

    -   Reports are displayed at:
        <https://sonarqube.ops-csc.com/dashboard?branch=develop&id=RS-PYTHON_rs-server_AYw0m7ixvQv-JMsowILQ>

**Publish wheels and Docker images** workflow
=============================================

This workflow is run either automatically after adding a git tag to a
commit, or manually. It:

-   Builds source code into Python wheel packages.

    -   Upload them into the Python registry.

    -   Make them available for manual download as GitHub Actions
        artifacts.

-   Builds the project Docker images (that use the Python wheel
    packages).

    -   Scan them with Trivy for security issues and update results into
        the GitHub Security tab:
        <https://github.com/RS-PYTHON/rs-server/security/code-scanning>

    -   Upload them into the ghcr.io GitHub package registry:
        <https://github.com/orgs/RS-PYTHON/packages>

The git tag name must conform to the following syntax examples:

-   `v0.2` is a version for a release with at least major updates.

-   `v0.2.1` is a version for a release without any major updates.

-   `v0.1rc1` is the version for the first 0.1 release-candidate.

-   `v0.1a3` is the version for sprint 3 features integration.

-   `v0.1a3+dev9afcfc1` is dev commit version during the sprint 3.

The `Poetry dynamic versioning` python plugin is then used to determine
automatically the wheels and Docker images version name. Note that it is
slighty different from the git tag name:

-   `v` is removed.

-   For Docker images, `+` is replaced by `.`

So we have e.g. the wheel filenames:

-   `rs_server-0.2-py3-none-any.whl`

-   `rs_server-0.2.1-py3-none-any.whl`

-   `rs_server-0.2.1rc1-py3-none-any.whl`

-   `rs_server-0.1a3-py3-none-any.whl`

-   `rs_server-0.1a3+dev9afcfc1-py3-none-any.whl`

And the Docker images:

-   `ghcr.io/rs-python/rs-server:0.2`

-   `ghcr.io/rs-python/rs-server:0.2.1`

-   `ghcr.io/rs-python/rs-server:0.2.1rc1`

-   `ghcr.io/rs-python/rs-server:0.1a3`

-   `ghcr.io/rs-python/rs-server:0.1a3.dev9afcfc1`

When running manually the workflow, the version name is determined
automatically as:

-   `0.0.0.post1.dev0+<short-hash-commit>` for the wheels.

-   `0.0.0.post1.dev0.<short-hash-commit>` for the Docker images.

e.g. `0.0.0.post1.dev0+216f7fa` and `0.0.0.post1.dev0.216f7fa`.

But running manually the workflow is discouraged, it is preferred to
generate the wheels and Docker images by creating a new git tag (to be
discussed).

Generate documentation workflow
===============================

This workflow is run either automatically after adding a git tag to a
commit, or manually.

It builds the documentation following the how-to procedure to generate
the documentation.

Then, the result is published as the [GitHub Pages of the
rs-server](https://rs-python.github.io/rs-server).
