# STAC mapping of external data

The external data sources (CADIP, AUXIP, PRIP) expose their data with the [OData](https://www.odata.org/) protocol.
rs-server maps these data as [STAC](https://stacspec.org/) items, so that the users only deal with STAC. This page
describes the mapping applied to each data source. The mapping is configured in the `*_stac_mapper.json` files of
the services:

| Data source | Mapping files |
|---|---|
| CADIP sessions | [cadip_sessions_stac_mapper.json](https://github.com/RS-PYTHON/rs-server/blob/develop/services/cadip/config/cadip_sessions_stac_mapper.json) |
| CADIP files | [cadip_stac_mapper.json](https://github.com/RS-PYTHON/rs-server/blob/develop/services/cadip/config/cadip_stac_mapper.json) |
| AUXIP products | [adgs_stac_mapper.json](https://github.com/RS-PYTHON/rs-server/blob/develop/services/adgs/config/adgs_stac_mapper.json) |
| PRIP products | [prip_stac_mapper.json](https://github.com/RS-PYTHON/rs-server/blob/develop/services/prip/config/prip_stac_mapper.json), [product_type_mapping.yaml](https://github.com/RS-PYTHON/rs-server/blob/develop/services/common/config/product_type_mapping.yaml) |

The STAC properties come from the [STAC common metadata](https://github.com/radiantearth/stac-spec/blob/master/commons/common-metadata.md)
and from the STAC extensions described in [Catalog data model and lifecycle](data-model.md#extensions).

## CADIP

CADIP sessions are mapped as STAC items, CADIP files as STAC assets of the session items.

### Sessions

| CADIP session property | STAC item property | Description |
|---|---|---|
| `SessionId` | `id` | Session identifier, e.g. `S1A_20170501121534062343`: 3 characters for the satellite, the acquisition start date and time, and the acquisition orbit. |
| `DownlinkStart` | `start_datetime` | Acquisition time of the first CADU of the session. |
| `PublicationDate` | `datetime`, `published` | Publication date of the session (time at which the first file becomes visible to the user). |
| `DownlinkStop` | `end_datetime` | Acquisition time of the last CADU of the session. |
| `Satellite` | `platform`, `constellation` | Satellite identifier, e.g. `S1A` is mapped to `sentinel-1a` and `sentinel-1`. |
| `NumChannels` | `cadip:num_channels` | Number of channels of the session (1 to 4). |
| `StationId` | `sat:acquisition_station` | Acquisition station. |
| `DownlinkOrbit` | `sat:absolute_orbit` | Absolute downlink orbit number of the acquired pass. |
| `AcquisitionId` | `cadip:acquisition_id` | Acquisition identifier from the acquisition plan. |
| `AntennaId` | `cadip:antenna_id` | Identifier of the antenna used. |
| `FrontEndId` | `cadip:front_end_id` | Identifier of the front-end processor (demodulator) used. |
| `Retransfer` | `cadip:retransfer` | Whether the session is a retransfer. |
| `AntennaStatusOK` | `cadip:antenna_status_ok` | Quality of the acquisition at antenna level. |
| `FrontEndStatusOK` | `cadip:front_end_status_ok` | Quality of the acquisition at front-end processor level. |
| `PlannedDataStart`, `PlannedDataStop` | `cadip:planned_data_start`, `cadip:planned_data_stop` | Planned start and stop of the downlink. |
| `DownlinkStatusOK` | `cadip:downlink_status_ok` | Overall status of the downlink: `false` warns about a potential data loss or corruption. |
| `DeliveryPushOK` | `cadip:delivery_push_ok` | Status of the transfer of the files from the station to the delivery point. |

### Files

| CADIP file property | STAC asset property | Description |
|---|---|---|
| `Name` | asset key | File name, e.g. `DCS_01_S1A_20170501121534062343_ch1_DSDB_00001.raw`. |
| `Channel` | `cadip:channel` | Channel of the file (1 to 4). |
| `BlockNumber` | `cadip:block_number` | Number of the file in its channel, starting from 1. |
| `FinalBlock` | `cadip:final_block` | Whether this is the last file of the session. |
| `Retransfer` | `cadip:retransfer` | Whether the file is part of a retransfer. |
| `PublicationDate` | `created` | Publication date of the file. |
| `EvictionDate` | `eviction_datetime` | Date when the file will be removed from the rolling archive of the station. |
| `Size` | `file:size` | File size in bytes. |

## AUXIP

AUXIP products are mapped as STAC items, the product file as their asset.

| AUXIP product property | STAC property | Description |
|---|---|---|
| `Name` | item `id` (without extension), asset key | File name, e.g. `S2__OPER_AUX_ECMWFD_PDMC_20190216T120000_V20190217T090000_20190217T210000.TGZ`. |
| `ContentDate/Start`, `ContentDate/End` | `start_datetime`, `datetime`, `end_datetime` | Validity period of the auxiliary data. |
| `PublicationDate` | `published` | Publication date of the file. |
| `EvictionDate` | `eviction_datetime` | Date when the file will be removed from the rolling archive. |
| `ContentType` | asset `type` | Media type of the file. |
| `ContentLength` | asset `file:size` | File size in bytes. |
| `Checksum` (MD5) | asset `file:checksum` | Checksum of the file. |
| `Attributes/productType` | `product:type` | Product type, e.g. `AUX_PP1`. |
| `Attributes/processingDate` | `processing:datetime` | Processing date. |
| `Attributes/processingCenter` | `processing:facility` | Processing centre. |
| `Attributes/platformShortName`, `Attributes/platformSerialIdentifier` | `constellation`, `platform` | e.g. `SENTINEL-1` and `A` are mapped to `sentinel-1` and `sentinel-1a`. |

## PRIP

PRIP products are mapped as STAC items, the product file as their asset.

| PRIP product property | STAC property | Description |
|---|---|---|
| `Name` | item `id` (without extension), asset key | Product file name, e.g. `S1A_IW_SLC__1SDV_20160117T103451_20160117T103518_009533_00DD94_D46A.zip`. |
| `ContentDate/Start`, `ContentDate/End` | `start_datetime`, `datetime`, `end_datetime` | Sensing period. |
| `GeoFootprint` | `geometry`, `bbox` | Footprint of the product. |
| `PublicationDate` | `published` | Publication date of the product. |
| `OriginDate` | `eopf:origin_datetime` | Date when the raw data used to generate the product became available at the acquisition interface point. |
| `EvictionDate` | `expires`, asset `eviction_datetime` | Date when the product will be removed from the rolling archive. |
| `ContentType`, `ContentLength`, `Checksum` | asset `type`, `file:size`, `file:checksum` | File information. |
| `ProductionType` | `processing:lineage` | `systematic_production`, `on-demand default` or `on-demand non-default`. |
| `Attributes/productType` | `product:type`, `processing:level`, `sar:instrument_mode`... | Legacy product type, converted into the EOPF product type and its components with the product type mapping, e.g. `IW_SLC__1S` gives `S01SIWSLC`, level `L1` and instrument mode `IW`. |
| `Attributes/processingDate` | `created`, `processing:datetime` | Processing date. |
| `Attributes/processingCenter` | `processing:facility` | Processing centre. |
| `Attributes/processorVersion` | `processing:version` | Version of the processor that generated the product. |
| `Attributes/platformShortName`, `Attributes/platformSerialIdentifier` | `constellation`, `platform` | Satellite. |
| `Attributes/instrumentShortName` | `instruments` | e.g. `SAR` is mapped to `c-sar`. |
| `Attributes/orbitNumber`, `Attributes/relativeOrbitNumber` | `sat:absolute_orbit`, `sat:relative_orbit` | Orbit numbers. |
| `Attributes/cycleNumber` | `sat:orbit_cycle` | Repeat cycle number. |
| `Attributes/orbitDirection` | `sat:orbit_state` | `ascending` or `descending`. |
| `Attributes/polarisationChannels` | `sar:polarizations` | e.g. `HH+HV` is mapped to `["HH", "HV"]`. |
| `Attributes/datatakeID` | `eopf:datatake_id` | Datatake identifier. |
| `Attributes/instrumentConfigurationID` | `eopf:instrument_configuration_id` | Sentinel-1 instrument configuration identifier. |

## OData support of the stations

rs-server translates the STAC and [CQL2](https://docs.ogc.org/is/21-065r2/21-065r2.html) filters into OData
[filter expressions](https://docs.oasis-open.org/odata/odata/v4.01/odata-v4.01-part1-protocol.html#sec_BuiltinFilterOperations).
All the stations do not support all the OData operators and functions: to stay compatible with all of them, only
use in your filters the properties listed by the `queryables` endpoints, and the operators required by the ESA
interface specifications:

| Operator or function | Required by the ESA specifications | Example of OData filter |
|---|---|---|
| `eq` | Yes | `Satellite eq 'S1A'` |
| `gt`, `lt` | Yes | `PublicationDate gt 2026-02-01T00:00:00.000Z` |
| `in` | Yes | `Satellite in ('S1A','S1C')` |
| `and`, `or` | Yes | `Satellite eq 'S1A' or Satellite eq 'S1C'` |
| `not` | Yes | `not (Satellite eq 'S1A')` (with a space after `not`) |
| `contains`, `startswith`, `endswith` | Yes | `startswith(SessionId,'S1A')` |
| `ne`, `ge`, `le`, `()` | No | `PublicationDate ge 2026-02-01T00:00:00.000Z` |
| `concat`, `indexof`, `length`, `substring`, `matchesPattern`, `tolower`, `toupper`, `trim` | No | `tolower(Satellite) eq 's1a'` |

The operators that are not required by the specifications are supported by some stations only. Test scripts to
check the OData support of the stations are available in the [rs-testsuite](https://github.com/RS-PYTHON/rs-testsuite)
repository.
