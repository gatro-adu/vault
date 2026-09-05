# 小金库

一个本机运行的个人物品管理工具（小金库）。原生静态前端通过 REST API 调用 FastAPI 后端，后端将数据保存到 JSON 文件；FastAPI 同时托管前端静态文件，前端与 API 同源访问。

## 功能

- 创建和维护物品、物品类别、现实存放位置。
- 位置可建立层级，例如“家 / 书房 / 抽屉”。
- 强大的标签系统：自由组合类别、位置、所有者、价格、日期及自定义标签。
- 全局搜索：可搜索物品名称、标签名或标签内容。
- 成本管理：根据价格、购买日期或使用次数自动分摊成本。
- 类别定制：针对不同类别定制是否开启使用次数统计或允许“小物品”免填日期。

## 运行

需要 Python 3.13 或更高版本，以及 `uv` 包管理器。首次运行先安装依赖：

```bash
uv sync --all-groups
```

### HTTPS 访问（推荐，供局域网其他机器访问）

通过 **nginx-gateway**（一个 docker nginx 容器，本机全局反向代理网关）提供 HTTPS：网关在 **6012** 端口终止 TLS，将请求转发给只监听本机回环的 FastAPI。局域网其他机器直接访问 `https://<服务器IP>:6012/`，无需 SSH 隧道，数据在传输中加密。

vault 固定对外 HTTPS 端口 **6012**（超出默认 8443-8500 段，已在 `~/nginx-gateway/docker-compose.yml` 单独发布）。网关已内置 vault 的反向代理配置（`~/nginx-gateway/conf.d/vault.conf`）与自签名证书（`~/nginx-gateway/ssl/`）。

**首次配置**：一次性准备好网关目录 `~/nginx-gateway/`（含 `docker-compose.yml`、`nginx.conf`、`conf.d/`、`ssl/`）。之后用全局命令 `ngh` 注册 vault 的代理即可（见下方「扩展其他服务」）。

**启动后端**（绑定 `127.0.0.1`，不直接暴露到网络）：

```bash
uv run python main.py
```

**局域网其他机器访问**：

```text
https://10.126.126.11:6012/
```

- 自签名证书首次访问会有安全警告，点击「高级」→「继续前往」即可。
- 若其他机器连不上，检查 Windows 防火墙是否放行 TCP 6012（每新增一个服务端口都要放行一次）。在 Windows PowerShell（管理员）执行：

  ```powershell
  New-NetFirewallRule -DisplayName "WSL HTTPS 6012" -Direction Inbound -LocalPort 6012 -Protocol TCP -Action Allow
  ```

- 前端与 API 同域（均由 `https://<host>:6012/` 提供），无需配置 CORS。

**扩展其他服务**：无需提前注册端口。用全局命令 `ngh`（来自共享项目 `~/work/nginx-gateway-cli/`，服务后端只需监听宿主机回环）即可为任意服务注册 HTTPS 反向代理。HTTPS 端口默认从 8443-8500 段自动分配；已注册的服务复用原端口、地址保持稳定，越界的端口会被自动纠正：

```bash
ngh add osm 8080                    # 服务名 + 后端端口，HTTPS 端口自动分配
ngh add vault 6011 --https 6012     # 或手动指定 (HTTPS端口, 后端端口)
ngh list                            # 查看已注册服务
```

`nginx_gateway.py` 是纯标准库模块，Python 项目也可复制进项目内、在启动入口调用
`setup_reverse_proxy()` 自动注册（见 `~/work/nginx-gateway-cli/`）。

无论哪种方式，新端口都要在 Windows 防火墙放行一次（见上一条 PowerShell 命令）。

完整的接入步骤、自定义端口方法、故障排查见 [docs/nginx-gateway接入指南.md](docs/nginx-gateway接入指南.md)。

### 本机访问

```bash
uv run python main.py
```

浏览器打开 <http://127.0.0.1:6011/> 即可使用；API 文档在 <http://127.0.0.1:6011/docs>。

## 测试

```bash
uv run pytest
```

## 数据存储

首次写入时会自动创建 `data/inventory.json`。该文件由 `.gitignore` 忽略，适用于单用户、本机、单进程运行；请定期备份。通过设置环境变量 `VAULT_DATA_FILE` 可改用其他 JSON 文件路径，便于测试或迁移。

当前 API 与 JSON 存储层解耦。将来使用 SQLite 或其他数据库时，可替换 `main.py` 中的 `load_data` 和 `save_data` 相关仓储函数，前端接口保持不变。
