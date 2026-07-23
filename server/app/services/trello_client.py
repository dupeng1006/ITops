# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— Trello REST API 客户端（v0.6.4）

- 仅使用 Python 标准库 urllib，不引入额外依赖；
- 所有请求均为只读 GET；
- 内置速率控制（默认每次请求间隔 0.3s，避免触发 100 req/10s 限制）。

作者：技术部
版本：1.0.0
日期：2026-07-23
"""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin

logger = logging.getLogger(__name__)

TRELLO_API_BASE = "https://api.trello.com/1/"
DEFAULT_DELAY = 0.3  # 秒


class TrelloAPIError(Exception):
    """Trello API 调用异常"""

    def __init__(self, message: str, status: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status = status
        self.body = body


class TrelloClient:
    """Trello REST API 只读客户端"""

    def __init__(self, api_key: str, token: str, delay: float = DEFAULT_DELAY):
        self.api_key = api_key
        self.token = token
        self.delay = delay
        self._last_request_at = 0.0

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """发送 GET 请求，返回解析后的 JSON"""
        query = {"key": self.api_key, "token": self.token}
        if params:
            query.update(params)
        url = urljoin(TRELLO_API_BASE, path) + "?" + urlencode(query, doseq=True)

        # 速率控制
        elapsed = time.time() - self._last_request_at
        if elapsed < self.delay:
            time.sleep(self.delay - elapsed)
        self._last_request_at = time.time()

        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data) if data else None
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:500]
            msg = f"Trello API 请求失败: {e.code}"
            try:
                err = json.loads(body)
                if isinstance(err, dict) and err.get("message"):
                    msg = f"Trello API: {err['message']}"
            except Exception:
                pass
            raise TrelloAPIError(msg, status=e.code, body=body) from e
        except urllib.error.URLError as e:
            raise TrelloAPIError(f"Trello API 网络异常: {e.reason}", status=None) from e

    def get_member(self) -> Dict[str, Any]:
        """获取当前成员信息（测试连接用）"""
        return self._get("members/me", {"fields": "id,fullName,username,avatarUrl,email"})

    def get_my_boards(self, fields: str = "id,name,url,shortUrl,closed") -> List[Dict[str, Any]]:
        """获取我加入的所有 boards"""
        return self._get("members/me/boards", {"fields": fields})

    def get_board_lists(self, board_id: str, fields: str = "id,name,pos") -> List[Dict[str, Any]]:
        """获取指定 board 的 lists"""
        return self._get(f"boards/{board_id}/lists", {"fields": fields, "cards": "none"})

    def get_my_cards(self, fields: str = "id,name,desc,due,dueComplete,idList,idBoard,labels,idMembers,url,pos", limit: int = 1000) -> List[Dict[str, Any]]:
        """获取所有分配给我的卡片（跨 board）"""
        return self._get("members/me/cards", {"fields": fields, "limit": limit})

    def get_board_cards(self, board_id: str, fields: str = "id,name,desc,due,dueComplete,idList,idBoard,labels,idMembers,url,pos") -> List[Dict[str, Any]]:
        """获取指定 board 的所有 open cards"""
        return self._get(f"boards/{board_id}/cards", {"fields": fields})
