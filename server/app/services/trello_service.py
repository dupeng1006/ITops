# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— Trello 同步服务（v0.6.4）

- 负责把 Trello API 数据同步到本地 SQLite 缓存；
- 状态字段从 labels 中提取（Done/Suspended/Help/Delayed/Not Started/Ongoing/Closed）；
- 只读同步，不修改 Trello 数据。

作者：技术部
版本：1.0.0
日期：2026-07-23
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_secret
from app.models.entities import TrelloBoard, TrelloCard, TrelloConfig
from app.services.trello_client import TrelloAPIError, TrelloClient

logger = logging.getLogger(__name__)

# 截图中约定的状态标签
STATUS_LABELS = {"Done", "Suspended", "Help", "Delayed", "Not Started", "Ongoing", "Closed"}


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    """解析 Trello ISO8601 日期为本地时区 datetime"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc)  # 保存 UTC 时间，避免时区问题
    except Exception:
        return None


def _extract_status(labels: List[Dict[str, Any]]) -> Optional[str]:
    """从标签中提取状态标签（第一个匹配）"""
    for label in labels or []:
        name = label.get("name", "")
        if name in STATUS_LABELS:
            return name
    return None


def _serialize_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def sync_trello_config(db: Session, config: TrelloConfig) -> Dict[str, Any]:
    """
    同步单个 Trello 配置：拉取我加入的 boards 和分配给我的卡片，写入本地缓存。

    Returns:
        {"success": bool, "boards": int, "cards": int, "message": str, "elapsed_ms": int}
    """
    start = time.time()
    try:
        token = decrypt_secret(config.token_enc)
    except Exception as e:
        return {
            "success": False,
            "boards": 0,
            "cards": 0,
            "message": f"Token 解密失败：{e}",
            "elapsed_ms": 0,
        }

    client = TrelloClient(api_key=config.api_key, token=token)

    try:
        # 1. 拉取 boards
        boards_raw = client.get_my_boards()
        boards_by_id: Dict[str, TrelloBoard] = {}
        for b in boards_raw:
            if b.get("closed"):
                continue
            board_id = b["id"]
            boards_by_id[board_id] = TrelloBoard(
                config_id=config.id,
                board_id=board_id,
                name=b.get("name", ""),
                url=b.get("url") or b.get("shortUrl"),
                is_closed=False,
                synced_at=datetime.now(),
            )

        # 2. 拉取 lists（为 list_name 映射）和卡片
        list_name_map: Dict[str, str] = {}
        for board_id in list(boards_by_id.keys()):
            try:
                lists = client.get_board_lists(board_id)
                for lst in lists:
                    list_name_map[lst["id"]] = lst.get("name", "")
            except TrelloAPIError as e:
                logger.warning(f"Trello 同步 board {board_id} lists 失败: {e}")
            # 速率控制已在 client 中处理，但 boards 之间也稍微放慢
            time.sleep(0.1)

        # 3. 拉取分配给我的卡片（跨 board）
        cards_raw = client.get_my_cards(limit=1000)
        cards: List[TrelloCard] = []
        for c in cards_raw:
            board_id = c.get("idBoard", "")
            if board_id not in boards_by_id:
                # 只同步 boards_by_id 中已存在的 board（即我加入的公开/私有 board）
                continue
            labels = c.get("labels", []) or []
            list_id = c.get("idList", "")
            cards.append(TrelloCard(
                config_id=config.id,
                card_id=c["id"],
                board_id=board_id,
                board_name=boards_by_id[board_id].name,
                list_id=list_id,
                list_name=list_name_map.get(list_id),
                name=c.get("name", ""),
                desc=c.get("desc") or None,
                status=_extract_status(labels),
                due_date=_parse_iso_datetime(c.get("due")),
                due_complete=bool(c.get("dueComplete", False)),
                labels_json=_serialize_json(labels),
                members_json=_serialize_json(c.get("idMembers") or c.get("memberIds")),
                url=c.get("url"),
                pos=c.get("pos"),
                synced_at=datetime.now(),
            ))

        # 4. 写入数据库：先清后插（保证幂等）
        db.execute(delete(TrelloBoard).where(TrelloBoard.config_id == config.id))
        db.execute(delete(TrelloCard).where(TrelloCard.config_id == config.id))
        for board in boards_by_id.values():
            db.add(board)
        for card in cards:
            db.add(card)

        elapsed_ms = int((time.time() - start) * 1000)
        config.last_sync_at = datetime.now()
        config.last_sync_status = "success"
        config.last_sync_error = None
        db.flush()

        return {
            "success": True,
            "boards": len(boards_by_id),
            "cards": len(cards),
            "message": f"同步成功：{len(boards_by_id)} 个 boards，{len(cards)} 张 cards",
            "elapsed_ms": elapsed_ms,
        }

    except TrelloAPIError as e:
        config.last_sync_at = datetime.now()
        config.last_sync_status = "failed"
        config.last_sync_error = str(e)
        return {
            "success": False,
            "boards": 0,
            "cards": 0,
            "message": f"同步失败：{e}",
            "elapsed_ms": int((time.time() - start) * 1000),
        }
