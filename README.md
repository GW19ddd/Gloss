# 💡 Gloss · 旁注

**照亮论文的批注 · 本地 AI 论文阅读助手**

> Logo 意象：一束光，照亮一页论文 —— 就像在字里行间写下的旁注。

Gloss（旁注）是一个 **自托管、本地运行** 的科研论文阅读工具，风格对标 [Moonlight](https://www.themoonlight.io/)（一个"陪你读论文的 AI 同事"）。它用一个 FastAPI 后端提供基于 React / PDF.js 的阅读器界面，并驱动一个大模型帮你速览、研读、翻译、答疑。

大模型 **默认使用你本机的 `claude` CLI**（走订阅登录，**无需 API key**，和你在终端里用 Claude 一样），此外还支持本机的 `codex` CLI、Anthropic API，以及 **任意 OpenAI 兼容端点**（本地 vLLM、claude_proxy 等）。它还能 **加载并运行 Claude / Codex 技能（skills）**，直接作用在你正在读的这篇论文上。

一切都跑在你自己的机器上：一个进程、一个端口，打开浏览器就能读。

---

## 🌟 Gloss 旁注 是什么

想象你在读一篇论文时，身边坐着一位读得又快又细的同事：你划一段公式，他给你讲清楚；你看不懂某句话，他帮你翻成中文；你想问"这方法和 baseline 差在哪"，他基于全文检索后有理有据地回答；读完还顺手帮你把参考文献理清、把相关工作找出来。

Gloss 就是把这位"同事"搬到你本地。名字取自 **gloss（旁注 / 注解）** —— 在古籍与手稿的字里行间写下的解释性小字。光照亮页面，旁注写在页边，这正是 Gloss 想做的事：**让 AI 的理解，成为你论文页边那束光。**

---

## ✨ 功能一览

| 功能 | 说明 |
|---|---|
| 📖 **PDF 阅读器** | 基于 PDF.js，带真正可选中的文本层；选中文字即弹出操作菜单（Explain / Translate / 加入会话 / 高亮） |
| 🧠 **速览 Summary** | 一键生成 3 句话 TL;DR + 问题 / 方法 / 结果 / 创新点 / 局限，快速判断值不值得读 |
| 📝 **研读笔记 Notes** | 结构化精读笔记，条理清晰，可 **一键复制** 或 **下载 `.md`** |
| 🗺️ **思维导图 Mind Map** | 交互式 React Flow 导图：缩放、展开 / 折叠、点击节点查看该节点的摘要与相互连接 |
| 💬 **对话 Chat** | 像同事一样提问 —— 基于全篇的 **BM25 检索（RAG）** 作答、**流式输出**、**每篇论文保留多个会话历史**、可随时 **新建会话** |
| 💡 **解释 Explain** | 选中一段公式 / 术语 / 表格，一次性解释清楚；数学公式用 **KaTeX** 渲染 |
| 🌐 **翻译 Translate** | **逐句翻译**、结果 **持久缓存**、**跨页范围复用**、默认 **只显示中文**、可切换 **显示原文对照** |
| 🖍️ **自动高亮 Auto-highlight** | AI 按类别（贡献 / 方法 / 结果 / 局限……）挑出关键句，并 **锚定到 PDF 原文位置** 标色 |
| ✍️ **批注 Highlights** | 你自己的高亮（**多种颜色**）+ 笔记，锚定在页面上并保存 |
| 🔗 **参考文献 References** | 解析文末参考文献，经 **Crossref / arXiv** 补全元信息，**每条可点击跳转** |
| 🔭 **学术搜索 Scholar** | 通过 **Semantic Scholar / arXiv** 找相关（related）论文，并一键 **导入** 到论文库 |
| 📚 **论文库 Library** | 通过 **arXiv id / DOI / URL / 上传 PDF** 导入，集中管理、可检索 |
| 🧩 **技能 Skills** | 发现并运行 **Claude / Codex 技能**（`~/.claude/skills`、插件、`$CODEX_HOME/skills` 等），作用于当前论文 |
| ➕ **加入会话** | 在 PDF 里或各面板里选中一段内容 → **一键送入 Chat**，让 AI 就这段内容回答 |
| 🎨 **主题** | 内置 **7 套配色**，在 Settings 里随时切换 |
| 🗣️ **语言可配置** | AI **回答语言** 与 **翻译目标语言** 都可在设置里配置 |

---

## 🚀 快速开始

```bash
cd /home/cjc/moonlight        # （它是 /root/autodl-tmp/cjc/moonlight 的符号链接）

scripts/setup.sh              # 首次：建后端 venv + 装依赖，装前端依赖并 build
scripts/run.sh                # 在 :8010 提供服务（前端已构建 + API，一个进程一个端口）
```

`setup.sh` 只需跑一次；之后每次启动用 `scripts/run.sh` 即可。启动后浏览器打开 `http://<host>:8010`，粘贴一个 arXiv id（例如 `1706.03762`）或上传一个 PDF，点开卡片就能读。

**端口 / 监听地址** 可用环境变量覆盖：

```bash
GLOSS_PORT=6006 GLOSS_HOST=0.0.0.0 scripts/run.sh
```

- `GLOSS_PORT` —— 服务端口（默认 `8010`）
- `GLOSS_HOST` —— 监听地址（默认 `0.0.0.0`，即对外可访问）
- `GLOSS_DATA_DIR` —— 数据目录（默认 `backend/data`）

> 想改代码热重载调试？用 `scripts/dev.sh`：后端 uvicorn `--reload`（:8010）+ Vite 开发服务器（:5173，自动代理 `/api`），改前端即时生效。

---

## 🖥️ 从自己电脑访问（服务跑在远程 AutoDL 上）

Gloss 通常跑在远程服务器（如 AutoDL）上，你要从 **自己电脑的浏览器** 访问它，有两种方式：

### 方式 A：AutoDL"自定义服务"映射 6006 端口

AutoDL 控制台的"自定义服务"只放行 **6006** 端口。把 Gloss 跑在 6006：

```bash
GLOSS_PORT=6006 scripts/run.sh
```

然后在 AutoDL 控制台点开"自定义服务"给出的访问链接即可。

### 方式 B：SSH 端口转发（推荐，稳定）

在 **你自己电脑** 的终端里运行（端口与主机来自 AutoDL 给的 SSH 登录指令）：

```bash
ssh -CNg -L 8010:127.0.0.1:8010 -p <SSH端口> root@<主机>
```

- `<SSH端口>` 和 `<主机>` 就是 AutoDL "SSH 登录指令"里的那两个值。
- 服务此时按默认在 `:8010` 跑即可（`scripts/run.sh`）。

保持这个终端 **一直开着**，然后浏览器打开：

```
http://localhost:8010
```

---

## 🧰 CLI

命令行是同一套后端的轻量封装，适合快速导入、终端速览与对话：

```bash
./gloss serve                  # 启动 web 应用（打印访问地址）
./gloss open <pdf|arxiv|doi>   # 导入 + 启动服务 + 打开浏览器
./gloss import <src>           # 把本地 PDF / arXiv / DOI 加入论文库
./gloss ls                     # 列出论文库
./gloss summarize <id|pdf|arxiv>   # 在终端打印一份速览
./gloss chat <id>              # 终端里的交互式对话（claude 风格）
./gloss skills                 # 列出发现到的 Claude / Codex 技能
```

例子：

```bash
./gloss open 1706.03762            # 打开《Attention Is All You Need》并启动阅读器
./gloss import paper.pdf           # 导入本地 PDF
./gloss summarize 2010.11929       # 终端速览一篇 arXiv 论文
./gloss chat <paper_id>            # 就某篇论文在终端里连续问答（空行退出）
```

---

## 🤖 AI 提供方与进阶设置

在 **Settings** 面板（或直接改 `backend/data/config.json`）里选择 provider：

| Provider | 说明 | 需要 key？ |
|---|---|---|
| `local_claude` | **默认**。调用本机 `claude` CLI，走订阅登录 | ❌ 免 key |
| `local_codex` | 调用本机 `codex` CLI，走 ChatGPT 订阅 | ❌ 免 key |
| `anthropic` | 官方 Anthropic API | ✅ 填 `api_key` |
| `openai` | 官方 OpenAI **或任意 OpenAI 兼容端点** | ✅ 填 `base_url` + `api_key` |

`openai` 这一项可指向 **本地 vLLM** 或本地 **claude_proxy**（如 `http://127.0.0.1:8899/v1`），从而完全离线用自己的模型。

**进阶设置**（每个 provider 都可单独配）：

- **模型**：`local_claude` 可填 `sonnet` / `opus` 等短名或完整 model id；`anthropic` 填 `claude-…`；`openai` 填对应模型名；`local_codex` 留空则用 codex 自己配置的默认模型。
- **思考深度 / reasoning effort**：
  - `local_claude` 的 `effort`：`""`（CLI 默认）/ `low` / `medium` / `high` / `xhigh` / `max`
  - `local_codex` 的 `effort`：`""` / `minimal` / `low` / `medium` / `high`
- **回答语言 `output_language`** 与 **翻译目标语言 `target_language`**：默认都是「中文 (Simplified Chinese)」，可在设置里改。

> Settings API 会对 key 做掩码处理（只回显是否已设置），`backend/data/` 整体已 gitignore，key 不会进版本库。

---

## 📚 使用指南 / 使用方式

一个典型的读论文流程：

1. **导入论文** —— 在 Library 里粘贴 arXiv id / DOI / URL，或上传 PDF；也可用 `./gloss import <src>`。
2. **打开阅读** —— 点开卡片进入阅读器，左侧是 PDF，右侧是 AI 面板。
3. **先速览再精读** —— 右侧标签页用 **总结 Summary** 判断价值、**研读笔记 Notes** 做结构化精读、**思维导图 Mind Map** 看全局结构（点节点看摘要与连接）。
4. **在 PDF 里选中文字** —— 弹出菜单里选：
   - 💡 **Explain** 解释这段公式 / 术语（KaTeX 渲染）
   - 🌐 **Translate** 翻译这段
   - 💬 **加入会话** 把这段送进 Chat 让 AI 就它回答
   - 🖍️ **高亮** 用喜欢的颜色标注 + 记笔记
5. **整段 / 整页翻译** —— 在 **Translate 面板** 按 **页码范围** 翻译；默认只显示中文，勾选 **"显示原文"** 看中英对照。结果逐句缓存、跨页复用，重复范围不会重复翻译。
6. **对话答疑** —— 在 **Chat** 里像问同事一样提问，基于全文 RAG 检索作答、流式输出；**每篇论文可开多个会话**，随时新建。
7. **理清引用** —— **References** 面板一键解析参考文献并经 Crossref / arXiv 补全，**每条可点击跳转**。
8. **顺藤摸瓜** —— **Scholar** 面板找相关论文，看到感兴趣的一键 **导入** 到论文库。
9. **跑技能** —— **Skills** 面板选一个 Claude / Codex 技能，作用在当前论文上运行。
10. **个性化** —— **Settings** 里换 **主题**（7 套配色）、改 **回答 / 翻译语言**、切换 **AI 提供方**。

> 生成类结果（**总结 / 笔记 / 导图 / 翻译 / 高亮**）首次生成后会 **持久保存**，重新进入论文不会重复生成，直接读缓存。

---

## 🏗️ 架构简述

```
backend/          FastAPI（一个进程挂载所有 /api/*，并托管已构建的前端 SPA）
  app/providers/  local_claude · local_codex · anthropic · openai · registry（LLM 抽象层）
  app/pdf/        PyMuPDF 解析（文本块 + bbox 坐标）+ 结构启发式（章节/引用/分句）
  app/features/   summarize · explain · translate · chat(RAG) · highlight · citations
  app/search/     scholar 检索 / 推荐（Semantic Scholar / arXiv）
  app/skills/     发现并运行 Claude/Codex 的 SKILL.md 技能
  app/library/    SQLite 库 + 导入器（arXiv/DOI/PDF）+ 服务
  app/routers/    papers · ai · citations · scholar · annotations · skills · settings
frontend/         React + Vite + pdfjs-dist + KaTeX + React Flow（build 到 frontend/dist，由后端托管）
cli/              gloss.py             scripts/  setup.sh · run.sh · dev.sh
```

**数据** 都在 `backend/data/`：一个 SQLite 库（papers / highlights / chats / messages / refs / cache）+ 每篇论文一个目录，含 `original.pdf` 与解析后的 `parsed.json`。

> 更深的设计说明（LLM 沙箱隔离、外网代理、坐标映射等）见仓库根目录的 **`CLAUDE.md`**。

---

## 💡 小贴士

- **本地 `claude` 在隔离 HOME 下运行**：Gloss 给它一个沙箱 `HOME`（`.claude-home/`），**只软链登录凭证**，不会串进你个人的 `~/.claude/CLAUDE.md` / memory / settings —— 论文的回答只关于论文，不会被你的其他指令污染。`codex` 同理有独立的干净工作目录。
- **外部检索走 HTTP 代理并优雅降级**：References、Scholar 等外网请求统一走机器的 HTTP 代理；一旦某个站点连不上（离线），会 **优雅降级** 到本地已解析的数据，不会整页报错。
- **生成结果持久缓存**：总结 / 笔记 / 导图 / 翻译 / 高亮 首次生成后落盘保存，重进论文直接复用，不重复消耗算力与额度。
- **重活都放数据盘**：venv、`node_modules`、论文库与数据库都在数据盘 `/root/autodl-tmp` 上（系统盘小，别把这些放系统盘）。
