"""Real login endpoints — see app/auth.py for the password hashing and
session-token implementation. Demo users are seeded (see app/db/seed_loader.py)
so this is usable without a signup flow; the login mechanism itself is real."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth, schemas
from ..db import models as db
from ..deps import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=schemas.LoginOut)
def login(payload: schemas.LoginIn, session: Session = Depends(get_db)):
    user = session.scalar(select(db.User).where(db.User.email == payload.email.strip().lower()))
    if user is None or not auth.verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid email or password")
    token = auth.create_session_token(user.id)
    return schemas.LoginOut(
        token=token,
        user=schemas.UserOut(id=user.id, email=user.email, role=user.role, organization_id=user.organization_id),
    )


@router.get("/me", response_model=schemas.UserOut)
def me(current: auth.CurrentUser = Depends(auth.get_current_user)):
    return schemas.UserOut(id=current.id, email=current.email, role=current.role, organization_id=current.organization_id)
