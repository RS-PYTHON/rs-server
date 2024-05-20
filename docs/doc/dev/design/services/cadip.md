The cadip service enables users to retrieve data from cadip stations.
Each instance of this service is started for a given station.

It provides 2 endpoints :

-   a search endpoint that enables to search files for a time period

-   a download endpoint that enables to download a file from its id and
    name

The processes are realized by a DataRetriever configured to use the
EODAG provider "CADIP".

Configuration
=============

This service uses several configurations elements :

-   the station to url mapping that defines the url of the cadip server
    for each station

-   the station handled by the instance

-   the eodag configuration used to interact with the cadip station
