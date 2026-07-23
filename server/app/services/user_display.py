# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 修改人姓名解析公共组件

背景：
    各业务表仅记录 updated_by（用户编号，如 admin/op01），页面要求按"人员姓名"
    展示。本组件提供批量解析能力，避免列表接口逐行查库（N+1）。

解析口径（与审计日志查询的姓名口径一致）：
    - "system-init"（初始导入占位）→ "系统初始化"；
    - sys_user 存在且 display_name 非空 → display_name；
    - 其余（用户已删除 / display_name 为空 / updated_by 为空）→ 回退原 updated_by。

作者：技术部
版本：1.0.0
日期：2026-07-23
"""

from typing import Dict, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import SysUser

# 初始导入占位修改人的展示名
SYSTEM_INIT_USERNAME = "system-init"
SYSTEM_INIT_DISPLAY_NAME = "系统初始化"


def resolve_display_names(db: Session, usernames: Iterable[Optional[str]]) -> Dict[str, str]:
    """
    批量解析 用户编号 → 展示姓名（一次查询，避免 N+1）

    Args:
        db: 平台库会话
        usernames: updated_by 原始值集合（可含 None / 重复值）

    Returns:
        dict: {用户编号: 展示姓名}；入参中的 None 不会出现在结果键中
    """
    result: Dict[str, str] = {}
    todo = set()
    for u in usernames:
        if u is None or u in result:
            continue
        if u == SYSTEM_INIT_USERNAME:
            result[u] = SYSTEM_INIT_DISPLAY_NAME
        else:
            todo.add(u)

    if todo:
        rows = db.execute(
            select(SysUser.username, SysUser.display_name)
            .where(SysUser.username.in_(todo))
        ).all()
        name_map = {username: display_name for username, display_name in rows}
        for u in todo:
            display = name_map.get(u)
            # 用户不存在或姓名为空 → 回退原编号
            result[u] = display if display else u

    return result
