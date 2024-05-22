[![Quality Gate Status](https://sonarqube.ops-csc.com/api/project_badges/measure?branch=develop&project=RS-PYTHON_rs-server_AYw0m7ixvQv-JMsowILQ&metric=alert_status&token=sqb_c9241ef82ea91a8e9a9b604570f834f622dfed05)](https://sonarqube.ops-csc.com/dashboard?id=RS-PYTHON_rs-server_AYw0m7ixvQv-JMsowILQ&branch=develop)

---

Quick links
===========

-   Deployed services: <https://dev-rspy.esa-copernicus.eu/docs>

-   Online documentation: <https://rs-python.github.io/rs-documentation/rs-server/docs/doc/>

-   SonarQube reports:
    <https://sonarqube.ops-csc.com/dashboard?id=RS-PYTHON_rs-server_AYw0m7ixvQv-JMsowILQ&branch=develop>

Overview
========

RS server is a toolbox that allows users to retrieve external data used
by Copernicus processing chains, store them in internal S3 buckets and
catalog them.

Its goal is to be used by the Copernicus processing chains to perform
their works.

The toolbox exposes REST endpoints enabling users to :

-   search for external data

-   download external data into a S3 bucket

-   catalog data

-   search for data in the catalog

All these functionalities are reserve to authorized users only. The
permissions are technical and/or functional.

Installing the rs-server
========================

TODO explain how to install the rs-server locally or with a cluster.

Using the rs-server
===================

TODO explain how to use the rs-server

Developing the rs-server
========================

Look at the [technical
documentation](https://rs-python.github.io/rs-server/). It contains all
the technical details to develop on the rs-server.

Links
=====

-   Project homepage: <https://github.com/RS-PYTHON/rs-server>

-   Repository: <https://github.com/RS-PYTHON/rs-server>

-   Issue tracker: <https://github.com/RS-PYTHON/rs-server/issues> In case of sensitive bugs like security vulnerabilities, please contact <my@email.com> directly instead of using issue tracker. We value your effort to improve the security and privacy of this project!

Licensing
=========

The code in this project is licensed under Apache License 2.0.

---

![](/docs/images/banner_logo.jpg)

This project is funded by the EU and ESA.
