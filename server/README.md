# O32 日常运维平台 —— 服务端（server）

一期范围：**M1 基金资产与净值核对** + **M3 基金属性表银行间ID匹配** +
**规则配置中心**（映射/大宗/阈值增删改查、导入导出、审计留痕、热生效）的
FastAPI 服务端骨架（本地认证、用户维护、核对/匹配接口、归档存储、审计日志
+ 黄金样本回归）。不含前端、数据源直连、任务调度（二期范围）。

## 目录说明

| 目录 | 说明 |
|------|------|
| `app/main.py` | FastAPI 入口（lifespan：建目录 → init_database → 初始管理员 + 规则导入） |
| `app/core/` | 基础设施：`config.py`（集中配置，.env/环境变量）、`security.py`（bcrypt+JWT）、`deps.py`（会话/认证/角色依赖） |
| `app/api/` | 路由：`routes_auth.py`（登录/改密）、`routes_admin.py`（用户维护）、`routes_recon.py`（M1/M3 任务）、`routes_rule.py`（规则配置中心） |
| `app/models/` | SQLAlchemy 实体（`entities.py`）与建库初始化（`database.py`，SQLite WAL） |
| `app/engines/` | `fund_reconciler_base.py`（验收基准复制件 v1.0）、`m1_fund_netvalue.py`、`m3_interbank_id.py` |
| `app/services/` | `rule_service.py`（DbRuleProvider 默认 / JsonRuleProvider 可切回）、`archive_service.py`、`audit_service.py` |
| `config/` | `rule_config.json`（规则初始数据，建库时导入规则库） |
| `scripts/` | `export_openapi.py`（接口契约固化导出） |
| `tests/golden/` | M1 黄金样本回归；`golden/m3/` M3 样本、预期基线与回归脚本 |
| `tests/api/` | `test_api_smoke.py`（M1，54 项断言）、`test_api_m3.py`（M3，41 项断言）、`test_api_rules.py`（规则配置，109 项断言） |
| `.env.example` | 环境配置示例（O32OPS_SECRET_KEY 等；.env 不入仓） |
| `requirements.txt` / `requirements-lock.txt` | 依赖清单 / 精确锁定版本 |

## 快速开始

```bash
# 启动服务（首启自动建库 + 初始管理员 admin/Admin@123，首登强制改密）
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 冒烟测试（临时目录，不污染开发库）
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_smoke.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_m3.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_rules.py
```
