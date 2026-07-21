# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 任务启动服务（二期 DS-F5：任务调度中心）

供定时调度以编程方式创建并执行 M1/M2 核对任务，口径与
POST /api/recon/m1|m2/jobs 端点一致（取数/快照/校验/登记/执行）：

    - db 模式：模板校验 → 同步取数 → 查询快照落 input/ → 输入校验
      → recon_job(trigger_type=schedule) → 执行；
    - file 模式：监测配置目录文件就绪（关键字匹配最新文件，执行时检查一次，
      不做守护线程）→ 复制入归档 → 同上流水线；文件未就绪抛
      FilesNotReadyError，由调度层标记"待文件"并安排重试。

执行方式：run_async=False 同步执行（定时场景，结果立即可判定，供失败重试）；
run_async=True 后台线程（手动"立即执行"亦可同步——调度线程内运行，不阻塞 HTTP）。

注意：routes_recon 端点逻辑保持原样不动（防回归），本服务复刻其创建口径；
执行线程函数（_run_m1_job/_run_m2_job）直接复用，唯一事实来源。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import logging
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import ReconJob, ReconResultFile
from app.services import archive_service, fetch_service
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

# file 模式目录监测关键字（按真实导出文件命名习惯）
M1_FUND_KEYWORD = "基金资产"
M1_NET_KEYWORD = "净值"
M2_SYSTEM_KEYWORD = "新综合信息查询"
M2_VALUATION_KEYWORD = "估值表"


class FilesNotReadyError(Exception):
    """file 模式监测目录文件未就绪（调度层据此标记任务"待文件"并安排重试）"""


def _new_job_id() -> str:
    return uuid.uuid4().hex[:16]


def _pick_files(file_dir: Path, keyword: str) -> List[Path]:
    """目录中按关键字 + 允许扩展名筛文件，按修改时间新→旧排序"""
    if not file_dir.is_dir():
        return []
    files = [
        p for p in file_dir.iterdir()
        if p.is_file() and p.suffix.lower() in archive_service.ALLOWED_UPLOAD_EXTS
        and keyword in p.name
    ]
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def _register_job_and_run(
    db: Session,
    *,
    job_id: str,
    module: str,
    biz_date: str,
    fetch_mode: str,
    trigger_type: str,
    created_by: str,
    input_paths: List[Path],
    audit_detail: str,
    run_async: bool,
) -> str:
    """登记 recon_job + 输入文件索引（或复用既有 wait_file 任务），随后执行"""
    from app.api import routes_recon  # 延迟导入避免循环

    job = db.get(ReconJob, job_id)
    if job is None:
        job = ReconJob(
            id=job_id, module=module, biz_date=biz_date, fetch_mode=fetch_mode,
            status="pending", trigger_type=trigger_type, progress=0, created_by=created_by,
        )
        db.add(job)
    else:
        # 复用"待文件"任务：补齐输入后重新进入待执行
        job.status = "pending"
        job.error = None
        job.progress = 0
        job.started_at = None
        job.finished_at = None
    for path in input_paths:
        db.add(ReconResultFile(
            job_id=job_id, file_type="input",
            file_path=str(path), file_name=Path(path).name,
        ))
    record_audit(db, created_by, "schedule_create_job", "recon_job", job_id, audit_detail, None)
    db.commit()

    runner = routes_recon._run_m1_job if module == "M1" else routes_recon._run_m2_job
    if run_async:
        threading.Thread(target=runner, args=(job_id,), daemon=True).start()
    else:
        runner(job_id)
    return job_id


# =============================================================================
# M1
# =============================================================================

def launch_m1_db_job(
    db: Session,
    *,
    fund_template_id: int,
    netvalue_template_id: int,
    biz_date: str,
    created_by: str,
    trigger_type: str = "schedule",
    run_async: bool = False,
    job_id: Optional[str] = None,
) -> str:
    """M1 db 取数建任务并执行（与 POST /api/recon/m1/jobs db 分支同口径）"""
    from app.engines.m1_fund_netvalue import M1FundNetvalueEngine

    settings = get_settings()
    job_id = job_id or _new_job_id()

    fund_tpl = fetch_service.load_template_checked(db, fund_template_id, "m1_fund", "基金资产查询模板")
    net_tpl = fetch_service.load_template_checked(db, netvalue_template_id, "m1_netvalue", "净值查询模板")

    input_dir, _ = archive_service.prepare_job_dirs("M1", biz_date, job_id)
    try:
        df_fund, ds_fund, _ = fetch_service.fetch_template_df(db, fund_tpl, biz_date, settings)
        df_net, ds_net, _ = fetch_service.fetch_template_df(db, net_tpl, biz_date, settings)
        fund_path = fetch_service.write_xlsx_materialization(
            df_fund, input_dir, f"fund__查询快照_基金资产表_tpl{fund_tpl.id}.xlsx")
        net_path = fetch_service.write_xlsx_materialization(
            df_net, input_dir, f"netvalue__查询快照_净值查询表_tpl{net_tpl.id}.xlsx")
        snap_fund = fetch_service.write_csv_snapshot(
            df_fund, input_dir, f"查询快照_基金资产表_tpl{fund_tpl.id}.csv")
        snap_net = fetch_service.write_csv_snapshot(
            df_net, input_dir, f"查询快照_净值查询表_tpl{net_tpl.id}.csv")
        M1FundNetvalueEngine().validate_input_columns(fund_path, net_path)
    except Exception:
        # 取数/校验失败：清理归档目录，不建任务记录（wait_file 复用场景保留任务行）
        if db.get(ReconJob, job_id) is None:
            shutil.rmtree(input_dir.parent, ignore_errors=True)
        raise

    return _register_job_and_run(
        db, job_id=job_id, module="M1", biz_date=biz_date, fetch_mode="db",
        trigger_type=trigger_type, created_by=created_by,
        input_paths=[fund_path, net_path, snap_fund, snap_net],
        audit_detail=(f"定时创建 M1 核对任务（db 取数），业务日期={biz_date}，"
                      f"基金资产模板={fund_tpl.name}(id={fund_tpl.id},数据源={ds_fund.name})，"
                      f"净值模板={net_tpl.name}(id={net_tpl.id},数据源={ds_net.name})"),
        run_async=run_async,
    )


def check_m1_files_ready(file_dir: str) -> Tuple[bool, str]:
    """M1 文件就绪检查（执行时检查一次）：返回 (是否就绪, 缺失说明)"""
    base = Path(file_dir)
    if not base.is_dir():
        return False, f"监测目录不存在: {file_dir}"
    missing = []
    if not _pick_files(base, M1_FUND_KEYWORD):
        missing.append(f"基金资产表（文件名需含「{M1_FUND_KEYWORD}」）")
    if not _pick_files(base, M1_NET_KEYWORD):
        missing.append(f"净值查询表（文件名需含「{M1_NET_KEYWORD}」）")
    if missing:
        return False, f"监测目录 {file_dir} 缺: " + "、".join(missing)
    return True, ""


def launch_m1_file_job(
    db: Session,
    *,
    file_dir: str,
    biz_date: str,
    created_by: str,
    trigger_type: str = "schedule",
    run_async: bool = False,
    job_id: Optional[str] = None,
) -> str:
    """M1 file 模式：从监测目录取最新两表建任务并执行；未就绪抛 FilesNotReadyError"""
    from app.engines.m1_fund_netvalue import M1FundNetvalueEngine

    ready, reason = check_m1_files_ready(file_dir)
    if not ready:
        raise FilesNotReadyError(reason)

    base = Path(file_dir)
    job_id = job_id or _new_job_id()
    input_dir, _ = archive_service.prepare_job_dirs("M1", biz_date, job_id)
    try:
        fund_src = _pick_files(base, M1_FUND_KEYWORD)[0]
        net_src = _pick_files(base, M1_NET_KEYWORD)[0]
        fund_path = archive_service.save_upload(input_dir, "fund", fund_src.name, fund_src.read_bytes())
        net_path = archive_service.save_upload(input_dir, "netvalue", net_src.name, net_src.read_bytes())
        M1FundNetvalueEngine().validate_input_columns(fund_path, net_path)
    except Exception:
        if db.get(ReconJob, job_id) is None:
            shutil.rmtree(input_dir.parent, ignore_errors=True)
        raise

    return _register_job_and_run(
        db, job_id=job_id, module="M1", biz_date=biz_date, fetch_mode="file",
        trigger_type=trigger_type, created_by=created_by,
        input_paths=[fund_path, net_path],
        audit_detail=(f"定时创建 M1 核对任务（file 监测目录 {file_dir}），业务日期={biz_date}，"
                      f"基金资产表={fund_path.name}，净值查询表={net_path.name}"),
        run_async=run_async,
    )


# =============================================================================
# M2
# =============================================================================

def launch_m2_db_job(
    db: Session,
    *,
    groups_json: str,
    biz_date: str,
    created_by: str,
    trigger_type: str = "schedule",
    run_async: bool = False,
    job_id: Optional[str] = None,
) -> str:
    """M2 db 取数建任务并执行（与 POST /api/recon/m2/jobs db 分支同口径）"""
    from app.api.routes_recon import _load_m2_engine_config
    from app.engines.m2_valuation_price import M2ValuationPriceEngine
    from app.models.database import get_session_factory

    settings = get_settings()
    job_id = job_id or _new_job_id()

    groups = fetch_service.parse_m2_groups(groups_json)
    plan: List[Dict] = []
    seen: Dict[str, str] = {}
    for i, g in enumerate(groups, 1):
        sys_tpl = fetch_service.load_template_checked(db, g["system_template_id"], "m2_system", "系统端查询模板")
        val_tpl = fetch_service.load_template_checked(db, g["valuation_template_id"], "m2_valuation", "估值表查询模板")
        product = fetch_service.derive_product(g["product"], sys_tpl.name, i)
        if product in seen:
            raise ValueError(f"存在重复产品标识 {product} 的分组（第 {seen[product]} 组与第 {i} 组）")
        seen[product] = str(i)
        plan.append({"product": product, "sys_tpl": sys_tpl, "val_tpl": val_tpl})

    input_dir, _ = archive_service.prepare_job_dirs("M2", biz_date, job_id)
    saved: Dict[str, Dict[str, Path]] = {}
    audit_sources: List[str] = []
    try:
        for p in plan:
            product = p["product"]
            df_sys, ds_sys, _ = fetch_service.fetch_template_df(db, p["sys_tpl"], biz_date, settings)
            df_val, ds_val, _ = fetch_service.fetch_template_df(db, p["val_tpl"], biz_date, settings)
            sys_path = fetch_service.write_csv_snapshot(
                df_sys, input_dir, f"system__{product}__查询快照_系统端_tpl{p['sys_tpl'].id}.csv")
            val_path = fetch_service.write_valuation_csv_snapshot(
                df_val, input_dir,
                f"valuation__{product}__查询快照_估值表_tpl{p['val_tpl'].id}.csv",
                ["证券投资基金估值表（数据库查询快照）",
                 f"模板:{p['val_tpl'].name} 数据源:{ds_val.name} 业务日期:{biz_date}",
                 ""])
            saved[product] = {"system": sys_path, "valuation": val_path}
            audit_sources.append(
                f"{product}[系统端={p['sys_tpl'].name}(id={p['sys_tpl'].id},数据源={ds_sys.name}) "
                f"估值表={p['val_tpl'].name}(id={p['val_tpl'].id},数据源={ds_val.name})]")

        configs, fuzzy_sim, price_tol = _load_m2_engine_config(get_session_factory(), logger)
        engine = M2ValuationPriceEngine(subject_rules=configs, fuzzy_sim=fuzzy_sim, price_tol=price_tol)
        for product in saved:
            engine.validate_input_files(saved[product]["system"], saved[product]["valuation"])
    except Exception:
        if db.get(ReconJob, job_id) is None:
            shutil.rmtree(input_dir.parent, ignore_errors=True)
        raise

    input_paths = [saved[p][k] for p in saved for k in ("system", "valuation")]
    return _register_job_and_run(
        db, job_id=job_id, module="M2", biz_date=biz_date, fetch_mode="db",
        trigger_type=trigger_type, created_by=created_by,
        input_paths=input_paths,
        audit_detail=(f"定时创建 M2 估值价格核对任务（db 取数），业务日期={biz_date}，"
                      f"产品={','.join(saved.keys())}，" + "；".join(audit_sources)),
        run_async=run_async,
    )


def check_m2_files_ready(file_dir: str) -> Tuple[bool, str]:
    """M2 文件就绪检查：系统端/估值表至少各 1 个（配对完整性在启动时校验）"""
    base = Path(file_dir)
    if not base.is_dir():
        return False, f"监测目录不存在: {file_dir}"
    missing = []
    if not _pick_files(base, M2_SYSTEM_KEYWORD):
        missing.append(f"系统端文件（文件名需含「{M2_SYSTEM_KEYWORD}」）")
    if not _pick_files(base, M2_VALUATION_KEYWORD):
        missing.append(f"估值表文件（文件名需含「{M2_VALUATION_KEYWORD}」）")
    if missing:
        return False, f"监测目录 {file_dir} 缺: " + "、".join(missing)
    return True, ""


def launch_m2_file_job(
    db: Session,
    *,
    file_dir: str,
    biz_date: str,
    created_by: str,
    trigger_type: str = "schedule",
    run_async: bool = False,
    job_id: Optional[str] = None,
) -> str:
    """M2 file 模式：监测目录内文件按产品标识配对建任务并执行；未就绪抛 FilesNotReadyError"""
    from app.api.routes_recon import _load_m2_engine_config, _pair_m2_files
    from app.engines.m2_valuation_price import M2ValuationPriceEngine
    from app.models.database import get_session_factory

    ready, reason = check_m2_files_ready(file_dir)
    if not ready:
        raise FilesNotReadyError(reason)

    base = Path(file_dir)
    sys_files = {p.name: p for p in _pick_files(base, M2_SYSTEM_KEYWORD)}
    val_files = {p.name: p for p in _pick_files(base, M2_VALUATION_KEYWORD)}
    pairs = _pair_m2_files(list(sys_files), list(val_files))  # 落单/重复/无标识 → HTTPException 400

    job_id = job_id or _new_job_id()
    input_dir, _ = archive_service.prepare_job_dirs("M2", biz_date, job_id)
    saved: Dict[str, Dict[str, Path]] = {}
    try:
        for product, pair in pairs.items():
            saved[product] = {
                "system": archive_service.save_upload(
                    input_dir, f"system__{product}", pair["system"],
                    sys_files[pair["system"]].read_bytes()),
                "valuation": archive_service.save_upload(
                    input_dir, f"valuation__{product}", pair["valuation"],
                    val_files[pair["valuation"]].read_bytes()),
            }
        configs, fuzzy_sim, price_tol = _load_m2_engine_config(get_session_factory(), logger)
        engine = M2ValuationPriceEngine(subject_rules=configs, fuzzy_sim=fuzzy_sim, price_tol=price_tol)
        for product in saved:
            engine.validate_input_files(saved[product]["system"], saved[product]["valuation"])
    except Exception:
        if db.get(ReconJob, job_id) is None:
            shutil.rmtree(input_dir.parent, ignore_errors=True)
        raise

    input_paths = [saved[p][k] for p in saved for k in ("system", "valuation")]
    return _register_job_and_run(
        db, job_id=job_id, module="M2", biz_date=biz_date, fetch_mode="file",
        trigger_type=trigger_type, created_by=created_by,
        input_paths=input_paths,
        audit_detail=(f"定时创建 M2 估值价格核对任务（file 监测目录 {file_dir}），业务日期={biz_date}，"
                      f"产品={','.join(saved.keys())}"),
        run_async=run_async,
    )
