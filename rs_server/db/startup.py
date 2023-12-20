from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

# Other imports
from rs_server.db.session import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Code executed before the application starts up.
    # This means that this code will be executed once, before the application starts receiving requests.
    #
    # Note: Base.metadata.tables contains all the models that were imported from python with 'import ...'
    # Create the corresponding SQL tables.
    Base.metadata.create_all(bind=engine)

    yield

    # Code executed when the application is shutting down.
    # In this case, this code will be executed once, after having handled possibly many requests.
    # Note: does not seem to work with TestClient.
    pass


db_app = APIRouter(lifespan=lifespan)

# TODO: where to put this code ?
app = FastAPI()
app.include_router(db_app)
