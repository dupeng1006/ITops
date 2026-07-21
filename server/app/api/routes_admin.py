# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 用户维护接口（仅 admin）

    GET    /api/admin/users                     用户列表
    POST   /api/admin/users                     新增用户（初始密码，首登强制改密）
    PUT    /api/admin/users/{id}                修改角色/启停
    POST   /api/admin/users/{id}/reset-password 重置密码
    DELETE /api/admin/users/{id}                删除用户

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from typing import Optional

from app.api.schemas import (
    ResetPasswordRequest,
    UserCreateRequest,
    UserInfo,
    UserUpdateRequest,
)
from app.core.deps import get_db, require_roles
from app.core.security import hash_password
from app.models.entities import SysUser
from app.services.audit_service import record_audit

router = APIRouter(
    prefix="/api/admin/users",
    tags=["用户维护"],
    dependencies=[Depends(require_roles("admin"))],
)


def _to_info(user: SysUser) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        department=user.department,
        role=user.role,
        status=user.status,
        source=user.source,
        must_change_password=user.must_change_password,
        created_at=user.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        updated_at=user.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _blank_to_none(value: Optional[str]) -> Optional[str]:
    """去首尾空格，空串转 None"""
    if value is None:
        return None
    v = value.strip()
    return v or None


def _get_user_or_404(db: Session, user_id: int) -> SysUser:
    user = db.get(SysUser, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"用户不存在: id={user_id}")
    return user


@router.get("", response_model=list[UserInfo], summary="用户列表")
def list_users(db: Session = Depends(get_db)):
    users = db.execute(select(SysUser).order_by(SysUser.id)).scalars().all()
    return [_to_info(u) for u in users]


@router.post("", response_model=UserInfo, summary="新增用户")
def create_user(
    body: UserCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else None
    exists = db.execute(
        select(SysUser).where(SysUser.username == body.username)
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=400, detail=f"用户编号已存在: {body.username}")

    user = SysUser(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        status="active",
        source="local",
        must_change_password=True,  # 初始密码首登强制修改
        display_name=_blank_to_none(body.display_name),
        department=_blank_to_none(body.department),
    )
    db.add(user)
    db.flush()
    record_audit(db, "admin", "user_create", "user", user.username,
                 f"新增用户（编号 {user.username}），角色={body.role}", ip)
    db.commit()
    return _to_info(user)


@router.put("/{user_id}", response_model=UserInfo, summary="修改用户角色/状态")
def update_user(
    user_id: int,
    body: UserUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else None
    user = _get_user_or_404(db, user_id)
    if user.username == "admin" and body.status == "disabled":
        raise HTTPException(status_code=400, detail="不允许停用初始管理员账号")
    if user.username == "admin" and body.role and body.role != "admin":
        raise HTTPException(status_code=400, detail="不允许变更初始管理员角色")

    changes = []
    if body.role is not None and body.role != user.role:
        changes.append(f"角色 {user.role}→{body.role}")
        user.role = body.role
    if body.status is not None and body.status != user.status:
        changes.append(f"状态 {user.status}→{body.status}")
        user.status = body.status
    if body.display_name is not None:
        new_name = _blank_to_none(body.display_name)
        if new_name != user.display_name:
            changes.append(f"用户姓名 {user.display_name or '(空)'}→{new_name or '(空)'}")
            user.display_name = new_name
    if body.department is not None:
        new_dept = _blank_to_none(body.department)
        if new_dept != user.department:
            changes.append(f"部门 {user.department or '(空)'}→{new_dept or '(空)'}")
            user.department = new_dept
    if not changes:
        return _to_info(user)

    record_audit(db, "admin", "user_update", "user", user.username,
                 "；".join(changes), ip)
    db.commit()
    return _to_info(user)


@router.post("/{user_id}/reset-password", summary="重置用户密码")
def reset_password(
    user_id: int,
    body: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else None
    user = _get_user_or_404(db, user_id)
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = True  # 重置后首登仍需改密
    record_audit(db, "admin", "user_reset_password", "user", user.username,
                 "管理员重置密码", ip)
    db.commit()
    return {"message": f"已重置用户 {user.username} 的密码，该用户下次登录需修改密码"}


@router.delete("/{user_id}", summary="删除用户")
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else None
    user = _get_user_or_404(db, user_id)
    if user.username == "admin":
        raise HTTPException(status_code=400, detail="不允许删除初始管理员账号")

    username = user.username
    db.delete(user)
    record_audit(db, "admin", "user_delete", "user", username, "删除用户", ip)
    db.commit()
    return {"message": f"已删除用户 {username}"}
