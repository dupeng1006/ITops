# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 任务调度服务（二期 DS-F5：APScheduler 封装）

- 调度器：BackgroundScheduler + SQLAlchemyJobStore（持久化到平台 SQLite，
  WAL 模式，服务重启不丢作业；一次性重试作业同样持久化）；
- 配置源：schedule_job 表（增删改/启停后调用 sync_schedule 同步到调度器；
  服务启动时对启用中的配置统一恢复）；
- 到点执行：按配置创建 recon_job（trigger_type=schedule）并同步执行
  （db 模式用配置模板 + biz_date=当日；file 模式执行时检查监测目录一次，
  未就绪则任务标记"待文件" wait_file）；
- 失败重试：失败/未就绪后隔 schedule_retry_delay_minutes（sys_config，
  默认 5 分钟）重试 1 次，仍失败置 failed 并记录；
- cron 合法性：CronTrigger.from_crontab 校验，非法抛 400 中文。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.database import get_session_factory
from app.models.entities import ReconJob, ScheduleJob, SysConfig
from app.services import job_launch_service

logger = logging.getLogger(__name__)

CRON_JOB_PREFIX = "schedule-cron-"
RETRY_JOB_PREFIX = "schedule-retry-"

_scheduler: Optional[BackgroundScheduler] = None


# =============================================================================
# 基础工具
# =============================================================================

def validate_cron(cron_expr: str) -> str:
    """cron 表达式合法性校验（5 段：分 时 日 月 周），非法抛 400 中文"""
    expr = (cron_expr or "").strip()
    try:
        CronTrigger.from_crontab(expr)
    except (ValueError, KeyError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"cron 表达式非法: {cron_expr}，应为 5 段（分 时 日 月 周），"
                   f"如 7 18 * * 1-5（工作日 18:07）",
        )
    return expr


def get_param(db: Session, key: str, default: str = "") -> str:
    """读取系统参数（sys_config），缺省返回 default"""
    row = db.execute(select(SysConfig).where(SysConfig.param_key == key)).scalars().first()
    return row.param_value if row else default


def _retry_delay_minutes(db: Session) -> float:
    try:
        return max(0.01, float(get_param(db, "schedule_retry_delay_minutes", "5")))
    except ValueError:
        return 5.0


# =============================================================================
# 调度器生命周期
# =============================================================================

def init_scheduler() -> None:
    """服务启动时初始化调度器并从 schedule_job 表恢复启用中的定时任务"""
    global _scheduler
    if _scheduler is not None:
        return
    settings = get_settings()
    _scheduler = BackgroundScheduler(
        jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{settings.DB_PATH}")},
    )
    _scheduler.start()

    db = get_session_factory()()
    try:
        rows = db.execute(
            select(ScheduleJob.id, ScheduleJob.cron_expr).where(ScheduleJob.enabled.is_(True))
        ).all()
    finally:
        db.close()
    for schedule_id, cron_expr in rows:
        _add_cron_job(schedule_id, cron_expr)
    logger.info(f"任务调度器已启动（SQLAlchemyJobStore 持久化），恢复启用定时任务 {len(rows)} 个")


def shutdown_scheduler() -> None:
    """服务停止时关闭调度器（等待运行中的作业收尾由 APScheduler 内部处理）"""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("任务调度器已停止")


def _add_cron_job(schedule_id: int, cron_expr: str) -> None:
    if _scheduler is None:
        return
    _scheduler.add_job(
        execute_schedule_job,
        trigger=CronTrigger.from_crontab(cron_expr),
        args=[schedule_id, 1, None],
        id=f"{CRON_JOB_PREFIX}{schedule_id}",
        replace_existing=True,
        misfire_grace_time=3600,
    )


def sync_schedule(sj: ScheduleJob) -> None:
    """配置变更后同步调度器（启用→按 cron 注册；停用→移除）"""
    if _scheduler is None:
        return
    job_key = f"{CRON_JOB_PREFIX}{sj.id}"
    if sj.enabled:
        _add_cron_job(sj.id, sj.cron_expr)
    else:
        try:
            _scheduler.remove_job(job_key)
        except Exception:  # noqa: BLE001（作业本就不存在时忽略）
            pass


def remove_schedule(schedule_id: int) -> None:
    """配置删除后移除调度器中的作业"""
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(f"{CRON_JOB_PREFIX}{schedule_id}")
    except Exception:  # noqa: BLE001
        pass


def _schedule_retry(schedule_id: int, attempt: int, prev_job_id: Optional[str], delay_minutes: float) -> None:
    """安排一次性重试（间隔取 sys_config.schedule_retry_delay_minutes，默认 5 分钟）"""
    if _scheduler is None:
        return
    run_date = datetime.now() + timedelta(minutes=delay_minutes)
    _scheduler.add_job(
        execute_schedule_job,
        trigger="date",
        run_date=run_date,
        args=[schedule_id, attempt, prev_job_id],
        id=f"{RETRY_JOB_PREFIX}{schedule_id}-{uuid.uuid4().hex[:8]}",
        replace_existing=False,
        misfire_grace_time=3600,
    )
    logger.info(f"定时任务 {schedule_id} 第 {attempt - 1} 次执行未成功，已安排 {delay_minutes} 分钟后重试")


# =============================================================================
# 到点执行
# =============================================================================

def _mark_wait_file(
    db: Session, sj: ScheduleJob, biz_date: str, job_id: Optional[str],
    reason: str, created_by: str,
) -> str:
    """文件未就绪：任务标记"待文件"（wait_file，附就绪时间参数提示），可复用既有任务行"""
    ready_time = get_param(db, "data_ready_time", "17:30")
    buffer_min = get_param(db, "buffer_minutes", "30")
    error_text = f"{reason}（数据就绪时间 {ready_time} + 缓冲 {buffer_min} 分钟）"
    job = db.get(ReconJob, job_id) if job_id else None
    if job is None:
        job = ReconJob(
            id=uuid.uuid4().hex[:16], module=sj.module.upper(), biz_date=biz_date,
            fetch_mode="file", status="wait_file", trigger_type="schedule",
            progress=0, created_by=created_by,
        )
        db.add(job)
    job.error = error_text
    job.finished_at = datetime.now()
    db.flush()
    return job.id


def execute_schedule_job(schedule_id: int, attempt: int = 1, prev_job_id: Optional[str] = None) -> None:
    """
    APScheduler 作业入口：按配置创建 recon_job 并同步执行，更新 schedule_job 最近执行信息

    Args:
        schedule_id: schedule_job.id
        attempt: 第几次执行（1=首次，2=重试；仅重试 1 次）
        prev_job_id: 上一次执行产生的 recon_job ID（file 模式 wait_file 复用）
    """
    db = get_session_factory()()
    job_id: Optional[str] = prev_job_id
    final = "failed"
    error_text: Optional[str] = None
    try:
        sj = db.get(ScheduleJob, schedule_id)
        if sj is None:
            logger.warning(f"定时任务配置不存在（可能已删除）: id={schedule_id}")
            return
        biz_date = datetime.now().strftime("%Y%m%d")
        created_by = f"schedule:{sj.name}"
        logger.info(f"定时任务[{sj.name}](id={schedule_id}) 第 {attempt} 次执行开始，业务日期={biz_date}")

        try:
            if sj.module == "m1" and sj.fetch_mode == "db":
                job_id = job_launch_service.launch_m1_db_job(
                    db, fund_template_id=sj.fund_template_id,
                    netvalue_template_id=sj.netvalue_template_id,
                    biz_date=biz_date, created_by=created_by, job_id=job_id)
            elif sj.module == "m1":
                job_id = job_launch_service.launch_m1_file_job(
                    db, file_dir=sj.file_dir or "", biz_date=biz_date,
                    created_by=created_by, job_id=job_id)
            elif sj.fetch_mode == "db":
                job_id = job_launch_service.launch_m2_db_job(
                    db, groups_json=sj.groups_json or "", biz_date=biz_date,
                    created_by=created_by, job_id=job_id)
            else:
                job_id = job_launch_service.launch_m2_file_job(
                    db, file_dir=sj.file_dir or "", biz_date=biz_date,
                    created_by=created_by, job_id=job_id)

            db.expire_all()
            job = db.get(ReconJob, job_id) if job_id else None
            final = job.status if job else "failed"
            if final not in ("success",):
                error_text = (job.error if job else None) or "任务执行失败（详见任务日志）"
        except job_launch_service.FilesNotReadyError as e:
            job_id = _mark_wait_file(db, sj, biz_date, job_id, str(e), created_by)
            final = "wait_file"
            error_text = db.get(ReconJob, job_id).error
        except Exception as e:  # noqa: BLE001（取数/校验/执行异常统一走失败路径）
            logger.error(f"定时任务[{sj.name}](id={schedule_id}) 第 {attempt} 次执行异常: {e}")
            final = "failed"
            error_text = str(e)
            if attempt >= 2 and (job_id is None or db.get(ReconJob, job_id) is None):
                # 取数阶段失败未产生任务记录：重试仍失败时补一条 failed 记录备查
                job = ReconJob(
                    id=uuid.uuid4().hex[:16], module=sj.module.upper(), biz_date=biz_date,
                    fetch_mode=sj.fetch_mode, status="failed", trigger_type="schedule",
                    progress=100, error=f"定时执行失败: {error_text}", created_by=created_by,
                    finished_at=datetime.now(),
                )
                db.add(job)
                db.flush()
                job_id = job.id

        # 更新 schedule_job 最近执行信息；失败重试安排在 commit 之后
        # （APScheduler jobstore 独立连接，避免与本会话未提交写事务争 SQLite 锁）
        delay_min = _retry_delay_minutes(db)
        do_retry = False
        retry_prev: Optional[str] = None
        sj.last_run_at = datetime.now()
        sj.last_job_id = job_id
        if final == "success":
            sj.last_status = "success"
            sj.last_error = None
        elif final == "wait_file":
            sj.last_status = "wait_file"
            sj.last_error = error_text
            if attempt < 2:
                do_retry = True
                retry_prev = job_id   # 待文件任务复用同一 recon_job 行
        else:
            sj.last_error = error_text
            if attempt < 2:
                sj.last_status = "retrying"
                do_retry = True
            else:
                sj.last_status = "failed"
        db.commit()
        if do_retry:
            _schedule_retry(schedule_id, 2, retry_prev, delay_min)
        logger.info(f"定时任务[{sj.name}](id={schedule_id}) 第 {attempt} 次执行结束: {final}"
                    + (f"，recon_job={job_id}" if job_id else ""))
    except Exception as e:  # noqa: BLE001
        logger.error(f"定时任务(id={schedule_id}) 调度执行内部异常: {e}")
        db.rollback()
    finally:
        db.close()
