"""
Database modules.

See tutorials:
https://fastapi.tiangolo.com/tutorial/sql-databases/
https://praciano.com.br/fastapi-and-async-sqlalchemy-20-with-pytest-done-right.html
https://medium.com/@tclaitken/setting-up-a-fastapi-app-with-async-sqlalchemy-2-0-pydantic-v2-e6c540be4308
"""

from sqlalchemy.orm import declarative_base

from services.common.models.product_download_status import ProductDownloadStatus

# Construct a sqlalchemy base class for declarative class definitions.
Base = declarative_base()
