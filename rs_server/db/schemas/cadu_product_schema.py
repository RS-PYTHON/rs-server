from pydantic import BaseModel

from rs_server.db.models.download_status_model import DownloadStatusEnum
from rs_server.db.schemas.download_status_schema import ItemRead


class CaduProductBase(BaseModel):
    name: str


class CaduProductCreate(CaduProductBase):
    pass


class CaduProductRead(CaduProductBase):
    id: int
    download_status: DownloadStatusEnum

    class Config:
        # allow_population_by_field_name = True
        orm_mode = True
        # use_enum_values = True


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
