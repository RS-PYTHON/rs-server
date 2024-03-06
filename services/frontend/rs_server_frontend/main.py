from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

app = FastAPI()


def custom_openapi():
    """Customize the openapi provided by the fastapi application."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="RS Server",
        version=app.version,
        summary=app.summary,
        description=app.description,
        routes=app.routes,
    )

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
