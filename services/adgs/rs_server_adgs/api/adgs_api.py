"""Other HTTP endpoints."""
from fastapi import APIRouter
from rs_server_common.schemas.health_schema import HealthSchema

router = APIRouter(tags=["Health"])


@router.get("/adgs/health", response_model=HealthSchema, name="Check ADGS service health")
async def health() -> HealthSchema:
    """
    Always return True if the service is up and running.
    Otherwise this code won't be run anyway and the caller will have other sorts of errors.
    """
    return HealthSchema(healthy=True)
