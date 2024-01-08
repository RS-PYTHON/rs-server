# app/config.py
import os


class Config:
    DATABASE_CONFIG = os.getenv(
        "DATABASE_CONFIG",
        "postgresql+asyncpg://{user}:{password}@{host}:{port}/{dbname}".format(
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            host=os.environ["POSTGRES_HOST"],
            port=os.environ["POSTGRES_PORT"],
            dbname=os.environ["POSTGRES_DB"],
        ),
    )


config = Config
