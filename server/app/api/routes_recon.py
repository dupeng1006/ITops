# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 核对任务接口（M1/M2/M3；M1/M2 支持文件/数据库两种取数模式）

    POST /api/recon/m1/jobs           创建 M1 核对任务（operator/admin）
                                      fetch_mode=file(默认) 上传两表；
                                      fetch_mode=db 传 fund_template_id/netvalue_template_id
                                      + biz_date，DbAdapter 同步取数落查询快照后走同一流水线
    POST /api/recon/m2/jobs           创建 M2 估值价格核对任务（operator/admin）
                                      fetch_mode=file(默认) 多文件按产品标识配对；
                                      fetch_mode=db 传 groups_json(系统端/估值表模板分组)
                                      + biz_date，快照 CSV 直接进引擎
    POST /api/recon/m3/jobs           上传基金属性表+交易成员表创建 M3 匹配任务（operator/admin，
                                      仅文件模式；db 取数预留）
    GET  /api/recon/jobs              历史任务分页查询（viewer 及以上）
    GET  /api/recon/jobs/{id}         任务详情：状态/进度/统计摘要/结果文件清单/日志尾部
    GET  /api/recon/jobs/{id}/download 下载结果文件（operator/admin；
                                      M3 支持 ?file=updated|detail|note 下载三件套；
                                      M2 支持 ?product= 按产品下载）

流程（file 模式）：
    上传校验 → 落盘 archive/{module}/{yyyyMMdd}/{jobId}/input/
    → 创建 recon_job(pending) → 后台线程执行引擎（规则现取）
    → 结果写 result/ → 统计摘要写库。

流程（db 模式，DS-F4）：
    模板校验（存在/模块/启用）→ 同步取数（biz_date 绑定，SQL Guard 双校验）
    → 查询快照落 input/（UTF-8-SIG CSV；M1 另物化 xlsx 引擎消费件）
    → 与 file 模式完全统一的输入校验、任务记录、后台执行与归档。
    取数/校验失败清理归档目录、不建任务记录，400 中文指明。

作者：技术部
版本：1.2.0
日期：2026-07-20
"""

import json
import logging
import re
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import JobCreateResponse, JobDetailResponse, JobInfo, JobListResponse
from app.core.config import get_settings
from app.core.deps import get_db, require_roles
from app.engines.m1_fund_netvalue import M1FundNetvalueEngine
from app.engines.m2_valuation_price import (
    M2ValuationPriceEngine,
    SubjectPriceRuleConfig,
)
from app.engines.m3_interbank_id import (
    OUTPUT_DETAIL_NAME,
    OUTPUT_NOTE_NAME,
    OUTPUT_UPDATED_NAME,
    M3InterbankIdEngine,
)
from app.models.database import get_session_factory
from app.models.entities import ReconJob, ReconJobItem, ReconResultFile, SysSubjectPriceRule, SysUser
from app.services import archive_service, fetch_service
from app.services.audit_service import record_audit
from app.services.rule_service import DbRuleProvider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/recon", tags=["核对任务"])

MODULE_M1 = "M1"
MODULE_M2 = "M2"
MODULE_M3 = "M3"

# M3 三件套下载键 → 文件名映射
M3_RESULT_FILE_MAP = {
    "updated": OUTPUT_UPDATED_NAME,   # 基金属性_精确匹配更新.xlsx
    "detail": OUTPUT_DETAIL_NAME,     # 精确匹配结果明细.xlsx
    "note": OUTPUT_NOTE_NAME,         # 精确匹配说明.md
}


# =============================================================================
# 工具函数
# =============================================================================

def _to_info(job: ReconJob) -> JobInfo:
    stats = json.loads(job.stats_json) if job.stats_json else None
    return JobInfo(
        job_id=job.id,
        module=job.module,
        biz_date=job.biz_date,
        fetch_mode=job.fetch_mode,
        status=job.status,
        trigger_type=job.trigger_type,
        progress=job.progress,
        stats=stats,
        error=job.error,
        result_filename=job.result_filename,
        created_by=job.created_by,
        created_at=job.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        started_at=job.started_at.strftime("%Y-%m-%d %H:%M:%S") if job.started_at else None,
        finished_at=job.finished_at.strftime("%Y-%m-%d %H:%M:%S") if job.finished_at else None,
    )


def _validate_biz_date(biz_date: str) -> str:
    if not biz_date.isdigit() or len(biz_date) != 8:
        raise HTTPException(status_code=400, detail=f"业务日期格式错误: {biz_date}，应为 yyyyMMdd")
    return biz_date


def _build_job_logger(job_id: str, log_path: Path, module: str = "m1") -> logging.Logger:
    """构造任务专属 logger：控制台 + run.log 文件双输出（中文日志）"""
    job_logger = logging.getLogger(f"o32ops.{module}.job.{job_id}")
    job_logger.handlers = []
    job_logger.propagate = False
    job_logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    job_logger.addHandler(file_handler)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    job_logger.addHandler(stream_handler)
    return job_logger


def _write_m1_job_items(db: Session, job_id: str, result_df, job_logger: logging.Logger) -> int:
    """
    M1 结果产品级明细写入 recon_job_item（统计看板持续差异分析用）

    最大差异百分比 = |总资产差值百分比| 与 |资产净值差值百分比| 的较大者（与基准排序口径一致）；
    未匹配行差异为 NULL。明细写库仅作用于本表，不改引擎基准与结果 Excel。
    """
    if result_df is None or result_df.empty:
        return 0
    d1 = pd.to_numeric(result_df["总资产差值百分比"], errors="coerce").abs()
    d2 = pd.to_numeric(result_df["资产净值差值百分比"], errors="coerce").abs()
    max_diff = pd.concat([d1, d2], axis=1).max(axis=1)
    count = 0
    for idx, row in result_df.iterrows():
        v = max_diff.loc[idx]
        code = row.get("信托计划代码")
        name = row.get("产品名称")
        db.add(ReconJobItem(
            job_id=job_id,
            product_code=str(code) if pd.notna(code) else "",
            product_name=str(name) if pd.notna(name) else None,
            max_diff_pct=round(float(v), 6) if pd.notna(v) else None,
            match_method=str(row.get("匹配方式") or ""),
            is_bulk=bool(row.get("是否大宗", False)),
        ))
        count += 1
    job_logger.info(f"结果明细已入库: {count} 条（recon_job_item，供统计看板）")
    return count


def _run_m1_job(job_id: str) -> None:
    """
    后台线程：执行 M1 核对任务

    状态流转：pending → running → success/failed；统计摘要与结果文件登记写库。
    """
    session_factory = get_session_factory()
    db = session_factory()
    job_logger: Optional[logging.Logger] = None
    try:
        job = db.get(ReconJob, job_id)
        if job is None:
            logger.error(f"任务不存在: {job_id}")
            return

        input_dir, result_dir = archive_service.prepare_job_dirs(
            job.module, job.biz_date, job.id
        )
        log_path = result_dir / "run.log"
        job_logger = _build_job_logger(job_id, log_path)

        job.status = "running"
        job.progress = 10
        job.started_at = datetime.now()
        db.commit()

        # 输入文件（保存时加了角色前缀）
        fund_files = sorted(input_dir.glob("fund__*"))
        net_files = sorted(input_dir.glob("netvalue__*"))
        if not fund_files or not net_files:
            raise FileNotFoundError("任务输入文件缺失，请重新上传")

        # 结果文件名（同日期重复执行自动 _vN，不覆盖）
        result_name = archive_service.allocate_result_filename(job.module, job.biz_date)
        output_path = result_dir / result_name

        engine = M1FundNetvalueEngine(
            rule_provider=DbRuleProvider(session_factory=session_factory, logger=job_logger),
            logger=job_logger,
        )
        result = engine.run(
            fund_path=str(fund_files[0]),
            netvalue_path=str(net_files[0]),
            output_path=str(output_path),
        )

        # 登记结果文件
        db.add(ReconResultFile(
            job_id=job.id, file_type="result",
            file_path=str(output_path), file_name=result_name,
        ))
        db.add(ReconResultFile(
            job_id=job.id, file_type="result",
            file_path=str(log_path), file_name="run.log",
        ))
        job.status = "success"
        job.progress = 100
        job.stats_json = json.dumps(result["stats"], ensure_ascii=False)
        job.result_filename = result_name
        job.finished_at = datetime.now()
        # 结果产品级明细入库（统计看板用；明细写库异常不影响任务本体）
        try:
            _write_m1_job_items(db, job.id, result.get("result_df"), job_logger)
        except Exception as item_err:  # noqa: BLE001
            job_logger.warning(f"结果明细写库失败（不影响任务结果）: {item_err}")
        db.commit()
        job_logger.info(f"任务执行成功: {job_id}")

    except Exception as e:  # noqa: BLE001
        logger.error(f"M1 任务执行失败: {job_id}: {e}\n{traceback.format_exc()}")
        try:
            job = db.get(ReconJob, job_id)
            if job is not None:
                job.status = "failed"
                job.progress = 100
                job.error = str(e)
                job.finished_at = datetime.now()
                db.commit()
            if job_logger:
                job_logger.error(f"任务执行失败: {e}")
        except Exception:  # noqa: BLE001
            logger.error(f"任务失败状态写库异常: {job_id}")
    finally:
        if job_logger:
            for handler in list(job_logger.handlers):
                handler.close()
                job_logger.removeHandler(handler)
        db.close()


def _run_m3_job(job_id: str) -> None:
    """
    后台线程：执行 M3 银行间ID 匹配任务

    状态流转：pending → running → success/failed；
    三件套（更新表/明细/说明md）与 run.log 写入 result/ 并登记索引。
    """
    session_factory = get_session_factory()
    db = session_factory()
    job_logger: Optional[logging.Logger] = None
    try:
        job = db.get(ReconJob, job_id)
        if job is None:
            logger.error(f"任务不存在: {job_id}")
            return

        input_dir, result_dir = archive_service.prepare_job_dirs(
            job.module, job.biz_date, job.id
        )
        log_path = result_dir / "run.log"
        job_logger = _build_job_logger(job_id, log_path, module="m3")

        job.status = "running"
        job.progress = 10
        job.started_at = datetime.now()
        db.commit()

        fund_files = sorted(input_dir.glob("fund__*"))
        member_files = sorted(input_dir.glob("member__*"))
        if not fund_files or not member_files:
            raise FileNotFoundError("任务输入文件缺失，请重新上传")

        engine = M3InterbankIdEngine(logger=job_logger)
        result = engine.run(
            fund_path=str(fund_files[0]),
            member_path=str(member_files[0]),
            output_dir=str(result_dir),
        )

        # 登记结果文件（三件套 + run.log）
        for output_file in result["output_files"]:
            db.add(ReconResultFile(
                job_id=job.id, file_type="result",
                file_path=output_file, file_name=Path(output_file).name,
            ))
        db.add(ReconResultFile(
            job_id=job.id, file_type="result",
            file_path=str(log_path), file_name="run.log",
        ))
        job.status = "success"
        job.progress = 100
        job.stats_json = json.dumps(result["stats"], ensure_ascii=False)
        job.result_filename = OUTPUT_UPDATED_NAME  # 主结果文件（下载默认件）
        job.finished_at = datetime.now()
        db.commit()
        job_logger.info(f"任务执行成功: {job_id}")

    except Exception as e:  # noqa: BLE001
        logger.error(f"M3 任务执行失败: {job_id}: {e}\n{traceback.format_exc()}")
        try:
            job = db.get(ReconJob, job_id)
            if job is not None:
                job.status = "failed"
                job.progress = 100
                job.error = str(e)
                job.finished_at = datetime.now()
                db.commit()
            if job_logger:
                job_logger.error(f"任务执行失败: {e}")
        except Exception:  # noqa: BLE001
            logger.error(f"任务失败状态写库异常: {job_id}")
    finally:
        if job_logger:
            for handler in list(job_logger.handlers):
                handler.close()
                job_logger.removeHandler(handler)
        db.close()


# =============================================================================
# M1 任务创建
# =============================================================================

@router.post("/m1/jobs", response_model=JobCreateResponse, summary="创建 M1 基金资产与净值核对任务（文件/数据库两种取数模式）")
def create_m1_job(
    request: Request,
    fund_file: Optional[UploadFile] = File(None, description="基金资产表 (.xls/.xlsx)，fetch_mode=file 时必填"),
    netvalue_file: Optional[UploadFile] = File(None, description="净值查询表 (.xls/.xlsx)，fetch_mode=file 时必填"),
    fetch_mode: str = Form("file", description="取数模式: file(默认,上传文件) / db(数据库查询)"),
    fund_template_id: Optional[int] = Form(None, description="db 模式：基金资产查询模板ID（模块 m1_fund）"),
    netvalue_template_id: Optional[int] = Form(None, description="db 模式：净值查询模板ID（模块 m1_netvalue）"),
    biz_date: Optional[str] = Form(None, description="业务日期 yyyyMMdd；file 模式默认当天，db 模式必填"),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    ip = request.client.host if request.client else None

    fetch_mode = (fetch_mode or "file").strip().lower()
    if fetch_mode not in ("file", "db"):
        raise HTTPException(status_code=400, detail=f"取数模式非法: {fetch_mode}，支持 file/db")
    if fetch_mode == "db" and not biz_date:
        raise HTTPException(
            status_code=400,
            detail="db 取数模式必须提供业务日期 biz_date（yyyyMMdd），将作为模板 :biz_date 参数注入查询")
    date_str = _validate_biz_date(biz_date) if biz_date else datetime.now().strftime("%Y%m%d")

    job_id = uuid.uuid4().hex[:16]

    if fetch_mode == "file":
        # ================= 文件取数模式（既有行为） =================
        if fund_file is None or netvalue_file is None:
            raise HTTPException(
                status_code=400,
                detail="文件取数模式需同时上传基金资产表与净值查询表（或改用 fetch_mode=db 数据库查询）")

        # 1. 扩展名与大小校验
        uploads = []
        for label, uf in (("基金资产表", fund_file), ("净值查询表", netvalue_file)):
            ext = Path(uf.filename or "").suffix.lower()
            if ext not in archive_service.ALLOWED_UPLOAD_EXTS:
                raise HTTPException(
                    status_code=400,
                    detail=f"{label}文件格式不支持: {uf.filename}，仅支持 .xls/.xlsx",
                )
            content = uf.file.read()
            if len(content) == 0:
                raise HTTPException(status_code=400, detail=f"{label}文件为空: {uf.filename}")
            if len(content) > settings.MAX_UPLOAD_SIZE:
                raise HTTPException(
                    status_code=400,
                    detail=f"{label}文件超过大小上限（{settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB）: {uf.filename}",
                )
            uploads.append((label, uf.filename, content))

        # 2. 落盘归档 input/（先落盘才能调用引擎列数校验）
        input_dir, _result_dir = archive_service.prepare_job_dirs(MODULE_M1, date_str, job_id)
        saved_paths = []
        for label, filename, content in uploads:
            prefix = "fund" if label == "基金资产表" else "netvalue"
            path = archive_service.save_upload(input_dir, prefix, filename, content)
            saved_paths.append((label, path))
        audit_detail = (f"创建 M1 核对任务，业务日期={date_str}，"
                        f"基金资产表={saved_paths[0][1].name}，净值查询表={saved_paths[1][1].name}")
        extra_inputs: List[Path] = []
    else:
        # ================= 数据库取数模式（DS-F4） =================
        # 1. 模板校验（纯元数据：404/模块不匹配 400/停用 400）
        fund_tpl = fetch_service.load_template_checked(db, fund_template_id, "m1_fund", "基金资产查询模板")
        net_tpl = fetch_service.load_template_checked(db, netvalue_template_id, "m1_netvalue", "净值查询模板")

        # 2. 同步取数 → 快照落盘（失败清理归档目录、不建任务记录，400 中文）
        input_dir, _result_dir = archive_service.prepare_job_dirs(MODULE_M1, date_str, job_id)
        try:
            df_fund, ds_fund, _ = fetch_service.fetch_template_df(db, fund_tpl, date_str, settings)
            df_net, ds_net, _ = fetch_service.fetch_template_df(db, net_tpl, date_str, settings)
            # 引擎消费件（xlsx 物化：基准复制件只读 Excel；fund__/netvalue__ 前缀与文件模式一致）
            fund_path = fetch_service.write_xlsx_materialization(
                df_fund, input_dir, f"fund__查询快照_基金资产表_tpl{fund_tpl.id}.xlsx")
            net_path = fetch_service.write_xlsx_materialization(
                df_net, input_dir, f"netvalue__查询快照_净值查询表_tpl{net_tpl.id}.xlsx")
            # 归档快照（CSV/UTF-8-SIG：原始查询结果，人读与重算比对用）
            snap_fund = fetch_service.write_csv_snapshot(
                df_fund, input_dir, f"查询快照_基金资产表_tpl{fund_tpl.id}.csv")
            snap_net = fetch_service.write_csv_snapshot(
                df_net, input_dir, f"查询快照_净值查询表_tpl{net_tpl.id}.csv")
        except HTTPException as e:
            import shutil
            shutil.rmtree(input_dir.parent, ignore_errors=True)
            record_audit(db, user.username, "upload_create_job", "recon_job", None,
                         f"M1 任务 db 取数失败: {e.detail}", ip)
            db.commit()
            raise
        saved_paths = [("基金资产表", fund_path), ("净值查询表", net_path)]
        extra_inputs = [snap_fund, snap_net]
        audit_detail = (f"创建 M1 核对任务（db 取数），业务日期={date_str}，"
                        f"基金资产模板={fund_tpl.name}(id={fund_tpl.id},数据源={ds_fund.name})，"
                        f"净值模板={net_tpl.name}(id={net_tpl.id},数据源={ds_net.name})")

    # 3. 输入校验（列数/选反特征，与 GUI v2.1 一致；两种模式统一）：
    #    失败则清理归档目录、不建任务记录，返回 400 + 中文提示
    engine = M1FundNetvalueEngine()
    try:
        engine.validate_input_columns(saved_paths[0][1], saved_paths[1][1])
    except ValueError as e:
        import shutil
        shutil.rmtree(input_dir.parent, ignore_errors=True)
        record_audit(db, user.username, "upload_create_job", "recon_job", None,
                     f"M1 任务输入校验失败: {str(e).splitlines()[0]}", ip)
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))

    # 4. 校验通过：创建任务记录（pending）与输入文件索引
    job = ReconJob(
        id=job_id, module=MODULE_M1, biz_date=date_str,
        fetch_mode=fetch_mode, status="pending", trigger_type="manual",
        progress=0, created_by=user.username,
    )
    db.add(job)
    for _label, path in saved_paths:
        db.add(ReconResultFile(
            job_id=job_id, file_type="input",
            file_path=str(path), file_name=path.name,
        ))
    for path in extra_inputs:
        db.add(ReconResultFile(
            job_id=job_id, file_type="input",
            file_path=str(path), file_name=path.name,
        ))
    record_audit(db, user.username, "upload_create_job", "recon_job", job_id, audit_detail, ip)
    db.commit()

    # 5. 后台异步执行
    threading.Thread(target=_run_m1_job, args=(job_id,), daemon=True).start()

    mode_text = "数据库查询" if fetch_mode == "db" else "文件上传"
    return JobCreateResponse(
        job_id=job_id, status="pending",
        message=f"M1 核对任务已创建（业务日期 {date_str}，取数模式: {mode_text}），正在后台执行",
    )


# =============================================================================
# M2 任务创建
# =============================================================================

def _extract_product_id(filename: str) -> Optional[str]:
    """从文件名提取产品标识（首个 4 位及以上数字组，如 6301）"""
    m = re.search(r"(\d{4,})", Path(filename).stem)
    return m.group(1) if m else None


def _pair_m2_files(system_names: List[str], valuation_names: List[str]) -> Dict[str, Dict[str, str]]:
    """
    按文件名产品标识自动配对系统端与估值表文件

    Returns:
        {product: {"system": 文件名, "valuation": 文件名}}（按产品标识排序）

    Raises:
        HTTPException 400: 文件名无法提取产品标识 / 同侧重复产品 / 配对落单
    """
    def index_by_product(names: List[str], side: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for name in names:
            product = _extract_product_id(name)
            if product is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"{side}文件名中未识别到产品标识（4 位数字，如 6301）: {name}，"
                           f"请按 新综合信息查询_基金证券-6301.xls / 证券投资基金估值表_6301-XXXX.xls 命名",
                )
            if product in result:
                raise HTTPException(
                    status_code=400,
                    detail=f"{side}存在重复产品标识 {product} 的文件: {result[product]} 与 {name}",
                )
            result[product] = name
        return result

    sys_map = index_by_product(system_names, "系统端")
    val_map = index_by_product(valuation_names, "估值表")

    only_sys = sorted(set(sys_map) - set(val_map))
    only_val = sorted(set(val_map) - set(sys_map))
    if only_sys or only_val:
        parts = []
        if only_sys:
            parts.append(f"以下系统端文件未能配对估值表: "
                         f"{'、'.join(f'{sys_map[p]}（{p}）' for p in only_sys)}")
        if only_val:
            parts.append(f"以下估值表文件未能配对系统端文件: "
                         f"{'、'.join(f'{val_map[p]}（{p}）' for p in only_val)}")
        raise HTTPException(status_code=400, detail="；".join(parts))

    return {p: {"system": sys_map[p], "valuation": val_map[p]} for p in sorted(sys_map)}


def _load_m2_engine_config(session_factory, logger_: logging.Logger):
    """从规则库现取 M2 配置（热生效：启用科目取价规则 + fuzzy_sim/price_tol）"""
    with session_factory() as session:
        rules = session.execute(
            select(SysSubjectPriceRule)
            .where(SysSubjectPriceRule.enabled.is_(True))
            .order_by(SysSubjectPriceRule.sort_order, SysSubjectPriceRule.id)
        ).scalars().all()
        from app.models.entities import RuleThreshold
        thresholds = session.execute(select(RuleThreshold)).scalars().all()
    threshold_map = {t.param_key: t.param_value for t in thresholds}
    fuzzy_sim = float(threshold_map.get("fuzzy_sim", 0.5))
    price_tol = float(threshold_map.get("price_tol", 0.0001))
    configs = [
        SubjectPriceRuleConfig(
            subject_prefix=r.subject_prefix, price_field=r.price_field,
            description=r.description or "", note=r.note or "", sort_order=r.sort_order,
        )
        for r in rules
    ]
    logger_.info(
        f"M2 配置加载完成(来源:数据库): 科目取价规则 {len(configs)} 条（"
        + "；".join(f"{c.subject_prefix}→{c.price_field}" for c in configs)
        + f"），fuzzy_sim={fuzzy_sim}，price_tol={price_tol}"
    )
    return configs, fuzzy_sim, price_tol


def _run_m2_job(job_id: str) -> None:
    """
    后台线程：执行 M2 估值价格核对任务（多产品批量）

    状态流转：pending → running → success/failed；
    逐产品出报告（{product}_估值价格核对报告.xlsx）与 run.log 写 result/ 并登记索引。
    """
    session_factory = get_session_factory()
    db = session_factory()
    job_logger: Optional[logging.Logger] = None
    try:
        job = db.get(ReconJob, job_id)
        if job is None:
            logger.error(f"任务不存在: {job_id}")
            return

        input_dir, result_dir = archive_service.prepare_job_dirs(
            job.module, job.biz_date, job.id
        )
        log_path = result_dir / "run.log"
        job_logger = _build_job_logger(job_id, log_path, module="m2")

        job.status = "running"
        job.progress = 10
        job.started_at = datetime.now()
        db.commit()

        # 按归档文件名还原配对（system__{product}__xxx / valuation__{product}__xxx）
        pairs: List[Dict] = []
        for system_path in sorted(input_dir.glob("system__*")):
            product = system_path.name.split("__")[1]
            val_matches = sorted(input_dir.glob(f"valuation__{product}__*"))
            if not val_matches:
                raise FileNotFoundError(f"产品 {product} 的估值表输入文件缺失，请重新上传")
            pairs.append({
                "product": product,
                "system_path": str(system_path),
                "valuation_path": str(val_matches[0]),
            })
        if not pairs:
            raise FileNotFoundError("任务输入文件缺失，请重新上传")

        configs, fuzzy_sim, price_tol = _load_m2_engine_config(session_factory, job_logger)
        engine = M2ValuationPriceEngine(
            subject_rules=configs, fuzzy_sim=fuzzy_sim, price_tol=price_tol,
            logger=job_logger,
        )
        result = engine.run(jobs=pairs, output_dir=str(result_dir))

        # 登记结果文件（逐产品报告 + run.log）
        for output_file in result["output_files"]:
            db.add(ReconResultFile(
                job_id=job.id, file_type="result",
                file_path=output_file, file_name=Path(output_file).name,
            ))
        db.add(ReconResultFile(
            job_id=job.id, file_type="result",
            file_path=str(log_path), file_name="run.log",
        ))
        job.status = "success"
        job.progress = 100
        job.stats_json = json.dumps(result["stats"], ensure_ascii=False)
        job.result_filename = Path(result["output_files"][0]).name if result["output_files"] else None
        job.finished_at = datetime.now()
        db.commit()
        job_logger.info(f"任务执行成功: {job_id}")

    except Exception as e:  # noqa: BLE001
        logger.error(f"M2 任务执行失败: {job_id}: {e}\n{traceback.format_exc()}")
        try:
            job = db.get(ReconJob, job_id)
            if job is not None:
                job.status = "failed"
                job.progress = 100
                job.error = str(e)
                job.finished_at = datetime.now()
                db.commit()
            if job_logger:
                job_logger.error(f"任务执行失败: {e}")
        except Exception:  # noqa: BLE001
            logger.error(f"任务失败状态写库异常: {job_id}")
    finally:
        if job_logger:
            for handler in list(job_logger.handlers):
                handler.close()
                job_logger.removeHandler(handler)
        db.close()


@router.post("/m2/jobs", response_model=JobCreateResponse, summary="创建 M2 基金估值价格核对任务（多产品批量，文件/数据库两种取数模式）")
def create_m2_job(
    request: Request,
    system_files: Optional[List[UploadFile]] = File(None, description="系统端 新综合信息查询_基金证券（多文件），fetch_mode=file 时必填"),
    valuation_files: Optional[List[UploadFile]] = File(None, description="财务端 证券投资基金估值表（多文件），fetch_mode=file 时必填"),
    fetch_mode: str = Form("file", description="取数模式: file(默认,上传文件) / db(数据库查询)"),
    groups_json: Optional[str] = Form(None, description='db 模式：模板分组 JSON，如 [{"product":"6301","system_template_id":1,"valuation_template_id":2}]'),
    biz_date: Optional[str] = Form(None, description="业务日期 yyyyMMdd；file 模式默认当天，db 模式必填"),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    ip = request.client.host if request.client else None

    fetch_mode = (fetch_mode or "file").strip().lower()
    if fetch_mode not in ("file", "db"):
        raise HTTPException(status_code=400, detail=f"取数模式非法: {fetch_mode}，支持 file/db")
    if fetch_mode == "db" and not biz_date:
        raise HTTPException(
            status_code=400,
            detail="db 取数模式必须提供业务日期 biz_date（yyyyMMdd），将作为模板 :biz_date 参数注入查询")
    date_str = _validate_biz_date(biz_date) if biz_date else datetime.now().strftime("%Y%m%d")

    job_id = uuid.uuid4().hex[:16]

    if fetch_mode == "file":
        # ================= 文件取数模式（既有行为） =================
        if not system_files or not valuation_files:
            raise HTTPException(
                status_code=400,
                detail="文件取数模式需系统端与估值表文件各至少上传 1 个（或改用 fetch_mode=db 数据库查询）")

        # 1. 扩展名/大小/总大小校验
        uploads: Dict[str, bytes] = {}
        total_size = 0
        for side, files in (("系统端", system_files), ("估值表", valuation_files)):
            for uf in files:
                ext = Path(uf.filename or "").suffix.lower()
                if ext not in archive_service.ALLOWED_UPLOAD_EXTS:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{side}文件格式不支持: {uf.filename}，仅支持 .xls/.xlsx",
                    )
                content = uf.file.read()
                if len(content) == 0:
                    raise HTTPException(status_code=400, detail=f"{side}文件为空: {uf.filename}")
                total_size += len(content)
                if total_size > settings.MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=400,
                        detail=f"本次上传总大小超过上限（{settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB），"
                               f"请分批创建任务",
                    )
                uploads[uf.filename] = content

        # 2. 按文件名产品标识自动配对（落单/重复/无标识 → 400 中文指明）
        pairs = _pair_m2_files([u.filename for u in system_files],
                               [u.filename for u in valuation_files])

        # 3. 落盘归档 input/（system__{product}__ / valuation__{product}__ 前缀）
        input_dir, _result_dir = archive_service.prepare_job_dirs(MODULE_M2, date_str, job_id)
        saved: Dict[str, Dict[str, Path]] = {}
        for product, pair in pairs.items():
            saved[product] = {
                "system": archive_service.save_upload(
                    input_dir, f"system__{product}", pair["system"], uploads[pair["system"]]),
                "valuation": archive_service.save_upload(
                    input_dir, f"valuation__{product}", pair["valuation"], uploads[pair["valuation"]]),
            }
        audit_detail = (f"创建 M2 估值价格核对任务，业务日期={date_str}，产品={','.join(pairs.keys())}，"
                        f"系统端 {len(system_files)} 个 / 估值表 {len(valuation_files)} 个")
        extra_inputs: List[Path] = []
    else:
        # ================= 数据库取数模式（DS-F4） =================
        # 1. 解析分组并校验模板（纯元数据：JSON 结构 400/不存在 404/模块不匹配 400）
        groups = fetch_service.parse_m2_groups(groups_json)
        plan: List[Dict] = []
        seen_products: Dict[str, str] = {}
        for i, g in enumerate(groups, 1):
            sys_tpl = fetch_service.load_template_checked(
                db, g["system_template_id"], "m2_system", "系统端查询模板")
            val_tpl = fetch_service.load_template_checked(
                db, g["valuation_template_id"], "m2_valuation", "估值表查询模板")
            product = fetch_service.derive_product(g["product"], sys_tpl.name, i)
            if product in seen_products:
                raise HTTPException(
                    status_code=400,
                    detail=f"存在重复产品标识 {product} 的分组（第 {seen_products[product]} 组与第 {i} 组）")
            seen_products[product] = str(i)
            plan.append({"product": product, "sys_tpl": sys_tpl, "val_tpl": val_tpl})

        # 2. 同步取数 → 快照落盘（system__/valuation__ 前缀 CSV，引擎直接消费；
        #    估值表快照含 3 行标题占位复刻真实版式；失败清理归档目录、不建任务记录）
        input_dir, _result_dir = archive_service.prepare_job_dirs(MODULE_M2, date_str, job_id)
        saved = {}
        audit_sources: List[str] = []
        try:
            for p in plan:
                product = p["product"]
                df_sys, ds_sys, _ = fetch_service.fetch_template_df(db, p["sys_tpl"], date_str, settings)
                df_val, ds_val, _ = fetch_service.fetch_template_df(db, p["val_tpl"], date_str, settings)
                sys_path = fetch_service.write_csv_snapshot(
                    df_sys, input_dir,
                    f"system__{product}__查询快照_系统端_tpl{p['sys_tpl'].id}.csv")
                val_path = fetch_service.write_valuation_csv_snapshot(
                    df_val, input_dir,
                    f"valuation__{product}__查询快照_估值表_tpl{p['val_tpl'].id}.csv",
                    ["证券投资基金估值表（数据库查询快照）",
                     f"模板:{p['val_tpl'].name} 数据源:{ds_val.name} 业务日期:{date_str}",
                     ""])
                saved[product] = {"system": sys_path, "valuation": val_path}
                audit_sources.append(
                    f"{product}[系统端={p['sys_tpl'].name}(id={p['sys_tpl'].id},数据源={ds_sys.name}) "
                    f"估值表={p['val_tpl'].name}(id={p['val_tpl'].id},数据源={ds_val.name})]")
        except HTTPException as e:
            import shutil
            shutil.rmtree(input_dir.parent, ignore_errors=True)
            record_audit(db, user.username, "upload_create_job", "recon_job", None,
                         f"M2 任务 db 取数失败: {e.detail}", ip)
            db.commit()
            raise
        extra_inputs = []
        audit_detail = (f"创建 M2 估值价格核对任务（db 取数），业务日期={date_str}，"
                        f"产品={','.join(saved.keys())}，" + "；".join(audit_sources))

    # 3. 输入校验（逐产品：关键列存在性 + 取价字段列存在性；两种模式统一）：
    #    失败则清理归档目录、不建任务记录，返回 400 + 中文提示
    configs, fuzzy_sim, price_tol = _load_m2_engine_config(get_session_factory(), logger)
    engine = M2ValuationPriceEngine(
        subject_rules=configs, fuzzy_sim=fuzzy_sim, price_tol=price_tol)
    try:
        for product in saved:
            engine.validate_input_files(saved[product]["system"], saved[product]["valuation"])
    except ValueError as e:
        import shutil
        shutil.rmtree(input_dir.parent, ignore_errors=True)
        record_audit(db, user.username, "upload_create_job", "recon_job", None,
                     f"M2 任务输入校验失败: {str(e).splitlines()[0]}", ip)
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))

    # 4. 创建任务记录（pending）与输入文件索引
    job = ReconJob(
        id=job_id, module=MODULE_M2, biz_date=date_str,
        fetch_mode=fetch_mode, status="pending", trigger_type="manual",
        progress=0, created_by=user.username,
    )
    db.add(job)
    for product in saved:
        for kind in ("system", "valuation"):
            db.add(ReconResultFile(
                job_id=job_id, file_type="input",
                file_path=str(saved[product][kind]), file_name=saved[product][kind].name,
            ))
    for path in extra_inputs:
        db.add(ReconResultFile(
            job_id=job_id, file_type="input",
            file_path=str(path), file_name=path.name,
        ))
    record_audit(db, user.username, "upload_create_job", "recon_job", job_id, audit_detail, ip)
    db.commit()

    # 5. 后台异步执行
    threading.Thread(target=_run_m2_job, args=(job_id,), daemon=True).start()

    mode_text = "数据库查询" if fetch_mode == "db" else "文件上传"
    return JobCreateResponse(
        job_id=job_id, status="pending",
        message=f"M2 估值价格核对任务已创建（业务日期 {date_str}，{len(saved)} 个产品，"
                f"取数模式: {mode_text}），正在后台执行",
    )


# =============================================================================
# M3 任务创建
# =============================================================================

@router.post("/m3/jobs", response_model=JobCreateResponse, summary="创建 M3 基金属性表银行间ID匹配任务")
def create_m3_job(
    request: Request,
    fund_file: UploadFile = File(..., description="基金属性表 (.xls/.xlsx)"),
    member_file: UploadFile = File(..., description="交易成员基本信息表 (.csv, GBK 编码)"),
    biz_date: Optional[str] = Form(None, description="业务日期 yyyyMMdd，默认当天"),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    ip = request.client.host if request.client else None
    date_str = _validate_biz_date(biz_date) if biz_date else datetime.now().strftime("%Y%m%d")

    # 1. 扩展名与大小校验
    uploads = []
    for label, uf, allowed in (
        ("基金属性表", fund_file, {".xls", ".xlsx"}),
        ("交易成员基本信息表", member_file, {".csv"}),
    ):
        ext = Path(uf.filename or "").suffix.lower()
        if ext not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"{label}文件格式不支持: {uf.filename}，"
                       f"仅支持 {'/'.join(sorted(allowed))}",
            )
        content = uf.file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail=f"{label}文件为空: {uf.filename}")
        if len(content) > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"{label}文件超过大小上限（{settings.MAX_UPLOAD_SIZE // 1024 // 1024}MB）: {uf.filename}",
            )
        uploads.append((label, uf.filename, content))

    # 2. 生成 jobId 并落盘归档 input/
    job_id = uuid.uuid4().hex[:16]
    input_dir, _result_dir = archive_service.prepare_job_dirs(MODULE_M3, date_str, job_id)
    saved_paths = []
    for label, filename, content in uploads:
        prefix = "fund" if label == "基金属性表" else "member"
        path = archive_service.save_upload(input_dir, prefix, filename, content)
        saved_paths.append((label, path))

    # 3. 输入校验（关键列存在性）：失败则清理归档目录、不建任务记录，返回 400 + 中文提示
    engine = M3InterbankIdEngine()
    try:
        engine.validate_input_files(saved_paths[0][1], saved_paths[1][1])
    except ValueError as e:
        import shutil
        shutil.rmtree(input_dir.parent, ignore_errors=True)
        record_audit(db, user.username, "upload_create_job", "recon_job", None,
                     f"M3 任务输入校验失败: {str(e).splitlines()[0]}", ip)
        db.commit()
        raise HTTPException(status_code=400, detail=str(e))

    # 4. 校验通过：创建任务记录（pending）与输入文件索引
    job = ReconJob(
        id=job_id, module=MODULE_M3, biz_date=date_str,
        fetch_mode="file", status="pending", trigger_type="manual",
        progress=0, created_by=user.username,
    )
    db.add(job)
    for _label, path in saved_paths:
        db.add(ReconResultFile(
            job_id=job_id, file_type="input",
            file_path=str(path), file_name=path.name,
        ))
    record_audit(db, user.username, "upload_create_job", "recon_job", job_id,
                 f"创建 M3 匹配任务，业务日期={date_str}，"
                 f"基金属性表={saved_paths[0][1].name}，交易成员表={saved_paths[1][1].name}", ip)
    db.commit()

    # 5. 后台异步执行
    threading.Thread(target=_run_m3_job, args=(job_id,), daemon=True).start()

    return JobCreateResponse(
        job_id=job_id, status="pending",
        message=f"M3 匹配任务已创建（业务日期 {date_str}），正在后台执行",
    )


# =============================================================================
# 任务查询与下载
# =============================================================================

@router.get("/jobs", response_model=JobListResponse, summary="核对任务历史查询")
def list_jobs(
    module: Optional[str] = Query(None, description="模块过滤，如 M1"),
    date_from: Optional[str] = Query(None, description="业务日期起 yyyyMMdd"),
    date_to: Optional[str] = Query(None, description="业务日期止 yyyyMMdd"),
    status: Optional[str] = Query(None, description="状态过滤 pending/running/success/failed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    user: SysUser = Depends(require_roles("admin", "operator", "viewer")),
    db: Session = Depends(get_db),
):
    stmt = select(ReconJob)
    if module:
        stmt = stmt.where(ReconJob.module == module.upper())
    if date_from:
        stmt = stmt.where(ReconJob.biz_date >= _validate_biz_date(date_from))
    if date_to:
        stmt = stmt.where(ReconJob.biz_date <= _validate_biz_date(date_to))
    if status:
        stmt = stmt.where(ReconJob.status == status)

    total = len(db.execute(stmt).scalars().all())
    stmt = stmt.order_by(ReconJob.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    jobs = db.execute(stmt).scalars().all()
    return JobListResponse(
        total=total, page=page, page_size=page_size,
        items=[_to_info(j) for j in jobs],
    )


@router.get("/jobs/{job_id}", response_model=JobDetailResponse, summary="核对任务详情（状态/进度/统计/日志）")
def get_job(
    job_id: str,
    log_tail: int = Query(50, ge=0, le=500, description="返回日志末尾行数"),
    user: SysUser = Depends(require_roles("admin", "operator", "viewer")),
    db: Session = Depends(get_db),
):
    job = db.get(ReconJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")

    info = _to_info(job)
    settings = get_settings()
    log_path = (settings.ARCHIVE_DIR / job.module.lower() / job.biz_date
                / job.id / "result" / "run.log")
    result_files = db.execute(
        select(ReconResultFile).where(
            ReconResultFile.job_id == job_id,
            ReconResultFile.file_type == "result",
        ).order_by(ReconResultFile.id)
    ).scalars().all()
    return JobDetailResponse(
        **info.model_dump(),
        log_tail=archive_service.read_log_tail(log_path, log_tail) if log_tail > 0 else [],
        result_files=[r.file_name for r in result_files],
    )


@router.get("/jobs/{job_id}/download", summary="下载核对结果文件")
def download_result(
    job_id: str,
    request: Request,
    file: Optional[str] = Query(
        None,
        description="M3 三件套选择: updated(更新表,默认) / detail(明细) / note(说明md)；M1/M2 任务忽略本参数",
    ),
    product: Optional[str] = Query(
        None,
        description="M2 按产品下载（如 6301）；缺省下载首个产品报告；其他模块忽略本参数",
    ),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    ip = request.client.host if request.client else None
    job = db.get(ReconJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"任务不存在: {job_id}")
    if job.status != "success":
        raise HTTPException(status_code=400, detail=f"任务未成功完成（当前状态: {job.status}），无法下载结果")

    # 确定目标文件名：M3 按 file 参数映射（默认 updated）；
    # M2 按 product 参数定位产品报告（缺省首个）；M1 为唯一结果 Excel
    if job.module == MODULE_M3:
        file_key = (file or "updated").lower()
        if file_key not in M3_RESULT_FILE_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"文件类型参数错误: {file}，M3 支持 updated/detail/note",
            )
        target_name = M3_RESULT_FILE_MAP[file_key]
    elif job.module == MODULE_M2:
        if product:
            target_name = f"{product}_估值价格核对报告.xlsx"
        else:
            # 缺省：首个产品报告（按登记顺序）
            first = db.execute(
                select(ReconResultFile).where(
                    ReconResultFile.job_id == job_id,
                    ReconResultFile.file_type == "result",
                    ReconResultFile.file_name.endswith("_估值价格核对报告.xlsx"),
                ).order_by(ReconResultFile.id)
            ).scalars().first()
            target_name = first.file_name if first else "__none__"
    else:
        target_name = None  # M1：取结果 .xlsx

    stmt = select(ReconResultFile).where(
        ReconResultFile.job_id == job_id,
        ReconResultFile.file_type == "result",
    )
    if target_name is not None:
        stmt = stmt.where(ReconResultFile.file_name == target_name)
    else:
        stmt = stmt.where(ReconResultFile.file_name.endswith(".xlsx"))
    record = db.execute(stmt).scalars().first()
    if record is None or not Path(record.file_path).exists():
        if job.module == MODULE_M2 and product:
            raise HTTPException(
                status_code=404,
                detail=f"产品 {product} 的核对报告不存在（可能该产品未参与本次任务），"
                       f"请在任务详情中核对产品清单")
        raise HTTPException(status_code=404, detail="结果文件不存在或已被清理")

    media_type = ("text/markdown; charset=utf-8" if record.file_name.endswith(".md")
                  else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    record_audit(db, user.username, "download", "recon_job", job_id,
                 f"下载结果文件 {record.file_name}", ip)
    db.commit()
    return FileResponse(
        path=record.file_path,
        filename=record.file_name,
        media_type=media_type,
    )
