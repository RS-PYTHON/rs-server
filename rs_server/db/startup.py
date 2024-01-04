from fastapi import FastAPI

from rs_server.db.crud import cadu_product_crud
from rs_server.db.session import Base, engine

# isort: off

# We need to import all the model modules before calling Base.metadata.create_all
import rs_server.db.models.cadu_product_model


#
# Note: Base.metadata.tables contains all the models that were imported from python with 'import ...'
# Create the corresponding SQL tables.
def create_all():
    Base.metadata.create_all(bind=engine)


# isort: on

main_app = FastAPI()
main_app.include_router(cadu_product_crud.router)
