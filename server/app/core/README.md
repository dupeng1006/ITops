# app/core —— 基础设施层

- `config.py`：集中配置（数据/归档目录、JWT 密钥与 8h 过期、上传上限 50MB、
  初始管理员）；从环境变量或 `server/.env` 读取，密钥不入库不入仓；
- `security.py`：bcrypt 密码哈希、JWT 签发/校验；
- `deps.py`：FastAPI 依赖注入（数据库会话、当前用户、三级角色校验、
  首登强制改密拦截）。
