# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 系统配置接口（二期 M2：科目取价规则）

    GET    /api/admin/system/subject-price-rules         规则列表（admin/operator）
    POST   /api/admin/system/subject-price-rules         新增规则（admin）
    PUT    /api/admin/system/subject-price-rules/{id}    修改规则（admin）
    DELETE /api/admin/system/subject-price-rules/{id}    删除规则（admin）

热生效说明：
    M2 任务每次执行时现取本表启用规则（无缓存），规则变更对**新创建**的
    核对任务立即生效，历史任务归档结果不受影响。全部写操作审计留痕。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    SubjectPriceRuleCreateRequest,
    SubjectPriceRuleInfo,
    SubjectPriceRuleUpdateRequest,
    SystemParamInfo,
    SystemParamsUpdateRequest,
)
from app.core.deps import get_db, require_roles
from app.models.entities import SysConfig, SysSubjectPriceRule, SysUser
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin/system", tags=["系统配置"])


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _to_info(r: SysSubjectPriceRule) -> SubjectPriceRuleInfo:
    return SubjectPriceRuleInfo(
        id=r.id, subject_prefix=r.subject_prefix, price_field=r.price_field,
        description=r.description, note=r.note, enabled=r.enabled,
        sort_order=r.sort_order, updated_by=r.updated_by,
        updated_at=r.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _check_prefix_unique(db: Session, prefix: str, exclude_id: Optional[int] = None) -> None:
    stmt = select(SysSubjectPriceRule).where(SysSubjectPriceRule.subject_prefix == prefix)
    if exclude_id is not None:
        stmt = stmt.where(SysSubjectPriceRule.id != exclude_id)
    if db.execute(stmt).scalars().first() is not None:
        raise HTTPException(
            status_code=400,
            detail=f"科目前缀 {prefix} 已存在取价规则，请修改已有记录或先删除",
        )


@router.get("/subject-price-rules", response_model=list[SubjectPriceRuleInfo],
            summary="科目取价规则列表")
def list_rules(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(SysSubjectPriceRule)
        .order_by(SysSubjectPriceRule.sort_order, SysSubjectPriceRule.id)
    ).scalars().all()
    return [_to_info(r) for r in rows]


@router.post("/subject-price-rules", response_model=SubjectPriceRuleInfo,
             summary="新增科目取价规则")
def create_rule(
    body: SubjectPriceRuleCreateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    prefix = body.subject_prefix.strip()
    field = body.price_field.strip()
    if not prefix:
        raise HTTPException(status_code=400, detail="科目前缀去空格后不能为空")
    if not field:
        raise HTTPException(status_code=400, detail="取价字段去空格后不能为空")
    _check_prefix_unique(db, prefix)

    row = SysSubjectPriceRule(
        subject_prefix=prefix, price_field=field,
        description=body.description, note=body.note,
        enabled=body.enabled, sort_order=body.sort_order,
        updated_by=user.username,
    )
    db.add(row)
    db.flush()
    record_audit(db, user.username, "sys_subject_rule_create", "sys_subject_price_rule",
                 str(row.id),
                 f"新增科目取价规则 {prefix}→{field}（{'启用' if body.enabled else '停用'}，排序 {body.sort_order}）",
                 _client_ip(request))
    db.commit()
    return _to_info(row)


@router.put("/subject-price-rules/{rule_id}", response_model=SubjectPriceRuleInfo,
            summary="修改科目取价规则")
def update_rule(
    rule_id: int,
    body: SubjectPriceRuleUpdateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = db.get(SysSubjectPriceRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"科目取价规则不存在: id={rule_id}")

    if body.subject_prefix is not None and body.subject_prefix.strip() != row.subject_prefix:
        new_prefix = body.subject_prefix.strip()
        if not new_prefix:
            raise HTTPException(status_code=400, detail="科目前缀去空格后不能为空")
        _check_prefix_unique(db, new_prefix, exclude_id=rule_id)

    changes = []
    if body.subject_prefix is not None and body.subject_prefix.strip() != row.subject_prefix:
        changes.append(f"科目前缀 {row.subject_prefix}→{body.subject_prefix.strip()}")
        row.subject_prefix = body.subject_prefix.strip()
    if body.price_field is not None and body.price_field.strip() != row.price_field:
        if not body.price_field.strip():
            raise HTTPException(status_code=400, detail="取价字段去空格后不能为空")
        changes.append(f"取价字段 {row.price_field}→{body.price_field.strip()}")
        row.price_field = body.price_field.strip()
    if body.description is not None and body.description != row.description:
        changes.append(f"科目说明 {row.description or '(空)'}→{body.description or '(空)'}")
        row.description = body.description
    if body.note is not None and body.note != row.note:
        changes.append("口径提示语已更新")
        row.note = body.note
    if body.enabled is not None and body.enabled != row.enabled:
        changes.append(f"启用 {row.enabled}→{body.enabled}")
        row.enabled = body.enabled
    if body.sort_order is not None and body.sort_order != row.sort_order:
        changes.append(f"排序号 {row.sort_order}→{body.sort_order}")
        row.sort_order = body.sort_order
    if not changes:
        return _to_info(row)

    row.updated_by = user.username
    record_audit(db, user.username, "sys_subject_rule_update", "sys_subject_price_rule",
                 str(row.id), f"修改科目取价规则 id={row.id}: " + "；".join(changes),
                 _client_ip(request))
    db.commit()
    return _to_info(row)


@router.delete("/subject-price-rules/{rule_id}", summary="删除科目取价规则")
def delete_rule(
    rule_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = db.get(SysSubjectPriceRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"科目取价规则不存在: id={rule_id}")

    detail = (f"删除科目取价规则 {row.subject_prefix}→{row.price_field}"
              f"（{'启用' if row.enabled else '停用'}）")
    db.delete(row)
    record_audit(db, user.username, "sys_subject_rule_delete", "sys_subject_price_rule",
                 str(rule_id), detail, _client_ip(request))
    db.commit()
    return {"message": f"已删除科目取价规则 id={rule_id}"}


# =============================================================================
# 系统参数（二期 DS-F5：data_ready_time / buffer_minutes 等，存 sys_config）
# =============================================================================

def _validate_param_value(key: str, value: str) -> str:
    """系统参数值校验（非法抛 400 中文），返回规范化后的值"""
    v = (value or "").strip()
    if key == "data_ready_time":
        import re
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", v)
        if not m or not (0 <= int(m.group(1)) <= 23 and 0 <= int(m.group(2)) <= 59):
            raise HTTPException(status_code=400, detail=f"data_ready_time 格式非法: {value}，应为 HH:MM（如 17:30）")
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    if key == "buffer_minutes":
        if not v.isdigit() or not (0 <= int(v) <= 180):
            raise HTTPException(status_code=400, detail=f"buffer_minutes 非法: {value}，应为 0-180 的整数分钟")
        return v
    if key == "schedule_retry_delay_minutes":
        try:
            f = float(v)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"schedule_retry_delay_minutes 非法: {value}，应为正数（分钟）")
        if f <= 0 or f > 1440:
            raise HTTPException(status_code=400, detail=f"schedule_retry_delay_minutes 非法: {value}，应为 (0, 1440] 分钟")
        return v
    raise HTTPException(status_code=400, detail=f"未知系统参数键: {key}，支持 data_ready_time/buffer_minutes/schedule_retry_delay_minutes")


@router.get("/params", response_model=list[SystemParamInfo], summary="系统参数列表")
def list_params(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(SysConfig).order_by(SysConfig.id)).scalars().all()
    return [
        SystemParamInfo(
            param_key=r.param_key, param_value=r.param_value, description=r.description,
            updated_by=r.updated_by, updated_at=r.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        for r in rows
    ]


@router.put("/params", response_model=list[SystemParamInfo], summary="批量修改系统参数（admin）")
def update_params(
    body: SystemParamsUpdateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    if not body.values:
        raise HTTPException(status_code=400, detail="values 不能为空（至少一项参数键值对）")
    changes = []
    for key, value in body.values.items():
        v = _validate_param_value(key, value)
        row = db.execute(select(SysConfig).where(SysConfig.param_key == key)).scalars().first()
        if row is None:
            row = SysConfig(param_key=key, param_value=v, description="", updated_by=user.username)
            db.add(row)
            changes.append(f"新增 {key}={v}")
        elif row.param_value != v:
            changes.append(f"{key} {row.param_value}→{v}")
            row.param_value = v
            row.updated_by = user.username
    if changes:
        record_audit(db, user.username, "sys_params_update", "sys_config", None,
                     "修改系统参数: " + "；".join(changes), _client_ip(request))
    db.commit()
    return list_params(user=user, db=db)
