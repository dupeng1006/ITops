# -*- coding: utf-8 -*-
"""
M1 黄金样本预期结果生成脚本

用 M1 引擎对黄金样本执行一次核对，将输出固化为回归基线：
    - expected/核对结果_预期.xlsx      （含颜色标注的结果 Excel）
    - expected/expected_stats.json     （统计 dict）
    - expected/expected_result_df.pkl  （结果 DataFrame，pickle 保 dtype）

注意：
    预期结果的正确性已由人工理论推导核对（见本目录 README.md 第 3、4 节），
    本脚本仅负责固化，不重算理论预期。
    仅当基准逻辑、规则配置或样本有经评审的变更时才应重新运行本脚本。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import json
import pickle
import sys
from pathlib import Path

# 将 server/ 加入模块搜索路径（本文件位于 server/tests/golden/）
SERVER_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SERVER_ROOT.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.engines.m1_fund_netvalue import M1FundNetvalueEngine  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent
EXPECTED_DIR = GOLDEN_DIR / "expected"
FUND_SAMPLE = PROJECT_ROOT / "samples" / "golden" / "基金资产表_样本.xlsx"
NETVALUE_SAMPLE = PROJECT_ROOT / "samples" / "golden" / "净值查询表_样本.xlsx"

EXPECTED_EXCEL = EXPECTED_DIR / "核对结果_预期.xlsx"
EXPECTED_STATS = EXPECTED_DIR / "expected_stats.json"
EXPECTED_DF = EXPECTED_DIR / "expected_result_df.pkl"


def main() -> int:
    for path in (FUND_SAMPLE, NETVALUE_SAMPLE):
        if not path.exists():
            print(f"样本不存在: {path}，请先运行 make_samples.py", file=sys.stderr)
            return 1

    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)

    engine = M1FundNetvalueEngine()
    result = engine.run(
        fund_path=str(FUND_SAMPLE),
        netvalue_path=str(NETVALUE_SAMPLE),
        output_path=str(EXPECTED_EXCEL),
    )

    with open(EXPECTED_STATS, "w", encoding="utf-8") as f:
        json.dump(result["stats"], f, ensure_ascii=False, indent=4)

    with open(EXPECTED_DF, "wb") as f:
        pickle.dump(result["result_df"], f)

    print("\n预期结果已固化:")
    print(f"  {EXPECTED_EXCEL}")
    print(f"  {EXPECTED_STATS}")
    print(f"  {EXPECTED_DF}")
    print("\n统计 dict:")
    for key, value in result["stats"].items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
