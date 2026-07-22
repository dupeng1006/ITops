# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 任务调度中心接口（二期 DS-F5）

    GET    /api/schedule/jobs              定时任务列表（operator 及以上）
    POST   /api/schedule/jobs              新建定时任务（operator/admin；cron 合法性校验，非法 400 中文）
    PUT    /api/schedule/jobs/{id}         修改定时任务（operator/admin）
    DELETE /api/schedule/jobs/{id}         删除定时任务（operator/admin）
    POST   /api/schedule/jobs/{id}/toggle  启停切换（operator/admin）
    POST   /api/schedule/jobs/{id}/run-now 立即执行一次（operator/admin；后台线程同步执行口径）
    GET    /api/schedule/executions        定时执行历史（复用 recon_job，trigger_type=schedule）

执行口径：
    到点由 schedule_service.execute_schedule_job 按配置创建 recon_job
    （trigger_type=schedule）并执行；db 模式用配置模板 + biz_date=当日；
    file 模式执行时检查监测目录一次，未就绪标记"待文件"(wait_file)；
    失败隔 schedule_retry_delay_minutes 重试 1 次，仍失败置 failed。
    就绪时间参数（data_ready_time/buffer_minutes）见 GET/PUT /api/admin/system/params。
    定时自动任务默认不预置，全部由用户自行创建。全部写操作审计留痕。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import json
import logging
import threading
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ScheduleExecutionInfo,
    ScheduleJobCreateRequest,
    ScheduleJobInfo,
    ScheduleJobUpdateRequest,
)
from app.core.deps import get_db, require_roles
from app.models.entities import ReconJob, ScheduleJob, SysUser
from app.services import fetch_service, schedule_service
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

MENU_SCH = "任务调度中心"

router = APIRouter(prefix="/api/schedule", tags=["任务调度中心"])


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _to_info(sj: ScheduleJob) -> ScheduleJobInfo:
    return ScheduleJobInfo(
        id=sj.id, name=sj.name, module=sj.module, fetch_mode=sj.fetch_mode,
        fund_template_id=sj.fund_template_id, netvalue_template_id=sj.netvalue_template_id,
        groups_json=sj.groups_json, file_dir=sj.file_dir,
        cron_expr=sj.cron_expr, enabled=sj.enabled,
        last_run_at=sj.last_run_at.strftime("%Y-%m-%d %H:%M:%S") if sj.last_run_at else None,
        last_status=sj.last_status, last_job_id=sj.last_job_id, last_error=sj.last_error,
        created_by=sj.created_by,
        created_at=sj.created_at.strftime("%Y-%m-%d %H:%M:%S"),
    )


def _to_execution(job: ReconJob) -> ScheduleExecutionInfo:
    return ScheduleExecutionInfo(
        job_id=job.id, module=job.module, biz_date=job.biz_date, fetch_mode=job.fetch_mode,
        status=job.status,
        stats=json.loads(job.stats_json) if job.stats_json else None,
        error=job.error, created_by=job.created_by,
        created_at=job.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        finished_at=job.finished_at.strftime("%Y-%m-%d %H:%M:%S") if job.finished_at else None,
    )


def _validate_config(db: Session, *, module: str, fetch_mode: str, cron_expr: str,
                     fund_template_id, netvalue_template_id, groups_json, file_dir) -> dict:
    """定时任务配置校验（cron/模块/取数模式/模式参数；db 模板做存在性与模块匹配校验）"""
    module = (module or "").strip().lower()
    if module not in ("m1", "m2"):
        raise HTTPException(status_code=400, detail=f"模块非法: {module}，支持 m1/m2")
    fetch_mode = (fetch_mode or "").strip().lower()
    if fetch_mode not in ("file", "db"):
        raise HTTPException(status_code=400, detail=f"取数模式非法: {fetch_mode}，支持 file/db")
    cron_expr = schedule_service.validate_cron(cron_expr)

    if fetch_mode == "db":
        if module == "m1":
            if not fund_template_id or not netvalue_template_id:
                raise HTTPException(
                    status_code=400,
                    detail="M1 db 模式需同时提供基金资产查询模板ID与净值查询模板ID")
            fetch_service.load_template_checked(db, fund_template_id, "m1_fund", "基金资产查询模板")
            fetch_service.load_template_checked(db, netvalue_template_id, "m1_netvalue", "净值查询模板")
        else:
            if not groups_json or not str(groups_json).strip():
                raise HTTPException(status_code=400, detail="M2 db 模式需提供模板分组 groups_json")
            groups = fetch_service.parse_m2_groups(groups_json)
            for g in groups:
                fetch_service.load_template_checked(db, g["system_template_id"], "m2_system", "系统端查询模板")
                fetch_service.load_template_checked(db, g["valuation_template_id"], "m2_valuation", "估值表查询模板")
    else:
        if not file_dir or not str(file_dir).strip():
            raise HTTPException(status_code=400, detail="file 模式需提供文件就绪监测目录 file_dir")

    return {
        "module": module, "fetch_mode": fetch_mode, "cron_expr": cron_expr,
        "fund_template_id": fund_template_id if fetch_mode == "db" and module == "m1" else None,
        "netvalue_template_id": netvalue_template_id if fetch_mode == "db" and module == "m1" else None,
        "groups_json": groups_json if fetch_mode == "db" and module == "m2" else None,
        "file_dir": str(file_dir).strip() if fetch_mode == "file" else None,
    }


@router.get("/jobs", response_model=list[ScheduleJobInfo], summary="定时任务列表")
def list_jobs(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    rows = db.execute(select(ScheduleJob).order_by(ScheduleJob.id)).scalars().all()
    return [_to_info(r) for r in rows]


@router.post("/jobs", response_model=ScheduleJobInfo, summary="新建定时任务")
def create_job(
    body: ScheduleJobCreateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    cfg = _validate_config(
        db, module=body.module, fetch_mode=body.fetch_mode, cron_expr=body.cron_expr,
        fund_template_id=body.fund_template_id, netvalue_template_id=body.netvalue_template_id,
        groups_json=body.groups_json, file_dir=body.file_dir)
    sj = ScheduleJob(
        name=body.name.strip(), **cfg, enabled=body.enabled, created_by=user.username,
    )
    db.add(sj)
    db.flush()
    record_audit(db, user.username, "schedule_create", "schedule_job", str(sj.id),
                 f"新建定时任务「{sj.name}」：模块={cfg['module']}，取数={cfg['fetch_mode']}，"
                 f"cron={cfg['cron_expr']}，{'启用' if sj.enabled else '停用'}", _client_ip(request), menu=MENU_SCH)
    db.commit()
    # 先提交库内写事务再同步调度器（APScheduler jobstore 独立连接，避免 SQLite 写锁冲突）
    schedule_service.sync_schedule(sj)
    return _to_info(sj)


@router.put("/jobs/{job_id}", response_model=ScheduleJobInfo, summary="修改定时任务")
def update_job(
    job_id: int,
    body: ScheduleJobUpdateRequest,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    sj = db.get(ScheduleJob, job_id)
    if sj is None:
        raise HTTPException(status_code=404, detail=f"定时任务不存在: id={job_id}")

    merged = {
        "module": body.module if body.module is not None else sj.module,
        "fetch_mode": body.fetch_mode if body.fetch_mode is not None else sj.fetch_mode,
        "cron_expr": body.cron_expr if body.cron_expr is not None else sj.cron_expr,
        "fund_template_id": body.fund_template_id if body.fund_template_id is not None else sj.fund_template_id,
        "netvalue_template_id": body.netvalue_template_id if body.netvalue_template_id is not None else sj.netvalue_template_id,
        "groups_json": body.groups_json if body.groups_json is not None else sj.groups_json,
        "file_dir": body.file_dir if body.file_dir is not None else sj.file_dir,
    }
    cfg = _validate_config(db, **merged)

    changes = []
    if body.name is not None and body.name.strip() != sj.name:
        changes.append(f"名称 {sj.name}→{body.name.strip()}")
        sj.name = body.name.strip()
    for key, label in (("module", "模块"), ("fetch_mode", "取数模式"), ("cron_expr", "cron")):
        if getattr(sj, key) != cfg[key]:
            changes.append(f"{label} {getattr(sj, key)}→{cfg[key]}")
        setattr(sj, key, cfg[key])
    for key in ("fund_template_id", "netvalue_template_id", "groups_json", "file_dir"):
        setattr(sj, key, cfg[key])
    if body.enabled is not None and body.enabled != sj.enabled:
        changes.append(f"启用 {sj.enabled}→{body.enabled}")
        sj.enabled = body.enabled

    if changes:
        record_audit(db, user.username, "schedule_update", "schedule_job", str(sj.id),
                     f"修改定时任务「{sj.name}」(id={sj.id}): " + "；".join(changes), _client_ip(request), menu=MENU_SCH)
    db.commit()
    # 先提交库内写事务再同步调度器（避免 SQLite 写锁冲突）
    schedule_service.sync_schedule(sj)
    return _to_info(sj)
@router.delete("/jobs/{job_id}", summary="删除定时任务")
def delete_job(
    job_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    sj = db.get(ScheduleJob, job_id)
    if sj is None:
        raise HTTPException(status_code=404, detail=f"定时任务不存在: id={job_id}")
    detail = f"删除定时任务「{sj.name}」(id={sj.id}，模块={sj.module}，cron={sj.cron_expr})"
    db.delete(sj)
    record_audit(db, user.username, "schedule_delete", "schedule_job", str(job_id), detail, _client_ip(request), menu=MENU_SCH)
    db.commit()
    # 先提交库内写事务再移除调度器作业（避免 SQLite 写锁冲突）
    schedule_service.remove_schedule(job_id)
    return {"message": f"已删除定时任务 id={job_id}"}


@router.post("/jobs/{job_id}/toggle", response_model=ScheduleJobInfo, summary="启停切换")
def toggle_job(
    job_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    sj = db.get(ScheduleJob, job_id)
    if sj is None:
        raise HTTPException(status_code=404, detail=f"定时任务不存在: id={job_id}")
    sj.enabled = not sj.enabled
    record_audit(db, user.username, "schedule_toggle", "schedule_job", str(sj.id),
                 f"定时任务「{sj.name}」(id={sj.id}) {'启用' if sj.enabled else '停用'}", _client_ip(request), menu=MENU_SCH)
    db.commit()
    # 先提交库内写事务再同步调度器（避免 SQLite 写锁冲突）
    schedule_service.sync_schedule(sj)
    return _to_info(sj)


@router.post("/jobs/{job_id}/run-now", summary="立即执行一次")
def run_now(
    job_id: int,
    request: Request,
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    sj = db.get(ScheduleJob, job_id)
    if sj is None:
        raise HTTPException(status_code=404, detail=f"定时任务不存在: id={job_id}")
    threading.Thread(
        target=schedule_service.execute_schedule_job, args=(sj.id, 1, None), daemon=True,
    ).start()
    record_audit(db, user.username, "schedule_run_now", "schedule_job", str(sj.id),
                 f"手动立即执行定时任务「{sj.name}」(id={sj.id})", _client_ip(request), menu=MENU_SCH)
    db.commit()
    return {"message": f"已触发定时任务「{sj.name}」立即执行（后台运行，结果见执行历史）"}


@router.get("/executions", response_model=list[ScheduleExecutionInfo], summary="定时执行历史")
def list_executions(
    schedule_id: Optional[int] = Query(None, description="按定时任务过滤（可选）"),
    limit: int = Query(50, ge=1, le=200, description="返回条数上限"),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    stmt = select(ReconJob).where(ReconJob.trigger_type == "schedule")
    if schedule_id is not None:
        sj = db.get(ScheduleJob, schedule_id)
        if sj is None:
            raise HTTPException(status_code=404, detail=f"定时任务不存在: id={schedule_id}")
        stmt = stmt.where(ReconJob.created_by == f"schedule:{sj.name}")
    rows = db.execute(
        stmt.order_by(ReconJob.created_at.desc(), ReconJob.id.desc()).limit(limit)
    ).scalars().all()
    return [_to_execution(j) for j in rows]
