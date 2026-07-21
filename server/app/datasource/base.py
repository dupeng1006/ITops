# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据源适配层抽象（方案 2.3）

核对引擎只面向 DataFrame，不感知数据来源：

    M1/M2/M3 任务 ──┬── FileAdapter（上传文件 → DataFrame，一期已内嵌任务流）
                    └── DbAdapter（数据源 + 查询模板 + 参数 → DataFrame）

作者：技术部
版本：1.0.0
日期：2026-07-18
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Optional

import pandas as pd


@dataclass
class FetchContext:
    """取数上下文（一次查询的全部输入与执行保护参数）"""

    params: Dict[str, str] = field(default_factory=dict)  # 模板参数（如 biz_date）
    timeout_seconds: int = 60        # 语句超时（尽力而为，方言支持时生效）
    max_rows: int = 1_000_000        # 最大返回行数（硬限制）
    limit_rows: Optional[int] = None  # 预览等场景的额外截断（如 50）


class SourceAdapter(ABC):
    """数据源适配器抽象：统一输出 DataFrame"""

    @abstractmethod
    def fetch(self, context: FetchContext) -> pd.DataFrame:
        """执行取数并返回 DataFrame（实现方负责映射为标准逻辑字段）"""
        raise NotImplementedError
