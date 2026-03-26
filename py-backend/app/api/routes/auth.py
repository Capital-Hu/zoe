from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.db import Account, get_db_session
from app.schemas.auth import LoginForm, RegisterForm

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(payload: RegisterForm, session: Session = Depends(get_db_session)):
    username = payload.username.strip()
    if len(username) < 3 or len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="username or password too short")

    existed = session.query(Account).filter(Account.username == username).first()
    if existed:
        raise HTTPException(status_code=409, detail="username already exists")

    row = Account(username=username, password_hash=hash_password(payload.password))
    session.add(row)
    session.commit()
    session.refresh(row)
    return {"userId": row.id, "username": row.username}


@router.post("/login")
def login(payload: LoginForm, session: Session = Depends(get_db_session)):
    username = payload.username.strip()
    row = session.query(Account).filter(Account.username == username).first()
    if not row or not verify_password(payload.password, row.password_hash):
        raise HTTPException(status_code=401, detail="invalid username or password")
    return {"userId": row.id, "username": row.username}
