# -*- coding: utf-8 -*-
"""
M3 黄金样本预期结果固化脚本

用 M3 引擎对黄金样本执行一次匹配，将输出固化为回归基线：
    - expected/基金属性_精确匹配更新.xlsx
    - expected/精确匹配结果明细.xlsx
    - expected/精确匹配说明.md
    - expected/expected_stats.json
    - expected/expected_detail_df.pkl

注意：预期正确性已由人工理论推导核对（见本目录 README.md 第 3、4 节），
本脚本仅负责固化，不重算理论预期。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import json
import pickle
import sys
from pathlib import Path

# 将 server/ 加入模块搜索路径（本文件位于 server/tests/golden/m3/）
SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.engines.m3_interbank_id import M3InterbankIdEngine  # noqa: E402

M3_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = M3_DIR / "samples"
EXPECTED_DIR = M3_DIR / "expected"

FUND_SAMPLE = SAMPLE_DIR / "基金属性表_样本.xlsx"
MEMBER_SAMPLE = SAMPLE_DIR / "交易成员基本信息表_样本.csv"


def main() -> int:
    for path in (FUND_SAMPLE, MEMBER_SAMPLE):
        if not path.exists():
            print(f"样本不存在: {path}，请先运行 make_samples_m3.py", file=sys.stderr)
            return 1

    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)

    engine = M3InterbankIdEngine()
    result = engine.run(
        fund_path=str(FUND_SAMPLE),
        member_path=str(MEMBER_SAMPLE),
        output_dir=str(EXPECTED_DIR),
    )

    with open(EXPECTED_DIR / "expected_stats.json", "w", encoding="utf-8") as f:
        json.dump(result["stats"], f, ensure_ascii=False, indent=4)

    with open(EXPECTED_DIR / "expected_detail_df.pkl", "wb") as f:
        pickle.dump(result["detail_df"], f)

    print("\n预期结果已固化:")
    for p in result["output_files"]:
        print(f"  {p}")
    print(f"  {EXPECTED_DIR / 'expected_stats.json'}")
    print(f"  {EXPECTED_DIR / 'expected_detail_df.pkl'}")
    print("\n统计 dict:")
    for key, value in result["stats"].items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
