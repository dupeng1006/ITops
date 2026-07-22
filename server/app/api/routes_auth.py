# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 认证接口

    POST /api/auth/login            登录（返回 JWT；首登用户带 must_change_password 标记）
    POST /api/auth/change-password  修改密码（首登强制改密亦走此接口）

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ChangePasswordRequest, LoginRequest, LoginResponse
from app.core.deps import get_current_user_allow_change, get_db
from app.core.security import create_access_token, hash_password, verify_password
from app.models.entities import SysUser
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post("/login", response_model=LoginResponse, summary="用户登录")
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """校验用户名密码，签发 JWT（8 小时过期）；首登用户返回需改密标记"""
    ip = request.client.host if request.client else None
    user = db.execute(
        select(SysUser).where(SysUser.username == body.username)
    ).scalars().first()

    if user is None or not verify_password(body.password, user.password_hash):
        record_audit(db, body.username, "login_failed", "user", body.username,
                     "用户名或密码错误", ip, menu="登录页")
        db.commit()
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != "active":
        record_audit(db, body.username, "login_failed", "user", body.username,
                     "账号已停用", ip, menu="登录页")
        db.commit()
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")

    token = create_access_token(subject=user.username, role=user.role)
    record_audit(db, user.username, "login", "user", user.username, "登录成功", ip,
                 menu="登录页")
    db.commit()
    return LoginResponse(
        access_token=token,
        must_change_password=user.must_change_password,
        username=user.username,
        role=user.role,
        display_name=user.display_name,
    )


@router.post("/change-password", summary="修改密码（含首登强制改密）")
def change_password(
    body: ChangePasswordRequest,
    request: Request,
    user: SysUser = Depends(get_current_user_allow_change),
    db: Session = Depends(get_db),
):
    """校验原密码后更新密码；首登用户改密后解除强制改密标志"""
    ip = request.client.host if request.client else None
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="原密码错误")
    if body.old_password == body.new_password:
        raise HTTPException(status_code=400, detail="新密码不能与原密码相同")

    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    record_audit(db, user.username, "change_password", "user", user.username,
                 "修改密码", ip, menu="登录页")
    db.commit()
    return {"message": "密码修改成功"}
