<p align="center">
  <img src="./docs/logo.svg" width="84" alt="Gloss logo" />
</p>

<h1 align="center">Gloss · 旁注</h1>

<p align="center"><b>照亮论文的批注 · 本地自托管的 AI 论文阅读助手</b></p>

<p align="center">
  <img src="./docs/cover.svg" width="760" alt="Gloss —— 一束光照亮一页论文，就像在字里行间写下的旁注" />
</p>

<p align="center"><sub><i>一束光，照亮一页论文 —— 就像在字里行间写下的旁注。</i></sub></p>

<p align="center"><a href="./README.md"><b>English →</b></a> · <a href="./CHANGELOG.md"><b>版本记录</b></a></p>

---

Gloss（旁注）是一个 **自托管、本地运行** 的科研论文阅读工具。它用一个 FastAPI 后端提供基于
React / PDF.js 的阅读器界面，并驱动一个大模型帮你速览、研读、翻译、答疑。

大模型 **默认使用你本机的 `claude` CLI**，
此外还支持本机的 `codex` CLI、Anthropic API，以及 **任意 OpenAI 兼容端点**（本地 vLLM、claude 代理等）。
它还能 **加载并运行 Claude / Codex 技能（skills）**，直接作用在你正在读的这篇论文上。

一切都跑在你自己的机器上：一个进程、一个端口，打开浏览器就能读。

---

## ✨ 功能一览

| 功能 | 说明 |
|---|---|
| 📖 **PDF 阅读器** | 基于 PDF.js，带真正可选中的文本层；选中文字即弹出操作（Explain / Translate / 加入会话 / 高亮） |
| 🧠 **速览 Summary** | 一键生成 TL;DR + 问题 / 方法 / 结果 / 创新点 / 局限 |
| 📝 **研读笔记 Notes** | 结构化精读笔记，可 **一键复制** 或 **下载 `.md`** |
| 🗺️ **思维导图 Mind Map** | 交互式 React Flow 导图：缩放、展开 / 折叠、点击节点看该节点的摘要与相互连接 |
| 💬 **对话 Chat** | 像同事一样提问 —— 基于全篇 **BM25 检索（RAG）** 作答、**流式输出**、**每篇论文保留多个会话**、可删除、随时新建 |
| 💡 **解释 Explain** | 选中一段公式 / 术语 / 表格，一次性解释清楚；数学用 **KaTeX** 渲染 |
| 🌐 **翻译 Translate** | **逐句翻译**、结果 **持久缓存**、**跨页范围复用**；默认只显示中文，可切换 **显示原文**；**点击译文可在 PDF 中闪烁定位**；arXiv 论文可 **直接翻译 LaTeX 源**，不漏文本 |
| 📐 **arXiv LaTeX** | **TeX 源码标签**：读取论文 LaTeX 源（精确、无提取损失），并可从源翻译 |
| 🖍️ **自动高亮 Auto-highlight** | AI 按类别挑出关键句，并 **锚定到 PDF 原文位置** 标色 |
| ✍️ **批注 Highlights** | 你自己的高亮（多种颜色）+ 笔记，锚定在页面上并保存 |
| 🔗 **参考文献 References** | 解析文末参考文献，经 **Crossref / arXiv** 补全，**每条可点击跳转** |
| 🔭 **学术搜索 Scholar** | 通过 **Semantic Scholar / arXiv** 找相关论文，一键 **导入** |
| 📚 **论文库 Library** | 通过 **arXiv id / DOI / URL / 上传 PDF** 导入，集中管理 |
| 🧩 **技能 Skills** | 发现并运行 **Claude / Codex 技能**，作用于当前论文 |
| ➕ **加入会话** | 在 PDF 或各面板里选中内容 → 一键送入 Chat，让 AI 就这段内容回答 |
| 🎨 **主题与阅读模式** | 内置 **7 套配色**，另有 PDF 阅读模式 —— **正常 / 护眼 / 夜间** |
| 🗣️ **多语言** | **界面语言**（English / 中文，默认英文），以及 AI **回答语言** 与 **翻译目标语言** |
| ⚙️ **体验** | 长任务切换标签也不中断；侧栏常驻，**滚动位置与思维导图视图都会保留**；每个提供方可 **测试连通性** |

---

## 🚀 运行（Linux）

```bash
scripts/setup.sh     # 首次：建后端 venv + 装依赖，装前端依赖并 build
scripts/run.sh       # 在 :8010 提供服务（前端已构建 + API，一个进程一个端口）
```

启动后浏览器打开 **`http://<host>:8010`**，粘贴一个 arXiv id（例如 `1706.03762`）或上传 PDF，点开卡片就能读。

端口 / 监听地址可用环境变量覆盖：

```bash
GLOSS_PORT=6006 GLOSS_HOST=0.0.0.0 scripts/run.sh
```

- `GLOSS_PORT` —— 服务端口（默认 `8010`）
- `GLOSS_HOST` —— 监听地址（默认 `0.0.0.0`）
- `GLOSS_DATA_DIR` —— 数据目录（默认 `backend/data`）

服务监听在 `0.0.0.0`，从别的电脑访问可用服务商的端口映射或 SSH 转发
（如 `ssh -CNg -L <端口>:127.0.0.1:<端口> -p <SSH端口> user@host`，然后打开 `http://localhost:<端口>`）。

> 想热重载调试用 `scripts/dev.sh`（后端 uvicorn `--reload` :8010 + Vite 开发服务器 :5173，自动代理 `/api`）。

---

## 🧰 CLI

```bash
./gloss serve                  # 启动 web 应用（打印访问地址）
./gloss open <pdf|arxiv|doi>   # 导入 + 启动服务 + 打开浏览器
./gloss import <src>           # 把本地 PDF / arXiv / DOI 加入论文库
./gloss ls                     # 列出论文库
./gloss summarize <id|pdf|arxiv>   # 在终端打印一份速览
./gloss chat <id>              # 终端里的交互式对话
./gloss skills                 # 列出发现到的 Claude / Codex 技能
```

例如：`./gloss open 1706.03762` 打开《Attention Is All You Need》并启动阅读器。

---

## 🤖 AI 提供方与进阶设置

在 **Settings** 里选 provider（或改 `backend/data/config.json`）：

| Provider | 说明 | 需要 key？ |
|---|---|---|
| `local_claude` | **默认**。调用本机 `claude` CLI，走订阅登录 | ❌ 免 key |
| `local_codex` | 调用本机 `codex` CLI，走 ChatGPT 订阅 | ❌ 免 key |
| `anthropic` | Anthropic API，或任意 Anthropic 兼容端点 | ✅ 填 `base_url` + `api_key` |
| `openai` | 官方 OpenAI **或任意 OpenAI 兼容端点** | ✅ 填 `base_url` + `api_key` |

`openai` 可指向 **本地 vLLM** 或本地 **claude 代理**（如 `http://127.0.0.1:8899/v1`），完全离线用自己的模型。

**进阶设置**（每个 provider 可单独配）：模型（如 `sonnet` / `opus`、完整 model id，或留空用 CLI 默认）与
**思考深度 / reasoning effort**（`local_claude`：`low … max`；`local_codex`：`minimal … high`）。**回答语言** 与
**翻译目标语言** 也都可配（默认均为中文）。key 会被 Settings API 掩码，`backend/data/` 已 gitignore，不进版本库。

---

## 🏗️ 架构简述

```
backend/          FastAPI（一个进程挂载所有 /api/*，并托管已构建的前端 SPA）
  app/providers/  local_claude · local_codex · anthropic · openai · registry（LLM 抽象层）
  app/pdf/        PyMuPDF 解析（文本块 + bbox）+ 结构启发式（章节/引用/分句）
  app/features/   summarize · explain · translate · chat(RAG) · highlight · notes · mindmap · citations
  app/search/     scholar 检索 / 推荐（Semantic Scholar / arXiv）
  app/skills/     发现并运行 Claude/Codex 的 SKILL.md 技能
  app/library/    SQLite 库 + 导入器（arXiv/DOI/PDF）
  app/routers/    papers · ai · citations · scholar · annotations · skills · settings
frontend/         React + Vite + pdfjs-dist + KaTeX + React Flow（build 到 frontend/dist，由后端托管）
cli/ gloss.py     scripts/ setup.sh · run.sh · dev.sh
```

**数据** 都在 `backend/data/`：一个 SQLite 库（papers / highlights / chats / messages / refs / cache）
+ 每篇论文一个目录，含 `original.pdf` 与解析后的 `parsed.json`。

---

## 💡 小贴士

- **本地 `claude` / `codex` 独立运行**：走你已有的订阅登录（无需 API key），每次回答只针对当前论文，
  不会和你个人的 Claude / Codex 配置混在一起。
- **数据都在本地**：论文、批注、笔记、对话都存在本地 SQLite 库与每篇论文的文件里（`backend/data/`）；
  除下面的外部检索外，数据不出你的机器。
- **外部检索优雅降级**：References、Scholar 等外网请求统一走机器的 HTTP 代理；某个站点连不上（离线）时会
  **优雅降级** 到本地已解析数据，不会整页报错。
- **生成结果持久缓存**：总结 / 笔记 / 导图 / 翻译 / 高亮 首次生成后落盘保存，重进论文直接复用，不重复消耗算力与额度。

---

## 🙏 致谢

Gloss 是对 **[Moonlight](https://www.themoonlight.io/)**（"陪你读论文的 AI 同事"）的一次 **本地自托管重构** ——
从零重写，让它完全跑在你自己的机器上。设计上还参考了两个很棒的项目：

- **[Understand-Anything](https://github.com/Egonex-AI/Understand-Anything)** —— 交互式节点连线 **思维导图**
  （React Flow、点击聚焦、可折叠节点）的灵感来源。
- **[DeepPaperNote](https://github.com/917Dhj/DeepPaperNote)** —— 结构化 **研读笔记** 的灵感来源。

衷心感谢以上三个项目的作者。🙏
