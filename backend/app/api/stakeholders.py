from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.models import Stakeholder
from app.schemas.schemas import StakeholderCreate, StakeholderOut

router = APIRouter(prefix="/stakeholders", tags=["stakeholders"])


@router.get("", response_model=list[StakeholderOut])
def list_stakeholders(db: Session = Depends(get_db)):
    return db.query(Stakeholder).order_by(Stakeholder.name).all()


@router.post("", response_model=StakeholderOut, status_code=201)
def create_stakeholder(payload: StakeholderCreate, db: Session = Depends(get_db)):
    # Names are unique; say so rather than fail the insert with a 500.
    if db.query(Stakeholder.id).filter(Stakeholder.name == payload.name).first() is not None:
        raise HTTPException(status_code=409, detail="A stakeholder with this name already exists")
    stakeholder = Stakeholder(name=payload.name, email=payload.email)
    db.add(stakeholder)
    db.commit()
    db.refresh(stakeholder)
    return stakeholder
