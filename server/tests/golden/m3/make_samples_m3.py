# -*- coding: utf-8 -*-
"""
M3 黄金样本构造脚本（全脱敏虚构数据）

重要声明：
    本脚本生成的所有数据均为虚构的脱敏测试数据，不包含任何真实生产数据。
    产品名称一律使用"测试XX"虚构名，银行间ID、机构代码均为虚构编号，
    不指向任何真实产品或机构。

样本设计（覆盖 M3 精确匹配全部分支与类型陷阱）：
    a. 精确匹配-无变化（原ID=新ID，蓝 BDD7EE）×4
       —— 原ID以**数值**存储于 Excel（如 1001），成员表 ID 为字符串 '1001'
    b. 精确匹配-有变动（绿 C6EFCE）×5
       —— 含 2 行原ID为空（空→新ID）
    c. 未匹配-内部简称（TR_ 前缀，红 FFC7CE）×2
    d. 未匹配-未注册产品（交易成员表无任何相近名称）×2
    e. 未匹配-命名后缀不一致（与成员全称互为包含关系）×2
    f. 类型陷阱：银行间ID 列为 数值+空值 混合，pandas 读回推断为 float64，
       验证 astype(str)/规整路径（'1001.0' 必须归一为 '1001'，空值为 ''）

输出（本文件目录 samples/ 下）：
    基金属性表_样本.xlsx            （5 列 × 15 行）
    交易成员基本信息表_样本.csv      （3 列 × 12 行，GBK 编码）

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import sys
from pathlib import Path

import pandas as pd

SAMPLE_DIR = Path(__file__).resolve().parent / "samples"
FUND_SAMPLE_PATH = SAMPLE_DIR / "基金属性表_样本.xlsx"
MEMBER_SAMPLE_PATH = SAMPLE_DIR / "交易成员基本信息表_样本.csv"

# =============================================================================
# 虚构样本数据定义
# =============================================================================

# 基金属性表：每行 (基金代码, 基金全称, 基金类型, 银行间ID[数值或None], 备注)
# 银行间ID 故意以数值/空值混合存储，制造 float64 类型陷阱
FUND_ROWS = [
    ("F001", "测试稳利1号",       "固收", 1001, "场景a-无变化"),
    ("F002", "测试稳利2号",       "固收", 1002, "场景a-无变化"),
    ("F003", "测试增益3号",       "混合", 1003, "场景a-无变化"),
    ("F004", "测试增益4号",       "混合", 1004, "场景a-无变化"),
    ("F005", "测试进取5号",       "股票", 1005, "场景b-有变动"),
    ("F006", "测试进取6号",       "股票", 1006, "场景b-有变动"),
    ("F007", "测试平衡7号",       "混合", None, "场景b-有变动(原ID空)"),
    ("F008", "测试平衡8号",       "混合", None, "场景b-有变动(原ID空)"),
    ("F009", "测试安享9号",       "固收", 1009, "场景b-有变动"),
    ("F010", "TR_测试现金管理1号", "货币", None, "场景c-内部简称"),
    ("F011", "TR_测试现金管理2号", "货币", None, "场景c-内部简称"),
    ("F012", "测试新发产品1号",    "固收", None, "场景d-未注册"),
    ("F013", "测试新发产品2号",    "混合", None, "场景d-未注册"),
    ("F014", "测试长青14号A类",    "固收", None, "场景e-后缀不一致"),
    ("F015", "测试恒远15号集合",   "混合", None, "场景e-后缀不一致"),
]

# 交易成员基本信息表：每行 (交易成员全称, 交易成员ID[字符串], 机构代码)
MEMBER_ROWS = [
    ("测试稳利1号",   "1001",   "ORG001"),
    ("测试稳利2号",   "1002",   "ORG002"),
    ("测试增益3号",   "1003",   "ORG003"),
    ("测试增益4号",   "1004",   "ORG004"),
    ("测试进取5号",   "MB1005", "ORG005"),
    ("测试进取6号",   "MB1006", "ORG006"),
    ("测试平衡7号",   "MB1007", "ORG007"),
    ("测试平衡8号",   "MB1008", "ORG008"),
    ("测试安享9号",   "MB1009", "ORG009"),
    ("测试长青14号",  "MB1014", "ORG014"),
    ("测试恒远15号",  "MB1015", "ORG015"),
    ("测试其他成员",  "MB9999", "ORG099"),  # 不相关成员，模拟真实表多余记录
]

FUND_COLUMNS = ["基金代码", "基金全称", "基金类型", "银行间ID", "备注"]
MEMBER_COLUMNS = ["交易成员全称", "交易成员ID", "机构代码"]


def build_fund_sample() -> pd.DataFrame:
    """构造基金属性表样本（银行间ID 为数值/空值混合 → 读回 float64 陷阱）"""
    df = pd.DataFrame(FUND_ROWS, columns=FUND_COLUMNS)
    # 显式转为 float64，与生产环境"数值+空值"读取形态一致
    df["银行间ID"] = df["银行间ID"].astype(float)
    return df


def build_member_sample() -> pd.DataFrame:
    """构造交易成员基本信息表样本（交易成员ID 统一字符串）"""
    return pd.DataFrame(MEMBER_ROWS, columns=MEMBER_COLUMNS)


def main() -> int:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)

    df_fund = build_fund_sample()
    df_fund.to_excel(FUND_SAMPLE_PATH, index=False)
    print(f"已生成: {FUND_SAMPLE_PATH}  ({df_fund.shape[0]}行 x {df_fund.shape[1]}列)")

    df_member = build_member_sample()
    df_member.to_csv(MEMBER_SAMPLE_PATH, index=False, encoding="gbk")
    print(f"已生成: {MEMBER_SAMPLE_PATH}  ({df_member.shape[0]}行 x {df_member.shape[1]}列, GBK)")

    # 验证类型陷阱 f 已生效：读回后 银行间ID 应为 float64（含 NaN）
    check = pd.read_excel(FUND_SAMPLE_PATH, header=0)
    dtype = str(check["银行间ID"].dtype)
    print(f"基金属性表银行间ID列读回 dtype: {dtype}（预期 float64，验证类型陷阱）")
    if dtype != "float64":
        print("警告: float64 类型陷阱未生效，请检查样本构造！", file=sys.stderr)
        return 1

    # 验证 CSV GBK 读回
    check_csv = pd.read_csv(MEMBER_SAMPLE_PATH, encoding="gbk")
    print(f"交易成员表读回 {len(check_csv)} 行，首行: {check_csv.iloc[0].tolist()}")

    print("M3 黄金样本构造完成（全脱敏虚构数据）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
