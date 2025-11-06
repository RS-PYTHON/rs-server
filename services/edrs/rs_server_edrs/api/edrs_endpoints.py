from __future__ import annotations

from typing import Optional, Literal
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse

from rs_server_common.authentication import authentication
from rs_server_common.stac_api_common import MockPgstac
from rs_server_common.utils.logging import Logging

from rs_server_edrs.edrs_utils import edrs_read_conf, edrs_select_config

logger = Logging.default(__name__)
router = APIRouter()

class MockPgstacEdrs(MockPgstac):
    """pgSTAC mock for EDRS (collections from YAML)."""
    def __init__(self, request: Optional[Request] = None, readwrite: Optional[Literal["r","w"]] = None):
        super().__init__(
            request=request,
            readwrite=readwrite,
            service="edrs",
            all_collections=lambda: edrs_read_conf().get("collections", []),
            select_config=edrs_select_config,
            stac_to_odata=lambda d: d,
            map_mission=lambda *_: None,
        )
        self.sortby = "id"
    async def process_search(self, request: Request) -> dict:
        raise HTTPException(status_code=404, detail="EDRS does not support /search. Use /edrs/collections/{id}/items.")

@router.get("/", include_in_schema=False)
async def home():
    return RedirectResponse("/edrs")

@router.get("/edrs")
async def get_root_catalog(request: Request):
    logger.info("Starting %s", request.url.path)
    authentication.auth_validation("edrs", "landing_page", request=request)
    return await request.app.state.pgstac_client.landing_page(request=request)

@router.get("/edrs/collections")
async def get_allowed_edrs_collections(request: Request) -> dict:
    logger.info("Starting %s", request.url.path)
    authentication.auth_validation("edrs", "landing_page", request=request)
    return await request.app.state.pgstac_client.all_collections(request=request)
