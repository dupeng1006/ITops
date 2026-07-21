# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 统计看板接口（二期 DS-F5）

    GET /api/dashboard/diff-trend?days=30
        按日返回 M1 任务统计（总记录/精确/模糊/未匹配/大宗/差异>1%），
        同一业务日期取当日最后一次成功任务，供 ECharts 折线图；
    GET /api/dashboard/persistent-diff?days=7&min_times=2
        近 N 日内差异超阈值（rule_threshold.diff_pct，默认 1.0%）出现
        ≥min_times 次的产品清单（数据来自 recon_job_item 明细）；
    GET /api/dashboard/health
        定时任务健康度：配置总数/启用数、近 30 天 scheduled 任务按状态
        计数、最近 10 次定时执行、就绪时间参数。

以上接口均 operator 及以上角色可访问（viewer 403）。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import json
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    DashboardHealthResponse,
    DiffTrendPoint,
    DiffTrendResponse,
    PersistentDiffItem,
    PersistentDiffResponse,
    ScheduleExecutionInfo,
)
from app.core.deps import get_db, require_roles
from app.models.entities import ReconJob, ReconJobItem, RuleThreshold, ScheduleJob, SysConfig, SysUser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["统计看板"])

# stats_json 键 → 趋势字段
_STATS_KEYS = {
    "total": "总记录数",
    "exact": "精确匹配",
    "fuzzy": "模糊匹配",
    "unmatched": "未匹配",
    "bulk": "大宗产品数",
    "diff": "差异>1.0%数量（非大宗）",
}


def _get_param(db: Session, key: str, default: str) -> str:
    row = db.execute(select(SysConfig).where(SysConfig.param_key == key)).scalars().first()
    return row.param_value if row else default


@router.get("/diff-trend", response_model=DiffTrendResponse, summary="M1 差异趋势（按业务日期）")
def diff_trend(
    days: int = Query(30, ge=1, le=365, description="回溯天数"),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    since = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    rows = db.execute(
        select(ReconJob)
        .where(ReconJob.module == "M1", ReconJob.status == "success", ReconJob.biz_date >= since)
        .order_by(ReconJob.biz_date, ReconJob.finished_at)
    ).scalars().all()

    by_date: dict = {}
    for job in rows:  # 同业务日期后者覆盖前者（取当日最后一次成功任务）
        by_date[job.biz_date] = job

    points = []
    for biz_date in sorted(by_date):
        stats = json.loads(by_date[biz_date].stats_json or "{}")
        points.append(DiffTrendPoint(
            biz_date=biz_date,
            **{field: int(stats.get(key, 0) or 0) for field, key in _STATS_KEYS.items()},
        ))
    return DiffTrendResponse(days=days, points=points)


@router.get("/persistent-diff", response_model=PersistentDiffResponse,
            summary="持续差异产品清单（recon_job_item 明细）")
def persistent_diff(
    days: int = Query(7, ge=1, le=90, description="回溯天数"),
    min_times: int = Query(2, ge=1, le=100, description="最少出现次数"),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    t_row = db.execute(
        select(RuleThreshold).where(RuleThreshold.param_key == "diff_pct")
    ).scalars().first()
    threshold = float(t_row.param_value) if t_row else 1.0

    since_dt = datetime.now() - timedelta(days=days)
    rows = db.execute(
        select(
            ReconJobItem.product_code,
            func.count().label("times"),
            func.max(ReconJobItem.max_diff_pct).label("max_diff"),
            func.max(ReconJobItem.created_at).label("last_at"),
        )
        .join(ReconJob, ReconJob.id == ReconJobItem.job_id)
        .where(ReconJob.created_at >= since_dt, ReconJobItem.max_diff_pct > threshold)
        .group_by(ReconJobItem.product_code)
        .having(func.count() >= min_times)
        .order_by(func.count().desc(), func.max(ReconJobItem.max_diff_pct).desc())
    ).all()

    items = []
    for code, times, max_diff, last_at in rows:
        last_item = db.execute(
            select(ReconJobItem)
            .where(ReconJobItem.product_code == code, ReconJobItem.max_diff_pct > threshold)
            .order_by(ReconJobItem.created_at.desc())
            .limit(1)
        ).scalars().first()
        items.append(PersistentDiffItem(
            product_code=code,
            product_name=last_item.product_name if last_item else None,
            times=times,
            last_diff_pct=round(last_item.max_diff_pct, 4) if last_item and last_item.max_diff_pct is not None else None,
            max_diff_pct=round(max_diff, 4) if max_diff is not None else None,
        ))
    return PersistentDiffResponse(days=days, min_times=min_times, threshold_pct=threshold, items=items)


@router.get("/health", response_model=DashboardHealthResponse, summary="定时任务健康度")
def health(
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    schedule_total = db.execute(select(func.count()).select_from(ScheduleJob)).scalar() or 0
    schedule_enabled = db.execute(
        select(func.count()).select_from(ScheduleJob).where(ScheduleJob.enabled.is_(True))
    ).scalar() or 0

    since_dt = datetime.now() - timedelta(days=30)
    status_rows = db.execute(
        select(ReconJob.status, func.count())
        .where(ReconJob.trigger_type == "schedule", ReconJob.created_at >= since_dt)
        .group_by(ReconJob.status)
    ).all()
    last30d = {status: count for status, count in status_rows}

    recent_jobs = db.execute(
        select(ReconJob)
        .where(ReconJob.trigger_type == "schedule")
        .order_by(ReconJob.created_at.desc(), ReconJob.id.desc())
        .limit(10)
    ).scalars().all()
    recent = [
        ScheduleExecutionInfo(
            job_id=j.id, module=j.module, biz_date=j.biz_date, fetch_mode=j.fetch_mode,
            status=j.status,
            stats=json.loads(j.stats_json) if j.stats_json else None,
            error=j.error, created_by=j.created_by,
            created_at=j.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=j.finished_at.strftime("%Y-%m-%d %H:%M:%S") if j.finished_at else None,
        )
        for j in recent_jobs
    ]

    return DashboardHealthResponse(
        schedule_total=schedule_total,
        schedule_enabled=schedule_enabled,
        last30d=last30d,
        recent=recent,
        data_ready_time=_get_param(db, "data_ready_time", "17:30"),
        buffer_minutes=_get_param(db, "buffer_minutes", "30"),
    )
