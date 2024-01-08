import os

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from rs_server.db import session
from rs_server.db.crud import cadu_product_crud
from rs_server.db.session import Base


def init():
    # SQLite configuration
    # SQLALCHEMY_DATABASE_URL = "sqlite:////tmp/sql_app.db"
    # engine = create_engine(
    #     SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    # )

    # PostgreSQL configuration.
    # Use postgresql+psycopg2://... ?
    # See: https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg2
    user = os.environ["POSTGRES_USER"]
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.environ["POSTGRES_HOST"]
    port = os.environ["POSTGRES_PORT"]
    dbname = os.environ["POSTGRES_DB"]
    SQLALCHEMY_DATABASE_URL = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}"

    engine = create_engine(SQLALCHEMY_DATABASE_URL)

    session.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # We need to import all the model modules before calling Base.metadata.create_all
    import rs_server.CADIP.models.cadu_download_status

    # Note: Base.metadata.tables contains all the models that were imported from python with 'import ...'
    # Create the corresponding SQL tables.
    Base.metadata.create_all(bind=engine)


# main_app = FastAPI()
# main_app.include_router(cadu_product_crud.router)
