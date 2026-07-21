# 安联资管运维管理平台

围绕恒生 O32 投资交易系统的日常运维场景，建设配置核对与风险排查能力。
（平台 v0.6.0 起更名"安联资管运维管理平台"，原 O32 日常运维平台；
内部技术标识 o32-server.exe、服务名、API 路径不变。当前版本 **v0.6.1**。）

一期交付 **Web 前端**（Vue 3 + Element Plus：登录/工作台/M1/M3 任务页/
归档/规则配置/用户维护）、**M1 基金资产与净值核对**、
**M3 基金属性表银行间ID匹配** 与 **规则配置中心**
（映射/特殊产品/阈值的增删改查、导入导出、审计留痕、热生效）：
核对引擎封装、FastAPI 服务端骨架（本地认证、用户维护、核对/匹配接口、
归档存储、审计日志、SPA 托管）、脱敏黄金样本与回归测试基线。
二期交付：**数据源管理（数据库只读直连）**——Oracle/MariaDB/MySQL/
SQL Server/PostgreSQL 五类数据源连接配置（密码 Fernet 加密、测试连接）、
查询模板（SQL + 字段映射 + 参数定义、预览执行），只读四道防线
（数据库只读账号授权示例 / SQL 白名单双校验 / 超时与行数限制与只读事务 /
凭据加密与全量审计）；**M2 基金估值价格核对（v0.4.0）**——多产品批量上传
（按文件名产品标识自动配对）、科目取价规则配置化（sys_subject_price_rule
预置 1101→市价 / 1501→单位成本，系统配置页维护、热生效、审计留痕）、
两步匹配（证券代码精确 → 证券名称模糊）、按产品出报告
（绿=一致 / 红=差异 / 橙=单边，底部汇总行 + 备注列）；
**数据库查询模式（v0.5.0，DS-F4）**——M1/M2 建任务支持 fetch_mode=file|db，
db 模式按查询模板同步取数（biz_date 绑定、SQL Guard 双校验），
查询快照（UTF-8-SIG CSV）归档后走与文件模式完全相同的核对流水线
（黄金样本一致性：统计与结果 Excel 逐格一致）；
**任务调度中心 + 统计看板（v0.5.0，DS-F5）**——APScheduler 持久化调度
（重启不丢；cron 配置 M1/M2 定时核对，db 模式模板取数 / file 模式监测目录，
未就绪标记"待文件"，失败自动重试 1 次；系统参数 data_ready_time/buffer_minutes
可配）、统计看板（差异趋势折线图 / 持续差异产品 / 任务健康度，
M1 产品级明细 recon_job_item 入库支撑）；
**数据字典查询（v0.5.1，M5）**——PDM 物理模型导入（PowerDesigner XML
解析入库，重复导入覆盖更新；预置 20 个 O32 模型：4,083 表 / 84,176 字段，
按表代码跨模型去重后 4,035 表 / 83,958 字段、58 条引用关系）、
表搜索（表代码/中文名/字段名三类命中点 + 分页 + 收藏置顶）、
表结构详情（字段清单/主键标识/父子两向引用）、可视化 SQL 生成器
（勾选字段 + 条件，多表按引用自动 JOIN，Oracle ROWNUM 行数限制，
生成 SQL 强制过 SQL Guard 只读校验，可保存为查询模板模块=custom）、
字典表收藏（dict_favorite，收藏表搜索与列表均置顶高亮）；
**升级数据保留 + 特殊产品清单（v0.6.0）**——upgrade.bat 平级目录升级迁移
（迁入旧版 data/archive/logs 全保留，旧目录留作回滚备份）、服务端 schema
轻量迁移机制（schema_version 登记 + 幂等迁移，首启自动结构升级）、
规则配置中心"大宗产品清单"更名"特殊产品清单"（每产品可配差异说明与
行填充颜色 6 位 HEX，缺省与 exe 小程序一致"大宗产品无需核对"+橙色 FFC000，
存量行为零变化，导入导出兼容新旧格式）；
**平台更名 + 登录体验优化（v0.6.1）**——登录页/侧边栏/浏览器标题/服务端横幅
更名，登录页密码错误表单上方明确提示（修复 401 被拦截静默缺陷）、
输入框改"用户编号"，用户维护新增"用户姓名""部门"字段（sys_user 加列，
迁移 v3 自动执行、存量无损），登录后右上角显示"用户姓名（用户编号）"。
M1 核心核对逻辑原样复用已验证的核对小程序（`samples/reference/fund_reconciler.py`
v1.0，验收基准），平台侧只做封装、服务化与质量保障。

## 目录说明

```
O32-OpsPlatform/
├── docs/                       # 项目文档
│   ├── 01-需求/                # 需求文档
│   ├── 02-方案/                # 落地方案、接口契约（接口契约_openapi.json）
│   ├── 03-手册/                # 部署手册（含只读账号授权示例）、操作手册
│   └── 04-测试/                # 测试报告（黄金样本回归 / API 冒烟 / 打包冒烟验证 / 数据源模块 / M2 模块 / 取数联动与调度看板）
├── package/                    # 打包产物：o32-ops-platform-v0.6.1\ 与同名 .zip（构建生成；升级用 upgrade.bat 平级迁移）
├── client/                     # 前端（Vue 3 + Vite + Element Plus + ECharts，构建产物 dist 由后端托管）
│   ├── src/views/              # 登录/工作台(看板)/M1/M2/M3/归档/数据字典/任务调度/规则/数据源连接/查询模板/系统配置/用户 十三页
│   └── src/{api,router,utils,layout}/
├── samples/
│   ├── reference/              # 验收基准：已验证核对小程序源码与配置（只读，禁改）
│   └── golden/                 # 黄金样本输入（全脱敏虚构数据，由脚本生成）
└── server/                     # 服务端（FastAPI + SQLite + APScheduler）
    ├── app/
    │   ├── main.py             # FastAPI 入口（lifespan 自动建库初始化 + 幂等迁移 + 调度器启停）
    │   ├── launcher.py         # 可执行程序启动器（PyInstaller 入口；亦可源码运行）
    │   ├── core/               # 配置(config)、安全(security)、依赖注入(deps)、加密(crypto)
    │   ├── api/                # 路由：routes_auth / routes_admin / routes_recon / routes_rule / routes_datasource / routes_system / routes_task / routes_dashboard / routes_dict
    │   ├── datasource/         # 数据源适配层：base / drivers / sql_guard / db_adapter
    │   ├── models/             # SQLAlchemy 实体、建库初始化（data/o32ops.db）与 migrations（schema_version 幂等迁移，当前到 v4=dict_favorite）
    │   ├── engines/            # 核对引擎（M1 基准复制件 + M1/M2/M3 引擎封装 + table_io）
    │   └── services/           # 规则加载(JSON/DB 双 Provider)、归档、审计、取数(fetch_service)、任务启动(job_launch)、调度(schedule_service)、数据字典(dict_service)
    ├── config/                 # rule_config.json（规则初始数据，建库时导入）
    ├── packaging/              # 打包流水线：build.spec / build.bat / 部署脚本模板（含 upgrade.bat 升级迁移）/ nssm / gen_pkg_info.py
    ├── scripts/                # export_openapi.py（接口契约固化导出）
    ├── tests/
    │   ├── golden/             # M1 黄金样本回归；golden/m2/ 为 M2 样本与回归；golden/m3/ 为 M3 样本与回归
    │   ├── unit/               # test_sql_guard.py（只读白名单门禁）/ test_db_adapter.py（SQLite 集成）/ test_migrations.py（schema 迁移）/ test_special_products.py（特殊产品引擎）/ test_pdm_import.py（PDM 导入）/ test_dict_gensql.py（SQL 生成）
    │   └── api/                # test_api_smoke.py(M1) / test_api_m2.py(M2) / test_api_m3.py(M3) / test_api_rules.py(规则) / test_api_datasource.py(数据源) / test_api_fetch_mode.py(取数模式) / test_api_schedule.py(调度+看板) / test_api_schedule_m2_file.py(调度补测) / test_api_dict.py(数据字典) 冒烟测试
    ├── .env.example            # 环境配置示例（密钥从 .env/环境变量读取，不入仓）
    ├── requirements.txt        # 依赖清单
    └── requirements-lock.txt   # 精确锁定版本（pip freeze，含 pyinstaller 与数据库驱动）
```

## 如何启动服务

环境：Windows，项目虚拟环境 `server\.venv`（Python 3.12，依赖已安装并锁定）。

```bash
# 1. 配置密钥：复制 server\.env.example 为 server\.env，设置 O32OPS_SECRET_KEY
#    （未配置时启动随机生成并告警，重启后登录态失效）

# 2. 启动（工作目录 server\）
cd /d/ITOps/O32-OpsPlatform/server
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 3. 访问
#    Swagger UI: http://127.0.0.1:8000/docs
#    健康检查:   http://127.0.0.1:8000/api/health
```

首次启动自动完成：建库 `server\data\o32ops.db`（WAL 模式）→ 建表 →
schema 幂等迁移（schema_version 登记，当前到 v4=dict_favorite）→
创建初始管理员 **admin / Admin@123**（首次登录强制改密）→
从 `server\config\rule_config.json` 导入规则（21 条映射、11 个特殊产品、
3 项阈值：diff_pct / fuzzy_sim / price_tol）→ 预置 M2 科目取价规则
（1101→市价、1501→单位成本）。数据字典库 `server\data\dictionary.db`
（20 个 O32 模型）随包预置，首启可直接使用。

## 如何构建部署包（PyInstaller + Vue 前端）

```bash
# 一键构建（Windows 双击 server\packaging\build.bat，或命令行）：
cd /d/ITOps/O32-OpsPlatform/server
packaging\build.bat
# 构建脚本自动执行前端构建（client: npm install + vite build，可用
# NODE_HOME 指定本机 Node）→ PyInstaller → 组装 package\
# 产物：package\o32-ops-platform-v0.6.1\ 与同名 .zip
# 部署包解压即用（目标机无需任何运行时），详见 docs\03-手册\部署手册.md
```

部署包含：o32-server.exe（onedir，已托管 app\web 前端静态资源）、
app\web（Vite 构建产物）、start/stop/install/uninstall.bat、
**upgrade.bat（版本升级数据迁移：从旧版平级目录迁入 data/archive/logs 全保留）**、
nssm（官方 2.24，含 SHA-256 说明；服务注册失败自动回退计划任务）、
版本.txt、依赖清单.txt。数据库驱动（oracledb/pymysql/psycopg2-binary/pymssql）
已随包验证可导入（二期直连免安装）。打包冒烟验证记录见
`docs\04-测试\打包冒烟验证报告.md`，前端构建与集成验证记录见
`docs\04-测试\前端构建与集成验证报告.md`。

## 接口清单摘要

| 接口 | 说明 | 角色 |
|------|------|------|
| `POST /api/auth/login` | 登录，返回 JWT（8h）；首登带改密标记 | 公开 |
| `POST /api/auth/change-password` | 修改密码（首登强制改密亦走此接口） | 登录用户 |
| `GET/POST /api/admin/users` | 用户列表 / 新增用户（含用户编号/用户姓名/部门/角色；登录后右上角显示"用户姓名（用户编号）"） | admin |
| `PUT /api/admin/users/{id}` | 修改角色/启停/姓名/部门 | admin |
| `POST /api/admin/users/{id}/reset-password` | 重置密码 | admin |
| `DELETE /api/admin/users/{id}` | 删除用户 | admin |
| `POST /api/recon/m1/jobs` | 创建 M1 核对任务（multipart，≤50MB）：fetch_mode=file 上传两表；fetch_mode=db 传 fund_template_id/netvalue_template_id + biz_date，同步取数落查询快照后走同一流水线 | admin/operator |
| `POST /api/recon/m2/jobs` | 创建 M2 估值价格核对任务：fetch_mode=file 多文件按文件名产品标识自动配对（落单/重复/无标识 400 中文指明）；fetch_mode=db 传 groups_json 模板分组 + biz_date | admin/operator |
| `POST /api/recon/m3/jobs` | 上传基金属性表+交易成员表(GBK CSV)创建 M3 匹配任务 | admin/operator |
| `GET /api/recon/jobs` | 任务历史分页查询（模块/日期区间/状态） | 全角色 |
| `GET /api/recon/jobs/{id}` | 任务详情：状态/进度/统计摘要/结果文件清单/日志尾部 | 全角色 |
| `GET /api/recon/jobs/{id}/download` | 下载结果文件；M3 支持 `?file=updated\|detail\|note`（默认 updated）；M2 支持 `?product=6301` 按产品下载（缺省首个产品报告） | admin/operator |
| `GET/POST /api/admin/system/subject-price-rules` | M2 科目取价规则列表 / 新增（前缀唯一，热生效） | 查 admin/operator，写 admin |
| `PUT/DELETE /api/admin/system/subject-price-rules/{id}` | 修改 / 删除科目取价规则 | admin |
| `GET/POST /api/rules/mappings` | 映射规则列表 / 新增映射 | 查 admin/operator，写 admin |
| `PUT/DELETE /api/rules/mappings/{id}` | 修改 / 删除映射（源代码唯一性校验） | admin |
| `GET/POST /api/rules/bulk-products` | 特殊产品清单 / 新增特殊产品（API 路径沿用 bulk-products 不变；每产品含差异说明 + 行填充颜色 6 位 HEX） | 查 admin/operator，写 admin |
| `PUT/DELETE /api/rules/bulk-products/{id}` | 修改 / 删除特殊产品 | admin |
| `GET /api/rules/thresholds`、`PUT /api/rules/thresholds/{key}` | 阈值查询 / 修改（diff_pct 0.01~100、fuzzy_sim 0~1、price_tol 0~1，越界 400） | 查 admin/operator，写 admin |
| `GET /api/rules/export`、`POST /api/rules/import` | 与小程序 config JSON 同构的导出 / 导入（导入整体替换映射与特殊产品，单事务回滚；兼容新旧两种 JSON 格式） | 查 admin/operator，写 admin |
| `GET/POST /api/datasources`、`PUT/DELETE /api/datasources/{id}` | 数据源连接 CRUD（五类库；密码 Fernet 加密，读取仅掩码；被模板引用禁删） | 查 admin/operator，写 admin |
| `POST /api/datasources/{id}/test` | 测试连接（中文友好结果） | admin/operator |
| `GET/POST /api/query-templates`、`PUT/DELETE /api/query-templates/{id}` | 查询模板 CRUD（SQL 保存时只读白名单校验，非法 400） | 查 admin/operator，写 admin |
| `POST /api/query-templates/{id}/preview` | 模板预览：参数绑定执行，返回前 50 行 + 列名 + 执行保护留痕 | admin/operator |
| `GET/POST /api/schedule/jobs`、`PUT/DELETE /api/schedule/jobs/{id}` | 定时任务 CRUD（模块 m1/m2、fetch_mode file/db、cron 合法性校验 400 中文；APScheduler 持久化，重启恢复） | admin/operator |
| `POST /api/schedule/jobs/{id}/toggle`、`POST /api/schedule/jobs/{id}/run-now` | 启停切换 / 立即执行一次（db 模板取数或 file 目录监测，未就绪标记"待文件"，失败自动重试 1 次） | admin/operator |
| `GET /api/schedule/executions` | 定时执行历史（复用 recon_job，trigger_type=schedule，可按 schedule_id 过滤） | admin/operator |
| `GET/PUT /api/admin/system/params` | 系统参数读写（data_ready_time / buffer_minutes / schedule_retry_delay_minutes，逐键校验） | 查 admin/operator，写 admin |
| `GET /api/dashboard/diff-trend?days=30` | M1 差异趋势（按业务日期：总记录/精确/模糊/未匹配/特殊产品/差异>1%，供折线图） | admin/operator |
| `GET /api/dashboard/persistent-diff?days=7&min_times=2` | 持续差异产品清单（recon_job_item 明细：次数/最近差异%/最大差异%） | admin/operator |
| `GET /api/dashboard/health` | 任务健康度：定时任务启用/总数、近 30 天 scheduled 按状态计数、最近 10 次执行 | admin/operator |
| `GET /api/dict/models` | 数据字典模型清单（按业务组分组） | admin/operator |
| `GET /api/dict/tables` | 表搜索（表代码/中文名/字段名三类命中点 + 分页 + 收藏置顶，标注 is_favorite） | admin/operator |
| `GET /api/dict/tables/{id}` | 表详情（全字段清单 + 主键标识 + 注释） | admin/operator |
| `GET /api/dict/tables/{id}/references` | 表关联（父子两向 Reference + JOIN 字段） | admin/operator |
| `POST /api/dict/gen-sql` | 可视化生成只读 SELECT（多表按外键自动 JOIN，无关联 CROSS 警告，Oracle ROWNUM 行数限制；生成后过 SQL Guard 自证 + 审计留痕） | admin/operator |
| `POST /api/dict/save-template` | 生成的 SQL 保存为查询模板（模块=custom，写 SQL 被 guard 拦截 400，重名 400） | admin |
| `GET/POST /api/dict/favorites`、`DELETE /api/dict/favorites/{table_id}` | 字典表收藏：列表 / 收藏（表不存在 404、重复 400）/ 取消收藏（未收藏 404）；收藏表搜索与列表置顶 | admin/operator |

规则**热生效**：M1 任务每次执行时由 DbRuleProvider 现取规则库（无缓存），
规则变更对新任务立即生效，历史归档结果不受影响；全部写操作记 sys_audit_log
（detail 含变更前后值）。

数据源**只读四道防线**：① 数据库侧只读账号（各库授权示例见部署手册第 9 章）；
② SQL 白名单（sqlparse token 级解析，仅单条 SELECT/WITH，保存与执行双校验）；
③ 执行保护（语句超时 60s、最大返回 100 万行、只读事务模式，均可配）；
④ 凭据 Fernet 加密（密钥由 data\secret.key 派生，不入库入仓）+ 全量操作审计。

完整契约：`docs/02-方案/接口契约_openapi.json`
（重新导出：`cd server && .venv\Scripts\python.exe scripts\export_openapi.py`）。

## 如何运行测试

```bash
# 1. 黄金样本回归（M1 使用托管运行时，无需 venv；M3 使用项目 venv）
PY="/c/Users/peng.du/AppData/Roaming/kimi-desktop/daimon-share/daimon/runtime/python/.venv/Scripts/python.exe"
PYTHONIOENCODING=utf-8 "$PY" server/tests/golden/make_samples.py   # 样本已存在可跳过
PYTHONIOENCODING=utf-8 "$PY" server/tests/golden/test_golden.py

# 2. M3 黄金样本回归 + API 冒烟（使用项目 venv，临时目录数据/归档，不影响开发库）
cd /d/ITOps/O32-OpsPlatform/server
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/golden/m3/make_samples_m3.py   # 样本已存在可跳过
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/golden/m3/test_golden_m3.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_smoke.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_m3.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_rules.py

# 2b. M2 黄金样本回归 + API 冒烟（含科目取价规则热生效专项）
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/golden/m2/make_samples_m2.py   # 样本已存在可跳过
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/golden/m2/build_expected_m2.py # 基线已存在可跳过
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/golden/m2/test_golden_m2.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_m2.py

# 3. 数据源模块（二期）：SQL Guard 单测 + DbAdapter SQLite 集成 + API 冒烟
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/unit/test_sql_guard.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/unit/test_db_adapter.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_datasource.py

# 4. 取数模式联动（DS-F4）+ 任务调度与统计看板（DS-F5）冒烟
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_fetch_mode.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_schedule.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_schedule_m2_file.py

# 5. 数据字典（M5）：PDM 导入 + SQL 生成 + 字典 API 冒烟
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/unit/test_pdm_import.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/unit/test_dict_gensql.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/api/test_api_dict.py

# 6. 升级与规则演进（v0.6.x）：schema 迁移 + 特殊产品引擎
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/unit/test_migrations.py
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe tests/unit/test_special_products.py
```

当前状态：**18 组门禁合计 849 项全绿**（以 `package\...\版本.txt` CHANGELOG 口径为准）。
主要分组：M1 黄金回归 21、M2 黄金回归 26、M3 黄金回归 33；M1 API 冒烟 54、
M2 API 冒烟 67、M3 API 冒烟 41、规则配置冒烟 124；SQL Guard 单测 75、
DbAdapter 集成 28、数据源 API 冒烟 76；取数模式冒烟 70、调度+看板冒烟 80、
调度补测 30；PDM 导入 18、SQL 生成 32、字典 API 冒烟 36；
schema 迁移 12、特殊产品引擎 14、迁移 v3 测试 6。
测试报告见 `docs/04-测试/黄金样本回归测试报告.md`、`docs/04-测试/API冒烟测试报告.md`
（M3 结果见附录 A，规则配置中心结果见附录 B）、`docs/04-测试/数据源模块测试报告.md`、
`docs/04-测试/M2估值价格核对测试报告.md`、`docs/04-测试/取数联动与调度看板测试报告.md`。

预期结果重建（仅当基准逻辑、规则配置或样本有经评审变更时）：
`python server/tests/golden/build_expected.py`、
`server/tests/golden/m2/build_expected_m2.py`、
`server/tests/golden/m3/build_expected_m3.py`

详细样本场景设计与理论预期对照见 `server/tests/golden/README.md`、
`server/tests/golden/m2/README.md`、
`server/tests/golden/m3/README.md`。
