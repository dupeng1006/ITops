# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 对称加密组件（Fernet，用于数据源密码等机密字段）

密钥机制（沿用 launcher 的 data\\secret.key 思路，独立派生、互不影响）：
    1. 环境变量 O32OPS_DS_KEY 优先（任意非空字符串，独立密钥）；
    2. 否则读取/生成 data\\secret.key（与 launcher 同一文件，首启自动生成，
       仅本机留存、已 gitignore，绝不入库入仓）；
    3. 以 SHA-256(key_material + 固定域分隔盐) 派生 32 字节，urlsafe base64
       编码后作为 Fernet 密钥——与 JWT 使用同一密钥材料但派生路径不同，
       修改 JWT 密钥不会使数据源密文失效（反之亦然）。

安全说明：
    - 加密结果（Fernet token，urlsafe base64）可安全落库；
    - 接口层承诺：读取/导出数据源时永不返回明文，仅返回掩码；
    - 本模块不做任何网络/文件输出，仅内存加解密。

作者：技术部
版本：1.0.0
日期：2026-07-18
"""

import base64
import hashlib
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# 域分隔盐：确保同一密钥材料派生出的 Fernet 密钥与 JWT 等其他用途互不相同
_DOMAIN_SALT = b"o32ops-ds-fernet-v1"

# 密码掩码（接口返回用，恒定值，不透露长度）
PASSWORD_MASK = "********"

_fernet: Optional[Fernet] = None


def _key_material() -> str:
    """获取密钥材料：环境变量优先，否则读/生成 data\\secret.key"""
    env_key = os.environ.get("O32OPS_DS_KEY")
    if env_key:
        return env_key.strip()

    # 与 launcher._ensure_secret_key 同口径：环境变量已注入 JWT 密钥时直接派生
    jwt_key = os.environ.get("O32OPS_SECRET_KEY")
    if jwt_key:
        return jwt_key.strip()

    # 源码直跑（uvicorn app.main:app）场景：自行读/生成 data\\secret.key
    key_file = get_settings().DATA_DIR / "secret.key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key, encoding="utf-8")
    logger.info(f"已生成加密密钥文件（仅本机留存，勿入库入仓）: {key_file}")
    return key


def _get_fernet() -> Fernet:
    """惰性构造 Fernet 实例（进程内缓存）"""
    global _fernet
    if _fernet is None:
        material = _key_material()
        derived = hashlib.sha256(material.encode("utf-8") + _DOMAIN_SALT).digest()
        _fernet = Fernet(base64.urlsafe_b64encode(derived))
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    """
    加密机密字段（如数据源密码），返回可落库的密文字符串

    Raises:
        ValueError: 明文为空
    """
    if not plaintext:
        raise ValueError("待加密内容不能为空")
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """
    解密密文字符串

    Raises:
        ValueError: 密文非法或密钥不匹配（如换机迁移未同步 secret.key）
    """
    if not ciphertext:
        raise ValueError("密文不能为空")
    try:
        return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        raise ValueError(
            "密文解密失败：密钥不匹配（请确认 data\\secret.key 与加密时一致）"
        ) from None


def reset_crypto() -> None:
    """重置缓存的 Fernet 实例（测试用）"""
    global _fernet
    _fernet = None
