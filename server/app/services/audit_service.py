# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 审计服务

覆盖操作（一期）：登录、上传建任务、下载结果、用户管理（新增/修改/重置密码/删除）。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.entities import SysAuditLog

logger = logging.getLogger(__name__)


def record_audit(
    db: Session,
    username: str,
    action: str,
    object_type: Optional[str] = None,
    object_id: Optional[str] = None,
    detail: Optional[str] = None,
    ip: Optional[str] = None,
) -> None:
    """
    写入一条审计日志（随调用方事务提交）

    Args:
        db: 数据库会话
        username: 操作人
        action: 操作类型（如 login / upload_create_job / download / user_create ...）
        object_type: 操作对象类型（如 user / recon_job）
        object_id: 操作对象标识
        detail: 操作明细
        ip: 来源 IP
    """
    db.add(SysAuditLog(
        username=username,
        action=action,
        object_type=object_type,
        object_id=object_id,
        detail=detail,
        ip=ip,
    ))
    logger.info(f"审计: {username} {action} {object_type or ''}{object_id or ''} {detail or ''}")
