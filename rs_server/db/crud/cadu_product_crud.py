from fastapi import APIRouter, Depends, HTTPException

from rs_server.db.models.cadu_product_model import CaduProductModel
from rs_server.db.models.download_status import DownloadStatus
from rs_server.db.schemas.cadu_product_schema import (
    CaduProductCreate,
    CaduProductDownloadDone,
    CaduProductDownloadFail,
    CaduProductDownloadStart,
    CaduProductRead,
)
from rs_server.db.session import add_commit_refresh, get_db, reraise_http

# All the HTTP
router = APIRouter(prefix="/cadu_products", tags=["cadu_products"], dependencies=[Depends(reraise_http)])

# from sqlalchemy.sql import text
# db.execute(text("select * from cadu_products"))


@router.get("/", response_model=list[CaduProductRead])
def get_all_products(skip: int = 0, limit: int = 100, db=Depends(get_db)):
    return db.query(CaduProductModel).offset(skip).limit(limit).all()


@router.get("/id={product_id}", response_model=CaduProductRead)
def get_product_by_id(product_id: int, db=Depends(get_db)):
    ret = db.query(CaduProductModel).filter(CaduProductModel.id == product_id).first()
    if ret is None:
        raise HTTPException(status_code=404, detail=f"CADU product not found for ID: {product_id!r}")
    return ret


# TODO: useful ?
@router.get("/name={product_name}", response_model=CaduProductRead)
def get_product_by_name(product_name: str, db=Depends(get_db)):
    ret = db.query(CaduProductModel).filter(CaduProductModel.name == product_name).first()
    if ret is None:
        raise HTTPException(status_code=404, detail=f"CADU product not found for name: {product_name!r}")
    return ret


@router.post("/", response_model=CaduProductRead)
def create_product(product: CaduProductCreate, db=Depends(get_db)):
    ret = CaduProductModel(**product.model_dump(exclude_unset=True))  # create model from the schema values
    return add_commit_refresh(db, ret)


# TODO: 3 methods for updating or a single one with status and optional fail message as input ?


@router.patch("/{product_id}/download_start", response_model=CaduProductRead)
def product_download_start(product_id: int, info: CaduProductDownloadStart, db=Depends(get_db)):
    ret = get_product_by_id(product_id, db)
    ret.downlink_start = info.downlink_start
    ret.status = DownloadStatus.IN_PROGRESS
    return add_commit_refresh(db, ret)


@router.patch("/{product_id}/download_done", response_model=CaduProductRead)
def product_download_done(product_id: int, info: CaduProductDownloadDone, db=Depends(get_db)):
    ret = get_product_by_id(product_id, db)
    ret.downlink_stop = info.downlink_stop
    ret.status = DownloadStatus.DONE
    return add_commit_refresh(db, ret)


@router.patch("/{product_id}/download_fail", response_model=CaduProductRead)
def product_download_fail(product_id: int, info: CaduProductDownloadFail, db=Depends(get_db)):
    ret = get_product_by_id(product_id, db)
    ret.downlink_stop = info.downlink_stop
    ret.status = DownloadStatus.FAILED
    ret.status_fail_message = info.status_fail_message
    return add_commit_refresh(db, ret)
