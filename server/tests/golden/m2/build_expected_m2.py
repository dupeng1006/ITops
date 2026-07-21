# -*- coding: utf-8 -*-
"""
M2 预期结果固化脚本

以样本为输入运行 M2 引擎（黄金口径：1101→市价 / 1501→单位成本，
fuzzy_sim=0.5，price_tol=0.0001），将统计与逐行判定固化为基线：

    expected/expected_stats.json   统计摘要（products + 合计）
    expected/expected_rows.json    逐行判定（证券代码/差异状态/匹配方式/科目类型/备注）

注意：仅在业务规格、引擎逻辑或样本有**经评审变更**时方可重建基线；
重建前必须先更新 README.md 第 3 节的理论预期并对照。

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests\\golden\\m2\\build_expected_m2.py

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import json
import sys
import tempfile
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[3]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.engines.m2_valuation_price import (  # noqa: E402
    M2ValuationPriceEngine,
    SubjectPriceRuleConfig,
)

M2_DIR = Path(__file__).resolve().parent
SAMPLES = M2_DIR / "samples"
EXPECTED = M2_DIR / "expected"

GOLDEN_RULES = [
    SubjectPriceRuleConfig("1101", "市价", "交易性金融资产", "", 1),
    SubjectPriceRuleConfig("1501", "单位成本", "债权投资",
                           "摊余成本与市场估值口径差异，属正常", 2),
]
GOLDEN_FUZZY_SIM = 0.5
GOLDEN_PRICE_TOL = 0.0001

ROW_KEYS = ["证券代码", "证券名称", "差异状态", "匹配方式", "科目类型", "备注"]


def run_engine(output_dir: Path):
    engine = M2ValuationPriceEngine(
        subject_rules=GOLDEN_RULES,
        fuzzy_sim=GOLDEN_FUZZY_SIM,
        price_tol=GOLDEN_PRICE_TOL,
    )
    jobs = [
        {"product": "6301",
         "system_path": str(SAMPLES / "新综合信息查询_基金证券-6301.xlsx"),
         "valuation_path": str(SAMPLES / "证券投资基金估值表_6301-20260720.xlsx")},
        {"product": "6302",
         "system_path": str(SAMPLES / "新综合信息查询_基金证券-6302.xlsx"),
         "valuation_path": str(SAMPLES / "证券投资基金估值表_6302-20260720.xlsx")},
    ]
    return engine.run(jobs=jobs, output_dir=str(output_dir))


def main() -> int:
    EXPECTED.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="o32ops_m2_expected_") as tmp:
        result = run_engine(Path(tmp))

    stats = result["stats"]
    rows = {
        r["product"]: [
            {k: (None if r["report_df"].iloc[i][k] != r["report_df"].iloc[i][k]
                 else r["report_df"].iloc[i][k]) for k in ROW_KEYS}
            for i in range(len(r["report_df"]))
        ]
        for r in result["results"]
    }

    (EXPECTED / "expected_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    (EXPECTED / "expected_rows.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"已固化: {EXPECTED / 'expected_stats.json'}")
    print(f"已固化: {EXPECTED / 'expected_rows.json'}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    for product, product_rows in rows.items():
        print(f"--- {product} 逐行 ---")
        for row in product_rows:
            print(f"  {row['证券代码']} | {row['差异状态']} | {row['匹配方式']} | "
                  f"{row['科目类型']} | {row['备注'][:30] if row['备注'] else ''}")
    print("M2 预期结果固化完成 ✅（请对照 README.md 第 3 节理论预期复核）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
