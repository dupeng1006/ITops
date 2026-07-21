# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 安全组件（密码哈希 + JWT）

- 密码：bcrypt 哈希（带盐），不可逆存储；
- 会话：JWT（HS256），默认 8 小时过期；
- 密钥来自集中配置（环境变量/.env），不入库不入仓。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
import jwt

from app.core.config import get_settings

# bcrypt 单密码最大长度（字节）
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """
    生成密码的 bcrypt 哈希

    Raises:
        ValueError: 密码为空或超过 bcrypt 长度上限
    """
    raw = password.encode("utf-8")
    if not raw:
        raise ValueError("密码不能为空")
    if len(raw) > BCRYPT_MAX_BYTES:
        raise ValueError(f"密码过长（bcrypt 上限 {BCRYPT_MAX_BYTES} 字节），请缩短密码")
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验密码与 bcrypt 哈希是否匹配"""
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(subject: str, role: str, expire_hours: Optional[int] = None) -> str:
    """
    签发 JWT 访问令牌

    Args:
        subject: 用户名
        role: 角色（admin/operator/viewer）
        expire_hours: 过期小时数，默认取配置（8h）
    """
    settings = get_settings()
    hours = expire_hours if expire_hours is not None else settings.JWT_EXPIRE_HOURS
    now = datetime.now()
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=hours)).timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    校验并解码 JWT

    Returns:
        payload dict（含 sub/role/exp）

    Raises:
        jwt.ExpiredSignatureError: 令牌已过期
        jwt.InvalidTokenError: 令牌非法
    """
    settings = get_settings()
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
