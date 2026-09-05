# nginx-gateway 新服务接入指南

> 目标：让局域网内其他机器通过 `https://<服务器IP>:<端口>/` 访问一个**新的后端服务**，
> 而后端仍只监听本机回环 `127.0.0.1`，不直接暴露到网络。
> 依赖本机的全局 HTTPS 反向代理网关 nginx-gateway。

## 架构一句话

**一个共享网关 + 每个项目一段启动代码。** nginx-gateway 是唯一一个 docker 容器，
所有服务共用它做 TLS 终止与转发；每个新项目只需要复制 `nginx_gateway.py`（纯标准库），
并在启动入口调用一次 `setup_reverse_proxy()`。

```
局域网设备 ──https──▶ nginx-gateway(容器) ──http──▶ host.docker.internal:<后端端口> ──▶ 127.0.0.1 上的后端
```

## 前置条件（每台目标机器一次性准备）

`~/nginx-gateway/` 目录已就绪，包含：

- `docker-compose.yml` —— 端口发布段（默认 `80`、`8443-8500`；自定义端口需在此单独发布）
- `nginx.conf` —— 网关主配置
- `conf.d/` —— 各服务的 server 块，由 `setup_reverse_proxy()` 自动生成并热加载
- `ssl/` —— 自签名证书（**所有服务共用同一份** `vault.crt` / `vault.key`）

## 接入步骤（每个新服务）

### 1. 复制 nginx_gateway.py

```bash
cp ~/work/nginx-gateway-cli/nginx_gateway.py 你的项目/
```

纯标准库、无第三方依赖，从共享项目 `~/work/nginx-gateway-cli/` 复制即可，无需改动。

### 2. 启动入口调用 setup_reverse_proxy

```python
if __name__ == "__main__":
    import uvicorn

    try:
        from nginx_gateway import setup_reverse_proxy
        setup_reverse_proxy({"myapp": 8000})            # 服务名 + 后端端口，HTTPS 端口自动分配
        # setup_reverse_proxy({"myapp": (8444, 8000)}) # 或手动指定 (HTTPS端口, 后端端口)
    except Exception as exc:
        print(f"[nginx-gateway] 反向代理配置跳过: {exc}")  # 代理失败不影响应用本身启动

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)
```

**后端端口必须等于 uvicorn 实际监听端口**，否则网关返回 502（这是最常见的坑）。

### 3. 启动并访问

```bash
uv run python main.py
```

- HTTPS 端口落在 `8443-8500` 段内 → **开箱即用**（容器已发布整段），无需碰 docker。
- 启动日志打印访问地址：`[nginx-gateway] myapp: https://<服务器IP>:<端口>/ → 127.0.0.1:8000`。
- 已注册的服务重启后**复用原 HTTPS 端口**，地址保持稳定。

## 命令行方式（推荐给非 Python 服务）

不想在项目代码里嵌入启动逻辑的服务（Node / Go / Java…），用共享项目
`~/work/nginx-gateway-cli/` 提供的全局命令 `ngh`（已 `uv tool install` 安装，
任意目录可用；未安装时也可 `python3 nginx_gateway_cli.py ...` 直接调用）：

```bash
ngh add myapp 8080               # 自动分配 HTTPS 端口
ngh add myapp 8080 --https 8444  # 手动指定 HTTPS 端口
ngh list                         # 查看已注册服务
ngh remove myapp                 # 注销服务
ngh start                        # 仅确保网关容器运行
```

把 `nginx_gateway.py` 与 `nginx_gateway_cli.py`（位于 `~/work/nginx-gateway-cli/`）一起复制到任意机器，即可为任何类型的服务接入 HTTPS。自定义端口（如 vault 的 6012）同样适用：

```bash
ngh add vault 6011 --https 6012
```

## 自定义 HTTPS 端口（如 vault 用 6012）

对外端口**必须被网关容器发布**，否则外部无法访问。四件事都要做：

1. **docker-compose.yml 单独发布该端口**：

   ```yaml
   ports:
     - "8443-8500:8443-8500"
     - "6012:6012"     # 新增行
   ```

2. **重建容器**（发布端口变更必须重建才生效；重建会短暂中断网关下所有服务）：

   ```bash
   cd ~/nginx-gateway && docker compose up -d
   ```

3. **main.py 指定元组并扩展 https_range**（否则会被判定越界并自动改分配）：

   ```python
   setup_reverse_proxy({"vault": (6012, 6011)}, https_range=(6012, 8500))
   ```

4. **Windows 防火墙放行**入站 TCP 端口（见下节）。

## Windows 防火墙

每新增一个对外端口，都要在 Windows 放行一次（管理员 PowerShell）：

```powershell
New-NetFirewallRule -DisplayName "WSL HTTPS 6012" -Direction Inbound -LocalPort 6012 -Protocol TCP -Action Allow
```

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `502 Bad Gateway` | 后端端口不匹配，`proxy_pass` 指向没人监听的端口 | 让 `setup_reverse_proxy` 的后端端口 = uvicorn 实际端口 |
| 本机 `connection refused` | 端口没有进程监听 | `ss -tlnp` 确认后端端口 |
| 其他设备 `connection refused` / 超时 | 端口没发布到容器，或 Windows 防火墙未放行 | 检查 docker-compose 发布 + 放行入站端口 |
| 浏览器证书警告 | 自签名证书 | 首次访问点「高级 → 继续前往」即可 |

## 常见坑

- **共享证书**：所有服务共用 `ssl/vault.crt`，无法按服务区分证书（局域网自签场景下可接受）。
- **服务名唯一**：conf 文件按 `<服务名>.conf` 生成，名字要唯一；改名会留下旧配置
  （函数只写自己列出的服务，不删除 conf.d 中其它服务的配置）。
- **换机器**：`SERVER_IP` 默认写死 `10.126.126.11`；部署到别处时设 `NGINX_GATEWAY_IP`
  环境变量，或传 `server_ip` 参数。
- **WebSocket**：模板已内置 `Upgrade` / `Connection: upgrade` / `proxy_read_timeout`，
  长连接（如 uvicorn reload、SSE）无需额外配置。
- **自动分配踩空**：`https_range` 覆盖到 6012 时，自动分配会从 6013 起找空闲端口，
  而 6013 等端口**未发布**到容器。新服务要么手动指定 HTTPS 端口，要么同步扩大
  docker-compose 的发布段。

## vault 现状（示例）

| 项 | 值 |
|---|---|
| 服务名 | `vault` |
| 对外 HTTPS | `https://10.126.126.11:6012/` |
| 后端 | `127.0.0.1:6011` |
| 配置文件 | `~/nginx-gateway/conf.d/vault.conf` |
