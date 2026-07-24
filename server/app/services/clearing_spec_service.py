# -*- coding: utf-8 -*-
"""
安联资管运维管理平台 —— 中登接口字段说明库服务

内置库来源：官方《登记结算数据接口规范》PDF 预解析（随版本发布，见
server/config/clearing_spec/*.json，打包时冻结进部署目录）。

匹配规则：
    文件名（不区分大小写、不含路径）以接口代号开头，取最长匹配。
    例：ZQYEJS329.713 → zqye（证券余额对账文件）；
        jsmx01_JS123.713 → jsmx01（优先于 jsmx）。

作者：技术部
版本：1.0.0
日期：2026-07-24
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from app.core.config import SERVER_ROOT

logger = logging.getLogger(__name__)

_SPEC_DIR = SERVER_ROOT / "config" / "clearing_spec"

_libs: Optional[list] = None       # [{market, spec_name, interfaces:{code:...}}]
_prefix_index: Optional[list] = None  # [(code, market, spec_name, interface)] 按 code 长度降序


def _load() -> None:
    global _libs, _prefix_index
    if _libs is not None:
        return
    _libs = []
    _prefix_index = []
    if not _SPEC_DIR.exists():
        logger.warning(f"中登接口说明库目录不存在: {_SPEC_DIR}")
        return
    for fp in sorted(_SPEC_DIR.glob("*.json")):
        try:
            lib = json.loads(fp.read_text(encoding="utf-8"))
            _libs.append(lib)
            for code, itf in lib.get("interfaces", {}).items():
                _prefix_index.append((code, lib.get("market", ""), lib.get("spec_name", ""), itf))
            logger.info(f"中登接口说明库加载: {fp.name}（{len(lib.get('interfaces', {}))} 个接口）")
        except Exception:  # noqa: BLE001
            logger.exception(f"中登接口说明库加载失败: {fp}")
    # 最长前缀优先（jsmx01 先于 jsmx）
    _prefix_index.sort(key=lambda x: -len(x[0]))


def match_interface(filename: str) -> Optional[dict]:
    """
    按文件名前缀匹配接口，未匹配返回 None。
    返回 {code, name, market, spec_name, file_pattern, fields: {NAME: {type,length,desc}}}
    """
    _load()
    base = os.path.basename(filename or "").lower()
    if not base:
        return None
    for code, market, spec_name, itf in (_prefix_index or []):
        if base.startswith(code):
            return {
                "code": code,
                "name": itf.get("name", ""),
                "market": market,
                "spec_name": spec_name,
                "file_pattern": itf.get("file_pattern", ""),
                "fields": itf.get("fields", {}),
            }
    return None


def library_stats() -> dict:
    """库规模统计（调试/页面展示用）"""
    _load()
    return {
        "libraries": [
            {"market": l.get("market", ""), "spec_name": l.get("spec_name", ""),
             "interfaces": len(l.get("interfaces", {}))}
            for l in (_libs or [])
        ]
    }
