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

Development DoR (Definition of Ready)
=====================================

-   Development team understands what is expected

-   Test cases are writen and clear

-   Identify the specific integration tests if needed

-   Technical documentation to write is identified

-   User documentation to write is identified

Development DoD (Definition of Done)
====================================

-   Code written covers the functionality

-   New code is covered by unit tests

-   New code is covered by integration tests if any

-   New test cases have been automated

-   Documentation has been updated

-   Changelog has been updated

-   All unit tests are green

-   All integration tests are green

-   All acceptance tests are green

-   The best practices are followed

    -   The design is followed

    -   The CI checks have been run and are green

    -   The sonarqube errors have been fixed

-   A code review with a team member has been made

Code review
===========

The objectives of the code reviews are :

-   Double-check the DoD completion

-   Share knowledge accros development team

-   Human feedback on written tests, code and documentation
