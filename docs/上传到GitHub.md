# 把「小金库」后端(6011 服务)上传到 GitHub

> 适用：把 `d:/codes/vault` 整个工程（FastAPI 后端 + frontend + docs + 微信/小红书小程序目录）推到 GitHub。
> 你的真实数据 `data/inventory.json` 已被 `.gitignore` 忽略，**不会被上传**，只在本地。
> 以下命令在 **Git Bash**（仓库根目录 `d:/codes/vault`）里执行；命令用 `<...>` 括起来的部分替换成你自己的值。

---

## 第 0 步：检查当前状态（确认无敏感文件会被推上去）

```bash
cd /d/codes/vault

# 看远端与提交情况（现在应显示：无远端、无 commit）
git remote -v
git log --oneline -3   # 报 "does not have any commits yet" 是正常的

# 关键：确认 inventory.json 不会被上传
git check-ignore data/inventory.json   # 有输出 = 已忽略(安全)
```

> 建议先花 1 分钟把下面几行**追加**到 `.gitignore` 末尾，避免把缓存/编辑器配置一起传上去：
>
> ```gitignore
> # 运行时缓存与本地配置（不要上传）
> .pytest_cache/
> .ruff_cache/
> .mypy_cache/
> .claude/
> *.zip
> 小金库-xhs.zip
> .DS_Store
> ```

---

## 第 1 步：在 GitHub 网页上建一个空仓库（一次性）

1. 登录 <https://github.com/new>（需先注册 GitHub 账号）
2. 填仓库名，例如 `vault` 或 `xiaojinku`（英文）
3. 可见性：**先选 Private**（之后想公开随时能改）
4. **不要勾选** "Add a README / .gitignore / license"（保持空仓库，避免历史冲突）
5. 点 **Create repository**
6. 复制页面上形如 `https://github.com/<你的用户名>/<仓库名>.git` 的地址

---

## 第 2 步：本地初始化并推送（一次性）

```bash
cd /d/codes/vault

# 2.1 可选：把分支统一叫 main（GitHub 默认分支名；不想要就跳过，把后续 main 改成 master）
git branch -m main

# 2.2 把要上传的文件加入暂存（被 .gitignore 忽略的不会进来）
git add -A

# 2.3 预览到底会上传哪些文件 —— 确认列表里【没有】data/inventory.json、.venv/ 等
git status

# 2.4 首次提交
git commit -m "feat: 小金库 FastAPI 后端 + 网页端 + 微信/小红书小程序端"

# 2.5 关联远端（把 <你的用户名>/<仓库名> 换成第 1 步复制的）
git remote add origin https://github.com/<你的用户名>/<仓库名>.git

# 2.6 推送到 GitHub
git push -u origin main
```

推送时若弹出登录窗口，用浏览器方式登录一次即可（Git for Windows 自带的凭据管理器）。
看到类似 `branch 'main' set up to track 'origin/main'` 就成功了，刷新 GitHub 页面应能看到代码。

---

## 第 3 步：以后每次改完代码再上传

```bash
cd /d/codes/vault
git add -A
git commit -m "改动说明，例如 fix: 修复价格格式"
git push

git commit --amend --no-edit
```

---

## 常见问题

| 现象 | 解决 |
|---|---|
| push 报 `Authentication failed` / 403 | 生成 Personal Access Token：GitHub → Settings → Developer settings → **Personal access tokens** → Generate new token (classic)，勾选 `repo`，然后把第 1 步的地址改成 `https://<用户名>:<token>@github.com/<用户名>/<仓库名>.git` 再 push；或安装 GitHub Desktop / `gh` 命令行代替 |
| 报 `refusing to merge unrelated histories` | 你建仓库时勾了 README/许可。先执行：`git pull origin main --allow-unrelated-histories`，解决冲突后再 `git push -u origin main` |
| 想删掉某次已传的文件（如误传了数据） | `git rm --cached <文件>`，把路径加进 `.gitignore`，再 commit + push（GitHub 历史里仍残留，需联系支持或用 filter-repo 清除） |

---

## 下一步：上云跑 6011（可选）

传到 GitHub 只是第一步。若要让手机/公网访问，还需要一台服务器拉取代码后运行后端：

```bash
# 在云服务器上
git clone https://github.com/<你的用户名>/<仓库名>.git
cd <仓库名>
uv sync --frozen          # 安装依赖（服务器需先装 uv，或用 pip install -e . 代替）
uv run python main.py     # 默认监听 0.0.0.0:6011
```

正式给小程序用还要：备案 HTTPS 域名 → 反代到 6011 → 微信后台配置 request 合法域名。
（main.py 注释里提到的 `ngh add vault 6011 --https 6012` 就是这类反代思路。）需要时我可以帮你把部署脚本整理好。
