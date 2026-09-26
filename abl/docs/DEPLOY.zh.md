# ABL 部署手册（中文）：新建 repo → 本地跑通 → 海外上线

目标：把 ABL 从 `playground` 拆成独立 repo，面板部署到 Render（`app.你的域名`），落地页和手册部署到 Vercel（`www.你的域名`）。
之后每次发布只需要"提 PR → CI 通过 → 合并"，两个平台自动上线。English version: `docs/DEPLOY.md`.

---

## 总览：你要做的 8 步

| # | 在哪做 | 做什么 | 预计时间 |
|---|---|---|---|
| 1 | GitHub 网页 | 新建一个空的私有 repo | 2 分钟 |
| 2 | 你的 Mac 终端 | 一条命令把 `abl/` 连同历史导出到新 repo | 3 分钟 |
| 3 | 你的 Mac 终端 | clone 新 repo，本地装环境、跑测试、看面板 | 20 分钟（含测试和演示数据） |
| 4 | GitHub 网页 | 给 `main` 分支加保护规则 | 3 分钟 |
| 5 | Render 网页 | 用 Blueprint 一键部署面板，设访问密码 | 5 分钟操作 + 约 10 分钟构建 |
| 6 | Vercel 网页 | 导入同一个 repo，部署落地页 | 5 分钟 |
| 7 | 域名服务商后台 | 加两条 DNS 记录，绑定自己的域名 | 10 分钟 + 生效等待 |
| 8 | Vercel 网页 | 把面板地址写回落地页，重新部署 | 2 分钟 |

实测资源：面板运行时内存峰值约 183 MB；镜像构建时生成演示台账，内存峰值约 1 GB。

费用：Render Starter 每月约 7 美元（推荐，常驻不休眠）；Free 档也能跑，但 15 分钟无访问会休眠，再打开要等约 1 分钟。Vercel Hobby 免费。GitHub 私有 repo 免费。

---

## 第 1 步：在 GitHub 新建空 repo

1. 打开 https://github.com/new
2. Owner：选你自己，或者以后公司的 Organization。
3. Repository name：例如 `abl`。
4. 选 **Private**。
5. **不要勾选** "Add a README"、".gitignore"、"license"，repo 必须是完全空的，否则第 2 步会冲突。
6. 点 Create repository，复制页面上显示的地址，形如 `https://github.com/<你的用户名>/abl.git`。

## 第 2 步：把 abl/ 导出到新 repo（保留全部提交历史）

在你的 Mac 上，进入现在的 playground 仓库（你的路径是 `~/Desktop/playground/myplayground`）：

```bash
cd ~/Desktop/playground/myplayground
git checkout claude/affectionate-franklin-ttwudk
git pull
bash abl/scripts/export_to_new_repo.sh https://github.com/<你的用户名>/abl.git
```

脚本做的事：用 `git subtree split` 把 `abl/` 目录单独拆出来（每个改过 `abl/` 的提交都保留），推到新 repo 的 `main` 分支。
看到 `Done.` 就成功了。刷新 GitHub 页面，新 repo 的根目录应该直接是 `Makefile`、`dashboard/`、`docs/` 等。

> 以后如果还在 playground 里改了 abl，重新跑一遍这条命令即可同步。但建议从现在起**只在新 repo 里开发**。

## 第 3 步：本地 clone 新 repo，跑通一次

```bash
cd ~/Desktop
git clone https://github.com/<你的用户名>/abl.git abl-app
cd abl-app
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
make test        # 全部测试，约 6–8 分钟，最后应显示全部 passed
make demo        # 生成演示台账，约 8 分钟（和线上面板看到的是同一份）
make watch       # 浏览器打开 http://localhost:8501
```

检查点：
- 面板默认中文，左侧栏可切换 English。
- 本地运行时能看到"暂停 / 恢复"按钮；线上演示模式会隐藏它们。
- 想看完整实验（含公开猪数据）：`make seal-holdout && make campaign`，约 20 分钟。

之后每次重开只需要：`cd ~/Desktop/abl-app && . .venv/bin/activate && make watch`。

## 第 4 步：保护 main 分支（main 就是生产环境）

1. 新 repo 页面 → **Settings** → **Branches** → **Add branch ruleset**（或旧版的 Add rule）。
2. Ruleset name：`protect-main`；Enforcement status：**Active**。
3. Target branches：**Include default branch**。
4. 勾选：
   - **Require a pull request before merging**
   - **Require status checks to pass**，添加检查项 `test (3.9)`、`test (3.11)`、`site`（第一次 CI 跑完之后这些名字才会出现在下拉框里；可以先跳过，等第一次 PR 跑完再回来加）
   - **Block force pushes**
5. 保存。

从此之后，任何改动都走：新建分支 → 提 PR → CI 绿 → 合并到 main → Render 和 Vercel 自动部署。直接往 main 推会被拒绝，不会再出现"推错到 master"的情况。

## 第 5 步：Render 部署面板

1. 打开 https://dashboard.render.com ，用 GitHub 账号登录，授权 Render 访问新 repo（可以只授权这一个 repo）。
2. 点 **New +** → **Blueprint**。
3. 选择 `abl` repo，分支 `main`。Render 会自动读取根目录的 `render.yaml`。
4. 它会要求你填 `ABL_DASHBOARD_PASSWORD`：填一个你自己定的访问密码。**这个密码不要写进代码或 repo。**
5. 点 **Apply**。第一次构建约 10–12 分钟（其中约 8 分钟在生成演示台账）。
6. 构建完成后，服务页面上方会显示地址，形如 `https://abl-dashboard.onrender.com`。打开它，输入密码，应该看到中文面板和"演示模式"横幅。

`render.yaml` 已经配好的内容：Docker 构建、健康检查、`main` 有新提交时自动部署、演示模式、默认中文。

## 第 6 步：Vercel 部署落地页和手册

1. 打开 https://vercel.com/new ，用 GitHub 登录，**Import** 同一个 `abl` repo。
2. Framework Preset 选 **Other**。其余构建设置不用改，根目录的 `vercel.json` 已经写好（构建命令 `python3 scripts/build_site.py`，输出目录 `site/dist`）。
3. 展开 **Environment Variables**，加一条：`ABL_APP_URL` = 第 5 步拿到的 Render 地址（第 8 步会换成你的域名）。
4. 点 **Deploy**，约 1 分钟。打开 Vercel 给的地址（形如 `https://abl-xxx.vercel.app`）：应看到中英切换的落地页、截图、手册和报告链接，"打开监护面板"按钮指向 Render。

## 第 7 步：绑定你买的域名

以你的域名是 `example.com` 为例（换成你的）。

**面板 → `app.example.com`**
1. Render 服务页面 → **Settings** → **Custom Domains** → **Add Custom Domain** → 填 `app.example.com`。
2. 到你买域名的地方（GoDaddy / Namecheap / Cloudflare / 阿里云国际等）的 DNS 管理，加一条：
   - 类型 `CNAME`，主机记录 `app`，值 `abl-dashboard.onrender.com`（以 Render 页面上显示的为准）。
3. 回到 Render 点 **Verify**，证书会自动签发（HTTPS）。

**落地页 → `example.com` 和 `www.example.com`**
1. Vercel 项目 → **Settings** → **Domains** → 添加 `example.com`，它会提示同时添加 `www`。
2. 按 Vercel 页面显示的记录去 DNS 后台添加（通常是根域名一条 `A` 记录、`www` 一条 `CNAME` 记录，**具体值以 Vercel 页面为准**）。
3. 等待生效，通常几分钟，最长 48 小时。HTTPS 自动。

> 如果你的域名 DNS 在 Cloudflare：给 `app` 这条记录关掉橙色云（设为 DNS only），否则会和 Render 的证书签发冲突。

## 第 8 步：把面板域名写回落地页

1. Vercel 项目 → **Settings** → **Environment Variables** → 把 `ABL_APP_URL` 改成 `https://app.example.com`。
2. **Deployments** → 最新一次 → **⋯** → **Redeploy**。
3. 打开 `https://www.example.com`，点"打开监护面板"，应跳到 `https://app.example.com` 并要求输入密码。

完成。

---

## 以后的日常发布流程

```bash
cd ~/Desktop/abl-app
git checkout -b feat/我的改动
# ……改代码……
make test
git add -A && git commit -m "说明改了什么"
git push -u origin feat/我的改动
```
然后在 GitHub 上点 **Compare & pull request** → 等 CI 变绿 → **Merge**。合并后 Render 和 Vercel 各自自动部署，不需要你再做任何事。

| 想做的事 | 怎么做 |
|---|---|
| 回滚面板 | Render 服务 → **Events** → 找到上一次成功的部署 → **Rollback** |
| 回滚落地页 | Vercel 项目 → **Deployments** → 上一个版本 → **⋯** → **Instant Rollback** |
| 改访问密码 | Render 服务 → **Environment** → 改 `ABL_DASHBOARD_PASSWORD` → 保存（自动重启） |
| 取消密码（公开访问） | 删掉 `ABL_DASHBOARD_PASSWORD` 这个变量。**只在确认不含任何客户数据时这么做。** |
| 本地先试镜像 | 装了 Docker Desktop 的话：`make docker && make docker-run`，打开 http://localhost:8501 ，密码默认 `demo` |
| 让面板显示英文为默认 | Render → Environment → `ABL_LANG` 改成 `en` |

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| 第 2 步报 `rejected ... non-fast-forward` | 新 repo 不是空的（建的时候勾了 README） | 删掉这个 repo 重建一个空的，再跑一次 |
| 第 2 步报 `abl/ has uncommitted changes` | 本地 playground 里 abl/ 有没提交的改动 | `git stash`，或先提交 |
| Render 构建失败，日志里有 `Killed` 或 `out of memory` | 构建机内存不够 | 在 Render → Environment 加 `DEMO_PROPOSALS=15`、`DEMO_FULL_EVALS=3` 后重新部署 |
| Render 页面一直转圈 | Free 档在休眠 | 等 1 分钟；或升级到 Starter |
| 打开面板显示"台账还没生成" | 镜像构建时 `build_demo.py` 没跑成功 | 看 Render 构建日志里 `demo ledger ready` 这一行是否出现 |
| Vercel 构建报 `python3: command not found` | 构建镜像变化 | 本地 `make site` 后，把 Vercel 的 Build Command 设为空、Output Directory 设为 `site/dist`，并把 `site/dist/` 从 `.gitignore` 删掉后提交 |
| 落地页"打开监护面板"是灰的 | 没设 `ABL_APP_URL` | 做第 6 步第 3 项，然后 Redeploy |
| 中国大陆访问很慢 | Render/Vercel 在海外 | 属预期；面向国内用户时换阿里云/腾讯云并办 ICP 备案 |

## 安全须知

- 线上面板是**演示模式**：只读、控制按钮隐藏、数据只有模拟数据（构建时生成），不含任何客户数据。
- 服务器上不放任何 API key（镜像固定 `ABL_LLM=stub`）。
- 访问密码只存在 Render 的环境变量里，不进 repo。
- 以后接客户数据时，**不要**用这套公开部署；按用户手册第 8 节在客户本地私有化部署。
