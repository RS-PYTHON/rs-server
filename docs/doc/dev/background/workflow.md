Git
===

The project is using the
[gitflow](https://git-flow.readthedocs.io/en/latest/presentation.html).

The feature branches are named following the pattern
"feat-&lt;jira-id&gt;/&lt;short-description&gt;" For example :
"feat-rspy31/init-tech-doc"

Sometimes, a branch can implement multiple stories. For example :
"feat-rspy36-37/read-write-storage"

JIRA tickets
============

The backlog is handled on a private JIRA instance.

The ticket is initially in the TODO state. When the implementation
starts, the state becomes "IN PROGRESS" and the ticket is assigned to
the responsible developer. When the implementation is completed, the
state becomes "IMPLEMENTED".

development DoR
===============

-   development team understands what is expected

-   test cases are writen and clear

-   identify the specific integration tests if needed

-   technical documentation to write is identified

-   user documentation to write is identified

development DoD
===============

-   code written covers the functionality

-   new code is covered by unit tests

-   new code is covered by integration tests if any

-   new test cases have been automated

-   documentation has been updated

-   changelog has been updated

-   all unit tests are green

-   all integration tests are green

-   all acceptance tests are green

-   the best practices are followed

    -   the design is followed

    -   the CI checks have been run and are green

    -   the sonarqube errors have been fixed

-   a code review with a team member has been made

Code review
===========

The objectives of the code reviews are :

-   double-check the DoD completion

-   share knowledge accros development team

-   human feedback on written tests, code and documentation