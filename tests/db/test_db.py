"""Test database implementation"""

import logging

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

import rs_server.db.crud.cadu_product_crud as crud
from rs_server.db.models.cadu_product_model import UserModel
from rs_server.db.models.download_status_model import ItemModel
from rs_server.db.schemas.cadu_product_schema import UserCreate
from rs_server.db.schemas.download_status_schema import ItemCreate
from rs_server.db.session import SessionLocal, get_db
from rs_server.db.startup import db_app

# Force call to 'async def lifespan(app: FastAPI)'
with TestClient(db_app) as _:
    pass


@pytest.fixture(autouse=True)
def populate(db: Session = Depends(get_db)):
    db = SessionLocal()
    try:
        db.query(ItemModel).delete()
        db.query(UserModel).delete()
        db.commit()

        a = crud.create_user(db=db, user=UserCreate(email="toto@gmail.com", password="toto-pass"))
        b = crud.create_user(db=db, user=UserCreate(email="tata@gmail.com", password="tata-pass"))

        crud.create_user_item(db=db, item=ItemCreate(title="item 1", description="desc for item 1"), user_id=a.id)
        crud.create_user_item(db=db, item=ItemCreate(title="item 2", description="desc for item 2"), user_id=b.id)

    except:
        logging.getLogger().warning(f"Exception caught, rollback database transactions")
        db.rollback()
        raise
    finally:
        db.close()


def test_read_main():
    with TestClient(db_app) as client:
        # assert response.status_code == 200
        # print(json.dumps(client.get("/users/").json(), indent=2))
        # print(json.dumps(client.get("/items/").json(), indent=2))
        bp = 0
