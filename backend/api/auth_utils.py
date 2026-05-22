from passlib.context import CryptContext
import pyotp
import jwt
import datetime

# Конфигурация для JWT (в реальном проекте секрет должен быть в .env)
SECRET_KEY = "super_secret_nova_key_for_university_project"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7 # 7 дней

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def generate_totp_secret():
    """Генерирует секретный ключ для приложения (Aegis/Google Auth)"""
    return pyotp.random_base32()

def verify_totp(secret: str, code: str):
    """Проверяет 6-значный код 2FA"""
    totp = pyotp.TOTP(secret)
    return totp.verify(code)

def create_access_token(data: dict, expires_delta: datetime.timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expires_delta
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
