# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— API 请求/响应模型（Pydantic）

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# =============================================================================
# 认证
# =============================================================================

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50, description="用户编号")
    password: str = Field(..., min_length=1, max_length=128, description="密码")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = Field(..., description="是否首次登录需强制改密")
    username: str
    role: str
    display_name: Optional[str] = Field(None, description="用户姓名（未设置为空）")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=128, description="原密码")
    new_password: str = Field(..., min_length=8, max_length=72, description="新密码（至少8位）")


# =============================================================================
# 用户维护
# =============================================================================

class UserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="用户编号（登录用）")
    password: str = Field(..., min_length=8, max_length=72, description="初始密码（至少8位，首次登录需修改）")
    role: str = Field(..., pattern="^(admin|operator|viewer)$", description="角色: admin/operator/viewer")
    display_name: Optional[str] = Field(None, max_length=100, description="用户姓名（选填）")
    department: Optional[str] = Field(None, max_length=100, description="部门（选填）")


class UserUpdateRequest(BaseModel):
    role: Optional[str] = Field(None, pattern="^(admin|operator|viewer)$", description="角色")
    status: Optional[str] = Field(None, pattern="^(active|disabled)$", description="状态")
    display_name: Optional[str] = Field(None, max_length=100, description="用户姓名（传空字符串清空）")
    department: Optional[str] = Field(None, max_length=100, description="部门（传空字符串清空）")


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=72, description="新密码（至少8位）")


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    department: Optional[str] = None
    role: str
    status: str
    source: str
    must_change_password: bool
    created_at: str
    updated_at: str


# =============================================================================
# 核对任务
# =============================================================================

class JobCreateResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobInfo(BaseModel):
    job_id: str
    module: str
    biz_date: str
    fetch_mode: str
    status: str
    trigger_type: str
    progress: int
    stats: Optional[dict] = None
    error: Optional[str] = None
    result_filename: Optional[str] = None
    created_by: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class JobDetailResponse(JobInfo):
    log_tail: List[str] = Field(default_factory=list, description="运行日志末尾N行")
    result_files: List[str] = Field(default_factory=list, description="结果文件清单（如 M3 三件套）")


class JobListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[JobInfo]


# =============================================================================
# 规则配置中心
# =============================================================================

class MappingInfo(BaseModel):
    id: int
    source_code: str
    target_code: str
    enabled: bool
    updated_by: Optional[str] = None
    updated_at: str


class MappingCreateRequest(BaseModel):
    source_code: str = Field(..., min_length=1, max_length=50, description="原代码（净值查询表侧）")
    target_code: str = Field(..., min_length=1, max_length=50, description="映射后代码（基金资产表侧）")
    enabled: bool = Field(True, description="是否启用")


class MappingUpdateRequest(BaseModel):
    source_code: Optional[str] = Field(None, min_length=1, max_length=50, description="原代码")
    target_code: Optional[str] = Field(None, min_length=1, max_length=50, description="映射后代码")
    enabled: Optional[bool] = Field(None, description="是否启用")


class BulkProductInfo(BaseModel):
    id: int
    product_code: str
    note: Optional[str] = Field(None, description="差异说明（M1 结果'差异原因'列；空=默认文案）")
    color: str = Field("FFC000", description="行填充色(6位HEX，不含#)")
    enabled: bool
    updated_by: Optional[str] = None
    updated_at: str


class BulkProductCreateRequest(BaseModel):
    product_code: str = Field(..., min_length=1, max_length=50, description="特殊产品代码")
    note: Optional[str] = Field(None, max_length=200, description="差异说明（空=默认文案）")
    color: Optional[str] = Field(None, description="行填充色(6位HEX，不含#)，缺省 FFC000")
    enabled: bool = Field(True, description="是否启用")


class BulkProductUpdateRequest(BaseModel):
    product_code: Optional[str] = Field(None, min_length=1, max_length=50, description="特殊产品代码")
    note: Optional[str] = Field(None, max_length=200, description="差异说明（传空字符串清空）")
    color: Optional[str] = Field(None, description="行填充色(6位HEX，不含#)")
    enabled: Optional[bool] = Field(None, description="是否启用")


class ThresholdInfo(BaseModel):
    param_key: str
    param_value: str
    description: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: str


class ThresholdUpdateRequest(BaseModel):
    value: float = Field(..., description="阈值数值（合法范围随参数键而定，详见接口文档）")


class SpecialProductItem(BaseModel):
    """特殊产品条目（导入导出 JSON 新格式）"""
    code: str = Field(..., min_length=1, max_length=50, description="产品代码")
    note: Optional[str] = Field(None, max_length=200, description="差异说明（空=默认文案）")
    color: Optional[str] = Field(None, description="行填充色(6位HEX，不含#)，缺省 FFC000")


class RuleImportRequest(BaseModel):
    """规则配置导入体（兼容新旧格式：special_products 优先，缺省回退 bulk_products）"""
    rename_map: Dict[str, str] = Field(..., description="信托计划代码映射（整体替换）")
    bulk_products: Optional[List[str]] = Field(None, description="特殊产品代码清单（旧格式，整体替换）")
    special_products: Optional[List[SpecialProductItem]] = Field(None, description="特殊产品对象数组（新格式，优先采用）")
    diff_threshold: Optional[float] = Field(None, description="差异阈值(%)，提供时同步更新 diff_pct")
    similarity_threshold: Optional[float] = Field(None, description="模糊匹配相似度阈值，提供时同步更新 fuzzy_sim")


class RuleImportResponse(BaseModel):
    message: str
    mappings_before: int
    mappings_after: int
    bulk_before: int
    bulk_after: int
    thresholds_updated: List[str] = Field(default_factory=list, description="本次同步更新的阈值键")


# =============================================================================
# 数据源管理（二期）
# =============================================================================

class DatasourceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="数据源名称（唯一）")
    db_type: str = Field(..., description="类型: oracle/mariadb/mysql/mssql/postgresql")
    host: Optional[str] = Field(None, max_length=200, description="主机")
    port: Optional[int] = Field(None, ge=1, le=65535, description="端口（缺省按类型取默认）")
    db_name: Optional[str] = Field(None, max_length=100, description="库名（Oracle 以外必填）")
    service_name: Optional[str] = Field(None, max_length=100, description="Oracle 服务名（与 SID 二选一）")
    sid: Optional[str] = Field(None, max_length=100, description="Oracle SID（与服务名二选一）")
    username: str = Field(..., min_length=1, max_length=100, description="账号")
    password: str = Field(..., min_length=1, max_length=200, description="密码（服务端加密存储）")
    extra: Optional[Dict[str, str]] = Field(None, description="连接参数 JSON（预留）")
    enabled: bool = Field(True, description="是否启用")


class DatasourceUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="数据源名称")
    db_type: Optional[str] = Field(None, description="类型")
    host: Optional[str] = Field(None, max_length=200, description="主机")
    port: Optional[int] = Field(None, ge=1, le=65535, description="端口")
    db_name: Optional[str] = Field(None, max_length=100, description="库名")
    service_name: Optional[str] = Field(None, max_length=100, description="Oracle 服务名")
    sid: Optional[str] = Field(None, max_length=100, description="Oracle SID")
    username: Optional[str] = Field(None, min_length=1, max_length=100, description="账号")
    password: Optional[str] = Field(None, max_length=200,
                                    description="密码；留空/null 表示不修改")
    extra: Optional[Dict[str, str]] = Field(None, description="连接参数 JSON（预留）")
    enabled: Optional[bool] = Field(None, description="是否启用")


class DatasourceInfo(BaseModel):
    """数据源视图（永不包含密码明文，password 恒为掩码）"""
    id: int
    name: str
    db_type: str
    host: Optional[str] = None
    port: Optional[int] = None
    db_name: Optional[str] = None
    service_name: Optional[str] = None
    sid: Optional[str] = None
    username: str
    password: str = Field(..., description="密码掩码（恒定 ********，无明文）")
    extra: Optional[Dict[str, str]] = None
    enabled: bool
    updated_by: Optional[str] = None
    updated_at: str


class TestConnectionResponse(BaseModel):
    success: bool
    message: str
    elapsed_ms: Optional[int] = None


class QueryTemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="模板名称（唯一）")
    module: str = Field(..., min_length=1, max_length=30,
                        description="所属模块: m1_fund/m1_netvalue/m2_system/m2_valuation/m3_member 等")
    ds_id: int = Field(..., description="数据源 ID")
    sql_text: str = Field(..., min_length=1, description="查询 SQL（仅单条 SELECT/WITH）")
    column_map: Optional[Dict[str, str]] = Field(None, description="结果列→标准逻辑字段映射")
    params_def: Optional[Dict[str, dict]] = Field(None, description="参数定义（如 biz_date）")
    enabled: bool = Field(True, description="是否启用")


class QueryTemplateUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="模板名称")
    module: Optional[str] = Field(None, min_length=1, max_length=30, description="所属模块")
    ds_id: Optional[int] = Field(None, description="数据源 ID")
    sql_text: Optional[str] = Field(None, min_length=1, description="查询 SQL（仅单条 SELECT/WITH）")
    column_map: Optional[Dict[str, str]] = Field(None, description="结果列→标准逻辑字段映射")
    params_def: Optional[Dict[str, dict]] = Field(None, description="参数定义")
    enabled: Optional[bool] = Field(None, description="是否启用")


class QueryTemplateInfo(BaseModel):
    id: int
    name: str
    module: str
    ds_id: int
    ds_name: Optional[str] = None
    sql_text: str
    column_map: Optional[Dict[str, str]] = None
    params_def: Optional[Dict[str, dict]] = None
    enabled: bool
    updated_by: Optional[str] = None
    updated_at: str


class TemplatePreviewRequest(BaseModel):
    params: Dict[str, str] = Field(default_factory=dict, description="模板参数值（如 biz_date）")


class TemplatePreviewResponse(BaseModel):
    columns: List[str]
    rows: List[dict]
    rows_returned: int = Field(..., description="本次返回行数（预览截断后）")
    elapsed_ms: int
    protections: List[str] = Field(default_factory=list, description="实际生效的执行保护")


# =============================================================================
# 系统配置（二期 M2：科目取价规则）
# =============================================================================

class SubjectPriceRuleInfo(BaseModel):
    id: int
    subject_prefix: str
    price_field: str
    description: Optional[str] = None
    note: Optional[str] = None
    enabled: bool
    sort_order: int
    updated_by: Optional[str] = None
    updated_at: str


class SubjectPriceRuleCreateRequest(BaseModel):
    subject_prefix: str = Field(..., min_length=1, max_length=20, description="科目前缀（如 1101/1501）")
    price_field: str = Field(..., min_length=1, max_length=50, description="取价字段（估值表列名，如 市价/单位成本）")
    description: Optional[str] = Field(None, max_length=100, description="科目说明（如 交易性金融资产）")
    note: Optional[str] = Field(None, max_length=200, description="口径提示语（报告备注用，可空）")
    enabled: bool = Field(True, description="是否启用")
    sort_order: int = Field(0, ge=0, le=9999, description="排序号（小者先提取）")


class SubjectPriceRuleUpdateRequest(BaseModel):
    subject_prefix: Optional[str] = Field(None, min_length=1, max_length=20, description="科目前缀")
    price_field: Optional[str] = Field(None, min_length=1, max_length=50, description="取价字段")
    description: Optional[str] = Field(None, max_length=100, description="科目说明")
    note: Optional[str] = Field(None, max_length=200, description="口径提示语")
    enabled: Optional[bool] = Field(None, description="是否启用")
    sort_order: Optional[int] = Field(None, ge=0, le=9999, description="排序号")


# =============================================================================
# 任务调度中心（二期 DS-F5）
# =============================================================================

class ScheduleJobCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="任务名称")
    module: str = Field(..., description="模块: m1/m2")
    fetch_mode: str = Field("file", description="取数模式: file/db")
    fund_template_id: Optional[int] = Field(None, description="M1 db：基金资产查询模板ID")
    netvalue_template_id: Optional[int] = Field(None, description="M1 db：净值查询模板ID")
    groups_json: Optional[str] = Field(None, description="M2 db：模板分组JSON")
    file_dir: Optional[str] = Field(None, max_length=500, description="file 模式：文件就绪监测目录")
    cron_expr: str = Field(..., min_length=1, max_length=100,
                           description="cron 表达式（5 段：分 时 日 月 周，如 7 18 * * 1-5）")
    enabled: bool = Field(True, description="是否启用")


class ScheduleJobUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="任务名称")
    module: Optional[str] = Field(None, description="模块: m1/m2")
    fetch_mode: Optional[str] = Field(None, description="取数模式: file/db")
    fund_template_id: Optional[int] = Field(None, description="M1 db：基金资产查询模板ID")
    netvalue_template_id: Optional[int] = Field(None, description="M1 db：净值查询模板ID")
    groups_json: Optional[str] = Field(None, description="M2 db：模板分组JSON")
    file_dir: Optional[str] = Field(None, max_length=500, description="file 模式：文件就绪监测目录")
    cron_expr: Optional[str] = Field(None, min_length=1, max_length=100, description="cron 表达式")
    enabled: Optional[bool] = Field(None, description="是否启用")


class ScheduleJobInfo(BaseModel):
    id: int
    name: str
    module: str
    fetch_mode: str
    fund_template_id: Optional[int] = None
    netvalue_template_id: Optional[int] = None
    groups_json: Optional[str] = None
    file_dir: Optional[str] = None
    cron_expr: str
    enabled: bool
    last_run_at: Optional[str] = None
    last_status: Optional[str] = None
    last_job_id: Optional[str] = None
    last_error: Optional[str] = None
    created_by: str
    created_at: str


class ScheduleExecutionInfo(BaseModel):
    """定时执行历史（复用 recon_job，trigger_type=schedule）"""
    job_id: str
    module: str
    biz_date: str
    fetch_mode: str
    status: str
    stats: Optional[dict] = None
    error: Optional[str] = None
    created_by: str
    created_at: str
    finished_at: Optional[str] = None


# =============================================================================
# 系统参数（data_ready_time / buffer_minutes 等）
# =============================================================================

class SystemParamInfo(BaseModel):
    param_key: str
    param_value: str
    description: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: str


class SystemParamsUpdateRequest(BaseModel):
    values: Dict[str, str] = Field(..., description="参数键值对（仅允许已登记的系统参数键）")


# =============================================================================
# 统计看板（二期 DS-F5）
# =============================================================================

class DiffTrendPoint(BaseModel):
    biz_date: str
    total: int = 0
    exact: int = 0
    fuzzy: int = 0
    unmatched: int = 0
    bulk: int = 0
    diff: int = 0


class DiffTrendResponse(BaseModel):
    days: int
    points: List[DiffTrendPoint]


class PersistentDiffItem(BaseModel):
    product_code: str
    product_name: Optional[str] = None
    times: int
    last_diff_pct: Optional[float] = None
    max_diff_pct: Optional[float] = None


class PersistentDiffResponse(BaseModel):
    days: int
    min_times: int
    threshold_pct: float
    items: List[PersistentDiffItem]


class DashboardHealthResponse(BaseModel):
    schedule_total: int
    schedule_enabled: int
    last30d: Dict[str, int] = Field(default_factory=dict,
                                    description="近 30 天 scheduled 任务按状态计数（success/failed/wait_file 等）")
    recent: List[ScheduleExecutionInfo] = Field(default_factory=list, description="最近 10 次定时执行")
    data_ready_time: str
    buffer_minutes: str


# =============================================================================
# 数据字典查询（三期）
# =============================================================================

class DictModelInfo(BaseModel):
    id: int
    file_name: str
    model_name: str
    biz_group: str
    table_count: int
    column_count: int
    imported_at: str


class DictMatchedColumn(BaseModel):
    col_code: str
    col_name: Optional[str] = None


class DictTableItem(BaseModel):
    id: int
    model_id: int
    table_code: str
    table_name: Optional[str] = None
    biz_group: str
    file_name: str
    matched_on: List[str] = Field(default_factory=list,
                                  description="命中点: table_code/table_name/column")
    matched_columns: List[DictMatchedColumn] = Field(default_factory=list)
    is_favorite: bool = Field(False, description="当前用户是否收藏")


class DictTableSearchResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[DictTableItem]


class DictColumnInfo(BaseModel):
    id: int
    col_code: str
    col_name: Optional[str] = None
    data_type: Optional[str] = None
    is_pk: int
    seq: int
    comment: Optional[str] = None


class DictTableDetail(BaseModel):
    id: int
    model_id: int
    table_code: str
    table_name: Optional[str] = None
    comment: Optional[str] = None
    biz_group: str
    file_name: str
    model_name: str
    columns: List[DictColumnInfo]


class DictReferenceItem(BaseModel):
    id: int
    ref_name: Optional[str] = None
    other_id: int
    other_code: str
    other_name: Optional[str] = None
    other_biz_group: str
    joins: List[Dict[str, str]]


class DictTableReferencesResponse(BaseModel):
    as_parent: List[DictReferenceItem] = Field(default_factory=list,
                                               description="本表为父表（被引用的子表列表）")
    as_child: List[DictReferenceItem] = Field(default_factory=list,
                                              description="本表为子表（引用的父表列表）")


class GenSqlTableSpec(BaseModel):
    table_id: int = Field(..., description="字典表 ID")
    columns: List[str] = Field(default_factory=list,
                               description="勾选字段代码（空 = 全部字段）")
    alias: Optional[str] = Field(None, max_length=20, description="表别名（默认 t1..tn）")


class GenSqlCondition(BaseModel):
    table_alias: str = Field(..., description="表别名")
    column: str = Field(..., description="字段代码")
    op: str = Field(..., description="运算符: =,!=,>,>=,<,<=,LIKE,IN,BETWEEN,IS NULL,IS NOT NULL")
    value: Optional[Any] = Field(None, description="条件值（IN 逗号分隔，BETWEEN 两个值）")


class GenSqlRequest(BaseModel):
    tables: List[GenSqlTableSpec] = Field(..., min_length=1, max_length=10)
    conditions: List[GenSqlCondition] = Field(default_factory=list)
    limit: int = Field(500, ge=1, le=100000, description="ROWNUM 行数限制")
    use_rownum: bool = Field(True, description="是否附加 ROWNUM 限制")


class GenSqlResponse(BaseModel):
    sql: str
    joins: List[str] = Field(default_factory=list, description="自动 JOIN 说明")
    warnings: List[str] = Field(default_factory=list, description="无关联等警告")


class DictSaveTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="模板名称（唯一）")
    ds_id: int = Field(..., description="数据源 ID")
    sql_text: str = Field(..., min_length=1, description="生成的 SQL（仅单条 SELECT/WITH）")


class DictFavoriteInfo(BaseModel):
    id: int
    table_id: int
    table_code: str
    table_name: Optional[str] = None
    created_at: str


class DictFavoriteCreateRequest(BaseModel):
    table_id: int = Field(..., description="字典表 ID")
    table_code: str = Field(..., min_length=1, max_length=100, description="表代码")
    table_name: Optional[str] = Field(None, max_length=200, description="表中文名")


# =============================================================================
# 系统日志查询（审计）
# =============================================================================

class AuditLogInfo(BaseModel):
    id: int
    time: str = Field(..., description="操作时间 YYYY-MM-DD HH:MM:SS")
    username: str = Field(..., description="用户编号")
    display_name: Optional[str] = Field(None, description="用户姓名")
    department: Optional[str] = Field(None, description="部门")
    ip: Optional[str] = Field(None, description="来源 IP")
    mac: Optional[str] = Field(None, description="来源 MAC（同网段解析，跨网段为空）")
    menu: Optional[str] = Field(None, description="操作菜单")
    action: str = Field(..., description="操作类型")
    detail: Optional[str] = Field(None, description="操作明细")


class AuditLogListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[AuditLogInfo]


# =============================================================================
# Trello 集成（v0.6.4）
# =============================================================================

class TrelloConfigCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="配置名称（唯一）")
    api_key: str = Field(..., min_length=1, max_length=200, description="Trello API Key")
    token: str = Field(..., min_length=1, max_length=300, description="Trello Token（服务端加密存储）")
    enabled: bool = Field(True, description="是否启用同步")
    sync_min: int = Field(5, ge=1, le=1440, description="同步间隔分钟数")


class TrelloConfigUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100, description="配置名称")
    api_key: Optional[str] = Field(None, min_length=1, max_length=200, description="Trello API Key")
    token: Optional[str] = Field(None, min_length=1, max_length=300, description="Trello Token；留空/null 表示不修改")
    enabled: Optional[bool] = Field(None, description="是否启用同步")
    sync_min: Optional[int] = Field(None, ge=1, le=1440, description="同步间隔分钟数")


class TrelloConfigInfo(BaseModel):
    id: int
    name: str
    api_key: str
    token: str = Field(..., description="Token 掩码（恒定 ********，无明文）")
    enabled: bool
    sync_min: int
    last_sync_at: Optional[str] = None
    last_sync_status: Optional[str] = None
    last_sync_error: Optional[str] = None
    updated_by: Optional[str] = None
    updated_at: str
    created_at: str


class TrelloBoardInfo(BaseModel):
    id: int
    config_id: int
    board_id: str
    name: str
    url: Optional[str] = None
    is_closed: bool
    synced_at: str


class TrelloCardInfo(BaseModel):
    id: int
    config_id: int
    card_id: str
    board_id: str
    board_name: Optional[str] = None
    list_id: str
    list_name: Optional[str] = None
    name: str
    desc: Optional[str] = None
    status: Optional[str] = Field(None, description="状态标签（Done/Suspended/Help/Delayed/Not Started/Ongoing/Closed）")
    due_date: Optional[str] = None
    due_complete: bool
    labels_json: Optional[str] = None
    members_json: Optional[str] = None
    url: Optional[str] = None
    pos: Optional[float] = None
    synced_at: str


class TrelloCardListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: List[TrelloCardInfo]


class TrelloSyncResponse(BaseModel):
    success: bool
    message: str
    boards: int = 0
    cards: int = 0
    elapsed_ms: Optional[int] = None
