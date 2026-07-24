# -*- mode: python ; coding: utf-8 -*-
"""
O32 日常运维平台 —— PyInstaller 构建脚本（onedir / console）

构建（工作目录 server/）：
    .venv\\Scripts\\python.exe -m PyInstaller --noconfirm --clean packaging\\build.spec

产物：server\\dist\\o32-server\\（o32-server.exe + _internal 依赖目录）

说明：
    - 入口 app/launcher.py（解析部署根、准备数据目录与密钥、启动 uvicorn）；
    - datas 仅打包 config/rule_config.json（规则初始种子），
      data/archive/logs 为运行时目录，不随包；
    - hidden imports 覆盖 uvicorn 动态加载、python-multipart（FastAPI 上传）、
      pandas/openpyxl/xlrd 等；数据库驱动（二期用）用 collect_all 全量收集，
      提前验证免安装可行性（oracledb thin / pymysql 纯 Python /
      psycopg2-binary 自带 libpq / pymssql 自带 FreeTDS）；
    - excludes 剔除测试期依赖（httpx/pytest 等）与无关大库。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

from PyInstaller.utils.hooks import collect_all

import os

# 路径基准：spec 文件位于 server/packaging/，SPECPATH 为其绝对路径
SERVER_ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

block_cipher = None

# 规则初始种子（首启建库时导入 rule_code_mapping / rule_bulk_product / rule_threshold）
datas = [
    (os.path.join(SERVER_ROOT, 'config', 'rule_config.json'), 'config'),
    # 中登接口字段说明内置库（v0.7.2，DBF 查看表头说明）
    (os.path.join(SERVER_ROOT, 'config', 'clearing_spec'), 'config/clearing_spec'),
]
binaries = []
hiddenimports = [
    # uvicorn 动态加载项
    'uvicorn.logging',
    'uvicorn.loops.auto',
    'uvicorn.loops.asyncio',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan.on',
    'uvicorn.lifespan.off',
    # FastAPI 文件上传（python-multipart，import 名为 multipart）
    'multipart',
    # Excel 读写
    'openpyxl',
    'xlrd',
    'et_xmlfile',
    # 认证与安全
    'bcrypt',
    'jwt',
    'cryptography',
    # 平台库
    'sqlalchemy',
    'greenlet',
    'sqlparse',
    # DBF 数据查看（v0.7.0，纯 Python dBase/FoxPro 解析）
    'dbfread',
]

# 数据库驱动（二期数据源直连用，本步随包验证免安装可行性）
for pkg in ('oracledb', 'pymysql', 'pymssql', 'psycopg2'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# APScheduler（任务调度中心）：jobstores/triggers/executors 字符串引用动态加载，全量收集
_d, _b, _h = collect_all('apscheduler')
datas += _d
binaries += _b
hiddenimports += _h

a = Analysis(
    [os.path.join(SERVER_ROOT, 'app', 'launcher.py')],
    pathex=[SERVER_ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 测试期依赖（运行时不使用）
        'httpx', 'httpcore', 'pytest', 'pip',
        # 无关大库（减小体积）
        'tkinter', 'matplotlib', 'scipy', 'IPython', 'jupyter', 'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='o32-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # 不用 UPX，避免杀毒软件误报
    console=True,       # console 模式：中文启动日志直接可见
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='o32-server',
)
