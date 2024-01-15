from rs_server.fastapi_app import init_app

# Init the FastAPI application.
app = init_app(init_db=True)
