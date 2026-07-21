# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 归档存储服务（一期：M1 文件模式）

目录约定（方案 2.8 按任务要求落为 archive\）：
    archive/{module}/{yyyyMMdd}/{jobId}/input/    原始上传文件
    archive/{module}/{yyyyMMdd}/{jobId}/result/   结果 Excel 与运行日志 run.log

命名规范：
    结果文件：基金资产与净值核对结果_yyyyMMdd.xlsx；
    同一业务日期重复执行自动追加 _v2、_v3 ... 版本号，不覆盖历史结果。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import logging
import re
from pathlib import Path
from typing import Tuple

from app.core.config import get_settings

logger = logging.getLogger(__name__)

RESULT_NAME_TEMPLATE = "基金资产与净值核对结果_{date}.xlsx"
RESULT_NAME_GLOB = "基金资产与净值核对结果_{date}*.xlsx"

# 允许的上传扩展名
ALLOWED_UPLOAD_EXTS = {".xls", ".xlsx"}


def sanitize_filename(filename: str) -> str:
    """文件名安全化：去除路径成分与危险字符，防路径穿越"""
    name = Path(filename).name  # 去掉任何目录成分
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    return name or "unnamed.xlsx"


def prepare_job_dirs(module: str, biz_date: str, job_id: str) -> Tuple[Path, Path]:
    """
    创建并返回任务归档目录 (input_dir, result_dir)
    """
    settings = get_settings()
    base = settings.ARCHIVE_DIR / module.lower() / biz_date / job_id
    input_dir = base / "input"
    result_dir = base / "result"
    input_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    return input_dir, result_dir


def save_upload(input_dir: Path, role_prefix: str, filename: str, content: bytes) -> Path:
    """
    保存上传文件到 input 目录

    Args:
        input_dir: 任务 input 目录
        role_prefix: 文件角色前缀（fund / netvalue），避免同名混淆
        filename: 原始文件名（安全化后落盘）
        content: 文件内容
    """
    safe_name = f"{role_prefix}__{sanitize_filename(filename)}"
    path = input_dir / safe_name
    path.write_bytes(content)
    logger.info(f"上传文件已归档: {path}（{len(content)} 字节）")
    return path


def allocate_result_filename(module: str, biz_date: str) -> str:
    """
    分配结果文件名：同一业务日期下已存在同名结果时自动追加 _v2、_v3 ...

    Returns:
        不冲突的结果文件名（不含目录）
    """
    settings = get_settings()
    module_dir = settings.ARCHIVE_DIR / module.lower() / biz_date
    base_name = RESULT_NAME_TEMPLATE.format(date=biz_date)
    if not module_dir.exists():
        return base_name

    existing = {
        p.name
        for p in module_dir.glob(f"*/result/{RESULT_NAME_GLOB.format(date=biz_date)}")
    }
    if base_name not in existing:
        return base_name

    version = 2
    while True:
        candidate = RESULT_NAME_TEMPLATE.format(date=biz_date).replace(
            ".xlsx", f"_v{version}.xlsx"
        )
        if candidate not in existing:
            return candidate
        version += 1


def read_log_tail(log_path: Path, tail_lines: int = 50) -> list:
    """读取日志文件末尾 N 行（文件不存在时返回空列表）"""
    if not log_path.exists():
        return []
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-tail_lines:]
