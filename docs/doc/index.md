# RS-Server

The Reference System server provides a set of services necessary to build Copernicus processing workflows. All services are subject to access control.

RS-Server offers a catalog of Sentinel products compatible with the STAC (SpatioTemporal Asset Catalog) standard, as well as functions to access data from AUXIP and CADIP stations.

## Features

To achieve this, RS-Server exposes REST endpoints that allow users to:
* Search CADU chunks from CADIP stations
* Stage CADU chunks from CADIP stations
* Search auxilliary data from AUXIP station
* Stage auxilliary data from AUXIP station
* ALL endpoints from [SpatioTemporal Asset Catalog API](https://stacspec.org/) 

Please note that the STAC catalog will also embedds STAC extension to support Sentinel product format from [EOPF-CPM](https://cpm.pages.eopf.copernicus.eu/eopf-cpm/main/index.html).


All these functionalities are available exclusively to authorized users. Permissions can be both technical and
functional.

## User Manual

Access the [User Manual](user_manual.md) for detailed instructions and guidance.

## Developer Manual

Access the [Developer Manual](developer_manual.md) for technical documentation and developer guidelines.






 

