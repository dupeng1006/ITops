# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— FastAPI 依赖注入（会话 / 认证 / 角色）

角色体系（方案 2.5）：
    admin    全部权限（含用户维护）
    operator 核对执行 + 下载
    viewer   只读（历史任务与结果查询）

首登强制改密：
    must_change_password=True 的用户，除登录/改密外的接口一律 403。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

from typing import Callable, Generator

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.models.database import get_session_factory
from app.models.entities import SysUser

_bearer = HTTPBearer(auto_error=False, description="JWT 访问令牌")


def get_db() -> Generator[Session, None, None]:
    """请求级数据库会话"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> SysUser:
    """解析 Bearer Token 并返回当前登录用户"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录：请先在 /api/auth/login 获取访问令牌")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="访问令牌非法，请重新登录")

    user = db.execute(
        select(SysUser).where(SysUser.username == payload.get("sub", ""))
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在或已被删除，请重新登录")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="首次登录请先调用 /api/auth/change-password 修改初始密码")
    return user


def get_current_user_allow_change(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> SysUser:
    """同 get_current_user，但放行 must_change_password（仅供改密接口使用）"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="未登录：请先获取访问令牌")
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="访问令牌非法，请重新登录")
    user = db.execute(
        select(SysUser).where(SysUser.username == payload.get("sub", ""))
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在或已被删除，请重新登录")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    return user


def require_roles(*roles: str) -> Callable:
    """
    角色校验依赖工厂

    用法：Depends(require_roles("admin")) 或 require_roles("admin", "operator")
    """
    def checker(user: SysUser = Depends(get_current_user)) -> SysUser:
        if user.role not in roles:
            role_names = {"admin": "管理员", "operator": "操作员", "viewer": "只读用户"}
            need = "、".join(role_names.get(r, r) for r in roles)
            raise HTTPException(status_code=403, detail=f"权限不足：该操作需要 {need} 角色")
        return user
    return checker
