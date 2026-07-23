# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据库实体定义（SQLAlchemy 2.x）

一期建表（依据《落地方案 V2.3》2.7 节）：
    用户与审计：sys_user、sys_audit_log
    核对任务：  recon_job、recon_result_file
    规则配置：  rule_code_mapping、rule_bulk_product、rule_threshold
               （初始数据由 server/config/rule_config.json 导入）

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """ORM 基类"""
    pass


# =============================================================================
# 用户与审计
# =============================================================================

class SysUser(Base):
    """用户表（本地 bcrypt 认证；角色 admin/operator/viewer）"""
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="用户编号（登录用）")
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False, comment="密码哈希(bcrypt)")
    display_name: Mapped[str] = mapped_column(String(100), nullable=True, comment="用户姓名")
    department: Mapped[str] = mapped_column(String(100), nullable=True, comment="部门")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer", comment="角色: admin/operator/viewer")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="active", comment="状态: active/disabled")
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="local", comment="来源: local/ad")
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="首次登录强制改密标志")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class SysAuditLog(Base):
    """审计日志表"""
    __tablename__ = "sys_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, comment="操作人")
    action: Mapped[str] = mapped_column(String(50), nullable=False, comment="操作类型")
    object_type: Mapped[str] = mapped_column(String(50), nullable=True, comment="操作对象类型")
    object_id: Mapped[str] = mapped_column(String(64), nullable=True, comment="操作对象标识")
    detail: Mapped[str] = mapped_column(Text, nullable=True, comment="操作明细")
    ip: Mapped[str] = mapped_column(String(50), nullable=True, comment="来源IP")
    mac: Mapped[str] = mapped_column(String(20), nullable=True, comment="来源MAC（服务端ARP解析，同网段可获取）")
    menu: Mapped[str] = mapped_column(String(100), nullable=True, comment="操作菜单（如 数据核对中心·M1）")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


# =============================================================================
# 核对任务
# =============================================================================

class ReconJob(Base):
    """核对任务实例表"""
    __tablename__ = "recon_job"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, comment="任务ID(uuid16)")
    module: Mapped[str] = mapped_column(String(10), nullable=False, comment="模块: M1/M2/M3")
    biz_date: Mapped[str] = mapped_column(String(8), nullable=False, comment="业务日期 yyyyMMdd")
    fetch_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="file", comment="取数模式: file/db")
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending", comment="状态: pending/running/success/failed")
    trigger_type: Mapped[str] = mapped_column(String(10), nullable=False, default="manual", comment="触发方式: manual/schedule")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="进度 0-100")
    stats_json: Mapped[str] = mapped_column(Text, nullable=True, comment="统计摘要JSON")
    error: Mapped[str] = mapped_column(Text, nullable=True, comment="错误信息")
    result_filename: Mapped[str] = mapped_column(String(255), nullable=True, comment="结果文件名(含日期与版本)")
    created_by: Mapped[str] = mapped_column(String(50), nullable=False, comment="创建人")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)


class ReconResultFile(Base):
    """核对结果文件索引表"""
    __tablename__ = "recon_result_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="任务ID")
    file_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="文件类型: input/result")
    file_path: Mapped[str] = mapped_column(String(500), nullable=False, comment="文件绝对路径")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="文件名")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class ReconJobItem(Base):
    """M1 核对结果产品级明细（任务成功时写入，供统计看板持续差异分析；历史任务不回填）"""
    __tablename__ = "recon_job_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="任务ID")
    product_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="产品代码（信托计划代码）")
    product_name: Mapped[str] = mapped_column(String(200), nullable=True, comment="产品名称")
    max_diff_pct: Mapped[float] = mapped_column(Float, nullable=True, comment="最大差异百分比（总资产/资产净值差值百分比绝对值较大者；未匹配为 NULL）")
    match_method: Mapped[str] = mapped_column(String(10), nullable=False, comment="匹配方式: 精确/模糊/未匹配")
    is_bulk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否大宗产品")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


# =============================================================================
# 任务调度中心（二期 DS-F5）
# =============================================================================

class ScheduleJob(Base):
    """定时任务配置表（本表为配置源；APScheduler 作业由此表同步，重启后恢复）"""
    __tablename__ = "schedule_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="任务名称")
    module: Mapped[str] = mapped_column(String(10), nullable=False, comment="模块: m1/m2")
    fetch_mode: Mapped[str] = mapped_column(String(10), nullable=False, default="file", comment="取数模式: file/db")
    fund_template_id: Mapped[int] = mapped_column(Integer, nullable=True, comment="M1 db：基金资产查询模板ID")
    netvalue_template_id: Mapped[int] = mapped_column(Integer, nullable=True, comment="M1 db：净值查询模板ID")
    groups_json: Mapped[str] = mapped_column(Text, nullable=True, comment="M2 db：模板分组JSON")
    file_dir: Mapped[str] = mapped_column(String(500), nullable=True, comment="file 模式：文件就绪监测目录")
    cron_expr: Mapped[str] = mapped_column(String(100), nullable=False, comment="cron 表达式（5 段：分 时 日 月 周）")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="启用状态")
    last_run_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="最近执行时间")
    last_status: Mapped[str] = mapped_column(String(20), nullable=True, comment="最近执行结果: success/failed/wait_file/retrying")
    last_job_id: Mapped[str] = mapped_column(String(32), nullable=True, comment="最近执行产生的 recon_job ID")
    last_error: Mapped[str] = mapped_column(Text, nullable=True, comment="最近失败原因")
    created_by: Mapped[str] = mapped_column(String(50), nullable=False, comment="创建人")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class SysConfig(Base):
    """系统参数表（键值：data_ready_time/buffer_minutes/schedule_retry_delay_minutes 等）"""
    __tablename__ = "sys_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    param_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="参数键")
    param_value: Mapped[str] = mapped_column(String(200), nullable=False, comment="参数值")
    description: Mapped[str] = mapped_column(String(200), nullable=True, comment="说明")
    updated_by: Mapped[str] = mapped_column(String(50), nullable=True, comment="修改人")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


# =============================================================================
# 数据源管理（二期）
# =============================================================================

class DsConnection(Base):
    """数据源连接配置表（密码 Fernet 密文存储，接口永不返回明文）"""
    __tablename__ = "ds_connection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="数据源名称")
    db_type: Mapped[str] = mapped_column(String(20), nullable=False, comment="类型: oracle/mariadb/mysql/mssql/postgresql")
    host: Mapped[str] = mapped_column(String(200), nullable=True, comment="主机")
    port: Mapped[int] = mapped_column(Integer, nullable=True, comment="端口")
    db_name: Mapped[str] = mapped_column(String(100), nullable=True, comment="库名（Oracle 以外）")
    service_name: Mapped[str] = mapped_column(String(100), nullable=True, comment="Oracle 服务名")
    sid: Mapped[str] = mapped_column(String(100), nullable=True, comment="Oracle SID")
    username: Mapped[str] = mapped_column(String(100), nullable=False, comment="账号")
    password_enc: Mapped[str] = mapped_column(Text, nullable=False, comment="密码密文(Fernet)")
    extra_json: Mapped[str] = mapped_column(Text, nullable=True, comment="连接参数JSON(预留)")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="启用")
    updated_by: Mapped[str] = mapped_column(String(50), nullable=True, comment="修改人")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class DsQueryTemplate(Base):
    """查询模板表（SQL 保存时经 SQL Guard 白名单校验）"""
    __tablename__ = "ds_query_template"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="模板名称")
    module: Mapped[str] = mapped_column(String(30), nullable=False, comment="所属模块: m1_fund/m1_netvalue/m2_system/m2_valuation/m3_member 等")
    ds_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="数据源ID(ds_connection.id)")
    sql_text: Mapped[str] = mapped_column(Text, nullable=False, comment="查询SQL(仅SELECT/WITH)")
    column_map_json: Mapped[str] = mapped_column(Text, nullable=True, comment="结果列→标准逻辑字段映射JSON")
    params_json: Mapped[str] = mapped_column(Text, nullable=True, comment="参数定义JSON(如biz_date)")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="启用")
    updated_by: Mapped[str] = mapped_column(String(50), nullable=True, comment="修改人")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class DictFavorite(Base):
    """数据字典表收藏（按用户）"""
    __tablename__ = "dict_favorite"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="用户ID(sys_user.id)")
    table_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="字典表ID")
    table_code: Mapped[str] = mapped_column(String(100), nullable=False, comment="表代码（冗余缓存，展示用）")
    table_name: Mapped[str] = mapped_column(String(200), nullable=True, comment="表中文名（冗余缓存，展示用）")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


# =============================================================================
# 系统配置（二期 M2）
# =============================================================================

class SysSubjectPriceRule(Base):
    """M2 科目取价规则表（热生效：M2 任务每次执行现取启用规则）"""
    __tablename__ = "sys_subject_price_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject_prefix: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, comment="科目前缀(如1101/1501)")
    price_field: Mapped[str] = mapped_column(String(50), nullable=False, comment="取价字段(估值表列名,如市价/单位成本)")
    description: Mapped[str] = mapped_column(String(100), nullable=True, comment="科目说明(如交易性金融资产)")
    note: Mapped[str] = mapped_column(String(200), nullable=True, comment="口径提示语(报告备注用,可空)")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="启用")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="排序号(小者先提取)")
    updated_by: Mapped[str] = mapped_column(String(50), nullable=True, comment="修改人")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


# =============================================================================
# 规则配置
# =============================================================================

class RuleCodeMapping(Base):
    """信托计划代码映射规则表"""
    __tablename__ = "rule_code_mapping"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="原代码")
    target_code: Mapped[str] = mapped_column(String(50), nullable=False, comment="映射后代码")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="启用")
    updated_by: Mapped[str] = mapped_column(String(50), nullable=True, comment="修改人")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class RuleBulkProduct(Base):
    """特殊产品清单表（原大宗产品清单；表名保持不变避免契约破坏）

    description 列语义：差异说明（展示在 M1 核对结果 Excel"差异原因"列；
    NULL 时输出默认文案"大宗产品无需核对"）。
    """
    __tablename__ = "rule_bulk_product"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="产品代码")
    description: Mapped[str] = mapped_column(String(200), nullable=True, comment="差异说明")
    color: Mapped[str] = mapped_column(String(7), nullable=False, server_default="FFC000", default="FFC000", comment="行填充色(6位HEX)")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="启用")
    updated_by: Mapped[str] = mapped_column(String(50), nullable=True, comment="修改人")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class RuleThreshold(Base):
    """阈值参数表（键：diff_pct/fuzzy_sim/price_tol）"""
    __tablename__ = "rule_threshold"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    param_key: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, comment="参数键")
    param_value: Mapped[str] = mapped_column(String(100), nullable=False, comment="参数值")
    description: Mapped[str] = mapped_column(String(200), nullable=True, comment="说明")
    updated_by: Mapped[str] = mapped_column(String(50), nullable=True, comment="修改人")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


# =============================================================================
# Trello 集成（v0.6.4）
# =============================================================================

class TrelloConfig(Base):
    """Trello 连接配置表（API Key / Token 均 Fernet 密文存储）"""
    __tablename__ = "trello_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="配置名称")
    api_key: Mapped[str] = mapped_column(String(200), nullable=False, comment="Trello API Key 密文(Fernet)")
    token_enc: Mapped[str] = mapped_column(Text, nullable=False, comment="Trello Token 密文(Fernet)")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, comment="是否启用同步")
    sync_min: Mapped[int] = mapped_column(Integer, nullable=False, default=5, comment="同步间隔分钟数")
    last_sync_at: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="最近同步时间")
    last_sync_status: Mapped[str] = mapped_column(String(20), nullable=True, comment="最近同步状态 success/failed")
    last_sync_error: Mapped[str] = mapped_column(Text, nullable=True, comment="最近同步失败原因")
    updated_by: Mapped[str] = mapped_column(String(50), nullable=True, comment="修改人")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)


class TrelloBoard(Base):
    """Trello Board 同步缓存"""
    __tablename__ = "trello_board"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="TrelloConfig ID")
    board_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="Trello board ID")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="Board 名称")
    url: Mapped[str] = mapped_column(String(500), nullable=True, comment="Board URL")
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="是否已归档")
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class TrelloCard(Base):
    """Trello Card 同步缓存（只读同步，v0.6.4）"""
    __tablename__ = "trello_card"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="TrelloConfig ID")
    card_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="Trello card ID")
    board_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="所属 board ID")
    board_name: Mapped[str] = mapped_column(String(200), nullable=True, comment="Board 名称（冗余）")
    list_id: Mapped[str] = mapped_column(String(50), nullable=False, comment="所属 list ID")
    list_name: Mapped[str] = mapped_column(String(200), nullable=True, comment="List 名称（冗余）")
    name: Mapped[str] = mapped_column(String(500), nullable=False, comment="卡片标题")
    desc: Mapped[str] = mapped_column(Text, nullable=True, comment="描述")
    status: Mapped[str] = mapped_column(String(50), nullable=True, comment="状态标签（Done/Suspended/Help/Delayed/Not Started/Ongoing/Closed）")
    due_date: Mapped[datetime] = mapped_column(DateTime, nullable=True, comment="截止时间")
    due_complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, comment="截止日期是否已完成")
    labels_json: Mapped[str] = mapped_column(Text, nullable=True, comment="全部标签 JSON")
    members_json: Mapped[str] = mapped_column(Text, nullable=True, comment="成员 JSON")
    url: Mapped[str] = mapped_column(String(500), nullable=True, comment="卡片 URL")
    pos: Mapped[float] = mapped_column(Float, nullable=True, comment="排序位置")
    synced_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


# 一期建表清单（供 init_database 使用；create_all 幂等，二期新增表自动补建）
ALL_TABLES = [
    SysUser.__table__,
    SysAuditLog.__table__,
    ReconJob.__table__,
    ReconResultFile.__table__,
    ReconJobItem.__table__,
    RuleCodeMapping.__table__,
    RuleBulkProduct.__table__,
    RuleThreshold.__table__,
    DsConnection.__table__,
    DsQueryTemplate.__table__,
    DictFavorite.__table__,
    SysSubjectPriceRule.__table__,
    ScheduleJob.__table__,
    SysConfig.__table__,
    TrelloConfig.__table__,
    TrelloBoard.__table__,
    TrelloCard.__table__,
]
