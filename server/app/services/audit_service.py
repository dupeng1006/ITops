# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 审计服务

覆盖操作（一期）：登录、上传建任务、下载结果、用户管理（新增/修改/重置密码/删除）。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import logging
import re
import socket
import subprocess
from typing import Optional

from sqlalchemy.orm import Session

from app.models.entities import SysAuditLog

logger = logging.getLogger(__name__)

# ARP 解析结果短缓存（同一终端短时间内重复操作避免频繁调 arp；MAC 租约内基本不变）
_MAC_CACHE: dict = {}
_MAC_CACHE_TTL = 300  # 秒


def _local_ips() -> set:
    """本机全部 IPv4 地址（含 127.0.0.1），用于识别"访问者即服务器本机"场景"""
    ips = {"127.0.0.1", "::1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    return ips


def _local_mac() -> Optional[str]:
    """本机网卡 MAC（访问者为本机时直接返回）"""
    try:
        import uuid
        node = uuid.getnode()
        if (node >> 40) % 2:  # 第 41 位为 1 表示随机/虚拟 MAC，不可用
            return None
        return "-".join(f"{(node >> (i * 8)) & 0xff:02X}" for i in reversed(range(6)))
    except Exception:
        return None


def resolve_mac(ip: Optional[str]) -> Optional[str]:
    """
    按来源 IP 解析 MAC（服务端 ARP 表查询；同网段可获取，跨网段返回 None）

    实现：Windows `arp -a`（中文 Windows 默认 GBK 输出，按 GBK 解码）；
    结果短缓存 TTL 秒；任何异常均返回 None（MAC 缺失不阻断审计）。
    """
    if not ip:
        return None
    if ip in _local_ips():
        return _local_mac()

    import time
    now = time.time()
    cached = _MAC_CACHE.get(ip)
    if cached and now - cached[1] < _MAC_CACHE_TTL:
        return cached[0]

    mac = None
    try:
        out = subprocess.run(
            ["arp", "-a", ip], capture_output=True, timeout=3
        ).stdout.decode("gbk", errors="replace")
        # 匹配形如 "172.16.20.15   74-5d-22-ac-6e-b6   动态" 的行
        m = re.search(
            re.escape(ip) + r"\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s", out)
        if m:
            mac = m.group(1).upper()
    except Exception as e:
        logger.debug(f"ARP 解析 {ip} 失败（忽略）: {e}")

    _MAC_CACHE[ip] = (mac, now)
    return mac


def record_audit(
    db: Session,
    username: str,
    action: str,
    object_type: Optional[str] = None,
    object_id: Optional[str] = None,
    detail: Optional[str] = None,
    ip: Optional[str] = None,
    menu: Optional[str] = None,
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
        ip: 来源 IP（MAC 由服务端按 IP 经 ARP 自动解析，同网段可获取）
        menu: 操作菜单（如 "数据核对中心·M1 基金资产与净值核对"）
    """
    db.add(SysAuditLog(
        username=username,
        action=action,
        object_type=object_type,
        object_id=object_id,
        detail=detail,
        ip=ip,
        mac=resolve_mac(ip),
        menu=menu,
    ))
    logger.info(f"审计: {username} {action} {object_type or ''}{object_id or ''} {detail or ''}")
