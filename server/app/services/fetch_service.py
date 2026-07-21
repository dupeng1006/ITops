# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据库取数服务（二期 DS-F4）

职责（任务创建时的同步取数链路）：
    查询模板校验（存在 404 / 所属模块匹配 400 / 模板与数据源启用）
    → DbAdapter 执行只读查询（biz_date 绑定注入，SQL Guard 双校验）
    → DataFrame 落**查询快照**进入任务 input 归档目录
    → 后续流水线与文件模式完全一致（同引擎、同输出、同归档）

快照约定（方案补充完善点 1：原始输入归档可重算）：
    - 快照一律 UTF-8-SIG 编码 CSV（防 Excel 打开乱码），pandas str() 精度
      写出（float64 最短往返表示），index 不落盘；
    - M1：基准复制件（fund_reconciler_base.py）受"逐字节一致"约束不改动，
      故每个查询结果同时落两件——
        `查询快照_*.csv`            归档工件（人读/重算比对用）
        `fund__/netvalue__*.xlsx`   引擎消费件（同 DataFrame 物化，
                                    匹配既有 fund__/netvalue__ 归当前缀，
                                    线程与引擎零改动）；
    - M2：引擎为平台自研且已支持按扩展名分派读取（table_io.read_table），
      直接消费带 `system__{产品}__/valuation__{产品}__` 前缀的 CSV 快照，
      单一工件；估值表快照按真实文件版式前置 3 行标题占位
      （引擎 skiprows=3 读取口径不变）。

模板契约（重要）：
    - M1/M2 引擎按**列位**解析输入，模板结果列序必须与对应文件版式一致；
      字段映射（column_map）用于把库表列名转为标准列名，不改变列位；
    - 任务仅注入 `:biz_date` 一个参数：模板声明了 biz_date 参数则按
      参数定义校验绑定；未声明则不注入（模板可自行固化日期条件）；
      声明了其他必填参数的模板无法由任务驱动，建任务时 400 中文指明。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import io
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.datasource.base import FetchContext
from app.datasource.db_adapter import (
    ConnectionSpec,
    DatasourceError,
    execute_query,
    validate_params,
)
from app.core.crypto import decrypt_secret
from app.models.entities import DsConnection, DsQueryTemplate

logger = logging.getLogger(__name__)

# 模块中文标签（报错与审计用）
MODULE_LABELS = {
    "m1_fund": "M1 基金资产查询模板",
    "m1_netvalue": "M1 净值查询模板",
    "m2_system": "M2 系统端查询模板",
    "m2_valuation": "M2 估值表查询模板",
    "m3_member": "M3 交易成员查询模板",
}


# =============================================================================
# 模板校验与取数
# =============================================================================

def load_template_checked(db: Session, tpl_id: Optional[int],
                          expected_module: str, label: str) -> DsQueryTemplate:
    """
    加载并校验查询模板：必填/存在(404)/所属模块匹配(400)/启用(400)

    Args:
        tpl_id: 模板 ID（None 时 400 指明缺参）
        expected_module: 任务要求的所属模块（如 m1_fund）
        label: 中文角色名（如 基金资产查询模板），用于错误提示
    """
    if tpl_id is None:
        raise HTTPException(
            status_code=400,
            detail=f"db 取数模式必须提供{label} ID（{expected_module}）")
    tpl = db.get(DsQueryTemplate, tpl_id)
    if tpl is None:
        raise HTTPException(status_code=404, detail=f"查询模板不存在: id={tpl_id}")
    if tpl.module != expected_module:
        raise HTTPException(
            status_code=400,
            detail=f"模板「{tpl.name}」(id={tpl.id}) 所属模块为 {tpl.module}"
                   f"（{MODULE_LABELS.get(tpl.module, tpl.module)}），"
                   f"不能用作{label}（要求 {expected_module}）")
    if not tpl.enabled:
        raise HTTPException(status_code=400, detail=f"查询模板已停用: {tpl.name}")
    return tpl


def _build_spec(ds: DsConnection) -> ConnectionSpec:
    """由实体构造连接规格（解密密码，仅内存使用）"""
    try:
        password = decrypt_secret(ds.password_enc)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return ConnectionSpec(
        db_type=ds.db_type, host=ds.host, port=ds.port,
        username=ds.username, password=password,
        db_name=ds.db_name, service_name=ds.service_name, sid=ds.sid,
    )


def fetch_template_df(db: Session, tpl: DsQueryTemplate, biz_date: str,
                      settings: Settings) -> Tuple[pd.DataFrame, DsConnection, List[str]]:
    """
    执行模板查询返回标准 DataFrame（任务侧同步调用）

    Returns:
        (df, ds, protections)：查询结果、数据源实体、实际生效的执行保护（审计用）

    Raises:
        HTTPException 400: 数据源停用 / 参数校验失败 / 查询执行失败（中文友好）
    """
    ds = db.get(DsConnection, tpl.ds_id)
    if ds is None:
        raise HTTPException(status_code=400, detail=f"模板「{tpl.name}」关联的数据源不存在: id={tpl.ds_id}")
    if not ds.enabled:
        raise HTTPException(status_code=400, detail=f"模板「{tpl.name}」关联的数据源已停用: {ds.name}")

    params_def = json.loads(tpl.params_json) if tpl.params_json else {}
    column_map = json.loads(tpl.column_map_json) if tpl.column_map_json else {}
    # 任务仅注入 biz_date；模板未声明任何参数时不注入（避免"未定义参数"报错）
    raw_params = {"biz_date": biz_date} if params_def else {}
    try:
        bound = validate_params(params_def, raw_params)
    except DatasourceError as e:
        raise HTTPException(
            status_code=400,
            detail=f"模板「{tpl.name}」参数校验失败：{e}（任务仅支持注入 biz_date 参数）")

    context = FetchContext(
        params=bound,
        timeout_seconds=settings.DS_QUERY_TIMEOUT,
        max_rows=settings.DS_MAX_ROWS,
    )
    try:
        result = execute_query(_build_spec(ds), tpl.sql_text, bound, column_map, context)
    except DatasourceError as e:
        raise HTTPException(status_code=400, detail=f"模板「{tpl.name}」查询失败：{e}")

    logger.info(
        f"db 取数完成: 模板={tpl.name}(id={tpl.id}) 数据源={ds.name} "
        f"biz_date={biz_date} 行数={result.rows_returned} 耗时={result.elapsed_ms}ms"
    )
    return result.df, ds, result.protections


# =============================================================================
# 快照落盘
# =============================================================================

def _csv_bytes(df: pd.DataFrame) -> bytes:
    """DataFrame → UTF-8-SIG CSV 字节（float64 最短往返精度，不落 index）"""
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue().encode("utf-8-sig")


def write_csv_snapshot(df: pd.DataFrame, input_dir: Path, filename: str) -> Path:
    """落查询快照 CSV（UTF-8-SIG；归档工件/引擎消费件）"""
    path = input_dir / filename
    path.write_bytes(_csv_bytes(df))
    logger.info(f"查询快照已归档: {path}（{len(df)} 行 × {len(df.columns)} 列）")
    return path


def write_valuation_csv_snapshot(df: pd.DataFrame, input_dir: Path, filename: str,
                                 meta_lines: List[str]) -> Path:
    """
    落 M2 估值表查询快照：前置 3 行标题占位（复刻真实估值表版式，
    引擎 skiprows=3 读取口径不变），随后为列头 + 数据行
    """
    lines = [(meta_lines + [""] * 3)[:3]]  # 恰好 3 行
    head = "\n".join(lines[0]) + "\n"
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    path = input_dir / filename
    path.write_bytes((head + buf.getvalue()).encode("utf-8-sig"))
    logger.info(f"估值表查询快照已归档: {path}（{len(df)} 行 × {len(df.columns)} 列，含 3 行标题占位）")
    return path


def write_xlsx_materialization(df: pd.DataFrame, input_dir: Path, filename: str) -> Path:
    """落引擎消费件 xlsx（M1 基准复制件只读 Excel，由快照同源物化）"""
    path = input_dir / filename
    df.to_excel(path, index=False)
    logger.info(f"引擎消费件已物化: {path}（{len(df)} 行 × {len(df.columns)} 列）")
    return path


# =============================================================================
# M2 分组解析（db 模式）
# =============================================================================

_PRODUCT_RE = re.compile(r"(\d{4,})")


def parse_m2_groups(groups_json: Optional[str]) -> List[Dict[str, object]]:
    """
    解析 M2 db 模式分组参数

    入参 JSON 数组，每组：{"product": "6301"(可省), "system_template_id": int,
    "valuation_template_id": int}；product 缺省时从系统端模板名称提取
    4 位数字产品标识（在路由层结合模板名兜底）。

    Raises:
        HTTPException 400: JSON 非法/结构非法/缺键（中文指明第几组）
    """
    if not groups_json or not groups_json.strip():
        raise HTTPException(
            status_code=400,
            detail='db 取数模式必须提供分组参数 groups_json，形如 '
                   '[{"product":"6301","system_template_id":1,"valuation_template_id":2}]')
    try:
        groups = json.loads(groups_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"groups_json 不是合法 JSON: {e}")
    if not isinstance(groups, list) or not groups:
        raise HTTPException(status_code=400, detail="groups_json 应为非空数组（至少一组模板配对）")

    normalized: List[Dict[str, object]] = []
    for i, g in enumerate(groups, 1):
        if not isinstance(g, dict):
            raise HTTPException(status_code=400, detail=f"groups_json 第 {i} 组应为对象")
        sys_id = g.get("system_template_id")
        val_id = g.get("valuation_template_id")
        if sys_id is None or val_id is None:
            raise HTTPException(
                status_code=400,
                detail=f"groups_json 第 {i} 组缺少 system_template_id 或 valuation_template_id")
        product = g.get("product")
        normalized.append({
            "product": str(product).strip() if product else None,
            "system_template_id": int(sys_id),
            "valuation_template_id": int(val_id),
        })
    return normalized


def derive_product(explicit: Optional[str], system_tpl_name: str, group_index: int) -> str:
    """确定产品标识：显式优先，否则从系统端模板名提取 4 位数字"""
    if explicit:
        return explicit
    m = _PRODUCT_RE.search(system_tpl_name or "")
    if m:
        return m.group(1)
    raise HTTPException(
        status_code=400,
        detail=f"groups_json 第 {group_index} 组未提供 product，且系统端模板名称"
               f"「{system_tpl_name}」中未识别到产品标识（4 位数字），"
               f"请显式指定 product 或规范模板命名")
