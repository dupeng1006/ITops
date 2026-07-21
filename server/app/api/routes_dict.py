# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据字典查询接口（三期）

    GET  /api/dict/models                    模型清单（admin/operator）
    GET  /api/dict/tables                    表搜索（表代码/中文名/字段名模糊，标注命中点）
    GET  /api/dict/tables/{id}               表详情（全字段 + 主键标识）
    GET  /api/dict/tables/{id}/references    表关联（父子两向）
    POST /api/dict/gen-sql                   生成 Oracle SELECT（多表按外键自动 JOIN，
                                             无关联输出 CROSS 警告；生成后过 SQL Guard 自证）
    POST /api/dict/save-template             生成的 SQL 保存为查询模板（admin，模块=custom）

权限：查询 admin/operator（viewer 403）；保存模板复用模板创建权限（admin）。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    DictFavoriteCreateRequest,
    DictFavoriteInfo,
    DictModelInfo,
    DictSaveTemplateRequest,
    DictTableDetail,
    DictTableReferencesResponse,
    DictTableSearchResponse,
    GenSqlRequest,
    GenSqlResponse,
    QueryTemplateInfo,
)
from app.core.deps import get_db, require_roles
from app.datasource.sql_guard import SqlGuardError, validate_select_only
from app.models.entities import DictFavorite, DsConnection, DsQueryTemplate, SysUser
from app.services import dict_service
from app.services.audit_service import record_audit
from app.services.dict_service import DictError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["数据字典查询"])


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _open_dict():
    """打开字典库连接，业务错误转 4xx/503"""
    try:
        return dict_service.get_conn()
    except DictError as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/api/dict/models", response_model=list[DictModelInfo],
            summary="字典模型清单")
def list_models(user: SysUser = Depends(require_roles("admin", "operator"))):
    conn = _open_dict()
    try:
        return dict_service.list_models(conn)
    finally:
        conn.close()


@router.get("/api/dict/tables", response_model=DictTableSearchResponse,
            summary="搜索表（表代码/中文名/字段名模糊，收藏优先置顶）")
def search_tables(
    keyword: str = Query("", max_length=50),
    model_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    # 读取当前用户收藏 ID 列表
    fav_rows = db.execute(
        select(DictFavorite.table_id)
        .where(DictFavorite.user_id == user.id)
    ).scalars().all()
    fav_ids = [int(r) for r in fav_rows]

    conn = _open_dict()
    try:
        return dict_service.search_tables(conn, keyword, model_id, page, page_size, fav_ids)
    finally:
        conn.close()


@router.get("/api/dict/tables/{table_id}", response_model=DictTableDetail,
            summary="表详情（全字段 + 主键标识）")
def table_detail(
    table_id: int,
    user: SysUser = Depends(require_roles("admin", "operator")),
):
    conn = _open_dict()
    try:
        detail = dict_service.get_table_detail(conn, table_id)
    finally:
        conn.close()
    if detail is None:
        raise HTTPException(status_code=404, detail=f"字典表不存在: id={table_id}")
    return detail


@router.get("/api/dict/tables/{table_id}/references",
            response_model=DictTableReferencesResponse,
            summary="表关联（父子两向）")
def table_references(
    table_id: int,
    user: SysUser = Depends(require_roles("admin", "operator")),
):
    conn = _open_dict()
    try:
        if dict_service.get_table_detail(conn, table_id) is None:
            raise HTTPException(status_code=404, detail=f"字典表不存在: id={table_id}")
        return dict_service.get_table_references(conn, table_id)
    finally:
        conn.close()


@router.get("/api/dict/favorites", response_model=list[DictFavoriteInfo],
            summary="当前用户收藏的字典表")
def list_favorites(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(DictFavorite)
        .where(DictFavorite.user_id == user.id)
        .order_by(DictFavorite.created_at.desc())
    ).scalars().all()
    return [
        DictFavoriteInfo(
            id=r.id, table_id=r.table_id, table_code=r.table_code,
            table_name=r.table_name,
            created_at=r.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        for r in rows
    ]


@router.post("/api/dict/favorites", response_model=DictFavoriteInfo,
             summary="收藏字典表")
def add_favorite(
    body: DictFavoriteCreateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    # 校验表存在
    conn = _open_dict()
    try:
        detail = dict_service.get_table_detail(conn, body.table_id)
    finally:
        conn.close()
    if detail is None:
        raise HTTPException(status_code=404, detail=f"字典表不存在: id={body.table_id}")

    exists = db.execute(
        select(DictFavorite).where(
            DictFavorite.user_id == user.id,
            DictFavorite.table_id == body.table_id,
        )
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=400, detail="该表已收藏")

    row = DictFavorite(
        user_id=user.id,
        table_id=body.table_id,
        table_code=detail["table_code"],
        table_name=detail["table_name"],
    )
    db.add(row)
    db.flush()
    record_audit(db, user.username, "dict_favorite_add", "dict_favorite", str(body.table_id),
                 f"收藏字典表 {detail['table_code']}（{detail['table_name'] or '-'}）",
                 _client_ip(request))
    db.commit()
    return DictFavoriteInfo(
        id=row.id, table_id=row.table_id, table_code=row.table_code,
        table_name=row.table_name,
        created_at=row.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


@router.delete("/api/dict/favorites/{table_id}", status_code=204,
               summary="取消收藏字典表")
def remove_favorite(
    table_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    row = db.execute(
        select(DictFavorite).where(
            DictFavorite.user_id == user.id,
            DictFavorite.table_id == table_id,
        )
    ).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="未收藏该表")
    db.delete(row)
    record_audit(db, user.username, "dict_favorite_remove", "dict_favorite", str(table_id),
                 f"取消收藏字典表 {row.table_code}（{row.table_name or '-'}）",
                 _client_ip(request))
    db.commit()
    return None


@router.post("/api/dict/gen-sql", response_model=GenSqlResponse,
             summary="生成 Oracle SELECT（多表按外键自动 JOIN）")
def gen_sql(
    body: GenSqlRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    conn = _open_dict()
    try:
        try:
            result = dict_service.generate_sql(
                conn,
                [t.model_dump() for t in body.tables],
                [c.model_dump() for c in body.conditions],
                limit=body.limit, use_rownum=body.use_rownum,
            )
        except DictError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except SqlGuardError as e:  # 自证未通过（防御性，理论不发生）
            logger.error(f"生成 SQL 未通过只读校验: {e}")
            raise HTTPException(
                status_code=500, detail=f"生成 SQL 安全自证未通过：{e}")
    finally:
        conn.close()
    record_audit(db, user.username, "dict_gen_sql", "dict_table",
                 ",".join(str(t.table_id) for t in body.tables),
                 f"数据字典生成 SQL（表 {len(body.tables)} 张，"
                 f"JOIN {len(result['joins'])} 个，警告 {len(result['warnings'])} 条）",
                 _client_ip(request))
    db.commit()
    return result


@router.post("/api/dict/save-template", response_model=QueryTemplateInfo,
             summary="生成的 SQL 保存为查询模板（模块=custom）")
def save_template(
    body: DictSaveTemplateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    exists = db.execute(
        select(DsQueryTemplate).where(DsQueryTemplate.name == name)
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=400, detail=f"模板名称已存在: {name}")
    ds = db.get(DsConnection, body.ds_id)
    if ds is None:
        raise HTTPException(status_code=400, detail=f"数据源不存在: id={body.ds_id}")
    try:
        validate_select_only(body.sql_text)
    except SqlGuardError as e:
        raise HTTPException(status_code=400, detail=f"SQL 安全校验未通过：{e}")

    row = DsQueryTemplate(
        name=name, module="custom", ds_id=body.ds_id,
        sql_text=body.sql_text.strip(),
        column_map_json=None, params_json=None,
        enabled=True, updated_by=user.username,
    )
    db.add(row)
    db.flush()
    record_audit(db, user.username, "tpl_create", "ds_query_template", str(row.id),
                 f"数据字典保存查询模板 {name}（模块 custom，数据源 id={row.ds_id}）",
                 _client_ip(request))
    db.commit()
    return QueryTemplateInfo(
        id=row.id, name=row.name, module=row.module, ds_id=row.ds_id,
        ds_name=ds.name, sql_text=row.sql_text, column_map=None, params_def=None,
        enabled=row.enabled, updated_by=row.updated_by,
        updated_at=row.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
    )
