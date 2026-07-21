# -*- coding: utf-8 -*-
"""
生成部署包元信息：版本.txt 与 依赖清单.txt

用法（工作目录 server/）：
    .venv\\Scripts\\python.exe packaging\\gen_pkg_info.py <部署目录> <版本号>

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import importlib.metadata
import sys
from datetime import datetime
from pathlib import Path

# 主要库 License 类型标注（依据各项目公开许可声明）
LICENSE_MAP = {
    "fastapi": "MIT",
    "starlette": "BSD-3-Clause",
    "uvicorn": "BSD-3-Clause",
    "pydantic": "MIT",
    "pydantic_core": "MIT",
    "sqlalchemy": "MIT",
    "greenlet": "MIT",
    "pandas": "BSD-3-Clause",
    "numpy": "BSD-3-Clause",
    "python-dateutil": "Apache-2.0 / BSD",
    "openpyxl": "MIT",
    "et_xmlfile": "MIT",
    "xlrd": "BSD-3-Clause",
    "bcrypt": "Apache-2.0",
    "pyjwt": "MIT",
    "python-multipart": "Apache-2.0",
    "anyio": "MIT",
    "h11": "MIT",
    "click": "BSD-3-Clause",
    "colorama": "BSD-3-Clause",
    "idna": "BSD-3-Clause",
    "certifi": "MPL-2.0",
    "typing_extensions": "PSF-2.0",
    "typing-inspection": "MIT",
    "annotated-types": "MIT",
    "annotated-doc": "MIT",
    "tzdata": "Apache-2.0",
    "six": "MIT",
    "oracledb": "Apache-2.0",
    "cryptography": "Apache-2.0 / BSD",
    "cffi": "MIT",
    "pycparser": "BSD-3-Clause",
    "pymysql": "MIT",
    "sqlparse": "BSD-3-Clause",
    "psycopg2-binary": "LGPL-3.0（随二进制 libpq 分发，见包内许可）",
    "pymssql": "LGPL-2.1（自带 FreeTDS，见包内许可）",
    "pyinstaller": "GPL-2.0（含打包产物商业分发例外条款）",
    "pyinstaller-hooks-contrib": "GPL-2.0（同上例外）",
    "altgraph": "MIT",
    "pefile": "MIT",
    "pywin32-ctypes": "BSD-3-Clause",
    "packaging": "Apache-2.0 / BSD",
    "setuptools": "MIT",
    "sniffio": "MIT / Apache-2.0",
    "apscheduler": "MIT",
    "tzlocal": "MIT",
}

CHANGELOG = """\
v0.6.1（2026-07-20）平台更名 + 登录体验与用户基础信息优化
  - 平台更名"安联资管运维管理平台"：登录页/侧边栏/浏览器标题/服务端
    横幅与接口文档（内部标识 o32-server.exe、服务名、API 路径不变）
  - 登录页：去除标题下小字描述；用户名密码错误时页面表单上方
    明确提示"用户名或密码错误"（修复原拦截器把登录 401 当"登录失效"
    静默处理、页面无任何反馈的缺陷）；输入框改"用户编号"
  - 用户维护：新增"用户姓名""部门"字段（sys_user 加列，迁移 v3 自动
    执行、存量用户无损）；列表/新增/编辑联动；登录后右上角显示
    "用户姓名（用户编号）"；登录响应补充 display_name
  - upgrade.bat：旧版本输入兼容序号/目录名/完整路径三种方式；
    修复路径含盘符冒号时被变量展开截断的缺陷
  - 新增迁移 v3 测试 6 项；18 组门禁 849 项全绿
v0.6.0（2026-07-20）升级数据保留修复 + 特殊产品清单
  - 【缺陷修复】版本升级数据保留：新增 upgrade.bat 升级迁移工具
    （迁入旧版 data/archive/logs，用户/规则/模板/数据源/历史任务/归档
    全保留；旧目录原样留作回滚备份；旧字典库优先、包内预置字典备份为
    dictionary.db.pkg）；服务端新增 schema 轻量迁移机制（schema_version
    表 + 幂等迁移，首启自动完成结构升级）；版本.txt 与部署手册补充
    标准升级流程
  - 【功能优化】规则配置中心"大宗产品清单"更名"特殊产品清单"：
    每个产品可配置差异说明（展示在 M1 结果 Excel"差异原因"列）与
    行填充颜色（6 位 HEX，前端色板选择）；缺省值与 exe 小程序完全一致
    （"大宗产品无需核对" + 橙色 FFC000），存量行为零变化；
    内部表名与 API 路径不变；规则导入导出兼容新旧两种 JSON 格式；
    存量 11 个产品迁移后数据无损
  - 前端：特殊产品清单页签（说明/颜色列 + 色板编辑），
    M1 任务页与统计看板"大宗"文案统一为"特殊"
  - 新增测试门禁：迁移机制 12 项、特殊产品引擎 14 项；rules API 冒烟
    扩至 124 项；M1 黄金回归原样逐格通过（默认行为红线）
v0.5.1（2026-07-20）二期第五项：数据字典查询（M5）
  - PDM 物理模型导入：PowerDesigner XML 解析入库（模型/表/字段/主键/引用），
    支持重复导入覆盖；预置 20 个 O32 模型成果（data\dictionary.db 随包，
    4,083 表 / 84,176 字段，去重后 4,035 表 / 83,958 字段、58 条引用）
  - 表搜索：表代码/中文名/字段名三类命中点 + 分页；表详情含字段清单、
    主键标识、父子两向引用关系
  - 可视化 SQL 生成器：勾选字段 + 条件（=,!=,>,>=,<,<=,LIKE,IN,BETWEEN,
    IS NULL），多表按引用自动 JOIN（无关联 CROSS 警告），Oracle ROWNUM
    行数限制；生成 SQL 强制过 SQL Guard 只读校验
  - 模板沉淀：生成 SQL 可保存为查询模板（模块=custom，admin），
    与数据源管理查询模板打通复用
  - 权限：operator 及以上可查可生成，viewer 403；生成与存模板全量审计
  - 前端新增"数据字典"菜单（搜索 / 详情 / SQL 生成器三页）
  - 新增测试门禁：PDM 导入 18 项、SQL 生成 32 项、字典 API 冒烟 36 项
v0.5.0（2026-07-20）二期第三、四项：数据库查询模式 + 任务调度中心 + 统计看板
  - 数据库查询模式（DS-F4）：M1/M2 建任务支持 fetch_mode=file|db（默认 file
    零变化）；db 模式按查询模板同步取数（biz_date 绑定、SQL Guard 双校验、
    模板 404 / 模块不匹配 400 中文），查询快照 UTF-8-SIG CSV 落
    archive\\{模块}\\{日期}\\{任务ID}\\input\\ 后走与文件模式完全相同的核对流水线；
    黄金样本一致性验证：统计 16/14/1/1/2/1 与结果 Excel 逐格（值+色）一致
  - 前端 M1/M2 任务页取数模式切换：模板下拉按模块过滤并显示数据源名，
    提交前回显所选模板与 SQL 摘要
  - 任务调度中心（DS-F5）：APScheduler + SQLAlchemyJobStore 持久化到平台库
    （重启不丢）；定时任务 CRUD / 启停 / 立即执行 / 执行历史；
    db 模式到点按配置模板取数（biz_date=当日），file 模式执行时检查
    监测目录一次，未就绪标记"待文件"；失败自动重试 1 次（间隔可配）
  - 系统参数（sys_config，系统配置页维护）：data_ready_time=17:30 /
    buffer_minutes=30 / schedule_retry_delay_minutes=5
  - 统计看板（工作台，operator 及以上）：M1 差异趋势折线图（ECharts）、
    持续差异产品（recon_job_item 产品级明细，M1 成功时自动入库）、
    任务健康度卡片与最近定时执行
  - 新增测试门禁：取数模式冒烟 70 项、调度+看板冒烟 80 项、
    调度补测（file/M2）30 项；12 组门禁合计 710 项全绿

v0.4.0（2026-07-20）二期第二项：M2 基金估值价格核对
  - M2 核对引擎：系统端 新综合信息查询_基金证券 × 财务端 证券投资基金估值表，
    按科目取价规则提取估值表叶子明细，两步匹配（证券代码精确 → 证券名称模糊），
    差异判定 price_tol=0.0001；绿=一致 / 红=差异 / 橙=单边
  - 多产品批量：按文件名产品标识（4 位数字）自动配对，落单/重复/无标识
    400 中文指明；按产品分别出报告（底部汇总行 + 备注列），下载支持 ?product=
  - 系统配置页（admin）：科目取价规则 CRUD（科目前缀唯一、取价字段可自定义、
    口径提示语随规则带出、排序启停），预置 1101→市价 / 1501→单位成本；
    规则热生效（任务执行时现取，免重启），全部写操作审计留痕
  - 报告备注设计：1501 摊余成本口径提示随规则配置自动带出；
    888880 新标准券等已知正常单边说明为引擎常量
  - 新增测试门禁：M2 黄金回归 26 项（含 1501 取价金丝雀）、
    M2 API 冒烟 67 项（含配置热生效专项）；既有八门禁回归全绿

v0.3.0（2026-07-20）二期首项：数据源管理（数据库只读直连）
  - 数据源连接配置：Oracle / MariaDB / MySQL / SQL Server / PostgreSQL
    五类；密码 Fernet 加密存储（密钥由 data\\secret.key 派生），
    接口永不返回明文；测试连接中文友好报错
  - 查询模板：所属模块 + 关联数据源 + SQL + 字段映射 + 参数定义；
    预览执行返回前 50 行与执行保护留痕
  - 只读四道防线：数据库只读账号授权示例（部署手册第 9 章）/
    SQL 白名单（sqlparse 单条 SELECT/WITH，保存与执行双校验）/
    语句超时 60s + 最大返回 100 万行 + 只读事务模式 / 凭据加密 + 全量审计
  - 前端新增"数据源管理"菜单（连接配置 / 查询模板两页，admin）
  - 新增测试门禁：SQL Guard 单测 75 项、DbAdapter 集成 28 项、
    数据源 API 冒烟 76 项；既有五门禁回归全绿

v0.2.0（2026-07-17）一期前端上线
  - 新增 Web 前端（Vue 3 + Element Plus）：登录/首登改密、工作台、
    M1/M3 任务页（上传→进度日志→统计结果→下载）、报告归档中心、
    规则配置中心（映射/大宗/阈值 + 导入导出）、用户维护；
    前端由服务端 exe 直接托管（app\\web），浏览器访问即用
  - 服务端新增 SPA 静态托管（/api 与 /docs 不受影响）

v0.1.0（2026-07-17）一期首次打包
  - M1 基金资产与净值核对（上传两表 → 核对 → 下载标色结果）
  - M3 基金属性表银行间ID匹配（三件套：更新表/明细/说明）
  - 规则配置中心（映射/大宗/阈值增删改查、导入导出、审计留痕、热生效）
  - 本地认证与用户维护（admin/operator/viewer 三角色，首登强制改密）
  - 历史任务检索与结果下载；SQLite 内嵌库首启自动建库
  - 数据库驱动随包（二期直连预留）：oracledb thin / pymysql /
    psycopg2-binary / pymssql，均免安装
"""


def main() -> int:
    pkg_dir = Path(sys.argv[1])
    version = sys.argv[2]
    build_date = datetime.now().strftime("%Y-%m-%d")

    # ---- 版本.txt ----
    version_txt = f"""安联资管运维管理平台 部署包
==================================================
版本号:    v{version}
构建日期:  {build_date}
构建环境:  Windows + Python 3.12 + PyInstaller（onedir, console）
==================================================

目录说明
  app\\       服务端程序（o32-server.exe 及运行时依赖）
  data\\      平台数据（SQLite 平台库 + 密钥 + 字典库，首启自动建库）
  archive\\   核对归档（上传原件与结果文件）
  logs\\      运行日志（server.log）
  nssm\\      NSSM 服务化工具（可选；install.bat 无 NSSM 时回退计划任务）
  install.bat / uninstall.bat   注册/卸载开机自启（需管理员）
  start.bat / stop.bat          免服务前台启停（试运行用）
  upgrade.bat                   版本升级数据迁移（从旧版本目录迁入 data/archive/logs）

新装部署：解压后运行 start.bat 即可（data 首启自动建库）。
版本升级：解压新包到旧版同级目录 → 运行新包内 upgrade.bat 迁入旧数据
  （用户/规则/模板/数据源/历史任务/归档全保留，旧目录原样留作回滚备份）。
  切勿直接覆盖解压到旧目录，也切勿用新包 data 目录替换旧数据。
  首次启动服务端自动完成数据库结构升级。
默认端口 8000；初始管理员 admin / Admin@123（首登强制改密）。
详细步骤见《部署手册》（docs/03-手册/部署手册.md）。

变更摘要
{CHANGELOG}"""
    (pkg_dir / "版本.txt").write_text(version_txt, encoding="utf-8")

    # ---- 依赖清单.txt ----
    rows = []
    for dist in sorted(importlib.metadata.distributions(),
                       key=lambda d: (d.metadata["Name"] or "").lower()):
        name = dist.metadata["Name"]
        if not name:
            continue
        ver = dist.version
        lic = LICENSE_MAP.get(name.lower()) or (dist.metadata.get("License") or "见各库官方声明")
        rows.append(f"{name}=={ver}    {lic}")

    deps_txt = (
        "O32 日常运维平台 依赖清单（构建机 pip freeze 等效 + License 标注）\n"
        f"构建日期: {build_date}    版本: v{version}\n"
        "=" * 60 + "\n"
        "说明：License 类型依据各项目公开许可声明标注；"
        "LGPL 组件（psycopg2-binary/pymssql）以动态链接二进制形式随包，\n"
        "符合其随二进制分发条款；PyInstaller 自身 GPL 不传染被其打包的应用。\n"
        "=" * 60 + "\n"
        + "\n".join(rows)
        + "\n\n第三方工具：NSSM 2.24（Public Domain，见 nssm\\README.txt 含 SHA-256）\n"
    )
    (pkg_dir / "依赖清单.txt").write_text(deps_txt, encoding="utf-8")

    print(f"已生成: {pkg_dir / '版本.txt'}")
    print(f"已生成: {pkg_dir / '依赖清单.txt'}（{len(rows)} 项依赖）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
