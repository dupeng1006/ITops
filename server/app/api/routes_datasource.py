# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据源管理接口（二期）

    GET    /api/datasources                  数据源列表（admin/operator，密码掩码）
    POST   /api/datasources                  新增数据源（admin，密码加密落库）
    PUT    /api/datasources/{id}             修改数据源（admin；密码留空表示不修改）
    DELETE /api/datasources/{id}             删除数据源（admin；被模板引用时 400）
    POST   /api/datasources/{id}/test        测试连接（admin/operator，中文友好报错）

    GET    /api/query-templates              查询模板列表（admin/operator）
    POST   /api/query-templates              新增模板（admin，SQL Guard 保存时校验）
    PUT    /api/query-templates/{id}         修改模板（admin，SQL Guard 保存时校验）
    DELETE /api/query-templates/{id}         删除模板（admin）
    POST   /api/query-templates/{id}/preview 预览（admin/operator，前 N 行 + 列名）

安全约束：
    - 密码 Fernet 加密存储；读取/导出永不返回明文（恒定掩码 ********）；
    - 全部写操作 + 连接测试 + 预览执行均审计留痕；
    - SQL 保存时校验一次、执行前再校验一次（双校验）。

作者：技术部
版本：1.0.0
日期：2026-07-18
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    DatasourceCreateRequest,
    DatasourceInfo,
    DatasourceUpdateRequest,
    QueryTemplateCreateRequest,
    QueryTemplateInfo,
    QueryTemplateUpdateRequest,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TestConnectionResponse,
)
from app.core.config import get_settings
from app.core.crypto import PASSWORD_MASK, decrypt_secret, encrypt_secret
from app.core.deps import get_db, require_roles
from app.datasource.base import FetchContext
from app.datasource.db_adapter import (
    ConnectionSpec,
    DatasourceError,
    execute_query,
    test_connection,
    validate_params,
)
from app.datasource.drivers import (
    ALL_DB_TYPES,
    DB_TYPE_LABELS,
    PUBLIC_DB_TYPES,
    DatasourceConfigError,
    build_connection_url,
)
from app.datasource.sql_guard import SqlGuardError, validate_select_only
from app.models.entities import DsConnection, DsQueryTemplate, SysUser
from app.services.audit_service import record_audit
from app.services.user_display import resolve_display_names

logger = logging.getLogger(__name__)

MENU_DS = "数据源管理 · 连接配置"
MENU_TPL = "数据源管理 · 查询模板"

router = APIRouter(tags=["数据源管理"])

# 所属模块取值（页面下拉；预留扩展，新增模块零代码）
# custom：数据字典查询生成的自助查询模板
TEMPLATE_MODULES = ("m1_fund", "m1_netvalue", "m2_system", "m2_valuation", "m3_member", "custom")


# =============================================================================
# 工具函数
# =============================================================================

def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _to_ds_info(ds: DsConnection, name_map: Optional[dict] = None) -> DatasourceInfo:
    extra = None
    if ds.extra_json:
        try:
            extra = json.loads(ds.extra_json)
        except json.JSONDecodeError:
            extra = None
    return DatasourceInfo(
        id=ds.id, name=ds.name, db_type=ds.db_type,
        host=ds.host, port=ds.port, db_name=ds.db_name,
        service_name=ds.service_name, sid=ds.sid,
        username=ds.username, password=PASSWORD_MASK,
        extra=extra, enabled=ds.enabled,
        updated_by=ds.updated_by,
        updated_by_name=(name_map.get(ds.updated_by) if name_map else None),
        updated_at=ds.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _to_tpl_info(db: Session, tpl: DsQueryTemplate,
                 name_map: Optional[dict] = None) -> QueryTemplateInfo:
    ds = db.get(DsConnection, tpl.ds_id)
    column_map = json.loads(tpl.column_map_json) if tpl.column_map_json else None
    params_def = json.loads(tpl.params_json) if tpl.params_json else None
    return QueryTemplateInfo(
        id=tpl.id, name=tpl.name, module=tpl.module, ds_id=tpl.ds_id,
        ds_name=ds.name if ds else None,
        sql_text=tpl.sql_text, column_map=column_map, params_def=params_def,
        enabled=tpl.enabled, updated_by=tpl.updated_by,
        updated_by_name=(name_map.get(tpl.updated_by) if name_map else None),
        updated_at=tpl.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _build_spec(ds: DsConnection) -> ConnectionSpec:
    """由实体构造连接规格（解密密码，仅内存使用）"""
    try:
        password = decrypt_secret(ds.password_enc)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    extra = {}
    if ds.extra_json:
        try:
            extra = json.loads(ds.extra_json)
        except json.JSONDecodeError:
            extra = {}
    return ConnectionSpec(
        db_type=ds.db_type, host=ds.host, port=ds.port,
        username=ds.username, password=password,
        db_name=ds.db_name, service_name=ds.service_name, sid=ds.sid,
        extra=extra,
    )


def _validate_ds_fields(db_type: str, host: Optional[str], port: Optional[int],
                        db_name: Optional[str], service_name: Optional[str],
                        sid: Optional[str], username: Optional[str]) -> None:
    """保存前字段完整性校验（复用 drivers 的 URL 构造做干跑，密码用占位符）

    类型范围取 ALL_DB_TYPES：含 sqlite 内部测试方言（页面下拉不展示，
    供自动化测试与部署冒烟使用；生产页面仅暴露 PUBLIC_DB_TYPES 五种）。
    """
    if db_type not in ALL_DB_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"数据源类型非法: {db_type}，支持: {', '.join(PUBLIC_DB_TYPES)}")
    try:
        build_connection_url(db_type, host=host, port=port, username=username,
                             password="***", db_name=db_name,
                             service_name=service_name, sid=sid)
    except DatasourceConfigError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _validate_tpl_fields(db: Session, module: str, ds_id: int, sql_text: str,
                         params_def: Optional[dict]) -> None:
    """模板保存校验：模块/数据源存在性/SQL Guard/参数定义结构"""
    if module not in TEMPLATE_MODULES:
        raise HTTPException(
            status_code=400,
            detail=f"所属模块非法: {module}，支持: {', '.join(TEMPLATE_MODULES)}")
    ds = db.get(DsConnection, ds_id)
    if ds is None:
        raise HTTPException(status_code=400, detail=f"数据源不存在: id={ds_id}")
    try:
        validate_select_only(sql_text)
    except SqlGuardError as e:
        raise HTTPException(status_code=400, detail=f"SQL 安全校验未通过：{e}")
    if params_def is not None:
        for pname, spec in params_def.items():
            if not isinstance(spec, dict):
                raise HTTPException(
                    status_code=400, detail=f"参数定义非法：{pname} 应为对象（含 type/required/label）")
            ptype = spec.get("type", "string")
            if ptype not in ("string", "number", "integer", "date"):
                raise HTTPException(
                    status_code=400,
                    detail=f"参数 {pname} 类型非法: {ptype}，支持: string/number/integer/date")


def _get_ds_or_404(db: Session, ds_id: int) -> DsConnection:
    ds = db.get(DsConnection, ds_id)
    if ds is None:
        raise HTTPException(status_code=404, detail=f"数据源不存在: id={ds_id}")
    return ds


def _get_tpl_or_404(db: Session, tpl_id: int) -> DsQueryTemplate:
    tpl = db.get(DsQueryTemplate, tpl_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"查询模板不存在: id={tpl_id}")
    return tpl


def _check_ds_name_unique(db: Session, name: str, exclude_id: Optional[int] = None) -> None:
    stmt = select(DsConnection).where(DsConnection.name == name)
    if exclude_id is not None:
        stmt = stmt.where(DsConnection.id != exclude_id)
    if db.execute(stmt).scalars().first() is not None:
        raise HTTPException(status_code=400, detail=f"数据源名称已存在: {name}")


def _check_tpl_name_unique(db: Session, name: str, exclude_id: Optional[int] = None) -> None:
    stmt = select(DsQueryTemplate).where(DsQueryTemplate.name == name)
    if exclude_id is not None:
        stmt = stmt.where(DsQueryTemplate.id != exclude_id)
    if db.execute(stmt).scalars().first() is not None:
        raise HTTPException(status_code=400, detail=f"模板名称已存在: {name}")


# =============================================================================
# 数据源连接配置
# =============================================================================

@router.get("/api/datasources", response_model=list[DatasourceInfo], summary="数据源列表")
def list_datasources(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(DsConnection).order_by(DsConnection.id)).scalars().all()
    return [_to_ds_info(ds, resolve_display_names(db, (x.updated_by for x in rows)))
            for ds in rows]


@router.post("/api/datasources", response_model=DatasourceInfo, summary="新增数据源")
def create_datasource(
    body: DatasourceCreateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    db_type = body.db_type.strip().lower()
    _check_ds_name_unique(db, name)
    _validate_ds_fields(db_type, body.host, body.port, body.db_name,
                        body.service_name, body.sid, body.username)

    row = DsConnection(
        name=name, db_type=db_type,
        host=body.host.strip() if body.host else None,
        port=body.port,
        db_name=body.db_name.strip() if body.db_name else None,
        service_name=body.service_name.strip() if body.service_name else None,
        sid=body.sid.strip() if body.sid else None,
        username=body.username.strip(),
        password_enc=encrypt_secret(body.password),
        extra_json=json.dumps(body.extra, ensure_ascii=False) if body.extra else None,
        enabled=body.enabled, updated_by=user.username,
    )
    db.add(row)
    db.flush()
    record_audit(db, user.username, "ds_create", "ds_connection", str(row.id),
                 f"新增数据源 {name}（{DB_TYPE_LABELS[db_type]} {body.host or ''}）", _client_ip(request), menu=MENU_DS)
    db.commit()
    return _to_ds_info(row, resolve_display_names(db, [row.updated_by]))


@router.put("/api/datasources/{ds_id}", response_model=DatasourceInfo, summary="修改数据源")
def update_datasource(
    ds_id: int,
    body: DatasourceUpdateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = _get_ds_or_404(db, ds_id)

    new_type = body.db_type.strip().lower() if body.db_type is not None else row.db_type
    new_host = body.host.strip() if body.host is not None else row.host
    new_port = body.port if body.port is not None else row.port
    new_db_name = body.db_name.strip() if body.db_name is not None else row.db_name
    new_service = body.service_name.strip() if body.service_name is not None else row.service_name
    new_sid = body.sid.strip() if body.sid is not None else row.sid
    new_username = body.username.strip() if body.username is not None else row.username
    if body.name is not None and body.name.strip() != row.name:
        _check_ds_name_unique(db, body.name.strip(), exclude_id=ds_id)
    _validate_ds_fields(new_type, new_host, new_port, new_db_name, new_service, new_sid, new_username)

    changes = []
    if body.name is not None and body.name.strip() != row.name:
        changes.append(f"名称 {row.name}→{body.name.strip()}")
        row.name = body.name.strip()
    if new_type != row.db_type:
        changes.append(f"类型 {row.db_type}→{new_type}")
        row.db_type = new_type
    if new_host != row.host:
        changes.append(f"主机 {row.host}→{new_host}")
        row.host = new_host
    if new_port != row.port:
        changes.append(f"端口 {row.port}→{new_port}")
        row.port = new_port
    if new_db_name != row.db_name:
        changes.append(f"库名 {row.db_name}→{new_db_name}")
        row.db_name = new_db_name
    if new_service != row.service_name:
        changes.append(f"服务名 {row.service_name}→{new_service}")
        row.service_name = new_service
    if new_sid != row.sid:
        changes.append(f"SID {row.sid}→{new_sid}")
        row.sid = new_sid
    if new_username != row.username:
        changes.append(f"账号 {row.username}→{new_username}")
        row.username = new_username
    if body.password:  # 留空/None 表示不修改；永不在审计中记录密码内容
        row.password_enc = encrypt_secret(body.password)
        changes.append("密码已更新")
    if body.extra is not None:
        row.extra_json = json.dumps(body.extra, ensure_ascii=False)
        changes.append("连接参数已更新")
    if body.enabled is not None and body.enabled != row.enabled:
        changes.append(f"启用 {row.enabled}→{body.enabled}")
        row.enabled = body.enabled
    if not changes:
        return _to_ds_info(row, resolve_display_names(db, [row.updated_by]))

    row.updated_by = user.username
    record_audit(db, user.username, "ds_update", "ds_connection", str(row.id),
                 f"修改数据源 id={row.id}: " + "；".join(changes), _client_ip(request), menu=MENU_DS)
    db.commit()
    return _to_ds_info(row, resolve_display_names(db, [row.updated_by]))


@router.delete("/api/datasources/{ds_id}", summary="删除数据源")
def delete_datasource(
    ds_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = _get_ds_or_404(db, ds_id)
    ref_count = len(db.execute(
        select(DsQueryTemplate).where(DsQueryTemplate.ds_id == ds_id)
    ).scalars().all())
    if ref_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"数据源 {row.name} 被 {ref_count} 个查询模板引用，请先删除或改挂相关模板")

    detail = f"删除数据源 {row.name}（{DB_TYPE_LABELS.get(row.db_type, row.db_type)} {row.host or ''}）"
    db.delete(row)
    record_audit(db, user.username, "ds_delete", "ds_connection", str(ds_id),
                 detail, _client_ip(request), menu=MENU_DS)
    db.commit()
    return {"message": f"已删除数据源 id={ds_id}"}


@router.post("/api/datasources/{ds_id}/test", response_model=TestConnectionResponse,
             summary="测试数据源连接")
def test_datasource(
    ds_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    row = _get_ds_or_404(db, ds_id)
    spec = _build_spec(row)
    try:
        result = test_connection(spec)
    except DatasourceError as e:
        record_audit(db, user.username, "ds_test", "ds_connection", str(ds_id),
                     f"测试连接 {row.name}: 失败（{e}）", _client_ip(request), menu=MENU_DS)
        db.commit()
        return TestConnectionResponse(success=False, message=str(e))
    record_audit(db, user.username, "ds_test", "ds_connection", str(ds_id),
                 f"测试连接 {row.name}: 成功（{result.elapsed_ms}ms）", _client_ip(request), menu=MENU_DS)
    db.commit()
    return TestConnectionResponse(
        success=True,
        message=f"连接成功（{DB_TYPE_LABELS.get(row.db_type, row.db_type)}，耗时 {result.elapsed_ms}ms）",
        elapsed_ms=result.elapsed_ms,
    )


# =============================================================================
# 查询模板
# =============================================================================

@router.get("/api/query-templates", response_model=list[QueryTemplateInfo], summary="查询模板列表")
def list_templates(
    module: Optional[str] = None,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    stmt = select(DsQueryTemplate).order_by(DsQueryTemplate.id)
    if module:
        stmt = stmt.where(DsQueryTemplate.module == module)
    rows = db.execute(stmt).scalars().all()
    return [_to_tpl_info(db, t, resolve_display_names(db, (x.updated_by for x in rows)))
            for t in rows]


@router.post("/api/query-templates", response_model=QueryTemplateInfo, summary="新增查询模板")
def create_template(
    body: QueryTemplateCreateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    _check_tpl_name_unique(db, name)
    _validate_tpl_fields(db, body.module.strip(), body.ds_id, body.sql_text, body.params_def)

    row = DsQueryTemplate(
        name=name, module=body.module.strip(), ds_id=body.ds_id,
        sql_text=body.sql_text.strip(),
        column_map_json=json.dumps(body.column_map, ensure_ascii=False) if body.column_map else None,
        params_json=json.dumps(body.params_def, ensure_ascii=False) if body.params_def else None,
        enabled=body.enabled, updated_by=user.username,
    )
    db.add(row)
    db.flush()
    record_audit(db, user.username, "tpl_create", "ds_query_template", str(row.id),
                 f"新增查询模板 {name}（模块 {row.module}，数据源 id={row.ds_id}）", _client_ip(request), menu=MENU_DS)
    db.commit()
    return _to_tpl_info(db, row, resolve_display_names(db, [row.updated_by]))


@router.put("/api/query-templates/{tpl_id}", response_model=QueryTemplateInfo, summary="修改查询模板")
def update_template(
    tpl_id: int,
    body: QueryTemplateUpdateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
    ):
    row = _get_tpl_or_404(db, tpl_id)

    new_name = body.name.strip() if body.name is not None else row.name
    new_module = body.module.strip() if body.module is not None else row.module
    new_ds_id = body.ds_id if body.ds_id is not None else row.ds_id
    new_sql = body.sql_text.strip() if body.sql_text is not None else row.sql_text
    new_params = body.params_def if body.params_def is not None else (
        json.loads(row.params_json) if row.params_json else None)
    if new_name != row.name:
        _check_tpl_name_unique(db, new_name, exclude_id=tpl_id)
    _validate_tpl_fields(db, new_module, new_ds_id, new_sql, new_params)

    changes = []
    if new_name != row.name:
        changes.append(f"名称 {row.name}→{new_name}")
        row.name = new_name
    if new_module != row.module:
        changes.append(f"模块 {row.module}→{new_module}")
        row.module = new_module
    if new_ds_id != row.ds_id:
        changes.append(f"数据源 {row.ds_id}→{new_ds_id}")
        row.ds_id = new_ds_id
    if body.sql_text is not None and new_sql != row.sql_text:
        changes.append("SQL 已更新（已通过安全校验）")
        row.sql_text = new_sql
    if body.column_map is not None:
        row.column_map_json = json.dumps(body.column_map, ensure_ascii=False)
        changes.append(f"字段映射已更新（{len(body.column_map)} 条）")
    if body.params_def is not None:
        row.params_json = json.dumps(body.params_def, ensure_ascii=False)
        changes.append(f"参数定义已更新（{len(body.params_def)} 个）")
    if body.enabled is not None and body.enabled != row.enabled:
        changes.append(f"启用 {row.enabled}→{body.enabled}")
        row.enabled = body.enabled
    if not changes:
        return _to_tpl_info(db, row, resolve_display_names(db, [row.updated_by]))

    row.updated_by = user.username
    record_audit(db, user.username, "tpl_update", "ds_query_template", str(row.id),
                 f"修改查询模板 id={row.id}: " + "；".join(changes), _client_ip(request), menu=MENU_TPL)
    db.commit()
    return _to_tpl_info(db, row, resolve_display_names(db, [row.updated_by]))


@router.delete("/api/query-templates/{tpl_id}", summary="删除查询模板")
def delete_template(
    tpl_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    row = _get_tpl_or_404(db, tpl_id)
    detail = f"删除查询模板 {row.name}（模块 {row.module}）"
    db.delete(row)
    record_audit(db, user.username, "tpl_delete", "ds_query_template", str(tpl_id),
                 detail, _client_ip(request), menu=MENU_TPL)
    db.commit()
    return {"message": f"已删除查询模板 id={tpl_id}"}


@router.post("/api/query-templates/{tpl_id}/preview", response_model=TemplatePreviewResponse,
             summary="预览查询模板（前 N 行）")
def preview_template(
    tpl_id: int,
    body: TemplatePreviewRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    row = _get_tpl_or_404(db, tpl_id)
    ds = _get_ds_or_404(db, row.ds_id)
    if not ds.enabled:
        raise HTTPException(status_code=400, detail=f"数据源已停用: {ds.name}")

    settings = get_settings()
    params_def = json.loads(row.params_json) if row.params_json else {}
    column_map = json.loads(row.column_map_json) if row.column_map_json else {}
    try:
        bound = validate_params(params_def, body.params)
    except DatasourceError as e:
        raise HTTPException(status_code=400, detail=str(e))

    spec = _build_spec(ds)
    context = FetchContext(
        params=bound,
        timeout_seconds=settings.DS_QUERY_TIMEOUT,
        max_rows=settings.DS_MAX_ROWS,
        limit_rows=settings.DS_PREVIEW_ROWS,
    )
    try:
        result = execute_query(spec, row.sql_text, bound, column_map, context)
    except DatasourceError as e:
        record_audit(db, user.username, "tpl_preview", "ds_query_template", str(tpl_id),
                     f"预览 {row.name}: 失败（{e}）", _client_ip(request), menu=MENU_TPL)
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))

    record_audit(db, user.username, "tpl_preview", "ds_query_template", str(tpl_id),
                 f"预览 {row.name}: 返回 {result.rows_returned} 行（{result.elapsed_ms}ms）", _client_ip(request), menu=MENU_DS)
    db.commit()

    # DataFrame → 前端可序列化结构（NaN/NaT 转 None，日期转字符串）
    df = result.df.astype(object).where(result.df.notna(), None)
    rows = [dict(zip(result.columns, row_values)) for row_values in df.itertuples(index=False, name=None)]
    return TemplatePreviewResponse(
        columns=result.columns,
        rows=rows,
        rows_returned=result.rows_returned,
        elapsed_ms=result.elapsed_ms,
        protections=result.protections,
    )
