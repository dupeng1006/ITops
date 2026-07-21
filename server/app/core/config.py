# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 集中配置

配置来源（优先级从高到低）：
    1. 环境变量（O32OPS_*）
    2. server/.env 文件（KEY=VALUE 逐行，# 开头为注释）
    3. 代码内默认值

安全要求：
    - JWT 密钥（O32OPS_SECRET_KEY）必须来自环境变量或 .env，不入库、不入仓；
    - 未配置时启动期随机生成并告警（重启后历史 token 失效），生产环境必须配置固定密钥；
    - .env 不入版本库（已加入 .gitignore），参考 .env.example。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import logging
import os
import secrets
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# server/app/core/config.py → parents[2] = server/
SERVER_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SERVER_ROOT.parent
ENV_FILE = SERVER_ROOT / ".env"

# 规则配置 JSON（一期初始数据来源，导入规则库后仅作兼容备份）
RULE_CONFIG_JSON = SERVER_ROOT / "config" / "rule_config.json"


def _load_env_file(path: Path) -> dict:
    """解析 .env 文件（KEY=VALUE，忽略注释与空行）"""
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


class Settings:
    """平台集中配置（实例化时从环境变量/.env 读取一次）"""

    def __init__(self) -> None:
        file_env = _load_env_file(ENV_FILE)

        def get(key: str, default: Optional[str] = None) -> Optional[str]:
            return os.environ.get(key) or file_env.get(key) or default

        # 目录
        self.DATA_DIR = Path(get("O32OPS_DATA_DIR", str(SERVER_ROOT / "data")))
        self.ARCHIVE_DIR = Path(get("O32OPS_ARCHIVE_DIR", str(SERVER_ROOT / "archive")))
        self.DB_PATH = Path(get("O32OPS_DB_PATH", str(self.DATA_DIR / "o32ops.db")))
        # 数据字典库（独立 SQLite，与平台库分离；PDM 文件不进部署包，字典库随包交付）
        self.DICT_DB_PATH = Path(get("O32OPS_DICT_DB_PATH", str(self.DATA_DIR / "dictionary.db")))

        # JWT
        secret = get("O32OPS_SECRET_KEY")
        if secret:
            self.SECRET_KEY = secret
            self._secret_random = False
        else:
            self.SECRET_KEY = secrets.token_hex(32)
            self._secret_random = True
        self.JWT_ALGORITHM = "HS256"
        self.JWT_EXPIRE_HOURS = int(get("O32OPS_JWT_EXPIRE_HOURS", "8"))

        # 上传
        self.MAX_UPLOAD_SIZE = int(get("O32OPS_MAX_UPLOAD_SIZE", str(50 * 1024 * 1024)))  # 50MB

        # 初始管理员（仅首次建库时生效）
        self.INITIAL_ADMIN_USERNAME = get("O32OPS_INITIAL_ADMIN", "admin")
        self.INITIAL_ADMIN_PASSWORD = get("O32OPS_INITIAL_ADMIN_PASSWORD", "Admin@123")

        # 数据源直连（二期）：执行保护默认值
        self.DS_QUERY_TIMEOUT = int(get("O32OPS_DS_QUERY_TIMEOUT", "60"))      # 语句超时(秒)
        self.DS_MAX_ROWS = int(get("O32OPS_DS_MAX_ROWS", "1000000"))           # 最大返回行数
        self.DS_PREVIEW_ROWS = int(get("O32OPS_DS_PREVIEW_ROWS", "50"))        # 模板预览行数

    @property
    def secret_is_random(self) -> bool:
        return self._secret_random

    def ensure_dirs(self) -> None:
        """确保数据与归档目录存在"""
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置实例（惰性初始化，进程内缓存）"""
    global _settings
    if _settings is None:
        _settings = Settings()
        if _settings.secret_is_random:
            logger.warning(
                "未配置 O32OPS_SECRET_KEY，已随机生成临时密钥；"
                "重启后历史登录态将失效，生产环境请在 server/.env 或环境变量中配置固定密钥"
            )
    return _settings


def reset_settings() -> None:
    """重置配置缓存（测试用）"""
    global _settings
    _settings = None
