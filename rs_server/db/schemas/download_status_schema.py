from pydantic import BaseModel


class ItemBase(BaseModel):
    title: str
    description: str | None = None


class ItemCreate(ItemBase):
    pass


class ItemRead(ItemBase):
    id: int
    owner_id: int

    class Config:
        orm_mode = True
