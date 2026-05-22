from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
import datetime

from backend.database.db import get_db
from backend.database.models import User
from backend.api import auth_utils

router = APIRouter()

# Pydantic схемы для валидации входных данных
class UserCreate(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class TokenVerify(BaseModel):
    username: str
    code: str  # 6-значный код из Aegis

@router.post("/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_password = auth_utils.get_password_hash(user.password)
    totp_secret = auth_utils.generate_totp_secret()
    
    new_user = User(
        username=user.username,
        password_hash=hashed_password,
        totp_secret=totp_secret
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    # Генерируем QR-код
    uri = auth_utils.get_totp_uri(totp_secret, user.username)
    qr_ascii = auth_utils.generate_qr_ascii(uri)
    
    return {
        "message": "User created successfully",
        "username": new_user.username,
        "totp_secret": totp_secret,
        "qr_ascii": qr_ascii,
        "instruction": "Scan the QR code with Aegis/Google Authenticator"
    }

@router.post("/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not auth_utils.verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    
    # Мы не возвращаем JWT сразу! Возвращаем указание ввести 2FA код.
    return {
        "message": "Credentials valid. Please provide 2FA code.",
        "username": db_user.username,
        "require_2fa": True
    }

@router.post("/verify-2fa")
def verify_2fa(data: TokenVerify, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == data.username).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not auth_utils.verify_totp(db_user.totp_secret, data.code):
        raise HTTPException(status_code=401, detail="Invalid 2FA code")
    
    # 2FA пройден, выдаем полноценный токен доступа
    access_token_expires = datetime.timedelta(minutes=auth_utils.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = auth_utils.create_access_token(
        data={"sub": db_user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}
