# for s in "adgs", "adgs2":
#     for t in ['AUX_PP2', 'OPER_AUX_ECMWFD_PDMC', 'OPER_AUX_OBMEMC', 'OPER_AUX_OBMEMC_PDMC', 'OPER_AUX_PREORB_OPOD', 'OPER_AUX_RESORB_OPOD', 'OPER_AUX_RESORB_OPODs', 'OPER_MPL_ORBPRE', 'OPER_MPL_ORBSCT']:
#         print(f"""
#   - id: {s}_{t.lower()}
#     station: {s}
#     query:
#       productType: {t}
#     title: "{t} {s!r} station"
#     description: "{t} {s!r} station" """)

# d = {
# "Sentinel-1": "S1A, S1B, S1C",
# "Sentinel-2": "S2A, S2B, S2C",
# "Sentinel-3": "S3A, S3B",
# "Sentinel-5": "S5P"
# }

# for s in "cadip", "mti", "sgs":
#     for c, p in d.items():
#         print(
# f"""
#   - id: {s}_{c.replace('-', '').lower()}
#     station: {s}
#     query:
#       Satellite: {p}
#     title: "{c} {s!r} station"
#     description: "{c} {s!r} station" """)

# bp = 0


import os
import sys
from json import JSONDecodeError

import requests

sys.path.append(os.path.dirname(os.path.realpath(__file__)))

os.environ["RSPY_HOST_USER"] = "jgaucher"
os.environ["RSPY_LOCAL_MODE"] = "1"
os.environ["S3_ACCESSKEY"] = "minio"
os.environ["S3_SECRETKEY"] = "Strong#Pass#1234"
os.environ["S3_ENDPOINT"] = "http://localhost:9100"
os.environ["S3_REGION"] = "sbg"
os.environ["RSPY_TEMP_BUCKET"] = "rs-cluster-temp"
os.environ["RSPY_CATALOG_BUCKET"] = "rs-cluster-catalog"
os.environ["RSPY_HOST_ADGS"] = "http://localhost:8001"
os.environ["RSPY_HOST_CADIP"] = "http://localhost:8002"
os.environ["RSPY_HOST_CATALOG"] = "http://localhost:8003"

# os.environ["RSPY_LOCAL_MODE"] = "0"
# os.environ["RSPY_OAUTH2_COOKIE"] = "eyJfc3RhdGVfa2V5Y2xvYWtfcVB5TkhHeE52d1o2RXE2Y09vSW5rZVVKc3BnUEdPIjogeyJkYXRhIjogeyJyZWRpcmVjdF91cmkiOiAiaHR0cDovL2xvY2FsaG9zdDo4MDAzL2F1dGgvbG9naW4iLCAiY29kZV92ZXJpZmllciI6ICJEZVQ4Q2NieWFRM3ZhVkY0M0NFQWFMUEdtOXc1WVZCSVp0dlM3SkNROVN5TUdZZ08iLCAibm9uY2UiOiAiRHhZS0JaOFV0TmNSc1JsbVVmbjkiLCAidXJsIjogImh0dHBzOi8vaWFtLmRldi1yc3B5LmVzYS1jb3Blcm5pY3VzLmV1L3JlYWxtcy9yc3B5L3Byb3RvY29sL29wZW5pZC1jb25uZWN0L2F1dGg/cmVzcG9uc2VfdHlwZT1jb2RlJmNsaWVudF9pZD1mYXN0YXBpX3Rlc3QmcmVkaXJlY3RfdXJpPWh0dHAlM0ElMkYlMkZsb2NhbGhvc3QlM0E4MDAzJTJGYXV0aCUyRmxvZ2luJnNjb3BlPW9wZW5pZCtwcm9maWxlK2VtYWlsJnN0YXRlPXFQeU5IR3hOdndaNkVxNmNPb0lua2VVSnNwZ1BHTyZub25jZT1EeFlLQlo4VXROY1JzUmxtVWZuOSZjb2RlX2NoYWxsZW5nZT0xOEpwb2ZSMEF4MnRrcmc3WmtlNDVWY0hrU3NLemwwb1ZfWWkwNTBJbWFrJmNvZGVfY2hhbGxlbmdlX21ldGhvZD1TMjU2In0sICJleHAiOiAxNzI0NDA5MTM1LjUwNzAxMzZ9LCAidXNlciI6IHsiZXhwIjogMTcyNDQwNTgzNiwgImlhdCI6IDE3MjQ0MDU1MzYsICJhdXRoX3RpbWUiOiAxNzI0Mzk5NDI0LCAianRpIjogIjRjNGIzOTE0LWY1MDYtNDkwNC05YzBhLTBkM2RhN2U0YWE2YiIsICJpc3MiOiAiaHR0cHM6Ly9pYW0uZGV2LXJzcHkuZXNhLWNvcGVybmljdXMuZXUvcmVhbG1zL3JzcHkiLCAiYXVkIjogImZhc3RhcGlfdGVzdCIsICJzdWIiOiAiZGYwYTFjZTEtMzg2ZC00OTIzLTlkOGYtMzZiZWYxMWMzMjEwIiwgInR5cCI6ICJJRCIsICJhenAiOiAiZmFzdGFwaV90ZXN0IiwgIm5vbmNlIjogIldxcW5UWXYyc0twVjl3ME9mckhIIiwgInNlc3Npb25fc3RhdGUiOiAiN2YzNDk2YzYtNzVhZC00ZDRkLWI3YjktYmNjNTZiODFkMmJlIiwgImF0X2hhc2giOiAiSWQyRVhjRldRUWJPOEpqY3RHQkxaUSIsICJhY3IiOiAiMCIsICJzaWQiOiAiN2YzNDk2YzYtNzVhZC00ZDRkLWI3YjktYmNjNTZiODFkMmJlIiwgImVtYWlsX3ZlcmlmaWVkIjogdHJ1ZSwgInByZWZlcnJlZF91c2VybmFtZSI6ICJweXRlYW0iLCAiZW1haWwiOiAibmljb2xhcy5sZWNvbnRlQGNzZ3JvdXAuZXUifX0=.ZsiBzw.iezaxFDw8lQjoPO-gVvKnY6dsw4"
# os.environ["RSPY_WEBSITE"] = "http://localhost:8003"
# os.environ["RSPY_UAC_CHECK_URL"] = "http://localhost:9999/auth/check_key"

# Init environment before running a demo notebook.
from resources.utils import *
init_demo()
from resources.utils import *  # reload the global vars again

import itertools
import json
import math
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import unquote

import iso8601
import rfc3339


# # STAC validation
# import sys
# from pystac_client import Client
# stac_io = None
# print("STAC auxip validation")
# stac_auxip_client: Client = Client.open(auxip_client.href_adgs + "/auxip/", stac_io=stac_io)
# stac_auxip_client.validate_all()
# bp = 0




# # Create a test collection and stage test items
# collection = create_test_collection()
# items = stage_test_item()

# bp = 0

# from datetime import datetime
# start_date = datetime(2010, 1, 1, 12, 0, 0)
# stop_date = datetime(2024, 1, 1, 12, 0, 0)
# auxip_client.search_stations(start_date, stop_date, limit=2)


@dataclass
class Error:
    """Errors in this tests."""

    endpoint: str
    params: dict
    messages: list[str]

    def __repr__(self):
        sep = "\n  - "
        return (
            f"\nPOST {self.endpoint!r}\n{json.dumps(self.params, indent=2)}\n"
            f"Error(s):{sep}{sep.join(self.messages)}\n"
        )


errors: list[Error] = []


def save_error(*args) -> None:
    """Print and save an error"""
    error = Error(*args)
    print(error, file=sys.stderr)
    errors.append(error)


# Collections to search. If None: search all collections.
adgs_collections = ["adgs"]
cadip_collections = ["cadip"]
collections = None

# Parameters on which we can sort
adgs_sortbys = [
    "id",
    "auxip:id",
    "file:size",
    "type",
    "eviction_datetime",
    "created",
    "start_datetime",
    "end_datetime"
    ]
cadip_sortbys = [
    "id",
    "start_datetime",
    "datetime",
    "end_datetime",
    "published",
    "platform",
    "startTimeFromAscendingNode",
    "completionTimeFromAscendingNode",
    "cadip:id",
    "cadip:num_channels",
    "cadip:station_unit_id",
    "sat:absolute_orbit",
    "cadip:acquisition_id",
    "cadip:antenna_id",
    "cadip:front_end_id",
    "cadip:retransfer",
    "cadip:antenna_status_ok",
    "cadip:front_end_status_ok",
    "cadip:planned_data_start",
    "cadip:planned_data_stop",
    "cadip:downlink_status_ok",
    "cadip:delivery_push_ok"
]
sortbys = None

def search_and_check(endpoint, params={}, from_feature=None, search_properties=[]):
    """Call the /search endpoint, check the results, return features and links."""

    print(f"Call POST {endpoint!r} with params: {list(search_properties) + list(params.keys())}")

    # Set the query parameters
    if collections:
        params["collections"] = collections
    for property in search_properties:
        in_value = from_feature.get(property) or from_feature["properties"].get(property)

        if property == "id":
            params["ids"] = [in_value]

        # Date interval start and stop use the input feature date.
        # We need to remove 1 second from the start, and add 1 to the stop.
        elif property == "datetime":
            dt = iso8601.parse_date(in_value)
            start = rfc3339.rfc3339(dt + timedelta(seconds=-1))
            stop = rfc3339.rfc3339(dt + timedelta(seconds=1))
            params[property] = f"{start}/{stop}".replace("+00:00", "Z")

        # query parameters
        else:
            params.setdefault("query", {})[property] = {"eq": in_value}

    # Call the search endpoint, read the returned features
    response = http_session.post(endpoint, json=params)

    if response.status_code != 200:
        save_error(endpoint, params, [f"Status code: {response.status_code}\n{unquote(response.content)}"])
        return None, None

    ret_features = response.json()["features"]
    if not ret_features:
        save_error(endpoint, params, [f"No features returned"])
        return None, None

    # Check that each returned feature property on which we filtered,
    # has the same value than in the input feature.
    messages: list[str] = []
    for property in search_properties:
        for ret_feature in ret_features:
            in_value = from_feature.get(property) or from_feature["properties"].get(property)
            ret_value = ret_feature.get(property) or ret_feature["properties"].get(property)

            if in_value != ret_value:
                messages.append(f"Wrong {property}: {ret_value!r}, expected: {in_value!r}")
                break  # only print error for first wrong feature

    if messages:
        save_error(endpoint, params, messages)
    return ret_features, response.json()["links"]


for service in "auxip", "cadip":

    # For better readability
    auxip = service == "auxip"
    cadip = service == "cadip"

    # Init
    if auxip:
        endpoint = f"{auxip_client.href_adgs}/auxip/search"
        collections = adgs_collections
        sortbys = adgs_sortbys
    elif cadip:
        endpoint = f"{cadip_client.href_cadip}/cadip/search"
        collections = cadip_collections
        sortbys = cadip_sortbys

    # Get all auxip products or cadip sessions
    all_features, _ = search_and_check(endpoint, {"limit": 10000})

    ##################
    # Test filtering #
    ##################

    # We take any existing feature returned by the stations, filter on its properties,
    # and check that the filter was applied.
    feature = all_features[1]

    # All properties on which we can filter
    properties = ["id", "datetime", "platform"]
    if auxip:
        properties += ["constellation", "product:type"]

    # # Test all combinations of n properties
    # for length in range(1, len(properties) + 1):
    #     for search_properties in itertools.combinations(properties, length):
    #         search_and_check(endpoint, {}, feature, search_properties)

    ###################
    # Test pagination #
    ###################

    # Split the total number of features in n pages
    pages = 3
    limit = math.ceil(len(all_features) / pages)

    # Test all sortby values, prefixed by + and -
    for sortby in sortbys:
        for direction in "asc", "desc":
            params = {
                "limit": limit,
                "sortby": [{"direction": direction, "field": sortby}]
            }
            page_endpoint = endpoint
            page_params = params

            # For each page to request
            for page in range(pages):

                # Request current page
                features, links = search_and_check(page_endpoint, page_params)

                # In case of error, don't process next pages
                if not links:
                    break

                # Read link tokens
                try:
                    next_page_token = \
                        [link for link in links if link["rel"] == "next"][0]["body"]["token"]
                    prev_page_token = \
                        [link for link in links if link["rel"] == "previous"][0]["body"]["token"] if page else None
                except (KeyError, IndexError):
                    save_error(page_endpoint, page_params, [f"Missing self/previous/next link(s)"])

                # Check the token for next and previous page
                if f"page={page+2}" not in next_page_token:
                    save_error(page_endpoint, page_params, 
                        [f"Wrong 'next' page token: {next_page_token!r}, should contain: 'page={page+2}'"])
                    break # don't process next page
                if prev_page_token and (f"page={page}" not in prev_page_token):
                    save_error(page_endpoint, page_params, 
                        [f"Wrong 'previous' page token: {prev_page_token!r}, should contain: 'page={page}'"])
                    
                # Use the "next" token for the next page
                page_params.update({"token": next_page_token})


    bp = 0

        # if property == "limit":
        #     feature_count = len(output_features)
        #     # TO BE FIXED BY https://pforge-exchange2.astrium.eads.net/jira/browse/RSPY-131 ?
        #     if feature_count > expected_value:
        #         messages.append(f"{feature_count} features returned, expected max: {expected_value}")
        #     continue

if errors:
    message = "\n## Error message start ##\n"
    for error in errors:
        message += str(error)
    message += "\n## Error message finish ##\n"
    raise RuntimeError(message)
