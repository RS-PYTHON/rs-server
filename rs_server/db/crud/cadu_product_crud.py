import traceback
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from rs_server.db.models.cadu_product_model import CaduProductModel, UserModel
from rs_server.db.models.download_status_model import ItemModel
from rs_server.db.schemas.cadu_product_schema import (
    CaduProductCreate,
    CaduProductRead,
    UserCreate,
    UserRead,
)
from rs_server.db.schemas.download_status_schema import ItemCreate, ItemRead
from rs_server.db.session import Base, engine, get_db, reraise_http

router = APIRouter(prefix="/cadu_product", tags=["cadu_product"], dependencies=[Depends(reraise_http)])


@router.post("/cadu/", response_model=CaduProductRead)
def create_cadu_product(cadu_product: CaduProductCreate, db: Session = Depends(get_db)) -> CaduProductRead:
    db_cadu_product = CaduProductModel(name=cadu_product.name)

    db.add(db_cadu_product)
    db.commit()
    db.refresh(db_cadu_product)
    return db_cadu_product


@router.get("/users/{user_id}", response_model=UserRead)
def get_user(user_id: int, db: Session = Depends(get_db)):
    return db.query(UserModel).filter(UserModel.id == user_id).first()


@router.post("/users/", response_model=UserRead)
def get_user_by_email(email: str, db: Session = Depends(get_db)):
    return db.query(UserModel).filter(UserModel.email == email).first()


@router.get("/users/", response_model=list[UserRead])
def get_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[UserRead]:
    return db.query(UserModel).offset(skip).limit(limit).all()


@router.post("/users/", response_model=UserRead)
def create_user(user: UserCreate, db: Session = Depends(get_db)) -> UserRead:
    fake_hashed_password = user.password + "notreallyhashed"
    db_user = UserModel(email=user.email, hashed_password=fake_hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


@router.get("/items/", response_model=list[ItemRead])
def get_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[ItemRead]:
    return db.query(ItemModel).offset(skip).limit(limit).all()


@router.post("/users/{user_id}/items/", response_model=ItemRead)
def create_user_item(item: ItemCreate, user_id: int, db: Session = Depends(get_db)) -> ItemRead:
    db_item = ItemModel(**item.dict(), owner_id=user_id)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item
