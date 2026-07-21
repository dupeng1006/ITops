# -*- coding: utf-8 -*-
"""
OpenAPI 接口契约导出脚本

用法（工作目录 server/，使用项目虚拟环境）：
    .venv\\Scripts\\python.exe scripts\\export_openapi.py

输出：docs/02-方案/接口契约_openapi.json
说明：仅实例化 FastAPI app 导出契约，不触发数据库初始化。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import json
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SERVER_ROOT.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.main import app  # noqa: E402

OUTPUT_PATH = PROJECT_ROOT / "docs" / "02-方案" / "接口契约_openapi.json"


def main() -> int:
    spec = app.openapi()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    paths = sorted(spec.get("paths", {}).keys())
    print(f"OpenAPI 契约已导出: {OUTPUT_PATH}")
    print(f"接口数: {len(paths)}")
    for p in paths:
        print(f"  {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
