# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— Trello 集成接口（v0.6.4）

    GET    /api/trello/configs             Trello 配置列表（admin，API Key/Token 掩码）
    POST   /api/trello/configs             新增配置（admin，API Key/Token 加密落库）
    PUT    /api/trello/configs/{id}         修改配置（admin；API Key/Token 留空不修改）
    DELETE /api/trello/configs/{id}         删除配置（admin）
    POST   /api/trello/configs/{id}/test   测试连接（admin）
    POST   /api/trello/configs/{id}/sync    手动同步（admin）
    GET    /api/trello/boards              Board 列表（全部角色）
    GET    /api/trello/cards               卡片列表（全部角色，支持状态/逾期/搜索筛选）

安全约束：
    - Trello API Key / Token 均用 Fernet 加密存储；读取永不返回明文（恒定掩码 ********）；
    - 存量明文 API Key 由 schema 迁移 v7 自动加密；
    - 全部写操作 + 测试/同步均审计留痕。

作者：技术部
版本：1.0.0
日期：2026-07-23
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    TrelloBoardInfo,
    TrelloCardInfo,
    TrelloCardListResponse,
    TrelloConfigCreateRequest,
    TrelloConfigInfo,
    TrelloConfigUpdateRequest,
    TrelloSyncResponse,
    TestConnectionResponse,
)
from app.core.crypto import PASSWORD_MASK, decrypt_secret, encrypt_secret
from app.core.deps import get_db, require_roles
from app.models.entities import SysUser, TrelloBoard, TrelloCard, TrelloConfig
from app.services.audit_service import record_audit
from app.services.user_display import resolve_display_names
from app.services import schedule_service
from app.services.trello_client import TrelloAPIError, TrelloClient
from app.services.trello_service import STATUS_LABELS, sync_trello_config

logger = logging.getLogger(__name__)

MENU_TRELLO = "Trello 工作看板"
MENU_TRELLO_CONFIG = "Trello 工作看板 · 连接配置"

router = APIRouter(tags=["Trello 工作看板"])


# =============================================================================
# 工具函数
# =============================================================================

def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _to_config_info(cfg: TrelloConfig, name_map: Optional[dict] = None) -> TrelloConfigInfo:
    return TrelloConfigInfo(
        id=cfg.id,
        name=cfg.name,
        api_key=PASSWORD_MASK,
        token=PASSWORD_MASK,
        enabled=cfg.enabled,
        sync_min=cfg.sync_min,
        last_sync_at=cfg.last_sync_at.strftime("%Y-%m-%d %H:%M:%S") if cfg.last_sync_at else None,
        last_sync_status=cfg.last_sync_status,
        last_sync_error=cfg.last_sync_error,
        updated_by=cfg.updated_by,
        updated_by_name=(name_map.get(cfg.updated_by) if name_map else None),
        updated_at=cfg.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        created_at=cfg.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _to_board_info(board: TrelloBoard) -> TrelloBoardInfo:
    return TrelloBoardInfo(
        id=board.id,
        config_id=board.config_id,
        board_id=board.board_id,
        name=board.name,
        url=board.url,
        is_closed=board.is_closed,
        synced_at=board.synced_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _to_card_info(card: TrelloCard) -> TrelloCardInfo:
    return TrelloCardInfo(
        id=card.id,
        config_id=card.config_id,
        card_id=card.card_id,
        board_id=card.board_id,
        board_name=card.board_name,
        list_id=card.list_id,
        list_name=card.list_name,
        name=card.name,
        desc=card.desc,
        status=card.status,
        due_date=card.due_date.strftime("%Y-%m-%d %H:%M:%S") if card.due_date else None,
        due_complete=card.due_complete,
        labels_json=card.labels_json,
        members_json=card.members_json,
        url=card.url,
        pos=card.pos,
        synced_at=card.synced_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _get_config_or_404(db: Session, config_id: int) -> TrelloConfig:
    cfg = db.get(TrelloConfig, config_id)
    if cfg is None:
        raise HTTPException(status_code=404, detail=f"Trello 配置不存在: id={config_id}")
    return cfg


def _check_name_unique(db: Session, name: str, exclude_id: Optional[int] = None) -> None:
    stmt = select(TrelloConfig).where(TrelloConfig.name == name)
    if exclude_id is not None:
        stmt = stmt.where(TrelloConfig.id != exclude_id)
    if db.execute(stmt).scalars().first() is not None:
        raise HTTPException(status_code=400, detail=f"Trello 配置名称已存在: {name}")


# =============================================================================
# 配置 CRUD
# =============================================================================

@router.get("/api/trello/configs", response_model=list[TrelloConfigInfo], summary="Trello 配置列表")
def list_trello_configs(
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(TrelloConfig).order_by(TrelloConfig.id)).scalars().all()
    return [_to_config_info(cfg, resolve_display_names(db, (x.updated_by for x in rows)))
            for cfg in rows]


@router.post("/api/trello/configs", response_model=TrelloConfigInfo, summary="新增 Trello 配置")
def create_trello_config(
    body: TrelloConfigCreateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    _check_name_unique(db, name)

    cfg = TrelloConfig(
        name=name,
        api_key=encrypt_secret(body.api_key.strip()),
        token_enc=encrypt_secret(body.token),
        enabled=body.enabled,
        sync_min=body.sync_min,
        updated_by=user.username,
    )
    db.add(cfg)
    db.flush()
    record_audit(db, user.username, "trello_config_create", "trello_config", str(cfg.id),
                 f"新增 Trello 配置 {name}", _client_ip(request), menu=MENU_TRELLO_CONFIG)
    db.commit()
    schedule_service.sync_trello_schedule(cfg)
    return _to_config_info(cfg, resolve_display_names(db, [cfg.updated_by]))


@router.put("/api/trello/configs/{config_id}", response_model=TrelloConfigInfo, summary="修改 Trello 配置")
def update_trello_config(
    config_id: int,
    body: TrelloConfigUpdateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    cfg = _get_config_or_404(db, config_id)
    changes = []

    if body.name is not None and body.name.strip() != cfg.name:
        _check_name_unique(db, body.name.strip(), exclude_id=config_id)
        changes.append(f"名称 {cfg.name}→{body.name.strip()}")
        cfg.name = body.name.strip()
    if body.api_key is not None and body.api_key.strip():
        cfg.api_key = encrypt_secret(body.api_key.strip())
        changes.append("API Key 已更新")
    if body.token is not None and body.token.strip():
        cfg.token_enc = encrypt_secret(body.token.strip())
        changes.append("Token 已更新")
    if body.enabled is not None and body.enabled != cfg.enabled:
        changes.append(f"启用 {cfg.enabled}→{body.enabled}")
        cfg.enabled = body.enabled
    if body.sync_min is not None and body.sync_min != cfg.sync_min:
        changes.append(f"同步间隔 {cfg.sync_min}→{body.sync_min} 分钟")
        cfg.sync_min = body.sync_min

    if not changes:
        return _to_config_info(cfg, resolve_display_names(db, [cfg.updated_by]))

    cfg.updated_by = user.username
    record_audit(db, user.username, "trello_config_update", "trello_config", str(config_id),
                 f"修改 Trello 配置 id={config_id}: " + "；".join(changes), _client_ip(request), menu=MENU_TRELLO_CONFIG)
    db.commit()
    schedule_service.sync_trello_schedule(cfg)
    return _to_config_info(cfg, resolve_display_names(db, [cfg.updated_by]))


@router.delete("/api/trello/configs/{config_id}", summary="删除 Trello 配置")
def delete_trello_config(
    config_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    cfg = _get_config_or_404(db, config_id)
    name = cfg.name
    db.delete(cfg)
    record_audit(db, user.username, "trello_config_delete", "trello_config", str(config_id),
                 f"删除 Trello 配置 {name}", _client_ip(request), menu=MENU_TRELLO_CONFIG)
    db.commit()
    schedule_service.remove_trello_schedule(config_id)
    return {"message": f"已删除 Trello 配置 id={config_id}"}


@router.post("/api/trello/configs/{config_id}/test", response_model=TestConnectionResponse, summary="测试 Trello 连接")
def test_trello_config(
    config_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    cfg = _get_config_or_404(db, config_id)
    try:
        token = decrypt_secret(cfg.token_enc)
        api_key = decrypt_secret(cfg.api_key)
    except ValueError as e:
        record_audit(db, user.username, "trello_config_test", "trello_config", str(config_id),
                     f"测试 Trello 配置 {cfg.name}: 失败（凭据解密失败：{e}）",
                     _client_ip(request), menu=MENU_TRELLO_CONFIG)
        db.commit()
        return TestConnectionResponse(success=False, message=f"凭据解密失败：{e}")
    try:
        client = TrelloClient(api_key=api_key, token=token)
        me = client.get_member()
        msg = f"连接成功：{me.get('fullName', '')}（@{me.get('username', '')}）"
        record_audit(db, user.username, "trello_config_test", "trello_config", str(config_id),
                     f"测试 Trello 配置 {cfg.name}: {msg}", _client_ip(request), menu=MENU_TRELLO_CONFIG)
        db.commit()
        return TestConnectionResponse(success=True, message=msg)
    except TrelloAPIError as e:
        record_audit(db, user.username, "trello_config_test", "trello_config", str(config_id),
                     f"测试 Trello 配置 {cfg.name}: 失败（{e}）", _client_ip(request), menu=MENU_TRELLO_CONFIG)
        db.commit()
        return TestConnectionResponse(success=False, message=f"连接失败：{e}")


@router.post("/api/trello/configs/{config_id}/sync", response_model=TrelloSyncResponse, summary="手动同步 Trello")
def sync_trello_config_manual(
    config_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    cfg = _get_config_or_404(db, config_id)
    result = sync_trello_config(db, cfg)
    db.commit()
    record_audit(db, user.username, "trello_config_sync", "trello_config", str(config_id),
                 f"手动同步 Trello 配置 {cfg.name}: {result['message']}", _client_ip(request), menu=MENU_TRELLO_CONFIG)
    db.commit()
    return TrelloSyncResponse(**result)


# =============================================================================
# Board / Card 查询
# =============================================================================

@router.get("/api/trello/boards", response_model=list[TrelloBoardInfo], summary="已同步的 Board 列表")
def list_trello_boards(
    user: SysUser = Depends(require_roles("admin", "operator", "viewer")),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(TrelloBoard).order_by(TrelloBoard.id)).scalars().all()
    return [_to_board_info(b) for b in rows]


@router.get("/api/trello/cards", response_model=TrelloCardListResponse, summary="已同步的卡片列表")
def list_trello_cards(
    status: Optional[str] = None,
    overdue: bool = False,
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 500,
    user: SysUser = Depends(require_roles("admin", "operator", "viewer")),
    db: Session = Depends(get_db),
):
    if status and status not in STATUS_LABELS and status != "未设置状态":
        raise HTTPException(status_code=400, detail=f"非法状态: {status}")
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 1000:
        page_size = 500

    stmt = select(TrelloCard)
    if status:
        if status == "未设置状态":
            stmt = stmt.where(TrelloCard.status.is_(None))
        else:
            stmt = stmt.where(TrelloCard.status == status)
    if overdue:
        stmt = stmt.where(
            TrelloCard.due_date.isnot(None),
            TrelloCard.due_complete.is_(False),
            TrelloCard.due_date < datetime.now(),
        )
    if search:
        stmt = stmt.where(TrelloCard.name.ilike(f"%{search}%"))

    stmt = stmt.order_by(TrelloCard.board_name, TrelloCard.list_name, TrelloCard.pos)

    total = len(db.execute(stmt).scalars().all())
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return TrelloCardListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_to_card_info(c) for c in rows],
    )
