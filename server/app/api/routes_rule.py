# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 规则配置中心接口（一期）

    GET    /api/rules/mappings              映射规则列表（admin/operator）
    POST   /api/rules/mappings              新增映射规则（admin）
    PUT    /api/rules/mappings/{id}         修改映射规则（admin）
    DELETE /api/rules/mappings/{id}         删除映射规则（admin）
    GET    /api/rules/bulk-products         特殊产品清单（admin/operator）
    POST   /api/rules/bulk-products         新增特殊产品（admin）
    PUT    /api/rules/bulk-products/{id}    修改特殊产品（admin）
    DELETE /api/rules/bulk-products/{id}    删除特殊产品（admin）
    GET    /api/rules/thresholds            阈值参数列表（admin/operator）
    PUT    /api/rules/thresholds/{key}      修改阈值（admin；数值范围校验）
    GET    /api/rules/export                按小程序 config JSON 结构导出启用规则（admin/operator）
    POST   /api/rules/import                按同结构导入，整体替换映射与特殊产品（admin，单事务）

热生效说明：
    M1 任务每次执行时由 DbRuleProvider 现取规则库（无缓存），
    本模块的规则变更对**新创建**的核对任务立即生效，历史任务归档结果不受影响。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    BulkProductCreateRequest,
    BulkProductInfo,
    BulkProductUpdateRequest,
    MappingCreateRequest,
    MappingInfo,
    MappingUpdateRequest,
    RuleImportRequest,
    RuleImportResponse,
    ThresholdInfo,
    ThresholdUpdateRequest,
)
from app.core.deps import get_db, require_roles
from app.models.entities import (
    RuleBulkProduct,
    RuleCodeMapping,
    RuleThreshold,
    SysUser,
)
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rules", tags=["规则配置"])

# 阈值参数键与合法取值范围（value 闭区间）
THRESHOLD_RULES = {
    "diff_pct": (0.01, 100.0, "差异阈值(%)，超过标浅红并计入差异统计"),
    "fuzzy_sim": (0.0, 1.0, "模糊匹配相似度阈值(0-1)"),
    "price_tol": (0.0, 1.0, "估值价格核对容差（M2 预留）"),
}

# 导出 JSON 固定字段（与验收基准 fund_reconciler_config.json 同构）
EXPORT_DESCRIPTION = "基金资产与净值核对工具配置文件"
EXPORT_VERSION = "1.1.0"
EXPORT_OUTPUT_SETTINGS = {
    "auto_timestamp": True,
    "default_filename": "基金资产与净值核对结果_{date}.xlsx",
}

# 特殊产品行填充色校验（6 位十六进制，不含 #）
COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")
COLOR_ERROR_MSG = "颜色须为6位十六进制（不含#），如 FFC000"
DEFAULT_SPECIAL_COLOR = "FFC000"


def _normalize_color(value: Optional[str]) -> Optional[str]:
    """颜色入参规范化：None → None（表示不修改/缺省）；非法 → 400 中文"""
    if value is None:
        return None
    v = value.strip()
    if not COLOR_RE.match(v):
        raise HTTPException(status_code=400, detail=COLOR_ERROR_MSG)
    return v.upper()


# =============================================================================
# 工具函数
# =============================================================================

def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _to_mapping_info(m: RuleCodeMapping) -> MappingInfo:
    return MappingInfo(
        id=m.id,
        source_code=m.source_code,
        target_code=m.target_code,
        enabled=m.enabled,
        updated_by=m.updated_by,
        updated_at=m.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _to_bulk_info(b: RuleBulkProduct) -> BulkProductInfo:
    return BulkProductInfo(
        id=b.id,
        product_code=b.product_code,
        note=b.description,
        color=(b.color or DEFAULT_SPECIAL_COLOR).upper(),
        enabled=b.enabled,
        updated_by=b.updated_by,
        updated_at=b.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _to_threshold_info(t: RuleThreshold) -> ThresholdInfo:
    return ThresholdInfo(
        param_key=t.param_key,
        param_value=t.param_value,
        description=t.description,
        updated_by=t.updated_by,
        updated_at=t.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _validate_threshold_value(param_key: str, value: float) -> None:
    """校验阈值取值范围，非法抛 400（中文提示，含合法区间）"""
    if param_key not in THRESHOLD_RULES:
        raise HTTPException(
            status_code=400,
            detail=f"未知阈值参数键: {param_key}，支持: {', '.join(THRESHOLD_RULES.keys())}",
        )
    low, high, label = THRESHOLD_RULES[param_key]
    if not (low <= value <= high):
        raise HTTPException(
            status_code=400,
            detail=f"阈值 {param_key}（{label}）取值 {value} 超出合法范围 [{low}, {high}]",
        )


def _check_mapping_codes(source_code: str, target_code: str) -> None:
    """映射代码语义校验：去空格后非空、源与目标不得相同"""
    if not source_code.strip() or not target_code.strip():
        raise HTTPException(status_code=400, detail="映射代码去空格后不能为空")
    if source_code.strip() == target_code.strip():
        raise HTTPException(
            status_code=400,
            detail=f"原代码与映射后代码相同（{source_code.strip()}），无映射意义",
        )


def _check_mapping_source_unique(db: Session, source_code: str, exclude_id: Optional[int] = None) -> None:
    """同一原代码仅允许存在一条映射（避免规则库取值歧义）"""
    stmt = select(RuleCodeMapping).where(RuleCodeMapping.source_code == source_code.strip())
    if exclude_id is not None:
        stmt = stmt.where(RuleCodeMapping.id != exclude_id)
    if db.execute(stmt).scalars().first() is not None:
        raise HTTPException(
            status_code=400,
            detail=f"原代码 {source_code.strip()} 已存在映射规则，请修改已有记录或先删除",
        )


# =============================================================================
# 映射规则（rule_code_mapping）
# =============================================================================

@router.get("/mappings", response_model=list[MappingInfo], summary="映射规则列表")
def list_mappings(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(RuleCodeMapping).order_by(RuleCodeMapping.id)
    ).scalars().all()
    return [_to_mapping_info(m) for m in rows]


@router.post("/mappings", response_model=MappingInfo, summary="新增映射规则")
def create_mapping(
    body: MappingCreateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    source = body.source_code.strip()
    target = body.target_code.strip()
    _check_mapping_codes(source, target)
    _check_mapping_source_unique(db, source)

    row = RuleCodeMapping(
        source_code=source, target_code=target,
        enabled=body.enabled, updated_by=user.username,
    )
    db.add(row)
    db.flush()
    record_audit(db, user.username, "rule_mapping_create", "rule_code_mapping", str(row.id),
                 f"新增映射 {source}→{target}（{'启用' if body.enabled else '停用'}）",
                 _client_ip(request))
    db.commit()
    return _to_mapping_info(row)


@router.put("/mappings/{mapping_id}", response_model=MappingInfo, summary="修改映射规则")
def update_mapping(
    mapping_id: int,
    body: MappingUpdateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = db.get(RuleCodeMapping, mapping_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"映射规则不存在: id={mapping_id}")

    new_source = body.source_code.strip() if body.source_code is not None else row.source_code
    new_target = body.target_code.strip() if body.target_code is not None else row.target_code
    _check_mapping_codes(new_source, new_target)
    if new_source != row.source_code:
        _check_mapping_source_unique(db, new_source, exclude_id=mapping_id)

    changes = []
    if new_source != row.source_code:
        changes.append(f"原代码 {row.source_code}→{new_source}")
        row.source_code = new_source
    if new_target != row.target_code:
        changes.append(f"映射后代码 {row.target_code}→{new_target}")
        row.target_code = new_target
    if body.enabled is not None and body.enabled != row.enabled:
        changes.append(f"启用 {row.enabled}→{body.enabled}")
        row.enabled = body.enabled
    if not changes:
        return _to_mapping_info(row)

    row.updated_by = user.username
    record_audit(db, user.username, "rule_mapping_update", "rule_code_mapping", str(row.id),
                 f"修改映射 id={row.id}: " + "；".join(changes), _client_ip(request))
    db.commit()
    return _to_mapping_info(row)


@router.delete("/mappings/{mapping_id}", summary="删除映射规则")
def delete_mapping(
    mapping_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = db.get(RuleCodeMapping, mapping_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"映射规则不存在: id={mapping_id}")

    detail = f"删除映射 {row.source_code}→{row.target_code}（{'启用' if row.enabled else '停用'}）"
    db.delete(row)
    record_audit(db, user.username, "rule_mapping_delete", "rule_code_mapping",
                 str(mapping_id), detail, _client_ip(request))
    db.commit()
    return {"message": f"已删除映射规则 id={mapping_id}"}


# =============================================================================
# 特殊产品清单（rule_bulk_product，表名沿用）
# =============================================================================

@router.get("/bulk-products", response_model=list[BulkProductInfo], summary="特殊产品清单")
def list_bulk_products(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(RuleBulkProduct).order_by(RuleBulkProduct.id)
    ).scalars().all()
    return [_to_bulk_info(b) for b in rows]


@router.post("/bulk-products", response_model=BulkProductInfo, summary="新增特殊产品")
def create_bulk_product(
    body: BulkProductCreateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    code = body.product_code.strip()
    if not code:
        raise HTTPException(status_code=400, detail="产品代码去空格后不能为空")
    exists = db.execute(
        select(RuleBulkProduct).where(RuleBulkProduct.product_code == code)
    ).scalars().first()
    if exists is not None:
        raise HTTPException(status_code=400, detail=f"特殊产品代码已存在: {code}")

    note = body.note.strip() if body.note and body.note.strip() else None
    color = _normalize_color(body.color) or DEFAULT_SPECIAL_COLOR
    row = RuleBulkProduct(
        product_code=code, description=note, color=color,
        enabled=body.enabled, updated_by=user.username,
    )
    db.add(row)
    db.flush()
    record_audit(db, user.username, "rule_bulk_create", "rule_bulk_product", str(row.id),
                 f"新增特殊产品 {code}（{'启用' if body.enabled else '停用'}，"
                 f"颜色 {color}，差异说明 {note or '(默认)'}）",
                 _client_ip(request))
    db.commit()
    return _to_bulk_info(row)


@router.put("/bulk-products/{bulk_id}", response_model=BulkProductInfo, summary="修改特殊产品")
def update_bulk_product(
    bulk_id: int,
    body: BulkProductUpdateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = db.get(RuleBulkProduct, bulk_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"特殊产品不存在: id={bulk_id}")

    changes = []
    if body.product_code is not None and body.product_code.strip() != row.product_code:
        new_code = body.product_code.strip()
        if not new_code:
            raise HTTPException(status_code=400, detail="产品代码去空格后不能为空")
        exists = db.execute(
            select(RuleBulkProduct).where(
                RuleBulkProduct.product_code == new_code,
                RuleBulkProduct.id != bulk_id,
            )
        ).scalars().first()
        if exists is not None:
            raise HTTPException(status_code=400, detail=f"特殊产品代码已存在: {new_code}")
        changes.append(f"产品代码 {row.product_code}→{new_code}")
        row.product_code = new_code
    if body.note is not None:
        new_note = body.note.strip() if body.note.strip() else None
        if new_note != row.description:
            changes.append(f"差异说明 {row.description or '(默认)'}→{new_note or '(默认)'}")
            row.description = new_note
    new_color = _normalize_color(body.color)
    if new_color is not None and new_color != (row.color or "").upper():
        changes.append(f"颜色 {row.color}→{new_color}")
        row.color = new_color
    if body.enabled is not None and body.enabled != row.enabled:
        changes.append(f"启用 {row.enabled}→{body.enabled}")
        row.enabled = body.enabled
    if not changes:
        return _to_bulk_info(row)

    row.updated_by = user.username
    record_audit(db, user.username, "rule_bulk_update", "rule_bulk_product", str(row.id),
                 f"修改特殊产品 id={row.id}: " + "；".join(changes), _client_ip(request))
    db.commit()
    return _to_bulk_info(row)


@router.delete("/bulk-products/{bulk_id}", summary="删除特殊产品")
def delete_bulk_product(
    bulk_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = db.get(RuleBulkProduct, bulk_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"特殊产品不存在: id={bulk_id}")

    detail = f"删除特殊产品 {row.product_code}（{'启用' if row.enabled else '停用'}）"
    db.delete(row)
    record_audit(db, user.username, "rule_bulk_delete", "rule_bulk_product",
                 str(bulk_id), detail, _client_ip(request))
    db.commit()
    return {"message": f"已删除特殊产品 id={bulk_id}"}


# =============================================================================
# 阈值参数（rule_threshold）
# =============================================================================

@router.get("/thresholds", response_model=list[ThresholdInfo], summary="阈值参数列表")
def list_thresholds(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(RuleThreshold).order_by(RuleThreshold.id)
    ).scalars().all()
    return [_to_threshold_info(t) for t in rows]


@router.put("/thresholds/{param_key}", response_model=ThresholdInfo, summary="修改阈值参数")
def update_threshold(
    param_key: str,
    body: ThresholdUpdateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    _validate_threshold_value(param_key, body.value)

    row = db.execute(
        select(RuleThreshold).where(RuleThreshold.param_key == param_key)
    ).scalars().first()
    if row is None:
        # 库中缺失的合法键允许补建（如历史库未含 price_tol 预留项）
        _low, _high, label = THRESHOLD_RULES[param_key]
        row = RuleThreshold(
            param_key=param_key, param_value=repr(body.value),
            description=label, updated_by=user.username,
        )
        db.add(row)
        db.flush()
        record_audit(db, user.username, "rule_threshold_update", "rule_threshold", param_key,
                     f"阈值 {param_key}: (新增){body.value}", _client_ip(request))
        db.commit()
        return _to_threshold_info(row)

    old_value = row.param_value
    row.param_value = repr(body.value)
    row.updated_by = user.username
    record_audit(db, user.username, "rule_threshold_update", "rule_threshold", param_key,
                 f"阈值 {param_key}: {old_value}→{body.value}", _client_ip(request))
    db.commit()
    return _to_threshold_info(row)


# =============================================================================
# 导入 / 导出（与小程序 fund_reconciler_config.json 结构同构）
# =============================================================================

@router.get("/export", summary="导出规则配置（小程序 config JSON 同构）")
def export_rules(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    mappings = db.execute(
        select(RuleCodeMapping).where(RuleCodeMapping.enabled.is_(True))
        .order_by(RuleCodeMapping.id)
    ).scalars().all()
    bulks = db.execute(
        select(RuleBulkProduct).where(RuleBulkProduct.enabled.is_(True))
        .order_by(RuleBulkProduct.id)
    ).scalars().all()
    thresholds = db.execute(select(RuleThreshold)).scalars().all()
    threshold_map = {t.param_key: t.param_value for t in thresholds}

    return {
        "description": EXPORT_DESCRIPTION,
        "version": EXPORT_VERSION,
        "rename_map": {m.source_code: m.target_code for m in mappings},
        # 新格式：对象数组（code/note/color）；旧格式键保留向下兼容
        "special_products": [
            {"code": b.product_code,
             "note": b.description,
             "color": (b.color or DEFAULT_SPECIAL_COLOR).upper()}
            for b in bulks
        ],
        "bulk_products": [b.product_code for b in bulks],
        "diff_threshold": float(threshold_map.get("diff_pct", 1.0)),
        "similarity_threshold": float(threshold_map.get("fuzzy_sim", 0.5)),
        "output_settings": EXPORT_OUTPUT_SETTINGS,
    }


@router.post("/import", response_model=RuleImportResponse,
             summary="导入规则配置（整体替换映射与特殊产品，单事务）")
def import_rules(
    body: RuleImportRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    # ---- 1. 全量校验（任何一项非法直接 400，不做任何写库） ----
    cleaned_map = {}
    for source, target in body.rename_map.items():
        s, t = str(source).strip(), str(target).strip()
        if not s or not t:
            raise HTTPException(
                status_code=400,
                detail=f"导入数据非法：映射存在空代码（{source!r}→{target!r}）",
            )
        if s == t:
            raise HTTPException(
                status_code=400,
                detail=f"导入数据非法：原代码与映射后代码相同（{s}），无映射意义",
            )
        if len(s) > 50 or len(t) > 50:
            raise HTTPException(
                status_code=400,
                detail=f"导入数据非法：映射代码超长（{s}→{t}，限 50 字符）",
            )
        cleaned_map[s] = t

    # ---- 特殊产品：special_products（新格式）优先，缺省回退 bulk_products（旧格式） ----
    cleaned_special = []   # [(code, note, color)]
    seen_special = set()
    if body.special_products is not None:
        for item in body.special_products:
            c = item.code.strip()
            if not c:
                raise HTTPException(status_code=400, detail="导入数据非法：特殊产品存在空代码")
            if len(c) > 50:
                raise HTTPException(
                    status_code=400, detail=f"导入数据非法：特殊产品代码超长（{c}，限 50 字符）")
            if c in seen_special:
                raise HTTPException(status_code=400, detail=f"导入数据非法：特殊产品代码重复（{c}）")
            color = _normalize_color(item.color) or DEFAULT_SPECIAL_COLOR
            note = item.note.strip() if item.note and item.note.strip() else None
            seen_special.add(c)
            cleaned_special.append((c, note, color))
    elif body.bulk_products is not None:
        for code in body.bulk_products:
            c = str(code).strip()
            if not c:
                raise HTTPException(status_code=400, detail="导入数据非法：特殊产品存在空代码")
            if len(c) > 50:
                raise HTTPException(
                    status_code=400, detail=f"导入数据非法：特殊产品代码超长（{c}，限 50 字符）")
            if c in seen_special:
                raise HTTPException(status_code=400, detail=f"导入数据非法：特殊产品代码重复（{c}）")
            seen_special.add(c)
            cleaned_special.append((c, None, DEFAULT_SPECIAL_COLOR))
    else:
        raise HTTPException(
            status_code=400,
            detail="导入数据非法：请提供 special_products（新格式）或 bulk_products（旧格式）")

    threshold_updates = {}
    if body.diff_threshold is not None:
        _validate_threshold_value("diff_pct", body.diff_threshold)
        threshold_updates["diff_pct"] = body.diff_threshold
    if body.similarity_threshold is not None:
        _validate_threshold_value("fuzzy_sim", body.similarity_threshold)
        threshold_updates["fuzzy_sim"] = body.similarity_threshold

    # ---- 2. 单事务整体替换（失败回滚，不留半截状态） ----
    mappings_before = len(db.execute(select(RuleCodeMapping)).scalars().all())
    bulk_before = len(db.execute(select(RuleBulkProduct)).scalars().all())
    try:
        for row in db.execute(select(RuleCodeMapping)).scalars().all():
            db.delete(row)
        for row in db.execute(select(RuleBulkProduct)).scalars().all():
            db.delete(row)
        # 先 flush 执行删除，再插入新行，避免唯一约束冲突；
        # flush 不提交事务，整体仍由末尾 commit / 异常 rollback 保证原子性
        db.flush()
        for s, t in cleaned_map.items():
            db.add(RuleCodeMapping(source_code=s, target_code=t,
                                   enabled=True, updated_by=user.username))
        for c, note, color in cleaned_special:
            db.add(RuleBulkProduct(product_code=c, description=note, color=color,
                                   enabled=True, updated_by=user.username))

        threshold_details = []
        for key, value in threshold_updates.items():
            row = db.execute(
                select(RuleThreshold).where(RuleThreshold.param_key == key)
            ).scalars().first()
            if row is None:
                _low, _high, label = THRESHOLD_RULES[key]
                db.add(RuleThreshold(param_key=key, param_value=repr(value),
                                     description=label, updated_by=user.username))
                threshold_details.append(f"{key}: (新增){value}")
            else:
                threshold_details.append(f"{key}: {row.param_value}→{value}")
                row.param_value = repr(value)
                row.updated_by = user.username

        audit_detail = (
            f"导入规则配置：映射 {mappings_before}→{len(cleaned_map)} 条，"
            f"特殊产品 {bulk_before}→{len(cleaned_special)} 个"
        )
        if threshold_details:
            audit_detail += "；阈值 " + "，".join(threshold_details)
        record_audit(db, user.username, "rule_import", "rule_config", None,
                     audit_detail, _client_ip(request))
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error(f"规则配置导入失败已回滚: {e}")
        raise HTTPException(status_code=500, detail=f"规则配置导入失败，已回滚: {e}")

    return RuleImportResponse(
        message=f"导入完成：映射 {mappings_before}→{len(cleaned_map)} 条，"
                f"特殊产品 {bulk_before}→{len(cleaned_special)} 个，全部启用",
        mappings_before=mappings_before,
        mappings_after=len(cleaned_map),
        bulk_before=bulk_before,
        bulk_after=len(cleaned_special),
        thresholds_updated=list(threshold_updates.keys()),
    )
