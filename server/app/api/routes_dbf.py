# -*- coding: utf-8 -*-
"""
安联资管运维管理平台 —— DBF 数据查看接口（v0.7.0 起）

场景：
    O32 及周边系统（估值、TA、恒生老模块）常产出 dBase/FoxPro 格式的 .dbf
    文件，运维人员手头没有 FoxPro/dBase 工具时无法直接查看。本接口提供
    纯只读的 DBF 解析展示与 Excel 导出，绝不修改原文件。

接口：
    POST /api/dbf/preview   上传 .dbf → 字段结构 + 总记录数 + 前 N 行预览
    POST /api/dbf/export    上传 .dbf → 全量导出 xlsx（限 20 万行）

编码策略：
    国产金融系统 DBF 多为 GBK；按 gbk → utf-8 → latin1 顺序尝试，
    latin1 单字节编码保底永不失败（此时中文可能乱码，会如实标注）。

作者：技术部
版本：1.0.0
日期：2026-07-24
"""

import io
import logging
import os
import tempfile
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.deps import get_db, require_roles
from app.models.entities import SysUser
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

MENU_DBF = "DBF 数据查看"

router = APIRouter(prefix="/api/dbf", tags=["DBF 数据查看"])

_PREVIEW_ROWS = 2000        # 预览返回上限（前端分页展示）
_EXPORT_MAX_ROWS = 200000   # 导出行数安全上限
_MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
_ENCODINGS = ("gbk", "utf-8", "latin1")

# dBase/FoxPro 版本标识字节（文件头第 1 字节）
_DBF_MAGIC = {
    0x02, 0x03, 0x04,                     # FoxBASE / dBase III / dBase IV
    0x30, 0x31, 0x32,                     # Visual FoxPro（中登文件为 0x30）
    0x43, 0x63, 0x83, 0x8B, 0x8E, 0xCB,   # dBase IV/SQL 各变体
    0xF5, 0xFB,                           # FoxPro 2.x / FoxBASE（含备注）
}

_TYPE_NAMES = {
    "C": "字符", "N": "数值", "F": "浮点", "D": "日期", "L": "逻辑",
    "M": "备注", "I": "整型", "B": "双精度", "Y": "货币", "T": "日期时间",
}


def _sniff_dbf(path: str, filename: str) -> None:
    """
    按文件内容识别 dBase/FoxPro 格式（不看扩展名）：
    第 1 字节为版本标识 + 头部长度/记录长度字段自洽。不合法抛 400 中文。
    兼容中登等"内容是 DBF、扩展名按日期命名（如 .713）"的文件。
    """
    try:
        with open(path, "rb") as f:
            head = f.read(32)
    except OSError as e:
        raise HTTPException(status_code=400, detail=f"文件读取失败: {e}")
    if len(head) < 32:
        raise HTTPException(status_code=400, detail=f"文件过小（{len(head)} 字节），不是合法的 DBF 文件: {filename}")
    import struct
    version = head[0]
    header_len = struct.unpack("<H", head[8:10])[0]
    record_len = struct.unpack("<H", head[10:12])[0]
    # 头部自洽：dBase 系列 (header_len-33) 应整除 32（字段描述块）；
    # Visual FoxPro（0x30-0x32）字段块后另有 263 字节库回链结构，需扣除后校验
    base = header_len - 33
    is_vfp = version in (0x30, 0x31, 0x32)
    struct_ok = header_len >= 33 and record_len >= 1 and (
        base % 32 == 0 or (is_vfp and base >= 263 and (base - 263) % 32 == 0)
    )
    if version not in _DBF_MAGIC or not struct_ok:
        raise HTTPException(
            status_code=400,
            detail=f"文件内容不是可识别的 dBase/FoxPro（DBF）格式: {filename}"
                   f"（首字节 0x{version:02X}，平台按内容识别而非扩展名）",
        )


def _client_ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


async def _save_upload(file: UploadFile) -> str:
    """流式落盘到临时文件，返回路径（dbfread 需要文件路径/二进制流）"""
    suffix = ".dbf"
    fd, path = tempfile.mkstemp(prefix="o32dbf_", suffix=suffix)
    total = 0
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = await file.read(4 * 1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_FILE_SIZE:
                    out.close()
                    os.unlink(path)
                    raise HTTPException(status_code=400, detail="DBF 文件超过 100MB 上限")
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        try:
            os.unlink(path)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"文件接收失败: {e}")
    if total == 0:
        os.unlink(path)
        raise HTTPException(status_code=400, detail="上传文件为空")
    return path


def _open_with_fallback(path: str):
    """按编码候选顺序打开 DBF，返回 (table, encoding_used, garbled_warn)"""
    from dbfread import DBF

    last_err: Optional[Exception] = None
    for enc in _ENCODINGS:
        try:
            table = DBF(path, encoding=enc, char_decode_errors="strict",
                        ignore_missing_memofile=True)
            # 强制触发一次全字段解码验证（取首行即可发现编码问题）
            for _ in table:
                break
            return DBF(path, encoding=enc, char_decode_errors="strict",
                       ignore_missing_memofile=True), enc, enc == "latin1"
        except UnicodeDecodeError as e:
            last_err = e
            continue
        except Exception as e:  # noqa: BLE001
            # 结构性错误（非 DBF 文件等）不做编码回退，直接报错
            raise HTTPException(status_code=400, detail=f"DBF 解析失败（文件可能不是合法的 dBase/FoxPro 格式）: {e}")
    raise HTTPException(status_code=400, detail=f"DBF 字符解码失败: {last_err}")


def _cell(v):
    """单元格值 JSON 化"""
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, bytes):
        return v.hex()
    return v


@router.post("/preview", summary="DBF 文件预览（字段结构 + 前 2000 行）")
async def preview(
    request: Request,
    file: UploadFile = File(...),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    filename = file.filename or ""
    path = await _save_upload(file)
    try:
        _sniff_dbf(path, filename)
        table, encoding, garbled = _open_with_fallback(path)
        fields = [
            {
                "name": f.name,
                "type": f.type,
                "type_name": _TYPE_NAMES.get(f.type, f.type),
                "length": f.length,
                "decimal": getattr(f, "decimal_count", 0),
            }
            for f in table.fields
        ]
        rows = []
        total = 0
        for rec in table:
            total += 1
            if total <= _PREVIEW_ROWS:
                rows.append({k: _cell(v) for k, v in rec.items()})
        truncated = total > _PREVIEW_ROWS

        record_audit(
            db, user.username, "dbf_view", "dbf_file", None,
            f"查看 DBF 文件 {filename}：{len(fields)} 字段 / {total} 行（编码 {encoding}）",
            _client_ip(request), menu=MENU_DBF,
        )
        db.commit()

        # 中登接口字段说明匹配（按文件名前缀，内置官方规范库）
        from app.services.clearing_spec_service import match_interface
        spec = match_interface(filename)
        spec_out = None
        if spec is not None:
            spec_fields = {}
            for f in fields:
                sf = spec["fields"].get(f["name"])
                if sf is not None:
                    spec_fields[f["name"]] = {"desc": sf.get("desc", "")}
            spec_out = {
                "code": spec["code"],
                "name": spec["name"],
                "spec_name": spec["spec_name"],
                "file_pattern": spec["file_pattern"],
                "market": spec["market"],
                "fields": spec_fields,
                "matched_fields": len(spec_fields),
                "total_spec_fields": len(spec["fields"]),
            }

        return {
            "filename": filename,
            "encoding": encoding,
            "garbled_warning": garbled,
            "field_count": len(fields),
            "total_rows": total,
            "preview_rows": len(rows),
            "truncated": truncated,
            "fields": fields,
            "rows": rows,
            "spec": spec_out,
        }
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@router.post("/export", summary="DBF 全量导出 Excel（限 20 万行）")
async def export(
    request: Request,
    file: UploadFile = File(...),
    user: SysUser = Depends(require_roles("admin", "operator")),
    db: Session = Depends(get_db),
):
    filename = file.filename or ""
    path = await _save_upload(file)
    try:
        _sniff_dbf(path, filename)
        table, encoding, garbled = _open_with_fallback(path)

        import openpyxl
        wb = openpyxl.Workbook(write_only=True)
        ws = wb.create_sheet("DBF数据")
        headers = [f.name for f in table.fields]
        ws.append(headers)
        total = 0
        for rec in table:
            total += 1
            if total > _EXPORT_MAX_ROWS:
                break
            ws.append([_cell(rec.get(h)) for h in headers])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        record_audit(
            db, user.username, "dbf_export", "dbf_file", None,
            f"导出 DBF 文件 {filename} 为 Excel：{total} 行（编码 {encoding}"
            + ("，超 20 万行已截断" if total > _EXPORT_MAX_ROWS else "") + "）",
            _client_ip(request), menu=MENU_DBF,
        )
        db.commit()

        out_name = os.path.splitext(os.path.basename(filename))[0] + ".xlsx"
        from urllib.parse import quote
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=\"export.xlsx\"; filename*=UTF-8''{quote(out_name)}"
            },
        )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
