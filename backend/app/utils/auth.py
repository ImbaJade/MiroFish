"""
简单的登录鉴权工具
"""

from typing import Optional
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from ..config import Config


_TOKEN_SALT = "mirofish-auth-token"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(Config.SECRET_KEY)


def generate_auth_token(username: str) -> str:
    """生成登录令牌。"""
    return _serializer().dumps({"username": username}, salt=_TOKEN_SALT)


def verify_auth_token(token: str) -> Optional[str]:
    """验证令牌，返回用户名；失败返回None。"""
    try:
        payload = _serializer().loads(
            token,
            salt=_TOKEN_SALT,
            max_age=Config.AUTH_TOKEN_EXPIRE_SECONDS,
        )
    except (BadSignature, SignatureExpired):
        return None

    username = payload.get("username") if isinstance(payload, dict) else None
    if not isinstance(username, str) or not username:
        return None
    return username
