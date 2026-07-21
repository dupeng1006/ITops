# API 冒烟测试报告 —— O32 日常运维平台（一期 M1 服务端）

| 项目 | 内容 |
|------|------|
| 测试日期 | 2026-07-17 |
| 测试对象 | FastAPI 服务端骨架（认证/用户维护/M1 核对接口/归档存储） |
| 测试环境 | Windows / Python 3.12.13 / server\.venv（fastapi 0.139.2、SQLAlchemy 2.0.51、pandas 3.0.3、openpyxl 3.1.5，精确版本见 `server/requirements-lock.txt`） |
| 测试数据 | `samples/golden/` 脱敏黄金样本；独立临时数据/归档目录（不污染开发库） |
| 结论 | **冒烟测试 54/54 PASS，退出码 0；黄金样本回归 21/21 PASS 保持全绿** |

## 1. 测试范围与方法

`server/tests/api/test_api_smoke.py`（纯脚本，fastapi.testclient）：
通过环境变量将数据目录、归档目录、SQLite 库、JWT 密钥指向临时目录后启动测试 app，
按真实用户链路逐接口调用并断言。

## 2. 测试场景与结果

| # | 场景 | 断言要点 | 结果 |
|---|------|----------|------|
| 1 | admin 首登 | `Admin@123` 登录成功、`must_change_password=True` | ✅ |
| 2 | 强制改密拦截 | 未改密访问用户维护 → 403，提示含"修改初始密码"；改密后放行 | ✅ |
| 3 | 用户维护 | 创建 operator/viewer（新用户强制首登改密）；重复用户名 → 400 | ✅ |
| 4 | M1 任务全流程 | operator 上传黄金样本两表建任务 → 后台异步执行 → 轮询 success、进度 100 | ✅ |
| 5 | 口径一致性 | 统计摘要与黄金基线 `expected_stats.json` 逐项相等（总记录16/精确14/模糊1/未匹配1/大宗2/差异>1%为1）；日志含中文步骤文案 | ✅ |
| 6 | 版本不覆盖 | 同业务日期第二次执行 → 结果文件名自动 `_v2.xlsx` | ✅ |
| 7 | 历史查询 | 按模块+状态分页查询返回 2 条 | ✅ |
| 8 | 下载与颜色抽样 | 下载 200、PK 头、文件名带日期版本；openpyxl 抽样：表头 B4C7DC、第2/12行大宗 FFC000、第3行差异 FFCCCC、第17行未匹配 FFFF99、共 17 行 | ✅ |
| 9 | viewer 权限边界 | 建任务 403（提示"权限不足"）；查历史/详情 200；下载 403 | ✅ |
| 10 | 错误输入 | 基金表 10 列 → 400 含"列数不足"+"选反"；两表选反上传 → 400 含"选反"（服务端同时记录 WARNING 告警） | ✅ |
| 11 | 审计落库 | login / user_create / upload_create_job / download / change_password 均写入 sys_audit_log | ✅ |

## 3. 关键输出（摘录）

```
--- 1. admin 首登 / 强制改密 ---
[PASS] 登录 admin 返回200
[PASS] admin 首登返回 must_change_password=True
[PASS] 未改密访问用户维护被拦截(403)
[PASS] 拦截提示含'修改初始密码'
[PASS] 修改密码返回200
[PASS] 改密后访问用户维护正常(200)
--- 3. M1 核对任务全流程 ---
[PASS] 任务1 执行成功
[PASS] 任务1 进度=100
[PASS] 任务1 统计摘要与黄金基线一致
[PASS] 任务1 日志含中文步骤文案
[PASS] 任务2 执行成功
[PASS] 同日期结果文件名自动 _v2
--- 4. 历史查询 / 下载 / 颜色抽样 ---
[PASS] 下载结果返回200
[PASS] 颜色抽样: 表头 B4C7DC
[PASS] 颜色抽样: 第2行大宗 FFC000
[PASS] 颜色抽样: 第3行差异 FFCCCC
[PASS] 颜色抽样: 第12行大宗 FFC000
[PASS] 颜色抽样: 第17行未匹配 FFFF99
--- 5. viewer 权限边界 ---
[PASS] viewer 建任务被拒(403)
[PASS] viewer 可查历史(200)
[PASS] viewer 可查任务详情与统计(200)
[PASS] viewer 下载被拒(403)
--- 6. 错误输入处理 ---
[PASS] 基金表列数不足返回400
[PASS] 400 提示含'列数不足'
[PASS] 400 提示含'选反'引导语
[PASS] 文件选反返回400
[PASS] 选反 400 提示含'选反'引导语
--- 7. 审计日志 ---
[PASS] 审计动作已记录: login / user_create / upload_create_job / download / change_password
======================================================================
API 冒烟测试全部通过 ✅   EXIT_CODE=0（54 PASS / 0 FAIL）
```

## 4. uvicorn 实启动验证

```
$ .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8123
INFO:     Uvicorn running on http://127.0.0.1:8123

GET  /api/health  → 200  {"status":"ok","service":"o32-ops-platform","phase":"一期(M1)"}
GET  /docs        → 200（Swagger UI 可访问）
GET  /openapi.json→ 200（10 个接口路径）
POST /api/auth/login {"username":"admin","password":"Admin@123"}
     → 200  返回 JWT，must_change_password=true（同时写审计日志）
```

## 5. 黄金样本回归（防回归门禁复核）

```
$ python server/tests/golden/test_golden.py
回归测试全部通过 ✅（统计 dict / DataFrame 逐值 / Excel 填充色 / 输入校验）
21 PASS / 0 FAIL，EXIT_CODE=0 —— 服务端改造未影响引擎口径
```

## 6. 结论与风险提示

- 一期服务端骨架（认证 + 用户维护 + M1 核对接口 + 归档 + 审计）功能完整，
  平台输出与小程序基准口径一致（统计与 Excel 颜色均对齐黄金基线）；
- **风险**：server\.venv 中 pandas 为 3.0.3（黄金基线生成于 3.0.2），本次验证输出
  无漂移；后续依赖升级须先重跑 `test_golden.py` + `test_api_smoke.py` 双门禁；
- 遗留项（二期范围）：直连取数、调度、WebSocket 进度推送、M2 模块。

---

# 附录 A：M3（基金属性表银行间 ID 匹配）回归与冒烟结果（2026-07-17）

## A.1 M3 黄金样本回归（`tests/golden/m3/test_golden_m3.py`，33 PASS / 0 FAIL）

样本（全脱敏虚构）：基金属性表 5 列 × 15 行（银行间ID 数值/空值混合，读回 float64 类型陷阱）、
交易成员基本信息表 3 列 × 12 行（GBK CSV）。场景覆盖：

| 场景 | 样本 | 预期 | 实际 |
|------|------|------|------|
| 精确匹配-无变化（蓝 BDD7EE） | 4 行（原ID数值存储 1001-1004，成员表为字符串） | 数值归一后判等成功 | ✅ 一致 |
| 精确匹配-有变动（绿 C6EFCE） | 5 行（含 2 行原ID为空） | 更新为新ID | ✅ 一致 |
| 未匹配-内部简称（TR_ 前缀） | 2 行 | 红 FFC7CE + 归类"内部简称" | ✅ 一致 |
| 未匹配-未注册产品 | 2 行 | 红 + 归类"未注册产品" | ✅ 一致 |
| 未匹配-后缀不一致 | 2 行（与成员全称互为包含） | 红 + 归类"命名后缀不一致" | ✅ 一致 |
| float64 类型陷阱 | 银行间ID 列数值+空值 | 归一为字符串（'1001' 不带 .0，空为 ''） | ✅ 一致（金丝雀场景） |

统计基线：`总记录数15 / 有变动5 / 无变化4 / 未匹配6`。
比对项：统计 dict、明细 DataFrame 逐格、更新表银行间ID 列值、
三类颜色抽样（更新表+明细表）、说明 md 全文一致、缺列中文报错 —— 全部 PASS。

## A.2 M3 API 冒烟（`tests/api/test_api_m3.py`，41 PASS / 0 FAIL）

```
[PASS] 创建 M3 任务返回200 → 轮询 success
[PASS] 统计摘要与 M3 黄金基线一致（15/5/4/6）
[PASS] 结果文件清单含三件套（更新表/明细/说明md）
[PASS] 下载 updated：第2行蓝 BDD7EE、第6行绿 C6EFCE、第11行红 FFC7CE、
       银行间ID 第6行=MB1005、第2行=1001（数值陷阱归一）
[PASS] 下载 detail/note：内容与基线一致（含三类归类提示）
[PASS] 默认下载（不带 file 参数）= 更新表；非法 file 参数 → 400
[PASS] viewer 建任务 403 / 下载 403 / 查历史 200
[PASS] 基金属性表缺列 → 400 含'银行间ID'；交易成员表缺列 → 400 含'交易成员ID'
```

## A.3 三门禁复核（M3 接入后）

| 门禁 | 结果 |
|------|------|
| M1 黄金回归 `test_golden.py` | 21 PASS / 0 FAIL，EXIT=0 ✅ |
| M3 黄金回归 `test_golden_m3.py` | 33 PASS / 0 FAIL，EXIT=0 ✅ |
| M1 API 冒烟 `test_api_smoke.py` | 54 PASS / 0 FAIL，EXIT=0 ✅ |
| M3 API 冒烟 `test_api_m3.py` | 41 PASS / 0 FAIL，EXIT=0 ✅ |
| uvicorn 实启动 | /docs 200；`/api/recon/m3/jobs` 与 `file` 参数已出现在 OpenAPI（11 接口） ✅ |


---

# 附录 B：规则配置中心接口冒烟结果（2026-07-17）

## B.1 范围

`server/app/api/routes_rule.py`（12 个接口）：
映射规则与大宗产品的增删改查、阈值修改（范围校验）、
与小程序 `fund_reconciler_config.json` 同构的导入/导出、变更审计留痕、
以及"改规则→新任务立即生效"的热生效专项验证。

## B.2 规则配置 API 冒烟（`tests/api/test_api_rules.py`，109 PASS / 0 FAIL）

```
[PASS] 初始数据：映射 21 条 / 大宗 11 个 / 阈值 diff_pct=1.0、fuzzy_sim=0.5、price_tol=0.0001(预留)
[PASS] 权限：operator 查询 200 ×4；operator 写操作 403 ×4；viewer 查询 403 ×3；未登录 401
[PASS] 映射 CRUD：新增(22条)→重复原代码 400→源=目标 400→修改(含停用)→删除(回21条)→404
[PASS] 大宗 CRUD：新增(12个)→重复 400→修改→删除(回11个)→404
[PASS] 阈值：fuzzy_sim 0.6 生效并恢复；diff_pct=0.005/200、fuzzy_sim=1.5/-0.1、
       price_tol=2.0 均 400（提示含合法范围）；未知键 400；price_tol 0.0002 生效并恢复
[PASS] 导出：rename_map/bulk_products/diff_threshold/similarity_threshold 与基准
       fund_reconciler_config.json 逐项一致，含 output_settings（同构）
[PASS] 导入：整体替换（映射 21→23、大宗 11→10；导入基准恢复 23→21 / 10→11，双向计数断言）；
       大宗重复 400、非法阈值 400，且失败后条目数不变（不落半截）；
       导入基准配置恢复后导出再次一致
[PASS] 热生效专项：详见 B.3
[PASS] 审计：rule_mapping_create/update/delete、rule_bulk_create/update/delete、
       rule_threshold_update、rule_import 均落库；detail 含变更前后值
       （如 fuzzy_sim 0.5→0.9、映射 T8001→T8002、导入计数 21→23）
```

## B.3 热生效专项证据（修改前后统计对比）

杠杆：fuzzy_sim 0.5→0.9（使相似度 0.875 的"测试稳益11号 vs A类"模糊场景变为未匹配）
＋ 临时新增大宗产品 C1002（使 ZH002 差异行转为大宗、退出差异统计）。
三个 M1 任务连跑（同一黄金样本，规则库现取，无缓存）：

| 任务 | 规则状态 | 总记录 | 精确 | 模糊 | 未匹配 | 大宗 | 差异>1%(非大宗) |
|------|----------|--------|------|------|--------|------|------------------|
| A（改前） | 基线 fuzzy_sim=0.5 | 16 | 14 | 1 | 1 | 2 | 1 |
| B（改后） | fuzzy_sim=0.9 ＋ 大宗+C1002 | 16 | 14 | **0** | **2** | **3** | **0** |
| C（恢复） | fuzzy_sim=0.5 ＋ 删除 C1002 | 16 | 14 | 1 | 1 | 2 | 1 |

任务 B 日志同时出现 `规则配置加载完成(来源:数据库)` 与 `模糊匹配完成: 0条`，
证明新任务执行时现取新规则；任务 A/C 统计与黄金基线完全一致，
证明规则恢复后行为还原、历史任务归档结果不受影响。

## B.4 五门禁复核（规则配置中心接入后）

| 门禁 | 结果 |
|------|------|
| M1 黄金回归 `test_golden.py` | 21 PASS / 0 FAIL，EXIT=0 ✅ |
| M3 黄金回归 `test_golden_m3.py` | 33 PASS / 0 FAIL，EXIT=0 ✅ |
| M1 API 冒烟 `test_api_smoke.py` | 54 PASS / 0 FAIL，EXIT=0 ✅ |
| M3 API 冒烟 `test_api_m3.py` | 41 PASS / 0 FAIL，EXIT=0 ✅ |
| 规则配置冒烟 `test_api_rules.py` | 109 PASS / 0 FAIL，EXIT=0 ✅ |
| uvicorn 实启动 | /docs 200；规则 8 路径全部入 OpenAPI（全量 19 路径/25 操作）；curl 抽查 401/200/400/导入导出正常 ✅ |
