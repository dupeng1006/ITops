# -*- coding: utf-8 -*-
"""
安联资管运维管理平台 —— 系统日志查询接口（审计读取侧）

    GET /api/audit-logs         审计日志分页查询（操作人/操作菜单/操作类型/时间区间/IP-MAC 过滤）
    GET /api/audit-logs/menus   操作菜单去重清单（查询下拉用）

权限：仅 admin（审计数据含全量操作留痕，不向 operator/viewer 开放）。

作者：技术部
版本：1.0.0
日期：2026-07-22
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import AuditLogInfo, AuditLogListResponse
from app.core.deps import get_db, require_roles
from app.models.entities import SysAuditLog, SysUser

logger = logging.getLogger(__name__)

router = APIRouter(tags=["系统日志查询"])


@router.get("/api/audit-logs", response_model=AuditLogListResponse,
            summary="审计日志分页查询")
def list_audit_logs(
    username: str = Query("", max_length=50, description="操作人（用户编号/姓名 模糊）"),
    menu: str = Query("", max_length=100, description="操作菜单（模糊）"),
    action: str = Query("", max_length=50, description="操作类型（精确）"),
    ip: str = Query("", max_length=50, description="IP 或 MAC（模糊）"),
    date_from: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    # 左联用户表取姓名/部门（登录失败的未知编号、已删除用户也能显示）
    stmt = (
        select(SysAuditLog, SysUser.display_name, SysUser.department)
        .outerjoin(SysUser, SysUser.username == SysAuditLog.username)
    )

    kw = (username or "").strip()
    if kw:
        like = f"%{kw}%"
        stmt = stmt.where(
            (SysAuditLog.username.like(like)) | (SysUser.display_name.like(like))
        )
    if menu.strip():
        stmt = stmt.where(SysAuditLog.menu.like(f"%{menu.strip()}%"))
    if action.strip():
        stmt = stmt.where(SysAuditLog.action == action.strip())
    if ip.strip():
        like_ip = f"%{ip.strip()}%"
        stmt = stmt.where(
            (SysAuditLog.ip.like(like_ip)) | (SysAuditLog.mac.like(like_ip))
        )
    if date_from:
        stmt = stmt.where(SysAuditLog.created_at >= f"{date_from} 00:00:00")
    if date_to:
        stmt = stmt.where(SysAuditLog.created_at <= f"{date_to} 23:59:59")

    # 总数（同一条件；distinct 防左联一对多——username 唯一，实际不会膨胀）
    count_stmt = select(SysAuditLog.id).outerjoin(
        SysUser, SysUser.username == SysAuditLog.username)
    if kw:
        like = f"%{kw}%"
        count_stmt = count_stmt.where(
            (SysAuditLog.username.like(like)) | (SysUser.display_name.like(like)))
    if menu.strip():
        count_stmt = count_stmt.where(SysAuditLog.menu.like(f"%{menu.strip()}%"))
    if action.strip():
        count_stmt = count_stmt.where(SysAuditLog.action == action.strip())
    if ip.strip():
        like_ip = f"%{ip.strip()}%"
        count_stmt = count_stmt.where(
            (SysAuditLog.ip.like(like_ip)) | (SysAuditLog.mac.like(like_ip)))
    if date_from:
        count_stmt = count_stmt.where(SysAuditLog.created_at >= f"{date_from} 00:00:00")
    if date_to:
        count_stmt = count_stmt.where(SysAuditLog.created_at <= f"{date_to} 23:59:59")
    total = len(db.execute(count_stmt).scalars().all())

    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    rows = db.execute(
        stmt.order_by(SysAuditLog.id.desc())
        .limit(page_size).offset((page - 1) * page_size)
    ).all()

    items = [
        AuditLogInfo(
            id=log.id,
            time=log.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            username=log.username,
            display_name=display_name,
            department=department,
            ip=log.ip,
            mac=log.mac,
            menu=log.menu,
            action=log.action,
            detail=log.detail,
        )
        for log, display_name, department in rows
    ]
    return AuditLogListResponse(total=total, page=page, page_size=page_size, items=items)


@router.get("/api/audit-logs/menus", response_model=list[str],
            summary="操作菜单去重清单（查询下拉用）")
def list_audit_menus(
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(SysAuditLog.menu)
        .where(SysAuditLog.menu.isnot(None))
        .distinct()
        .order_by(SysAuditLog.menu)
    ).scalars().all()
    return [r for r in rows if r]
