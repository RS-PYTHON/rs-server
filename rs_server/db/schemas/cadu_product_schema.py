from pydantic import BaseModel

from rs_server.db.schemas.download_status_schema import ItemRead


class UserBase(BaseModel):
    email: str


class UserCreate(UserBase):
    password: str


class UserRead(UserBase):
    id: int
    is_active: bool
    items: list[ItemRead] = []

    class Config:
        orm_mode = True
