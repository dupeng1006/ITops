# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 可执行程序启动器（PyInstaller 入口）

职责：
    1. 解析部署根目录（exe 位于 <部署根>\\app\\o32-server.exe，数据/归档/日志
       默认落在部署根下，与程序目录分离，升级只替换 app\\）；
    2. 准备运行目录（data / archive / logs）与持久化 JWT 密钥
       （data\\secret.key 首启自动生成，避免重启后登录态失效）；
    3. 解析命令行（--host/--port，环境变量 O32OPS_HOST/O32OPS_PORT 亦可覆盖）；
    4. 打印中文启动横幅（服务地址、默认账号提示、数据目录位置）；
    5. 以 console 模式启动 uvicorn（控制台 + logs\\server.log 双输出）。

源码运行（等价于 uvicorn app.main:app，工作目录 server/）：
    .venv\\Scripts\\python.exe app\\launcher.py --port 8000

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import argparse
import logging
import os
import secrets
import sys
from pathlib import Path

IS_FROZEN = getattr(sys, "frozen", False)


def _deploy_root() -> Path:
    """部署根目录：冻结态取 exe 上一级（app\\）的上一级；源码态取 server/"""
    if IS_FROZEN:
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parents[1]


def _ensure_secret_key(data_dir: Path) -> None:
    """
    确保持久化 JWT 密钥存在于环境变量：

    - 已配置 O32OPS_SECRET_KEY（环境变量）则直接沿用；
    - 否则读取/生成 data\\secret.key（首启自动生成，仅本机留存，不入版本库）。
    """
    if os.environ.get("O32OPS_SECRET_KEY"):
        return
    key_file = data_dir / "secret.key"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
    else:
        key = secrets.token_hex(32)
        data_dir.mkdir(parents=True, exist_ok=True)
        key_file.write_text(key, encoding="utf-8")
    os.environ["O32OPS_SECRET_KEY"] = key


def _print_banner(host: str, port: int, data_dir: Path, archive_dir: Path, logs_dir: Path) -> None:
    show_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    print("=" * 64)
    print("  安联资管运维管理平台服务端（M1+M2+M3+数据字典）")
    print("=" * 64)
    print(f"  服务地址:   http://{show_host}:{port}")
    print(f"  接口文档:   http://{show_host}:{port}/docs")
    print(f"  健康检查:   http://{show_host}:{port}/api/health")
    print(f"  数据目录:   {data_dir}")
    print(f"  归档目录:   {archive_dir}")
    print(f"  日志文件:   {logs_dir / 'server.log'}")
    print("-" * 64)
    print("  初始管理员: admin / Admin@123（首次登录强制修改密码）")
    print("  按 Ctrl+C 停止服务")
    print("=" * 64)


def main() -> None:
    # Windows 控制台中文输出兼容
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    deploy_root = _deploy_root()
    data_dir = Path(os.environ.get("O32OPS_DATA_DIR", str(deploy_root / "data")))
    archive_dir = Path(os.environ.get("O32OPS_ARCHIVE_DIR", str(deploy_root / "archive")))
    logs_dir = Path(os.environ.get("O32OPS_LOGS_DIR", str(deploy_root / "logs")))
    for d in (data_dir, archive_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 注入集中配置（环境变量已显式设置者优先）
    os.environ.setdefault("O32OPS_DATA_DIR", str(data_dir))
    os.environ.setdefault("O32OPS_ARCHIVE_DIR", str(archive_dir))
    os.environ.setdefault("O32OPS_DB_PATH", str(data_dir / "o32ops.db"))
    _ensure_secret_key(data_dir)

    parser = argparse.ArgumentParser(description="安联资管运维管理平台服务端")
    parser.add_argument("--host", default=os.environ.get("O32OPS_HOST", "0.0.0.0"),
                        help="监听地址（默认 0.0.0.0）")
    parser.add_argument("--port", type=int,
                        default=int(os.environ.get("O32OPS_PORT", "8000")),
                        help="监听端口（默认 8000）")
    args = parser.parse_args()

    if not IS_FROZEN:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from app.main import app  # noqa: E402  须在环境变量注入之后导入

    # 追加文件日志（控制台 + logs/server.log 双输出）
    file_handler = logging.FileHandler(logs_dir / "server.log", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s")
    )
    logging.getLogger().addHandler(file_handler)

    _print_banner(args.host, args.port, data_dir, archive_dir, logs_dir)

    import uvicorn  # noqa: E402
    uvicorn.run(app, host=args.host, port=args.port, ws="none", log_level="info")


if __name__ == "__main__":
    main()
