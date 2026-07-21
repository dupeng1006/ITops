# -*- coding: utf-8 -*-
"""
M1 基金资产与净值核对 —— 规则加载服务

职责：
    为 M1 引擎提供核对规则（重命名映射 rename_map、特殊产品清单
    special_products（差异说明/行填充色）、差异阈值 diff_threshold、
    模糊匹配相似度阈值 similarity_threshold）。

设计说明：
    - 一期规则承载于 JSON 文件（server/config/rule_config.json），
      初始内容与验收基准 samples/reference/fund_reconciler_config.json 一致；
    - 通过 RuleProvider 抽象基类预留二期扩展：二期可实现
      DatabaseRuleProvider 从数据库读取规则，引擎无需改动。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

# 默认规则配置文件路径：server/config/rule_config.json
# 本文件位于 server/app/services/rule_service.py，parents[2] 即 server/
DEFAULT_RULE_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "rule_config.json"
)


@dataclass(frozen=True)
class SpecialProductRule:
    """
    特殊产品规则（原大宗产品）

    Attributes:
        note: 差异说明（展示在 M1 结果 Excel"差异原因"列；
              None 时输出默认文案"大宗产品无需核对"）
        color: 行填充色（6 位 HEX，不含 #；默认 FFC000 橙色）
    """
    note: Optional[str] = None
    color: str = "FFC000"


@dataclass(frozen=True)
class RuleConfig:
    """
    M1 核对规则配置（不可变数据载体）

    Attributes:
        rename_map: 净值查询表信托计划代码重命名映射（如 7001 -> 6001）
        special_products: 特殊产品代码 → 规则（差异说明/行填充色）
        diff_threshold: 差异阈值（%），超过则标浅红并计入差异统计
        similarity_threshold: 模糊匹配相似度阈值（0-1）
    """
    rename_map: Dict[str, str] = field(default_factory=dict)
    special_products: Dict[str, SpecialProductRule] = field(default_factory=dict)
    diff_threshold: float = 1.0
    similarity_threshold: float = 0.5


def parse_special_products(raw: dict, source: str = "配置") -> Dict[str, SpecialProductRule]:
    """
    解析特殊产品配置（兼容新旧两种 JSON 格式）

    Args:
        raw: 含 special_products（新格式对象数组 [{code,note,color}]）
             或 bulk_products（旧格式字符串数组）的配置 dict
        source: 来源描述（错误提示用）

    Returns:
        {产品代码: SpecialProductRule}
    """
    result: Dict[str, SpecialProductRule] = {}
    new_items = raw.get("special_products")
    if isinstance(new_items, list):
        for item in new_items:
            if not isinstance(item, dict) or not item.get("code"):
                raise ValueError(f"{source}：special_products 存在非法条目（缺 code）: {item!r}")
            note = item.get("note")
            color = (item.get("color") or "FFC000").strip().upper().lstrip("#")
            if len(color) != 6 or any(c not in "0123456789ABCDEF" for c in color):
                raise ValueError(
                    f"{source}：产品 {item['code']} 颜色非法（须为6位十六进制）: {color}")
            result[str(item["code"]).strip()] = SpecialProductRule(
                note=str(note).strip() if note else None, color=color)
        return result
    # 旧格式：bulk_products 字符串数组 → 默认 note=None/color=FFC000
    for code in raw.get("bulk_products", []) or []:
        result[str(code).strip()] = SpecialProductRule()
    return result


class RuleProvider(ABC):
    """
    规则提供者抽象基类

    一期实现：JsonRuleProvider（JSON 文件）
    二期预留：DatabaseRuleProvider（数据库），引擎通过依赖注入切换。
    """

    @abstractmethod
    def get_rule_config(self) -> RuleConfig:
        """加载并返回 M1 核对规则配置"""
        raise NotImplementedError


class JsonRuleProvider(RuleProvider):
    """从 JSON 文件加载 M1 核对规则（一期实现）"""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Args:
            config_path: 规则配置文件路径，默认 server/config/rule_config.json
            logger: 日志记录器
        """
        self.config_path = Path(config_path) if config_path else DEFAULT_RULE_CONFIG_PATH
        self.logger = logger or logging.getLogger(__name__)

    def get_rule_config(self) -> RuleConfig:
        """
        读取 JSON 配置文件并解析为 RuleConfig

        Returns:
            RuleConfig 实例

        Raises:
            FileNotFoundError: 配置文件不存在
            ValueError: 配置文件 JSON 解析失败或关键字段类型非法
        """
        if not self.config_path.exists():
            raise FileNotFoundError(
                f"规则配置文件不存在: {self.config_path}，"
                f"请确认 server/config/rule_config.json 已部署"
            )

        self.logger.info(f"正在加载规则配置: {self.config_path}")
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"规则配置文件 JSON 解析失败: {self.config_path}: {e}")

        try:
            config = RuleConfig(
                rename_map=dict(raw.get("rename_map", {})),
                special_products=parse_special_products(raw, str(self.config_path)),
                diff_threshold=float(raw.get("diff_threshold", 1.0)),
                similarity_threshold=float(raw.get("similarity_threshold", 0.5)),
            )
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"规则配置关键字段类型非法: {self.config_path}: {e}"
            )

        self.logger.info(
            f"规则配置加载完成: 映射规则{len(config.rename_map)}条, "
            f"特殊产品{len(config.special_products)}个, "
            f"差异阈值{config.diff_threshold}%, "
            f"相似度阈值{config.similarity_threshold}"
        )
        return config


class DbRuleProvider(RuleProvider):
    """
    从平台规则库加载 M1 核对规则（二期正式实现，一期随 API 启用为默认）

    数据来源：
        rule_code_mapping（enabled=True）→ rename_map
        rule_bulk_product（enabled=True）→ special_products
          （description 列 → note，color 列 → color）
        rule_threshold.diff_pct / fuzzy_sim → 阈值

    说明：
        - 规则库初始数据由 rule_config.json 于首次建库时导入；
        - 与 JSON 口径保持一致（键值同源），可随时切回 JsonRuleProvider 比对。
    """

    def __init__(
        self,
        session_factory=None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Args:
            session_factory: SQLAlchemy 会话工厂，默认取全局数据库会话工厂
            logger: 日志记录器
        """
        self._session_factory = session_factory
        self.logger = logger or logging.getLogger(__name__)

    def get_rule_config(self) -> RuleConfig:
        """从数据库读取启用的规则并组装 RuleConfig"""
        # 延迟导入，避免与服务启动期的数据库初始化形成循环依赖
        from app.models.database import get_session_factory
        from app.models.entities import RuleBulkProduct, RuleCodeMapping, RuleThreshold
        from sqlalchemy import select

        session_factory = self._session_factory or get_session_factory()
        with session_factory() as session:
            mappings = session.execute(
                select(RuleCodeMapping).where(RuleCodeMapping.enabled.is_(True))
            ).scalars().all()
            bulks = session.execute(
                select(RuleBulkProduct).where(RuleBulkProduct.enabled.is_(True))
            ).scalars().all()
            thresholds = session.execute(select(RuleThreshold)).scalars().all()

        if not mappings and not bulks and not thresholds:
            raise ValueError(
                "规则库为空：rule_code_mapping / rule_bulk_product / rule_threshold "
                "均无数据，请确认服务启动时已完成规则初始化导入"
            )

        threshold_map = {t.param_key: t.param_value for t in thresholds}
        config = RuleConfig(
            rename_map={m.source_code: m.target_code for m in mappings},
            special_products={
                b.product_code: SpecialProductRule(
                    note=b.description or None,
                    color=(b.color or "FFC000").upper(),
                ) for b in bulks
            },
            diff_threshold=float(threshold_map.get("diff_pct", 1.0)),
            similarity_threshold=float(threshold_map.get("fuzzy_sim", 0.5)),
        )
        self.logger.info(
            f"规则配置加载完成(来源:数据库): 映射规则{len(config.rename_map)}条, "
            f"特殊产品{len(config.special_products)}个, "
            f"差异阈值{config.diff_threshold}%, "
            f"相似度阈值{config.similarity_threshold}"
        )
        return config
