import os
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.user import UserRegister, UserResponse, UserLogin
from app.services.auth import register_user, login_user
from app.models.user import User
from app.utils.dependencies import get_current_user, require_role

router = APIRouter(
    prefix="/api/auth",
    tags=["Authentication"]
)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
def register(
    user_data: UserRegister,
    db: Session = Depends(get_db)
):
    if user_data.role == "instructor":
        expected_invite_code = os.getenv("INSTRUCTOR_INVITE_CODE")
        if not expected_invite_code or user_data.invite_code != expected_invite_code:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or missing instructor invite code"
            )

    try:
        return register_user(db, user_data)

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )

@router.post("/login")
def login(
    user_data: UserLogin,
    db: Session = Depends(get_db)
):
    try:
        access_token = login_user(db, user_data)
        return {"access_token": access_token, "token_type": "bearer"}

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e)
        )

@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user)
):
    return current_user

