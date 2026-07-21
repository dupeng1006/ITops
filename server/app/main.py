# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— FastAPI 应用入口

启动方式（工作目录 server/）：
    .venv\\Scripts\\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000

一期范围：本地认证与用户维护、M1 基金资产与净值核对（文件模式）、归档存储。
二期范围：M2 基金估值价格核对（多产品批量）、M3 银行间ID匹配、数据源管理、
系统配置（科目取价规则）。
字典范围：M5 数据字典查询（PDM 导入、表搜索、可视化只读 SQL 生成）。
接口文档：/docs（Swagger UI） / /openapi.json

前端托管：
    若检测到前端构建产物（冻结态取 exe 同级 web\\ 目录，源码态取
    server\\web\\ 或 client\\dist\\），则在全部 API 路由之后以 SPA 方式
    挂载到 /（html=True，未知路径回退 index.html；/api 与 /docs 不受影响）。

作者：技术部
版本：1.1.0
日期：2026-07-17
"""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    routes_admin,
    routes_auth,
    routes_dashboard,
    routes_datasource,
    routes_dict,
    routes_recon,
    routes_rule,
    routes_system,
    routes_task,
)
from app.core.config import get_settings
from app.models.database import get_engine, init_database
from app.models.migrations import run_migrations
from app.services import schedule_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动期：建目录、初始化数据库（建表 + 初始管理员 + 规则导入）、恢复任务调度器"""
    settings = get_settings()
    settings.ensure_dirs()
    init_database(settings.DB_PATH)
    run_migrations(get_engine())
    schedule_service.init_scheduler()
    logger.info("安联资管运维管理平台服务端启动完成（M1/M2/M3 核对 + 数据源管理 + 系统配置 + 任务调度中心 + 统计看板 + 数据字典）")
    yield
    schedule_service.shutdown_scheduler()
    logger.info("安联资管运维管理平台服务端正在停止")


app = FastAPI(
    title="安联资管运维管理平台",
    description="安联资管运维管理平台（恒生 O32 投资交易系统日常运维）：M1/M2/M3 核对 + 数据源管理 + 系统配置 + 任务调度中心 + 统计看板 + 数据字典 + 本地认证",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(routes_auth.router)
app.include_router(routes_admin.router)
app.include_router(routes_recon.router)
app.include_router(routes_rule.router)
app.include_router(routes_datasource.router)
app.include_router(routes_system.router)
app.include_router(routes_task.router)
app.include_router(routes_dashboard.router)
app.include_router(routes_dict.router)


@app.get("/api/health", tags=["系统"], summary="健康检查")
def health():
    return {"status": "ok", "service": "o32-ops-platform", "phase": "二期(M1+M2+M3+数据字典)"}


# =============================================================================
# 前端 SPA 托管（挂载于全部 API 路由之后）
# =============================================================================

class SPAStaticFiles(StaticFiles):
    """SPA 静态文件托管：未命中的非 /api 路径回退 index.html"""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            # /api 下的未知路径不回退，保持 404 JSON 语义
            # （StaticFiles.get_path 按 OS 归一化，Windows 下分隔符为反斜杠）
            p = path.replace("\\", "/").lstrip("/")
            if e.status_code == 404 and not (p == "api" or p.startswith("api/")):
                return await super().get_response("index.html", scope)
            raise


def _find_web_dir() -> Optional[Path]:
    """定位前端构建产物目录（含 index.html 才认定），找不到则跳过挂载"""
    if getattr(sys, "frozen", False):
        candidates = [Path(sys.executable).resolve().parent / "web"]
    else:
        server_root = Path(__file__).resolve().parents[1]
        candidates = [
            server_root / "web",
            server_root.parent / "client" / "dist",
        ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return None


_web_dir = _find_web_dir()
if _web_dir is not None:
    app.mount("/", SPAStaticFiles(directory=str(_web_dir), html=True), name="web")
    logger.info(f"前端静态文件已挂载: {_web_dir}")
else:
    logger.info("未检测到前端构建产物（web/ 或 client/dist），仅提供 API 服务")

