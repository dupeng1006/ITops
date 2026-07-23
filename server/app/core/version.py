# -*- coding: utf-8 -*-
"""
安联资管运维管理平台 —— 版本信息

版本来源：
    - 冻结态（部署包）：exe 同级 version.txt（打包时由 build.bat 写入）；
    - 源码态：server/version.txt（可选），缺省 "dev"。

作者：技术部
版本：1.0.0
日期：2026-07-23
"""

import sys
from pathlib import Path

_UNKNOWN = "unknown"


def get_version() -> str:
    """读取当前运行版本号，读取失败返回 "unknown" """
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "version.txt")
    else:
        candidates.append(Path(__file__).resolve().parents[2] / "version.txt")
    for p in candidates:
        try:
            if p.exists():
                v = p.read_text(encoding="utf-8", errors="replace").strip()
                if v:
                    return v
        except Exception:  # noqa: BLE001
            pass
    return _UNKNOWN


def get_install_info() -> dict:
    """返回部署信息（冻结态）：安装根目录、程序目录、数据目录"""
    from app.core.config import get_settings

    settings = get_settings()
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
        install_root = app_dir.parent
        frozen = True
    else:
        app_dir = None
        install_root = Path(__file__).resolve().parents[2]
        frozen = False
    return {
        "frozen": frozen,
        "install_root": str(install_root),
        "app_dir": str(app_dir) if app_dir else None,
        "data_dir": str(settings.DATA_DIR),
        "archive_dir": str(settings.ARCHIVE_DIR),
    }
