# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 引擎输入表读取统一入口（table_io）

背景（二期 DS-F4 数据库取数联动）：
    db 取数模式下，DbAdapter 查询结果落为**查询快照 CSV**（UTF-8-SIG）进入
    与文件模式完全相同的归档结构与引擎流水线。M2 引擎（平台自研）各读取点
    统一走 read_table：按扩展名分派 .csv → pd.read_csv（utf-8-sig），
    其余（.xls/.xlsx）→ pd.read_excel，行为与原实现一致。

    本模块只改变**输入读取方式**，不改变任何核对/匹配/判定逻辑。
    注：M1 基准复制件（fund_reconciler_base.py）受"逐字节一致"约束不改动，
    M1 db 模式的引擎消费件由 fetch_service 同源物化为 xlsx，故 M1 不使用本模块。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

from pathlib import Path
from typing import Union

import pandas as pd

CSV_SUFFIXES = {".csv"}


def is_csv_path(path: Union[str, Path]) -> bool:
    return Path(path).suffix.lower() in CSV_SUFFIXES


def read_table(path: Union[str, Path], **kwargs) -> pd.DataFrame:
    """
    按扩展名分派读取表格文件

    - .csv：pd.read_csv(encoding="utf-8-sig")（查询快照约定编码，
      utf-8-sig 同时兼容带 BOM 与不带 BOM 的 CSV）；
    - 其他扩展名：pd.read_excel（与原实现一致，.xls 老格式需 xlrd，
      缺失时由调用方按既有中文提示处理）。

    kwargs（header/nrows/skiprows 等）两个读取器均支持，原样透传。
    """
    if is_csv_path(path):
        kwargs.setdefault("encoding", "utf-8-sig")
        return pd.read_csv(path, **kwargs)
    return pd.read_excel(path, **kwargs)
