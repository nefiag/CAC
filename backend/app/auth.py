import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import HTTPException, Request
from sqlalchemy import select

from .database import AsyncSessionLocal
from .models import User, UserSession

SESSION_COOKIE = "coxiaoac_session"
SESSION_DAYS = 7


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("密码至少需要 8 个字符")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 310_000)
    return f"pbkdf2_sha256$310000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        _, rounds, salt, expected = encoded.split("$", 3)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(user_id: str) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(48)
    expires = datetime.utcnow() + timedelta(days=SESSION_DAYS)
    async with AsyncSessionLocal() as db:
        db.add(UserSession(user_id=user_id, token_hash=token_hash(token), expires_at=expires))
        await db.commit()
    return token, expires


async def authenticated_user(request: Request) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(User).join(UserSession, UserSession.user_id == User.id).where(
                UserSession.token_hash == token_hash(token),
                UserSession.expires_at > datetime.utcnow(),
                User.is_active.is_(True),
            )
        )).scalar_one_or_none()
        return row


def require_admin(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if not user or user.role != "ADMIN":
        raise HTTPException(status_code=403, detail="需要系统管理员权限")
    return user
