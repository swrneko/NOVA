from passlib.context import CryptContext
import pyotp
import jwt
import datetime
import qrcode
import io

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

def get_totp_uri(secret: str, username: str, issuer_name: str = "NOVA"):
    """Генерирует URI (строку), которую можно превратить в QR-код"""
    return pyotp.totp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer_name)

def generate_qr_ascii(uri: str) -> str:
    """Генерирует ASCII QR-код для вывода в консоль/TUI"""
    import io
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    
    # Кастомный TTY-рендер, так как qr.print_tty() падает на StringIO
    # Идея взята из исходников qrcode, но без проверки isatty
    out = io.StringIO()
    matrix = qr.get_matrix()
    
    # Рисуем по две строки за раз, используя '▀' (верхняя половина черная), 
    # '▄' (нижняя половина черная), '█' (полностью черный), ' ' (белый)
    # Заметь, что True в матрице - это ЧЕРНЫЙ цвет (часть кода), False - белый фон.
    # Для светлой темы терминала нужно было бы инвертировать, но Textual делает фон темным.
    # Поэтому мы рисуем светлый фон и темные блоки.
    
    for row_idx in range(0, len(matrix), 2):
        row_top = matrix[row_idx]
        row_bottom = matrix[row_idx + 1] if row_idx + 1 < len(matrix) else [False] * len(matrix)
        
        for col_idx in range(len(matrix)):
            top = row_top[col_idx]
            bottom = row_bottom[col_idx]
            
            # Инвертированные цвета (терминалы обычно темные, так что белый цвет = черный фон терминала)
            # В Aegis QR-код должен быть черным на белом фоне.
            # Если "top" это черный блок QR кода, он должен быть черным (фон терминала).
            # В Textual у нас есть виджет Static, мы просто выведем блок.
            if top and bottom:
                out.write(" ")      # Чёрный сверху, чёрный снизу (фон терминала = черный)
            elif top and not bottom:
                out.write("▄")      # Чёрный сверху, белый снизу 
            elif not top and bottom:
                out.write("▀")      # Белый сверху, чёрный снизу 
            else:
                out.write("█")      # Белый сверху, белый снизу (светлый блок QR кода)
        out.write("\n")
        
    return out.getvalue()

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
