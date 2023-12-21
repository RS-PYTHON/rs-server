from fastapi import APIRouter, FastAPI

from rs_server.db.crud import cadu_product_crud
from rs_server.db.session import Base, engine

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Code executed before the application starts up.
#     # This means that this code will be executed once, before the application starts receiving requests.
#     #
#     # Note: Base.metadata.tables contains all the models that were imported from python with 'import ...'
#     # Create the corresponding SQL tables.
#     Base.metadata.create_all(bind=engine)

#     raise Exception ("BEGIN !")

#     yield
#     raise Exception ("END !")

#     # Code executed when the application is shutting down.
#     # In this case, this code will be executed once, after having handled possibly many requests.
#     # Note: does not seem to work with TestClient.
#     pass

# create_all_db = APIRouter()

# @create_all_db.on_event("startup")
# async def startup_event():

# isort: off

# We need to import all the model modules before calling Base.metadata.create_all
import rs_server.db.models.cadu_product_model
import rs_server.db.models.download_status_model

#
# Note: Base.metadata.tables contains all the models that were imported from python with 'import ...'
# Create the corresponding SQL tables.
Base.metadata.create_all(bind=engine)


# isort: on


main_app = FastAPI()
main_app.include_router(cadu_product_crud.router)
