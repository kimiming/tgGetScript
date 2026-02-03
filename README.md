# TG 管理系统 — 部署说明

最小说明：本仓库包含一个基于 FastAPI 的简单管理界面，需要一个 Redis 实例用于存储临时状态。

推荐在 Ubuntu 服务器上通过 Docker / docker-compose 部署。

构建并运行（使用 docker-compose，包含 Redis）：

```bash
# 在项目根目录
docker-compose build
docker-compose up -d
```

访问: http://<your-server-ip>:8000

环境变量（可通过 `docker-compose.yml` 或 `docker run -e ...` 设置）：

- `REDIS_HOST` (默认: redis)
- `REDIS_PORT` (默认: 6379)
- `REDIS_DB` (默认: 0)
- `ADMIN_TOKEN` (默认示例 token，请务必修改为强密码)
- `BASE_URL` (用于生成导出的 CSV 链接)

直接使用 Docker（不使用 compose）：

```bash
# 构建镜像
docker build -t tg-admin:latest .

# 运行（示例：使用宿主机上的 redis）
docker run -d --name tg-admin -p 8000:8000 \
  -e REDIS_HOST=127.0.0.1 \
  -e REDIS_PORT=6379 \
  -e ADMIN_TOKEN=你的强密码 \
  -v $(pwd)/sessions:/app/sessions \
  tg-admin:latest
```

注意事项：

- 强烈建议修改 `ADMIN_TOKEN` 环境变量，避免使用默认密钥。
- 如果部署在公网，请在前面加一层反向代理（如 nginx），并启用 HTTPS。
- 默认 `sessions` 目录会映射到容器内部，确保目录权限正确。
