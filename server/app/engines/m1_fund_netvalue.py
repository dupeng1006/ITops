# -*- coding: utf-8 -*-
"""
M1 引擎 —— 基金资产与净值核对（Fund Asset & Net Value Reconciliation）

职责：
    1. 输入校验（与 GUI v2.1 校验逻辑一致）：
       - 基金资产表列数 < 28 抛 ValueError（中文提示，含"是否文件选反"引导）
       - 净值查询表列数 < 9 抛 ValueError（中文提示，含"是否文件选反"引导）
       - 两表列数特征疑似选反（基金表 <15 列且净值表 >25 列）时记录告警日志
    2. 从规则加载器（RuleProvider）获取核对规则；
    3. 注入规则参数，驱动基准核对器 FundAssetReconciler 执行 11 步核对流水线；
    4. 返回 {stats, result_df, output_path}。

基准说明：
    核对核心逻辑原样复用 server/app/engines/fund_reconciler_base.py
    （复制自 samples/reference/fund_reconciler.py v1.0，验收基准，逻辑零改动）。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import logging
import sys
from pathlib import Path
from typing import Dict, Optional, Union

import pandas as pd

from app.engines.fund_reconciler_base import FundAssetReconciler
from app.services.rule_service import JsonRuleProvider, RuleConfig, RuleProvider

# 输入校验阈值（与 GUI v2.1 一致）
FUND_MIN_COLUMNS = 28       # 基金资产表最少列数
NETVALUE_MIN_COLUMNS = 9    # 净值查询表最少列数
FUND_TYPICAL_MIN = 15       # 基金资产表典型列数下限（低于则疑似选反）
NETVALUE_TYPICAL_MAX = 25   # 净值查询表典型列数上限（高于则疑似选反）


def setup_engine_logger(name: str = "o32ops.m1") -> logging.Logger:
    """构造 M1 引擎默认日志记录器（中文日志，输出到 stdout）"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


class M1FundNetvalueEngine:
    """
    M1 基金资产与净值核对引擎

    使用示例：
        >>> engine = M1FundNetvalueEngine()
        >>> result = engine.run(
        ...     fund_path="基金资产表.xlsx",
        ...     netvalue_path="净值查询表.xlsx",
        ...     output_path="核对结果.xlsx",
        ... )
        >>> print(result["stats"])
    """

    MODULE_CODE = "M1"
    MODULE_NAME = "基金资产与净值核对"

    def __init__(
        self,
        rule_provider: Optional[RuleProvider] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Args:
            rule_provider: 规则提供者（一期默认 JsonRuleProvider；
                           二期可注入 DatabaseRuleProvider，引擎无需改动）
            logger: 日志记录器
        """
        self.logger = logger or setup_engine_logger()
        self.rule_provider = rule_provider or JsonRuleProvider(logger=self.logger)

    def validate_input_columns(
        self,
        fund_path: Union[str, Path],
        netvalue_path: Union[str, Path],
    ) -> None:
        """
        输入文件列数校验（与 GUI v2.1 校验逻辑一致）

        校验顺序：先记录疑似选反告警日志，再抛列数不足异常，
        保证"文件选反"场景下告警日志与异常提示可同时被捕获。

        Raises:
            ValueError: 基金资产表列数 < 28 或净值查询表列数 < 9，
                        中文提示含"是否文件选反"引导
        """
        self.logger.info("正在校验输入文件...")

        # 仅读取表头获取列数，避免重复加载全表
        fund_columns = len(pd.read_excel(fund_path, header=0, nrows=0).columns)
        net_columns = len(pd.read_excel(netvalue_path, header=0, nrows=0).columns)
        self.logger.info(f"基金资产表列数: {fund_columns}, 净值查询表列数: {net_columns}")

        # 疑似选反告警（特征：基金表异常窄、净值表异常宽）
        if fund_columns < FUND_TYPICAL_MIN and net_columns > NETVALUE_TYPICAL_MAX:
            self.logger.warning("⚠️ 警告：检测到文件列数异常，可能文件选反了！")
            self.logger.warning(f"  基金资产表列数: {fund_columns} (通常>25)")
            self.logger.warning(f"  净值查询表列数: {net_columns} (通常~9)")

        if fund_columns < FUND_MIN_COLUMNS:
            raise ValueError(
                f"基金资产表列数不足！当前{fund_columns}列，需要至少{FUND_MIN_COLUMNS}列。\n"
                f"请确认：\n"
                f"1. 选择的文件是否正确（基金资产表应该有'基金编号'、'基金名称'等列）\n"
                f"2. 是否文件选反（是否将净值查询表误选为基金资产表）"
            )

        if net_columns < NETVALUE_MIN_COLUMNS:
            raise ValueError(
                f"净值查询表列数不足！当前{net_columns}列，需要至少{NETVALUE_MIN_COLUMNS}列。\n"
                f"请确认：\n"
                f"1. 选择的文件是否正确（净值查询表应该有'信托计划代码'、'资产净值'等列）\n"
                f"2. 是否文件选反（是否将基金资产表误选为净值查询表）"
            )

        self.logger.info("输入文件校验通过")

    def run(
        self,
        fund_path: Union[str, Path],
        netvalue_path: Union[str, Path],
        output_path: Union[str, Path],
        rule_config: Optional[RuleConfig] = None,
    ) -> Dict:
        """
        执行 M1 基金资产与净值核对

        Args:
            fund_path: 基金资产表路径（.xlsx）
            netvalue_path: 净值查询表路径（.xlsx）
            output_path: 核对结果 Excel 输出路径
            rule_config: 可选，直接指定规则配置（跳过规则加载器，便于测试）；
                         为 None 时通过 rule_provider 加载

        Returns:
            dict: {
                "module": 模块代码 "M1",
                "stats": 核对统计 dict（与基准小程序一致）,
                "result_df": 核对结果 DataFrame（含是否大宗列）,
                "output_path": 结果 Excel 落盘路径 str,
            }

        Raises:
            FileNotFoundError: 输入文件不存在
            ValueError: 输入文件列数不足（提示含"是否文件选反"引导）
        """
        fund_path = Path(fund_path)
        netvalue_path = Path(netvalue_path)
        output_path = Path(output_path)

        self.logger.info("=" * 60)
        self.logger.info(f"开始 {self.MODULE_CODE} {self.MODULE_NAME}引擎执行")
        self.logger.info("=" * 60)

        # 1. 输入文件存在性检查
        for label, path in (("基金资产表", fund_path), ("净值查询表", netvalue_path)):
            if not path.exists():
                raise FileNotFoundError(f"{label}不存在: {path}")

        # 2. 输入列数校验（GUI v2.1 逻辑回移）
        self.validate_input_columns(fund_path, netvalue_path)

        # 3. 加载核对规则
        if rule_config is None:
            rule_config = self.rule_provider.get_rule_config()

        # 4. 注入规则，构造基准核对器并执行 11 步核对流水线
        self.logger.info("正在初始化核对器（注入规则配置）...")
        reconciler = FundAssetReconciler(
            rename_map=dict(rule_config.rename_map),
            special_products=dict(rule_config.special_products),
            diff_threshold=rule_config.diff_threshold,
            similarity_threshold=rule_config.similarity_threshold,
            logger=self.logger,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        stats = reconciler.reconcile(
            fund_path=str(fund_path),
            netvalue_path=str(netvalue_path),
            output_path=str(output_path),
        )

        self.logger.info(f"{self.MODULE_CODE} 引擎执行完成，结果文件: {output_path}")

        return {
            "module": self.MODULE_CODE,
            "stats": stats,
            "result_df": reconciler.result_df,
            "output_path": str(output_path),
        }
