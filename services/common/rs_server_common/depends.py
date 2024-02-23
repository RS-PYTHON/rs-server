"""Objects used by fastapi dependency injection."""

from httpx import AsyncClient

# HTTP client
http_client: AsyncClient = None


async def http_client() -> AsyncClient:
    """Get HTTP client instance"""
    return http_client
