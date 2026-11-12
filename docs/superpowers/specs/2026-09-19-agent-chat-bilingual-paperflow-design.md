# 设计：对话式操作 + 双语对照批注 + PaperFlow 外部集成

日期：2026-09-19
状态：待实现

## 1. 目标与非目标

### 目标

1. **Agent Chat**：在现有 `ChatPanel` 里用自然语言下指令，AI 判断意图并执行动作（生成笔记、改标注样式、回写 PDF），结果以卡片形式出现在对话流里，可撤销。
2. **双语对照批注**：把证据批注正确落到 PaperFlow 产出的双语文件上——`-dual.pdf`（原文页 / 译文页交替）与 `-side_by_side.pdf`（同一页左右分栏）。
3. **PaperFlow 外部集成**：Gloss 调用本机 PaperFlow 生成双语版，不内嵌 pdf2zh。

### 非目标（明确排除）

- Zotero `.xpi` 插件（内部 API）——独立项目。
- `-mono.pdf` 的精确定位批注（版面被重排，rects 无意义）。
- 把 pdf2zh 装进 Gloss venv（依赖 torch / onnxruntime / doclayout_yolo，会拖垮体积与启动）。
- PaperFlow 术语表（glossary）编辑。

### 默认行为必须保留

`NotesPanel` 原有按钮（生成 / 复制 / 下载 / 导出 Zotero / 回写 PDF）全部不动。不带指令等于现有默认模板。

## 2. 现状（代码事实）

- 笔记生成：`backend/app/features/notes.py`，固定 `SYSTEM` + user prompt，结果 `{markdown, evidence}`，缓存键 `notes2:{lang}`。
- 任务调度：`backend/app/tasks/manager.py:479` 的 `_dispatch` 调 `notes_feat.build_notes`，不透传自定义参数；`cached_result`（`:261`）读同一缓存键。
- 批注：`backend/app/pdf/annot_writer.py`，`target_path()`（`:53`）= `source_pdf or 内部副本`；`add_evidence` 写 `/T = "Gloss Evidence"` 的原生批注，颜色 `#ffd400`。
- 聊天：`ChatPanel.tsx` + `features/chat.py`（BM25 检索 + 流式）+ `/api/papers/{id}/chats`、`/chats/{id}/messages`。`store.add_message(chat_id, role, content, attachments)`，消息没有动作字段。
- 迁移方式：`store.py:150-197` 用 `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`。
- PaperFlow 版面：`core/site-packages/pdf2zh/high_level.py:701-703`

  ```python
  doc_en.insert_file(doc_zh)
  for id in range(page_count):
      doc_en.move_page(page_count + id, id * 2 + 1)
  ```

  dual 第 `2p` 页就是原文第 `p` 页（字节级复制，页面尺寸一致），第 `2p+1` 页是译文页。
- PaperFlow CLI：`pdf2zh <files> -o <dir> -li en -lo zh -s google -t 4`，产出 `-mono.pdf` 与 `-dual.pdf`。
- PaperFlow HTTP：`backend.py` 的 Flask + celery + redis，默认不随桌面版启动，只能作为可选通道。

## 3. 项目 1：Agent Chat

### 3.1 后端

**新模块 `backend/app/features/agent.py`**

```python
ACTIONS = ("notes", "style", "write_pdf", "none")

async def route(message, *, paper_id, has_notes, style, language) -> dict:
    """意图路由。返回 {action, instruction, style, reply}。"""

async def execute(paper_id, action, params) -> dict:
    """执行动作，返回 {ok, summary, undo, data}。"""
```

- 用现有 `json_complete(system, user, SHAPE, ...)` 产出结构化结果，不引入 tool-calling 框架。
- `action="none"` 或解析失败时降级为普通 chat 回答（走现有 `features/chat.py`）。
- 三个动作：`notes`（调 `build_notes(instruction=...)`）、`style`（写入全局配置 `annotation_style`，不做 per-paper 样式）、`write_pdf`（调 `annot_writer.add_evidence(style=..., target=...)`）。

**`features/notes.py` 改动**

- `build_notes(..., instruction: str | None = None)`：指令非空时追加到 `SYSTEM` 末尾与 user prompt。
- 缓存键：无指令保持 `notes2:{lang}`（旧缓存继续命中）；有指令用 `notes2:{lang}:{sha1(instruction)[:8]}`。

**`tasks/manager.py` 改动**

- `_dispatch`（`:479`）传 `instruction=record.input.get("instruction")`。
- `cached_result`（`:261`）同样按 instruction 取缓存，否则恢复任务会拿错结果。

**`annot_writer` 改动**

- `add_evidence(paper_id, evidence, *, style=None, target="auto")`，`style = {color, type}`，`type` 取 `highlight | underline | squiggly | strikeout`。
- 批注 `/Contents` 写 `[E1] why`。

**存储**：`messages` 表新增 `action TEXT`（可空 JSON），按 `store.py` 现有 PRAGMA 方式迁移，刷新后动作卡片可还原。

**端点**：`POST /api/papers/{paper_id}/agent`，body `{chat_id, content}`，返回 `{reply, action, result, message}`。长动作（生成笔记）复用 `AITaskManager` 的任务态。

### 3.2 前端 `ChatPanel.tsx`

- 输入框上方一排动作 chips（生成笔记 / 换成黄色高亮 / 写回 PDF）：点击填入指令模板，不强制。
- assistant 消息渲染 `AgentActionCard`：动作名 + 结果摘要 + 撤销（仅 `write_pdf` 可撤销，调 `annot_writer.remove_evidence`；`notes` 不做撤销，重新生成即可）。
- 动作完成后通知 store 刷新 `NotesPanel` 与 PDF 批注层。

### 3.3 错误处理

- 路由失败或 JSON 解析失败时降级为普通回答，不把错误抛给用户。
- `write_pdf` 前检查 `annot_writer.enabled()`；未开启给提示而非静默失败。
- 写 PDF 抛异常时在回复里带上原因，对话可继续。

### 3.4 测试

- `tests/test_agent_routing.py`：fake provider 返回固定 JSON，断言 action 解析、参数透传、`action="none"` 降级。不真调 LLM。
- `tests/test_notes_instruction.py`：不同 instruction 产生不同缓存键；空 instruction 沿用 `notes2:{lang}` 且能读到旧缓存。

## 4. 项目 2：双语对照批注

### 4.1 两类页面，两种难度

dual 是原文页与译文页交替（`high_level.py:701`），两者难度完全不同：

| 页 | 来源 | 版面 | 定位方式 |
|---|---|---|---|
| dual 第 `2p` 页 | 原文页原样复制 | 与原文 PDF 一致 | 页码 `p → 2p`，rects 直接复用 |
| dual 第 `2p+1` 页 | 译文页 | 被 pdf2zh 重排 | 几何投影 + 块并集 |
| mono 第 `p` 页 | 译文页 | 被重排 | 同上，页码 1:1 |

用户观察到的现象（一个段落被拆成多个小块）**只发生在译文页**，原文页不受影响。

### 4.2 新模块 `backend/app/pdf/bilingual.py`

```python
def kind(path) -> str                                  # "original" | "dual" | "mono"
def dual_path_for(path) -> Path | None                 # xxx.pdf 与 xxx-dual.pdf 双向探测
def map_evidence(path, evidence) -> list[dict]         # 原文页
def map_evidence_to_translated(path, evidence) -> list[dict]  # 译文页
```

**原文页（精确）**：页码 `p → 2p`，先校验页面尺寸（`|Δw| < 1` 且 `|Δh| < 1`）才复用 rects；尺寸不符回退 `ingest.locate_text(path, quote)`；仍失败标记 `page=None`（与现有 unlocated 语义一致，UI 已能处理）。

**译文页（近似，sidecar 缺失时的兜底）**：

1. 原文 rects 按页面宽高归一化成比例坐标。
2. 投影到译文页得到候选区，垂直方向适度外扩以容忍重排位移。
3. 用 `page.get_text("blocks")` 取译文页全部文本块，做**对齐聚类**：左边界接近、且纵向间距小于约 1.5 倍行高的相邻块归为同一段落簇。pdf2zh 排版保持段内各行左对齐、行距一致（`converter.py:416` 起），该特征可靠，能区分"同一段落的多行"与"相邻的另一段"。
4. 用候选区筛选命中的簇，取簇内**全部行块**作为 rects——这些就是被拆开的小段。一个证据对应多个矩形，数据模型已支持（`notes.py:103` 的 `rects` 是列表）。
5. 一个簇都没命中 → 降级为投影矩形本身（粗标注，覆盖大致区域）。

注意译文可能溢出原文 bbox（pdf2zh 只把行距压到 1.0，`brk=False` 时甚至不折行），所以聚类优先于纯投影：先按版面特征还原段落，再用投影限界，而不是反过来。

**不采用的方案**：把 quote 译成中文再去译文页 `search_for`。pdf2zh 的译文措辞与 Gloss 翻译结果不可能逐字一致，匹配率过低。

### 4.3 写入目标

- `EvidenceBody`：
  - `target`：`auto | original | dual | mono | both`
  - `side`：`original | translated | both`——写双语文件时落在原文侧（dual 的 `2p`，side_by_side 的左半栏）还是译文侧（dual 的 `2p+1`，side_by_side 的右半栏），或**两侧都落**
- `auto`：存在 dual 就写 dual（按 `side`），否则写原文。
- `both`：原文与译文**各写一份**，返回值带 `targets` 列出实际写入的文件；没有译文文件时退化成只写原文。
- `annot_writer.count_evidence` / `remove_evidence` 增加 `path`，所以查询与清除都作用于**所选目标**，而不是永远只认库内副本。否则写进 dual 之后 GET 报 0、DELETE 又清不掉。

**两侧都写（用户要的实际效果）**：一条批注必须是**一对**——原文一处、译文一处，**定位始终从原文侧出发**（quote 与 rects 都是在原文上找到的）。译文侧的位置由 sidecar 给出，没有 sidecar 时退回聚类/投影。

双语文件有两种版面，配对的方向不同：

- **dual**（`NAME-dual.pdf`）：原文页与译文页交替，所以对开阅读时左页原文、右页译文——配对页就是 `2p+1`（`bilingual.mirror_rects`）。
- **side_by_side**（`NAME-side_by_side.pdf`）：原文与译文**并排在同一页上**，左半英文、右半中文。PaperFlow 按原尺寸并排放，页宽翻倍、高度不变，所以**左半就是原页的精确复制**（坐标一模一样：实测左半 x 80..533 与原文页 x 80..533 相同），右半是重排的中文，偏移正好半页宽（实测 612.0）。配对就是**同页内平移一个半页**（`bilingual.side_by_side_rects`）。

用户实际用的是 side_by_side（"左边标注、右边中文没反应"里的"左边/右边"是**同一页的两个分栏**，不是两页）——最初的规格只考虑了 dual，这一步补上。

实现放在写入层而不是映射层，因此它同时覆盖两类批注：

- 证据批注：`side="both"` 时 `add_evidence(mirror=True)`。
- 用户手动画的高亮：写入目标本身就是 dual 文件时自动镜像（`_mirror_map`）——例如把论文链接到 Zotero 里的 dual 附件。此时页码还要先 `p → 2p`（`_page_in_dual`，用"页数恰为 Gloss 副本两倍"确认页码基准是原文页；确认不了就不镜像，宁缺勿错）。

镜像对的生命周期：镜像与主体内容相同，因此按内容在配对页上找到对方（`_partner_annots`）——删除、改色、改备注都会同步到另一页，不会留下孤儿。注意必须用**同一个 page 对象**删除（PyMuPDF 不允许跨 page 对象删标注）。

**认出双语文件**（这是"导入到 Gloss 里读"这条路径的关键）：双语文件有两种来法，Gloss 都得认得：

1. **外部产物**：PaperFlow 生成的 `NAME-dual.pdf` 躺在源 PDF 旁边，按文件名探测（现有 `bilingual.kind`）。
2. **直接导入**：读者把双语文件拖进 Gloss 读。Gloss 把每份导入一律存成 `original.pdf`，`-dual` 后缀**在落盘那一刻就丢了**，名字再无可用信息。

所以导入时（`service.create_from_pdf_bytes`）先把到达时的文件名判一次，存进 `papers.pdf_kind`；判不出的（改过名、或导入时还没这一列的老论文）再看页面内容（`bilingual.detect_kind`，抽样前 20 页，结果缓存进同一列，只看一次）：

- **side_by_side**：页内左右两半，一半是译文、一半几乎不含中文（`side_by_side_shift`）。两个附加条件都是实测逼出来的：① **两半都得有字**（`HALF_CHARS_MIN`）——否则一列排版的纯中文页会被当成对开；② **逐词统计而非逐块**——左右两列可能被 PyMuPDF 并进同一个文本块，按块划分会把右半的字算到左半头上。
- **dual**：页间奇偶交替，奇数页的 CJK 占比须明显高于偶数页。

判定特意做成**单向**的。普通英文论文（两边都 ≈0）和纯译文 PDF（两边都高、彼此相仿）都不会命中。**漏判只是少一个镜像，误判会把每一条高亮都放错页**，宁可漏。

分栏的 CJK 占比门槛比整页低（`CJK_SHARE_MIN_SIDE=0.2` 对 `CJK_SHARE_MIN=0.3`）：译文列里夹着公式、代码和英文术语，实测某些页只有 0.25。补偿条件是**另一侧必须几乎不含中文**（≤0.1）——实测原文列是 0.00，这个信号比绝对值强得多。

由此分出几种页码基准：读的**就是**双语文件时（导入型），页码已是该文件页码，直接用；读的是原文、写的是外部双语文件时，dual 的源页 `p` 是它的 `2p`，side_by_side 则是 `p`（页数与源相同）。两者都用"页数对得上"确认，确认不了就不镜像。

**已写过的批注补镜像**：`add_evidence` 在主体已存在时仍检查译文侧有没有配对的那一条，有就补上。所以用户上次导出的 24 条证据不必删掉重来，再导出一次中文侧就有了。幂等靠内容判重：side_by_side 的镜像与主体**同页且内容相同**，所以判据是"该页上这样说的一共有几条"（≥2 即已齐全），而不是"有没有"。

**一份证据只产出一英一中，不叠加**：`add_evidence` 增加按位置去重（`_zone_key`，取并集 bbox）。同一段落英文一句、中文一句是两条证据，落到译文页却是同一个段落矩形——第二条按位置判重跳过，不会两条高亮糊在一起。重复导出也靠它（连同原有的内容判重）保持幂等。

**两处偏离规格**（实现时确认更合理）：

- 原计划 `papers` 表新增 `dual_pdf TEXT` 缓存双语版路径。改为每次按文件名探测（`bilingual.dual_path_for`）——译文是用户随时用 PaperFlow 生成的外部产物，缓存必然过期，而探测只是一次 `Path.is_file()`。
- 未加 `style` 参数。证据批注统一用高亮（`_create` 的现有行为），且没有 UI 入口，需要时再加。

### 4.4 端点与前端

- `POST /api/papers/{id}/evidence/pdf`：`EvidenceBody` 的 `target`/`side`；返回新增 `targets`（实际写入的文件）。
- `GET /api/papers/{id}/evidence/pdf`：`?target=&side=`（默认 `auto`/`original`），`embedded` 按所选目标计数；`dual`/`mono` 各自返回 `{available, path}`，dual 额外给 `sidecar`（是否有 PaperFlow 映射表）。
- `DELETE /api/papers/{id}/evidence/pdf`：同样接受 `?target=&side=`，只清除所选目标。
- `NotesPanel`「回写到 PDF」旁的下拉：自动 / 原文 / 双语·原文+译文（左右都有）/ 双语·只写原文页 / 双语·只写译文页 / 纯译文 / 两个文件都写，默认 `auto:both`（有双语就两侧都写）；悬停提示说明映射表是否可用（精确 vs 近似）。
- 译文页会产生多矩形高亮，UI 渲染与跳转沿用现有多 rects 逻辑，不改前端模型。

### 4.5 sidecar 映射（PaperFlow 侧已完成，真机验证通过）

pdf2zh 排版时同时掌握原文段落 bbox（`pstk[id]`）与它生成的每个译文文本对象 bbox，因此在排版循环里顺手记录即可导出精确映射，无需几何近似。已在 `d:/03-Codes/pdf2zh-desktop`（PaperFlow）实现：converter.py +53 行、high_level.py +102 行、0 删除，翻译与排版逻辑未动，只额外落一个 `{文件名}-map.json`：

```json
{"version": 1, "source": "xxx.pdf", "coord": "fitz",
 "pages": [{"page": 0, "width": 595.2, "height": 841.9,
            "paragraphs": [{"orig": [x0,y0,x1,y1],
                            "trans": [[x0,y0,x1,y1], "..."]}]}]}
```

约定：`page` 为**原文页码（0-based）**（`high_level.py:538` 把 `page.pageno` 覆盖为 `enumerate` 索引并直接当 `doc_zh[...]` 用），`coord="fitz"` 表示左上原点、y 向下；坐标翻转在 PaperFlow 内部完成（`_para_map_to_fitz`，以 `doc_zh` 的 `page.rect` 为准），Gloss 拿到即用。

**实测**（假 translator 跑通管线，样本 2 页 / 5 页）：2260 与 6953 个矩形，退化 0，y 越界 0.00；用 `get_textbox` 在译文页取词命中 100% 与 99.47%（未命中的全是宽约 2.6pt 的空白公式字符）；`orig` 在原文 PDF 取词 100%；相邻行间距 p50 ≈ -1.1pt（微重叠）、左边界偏差 p50 = 0.00；x 越界 0.63%~1.29%（原文段落 `brk=False` 时译文不折行，pdf2zh 本身就画到边界外）。

Gloss 侧的读取优先级：

1. sidecar 存在 → 查表（精确）。
2. sidecar 不存在 → 退回 4.2 的对齐聚类（近似）。

查表结果还要过三道处理才适合写批注——都是实测数据倒逼出来的：

- **行合并**（`_merge_lines`）：sidecar 按"每个文本对象"记录，公式字符各占一个对象，实测平均**每段落 65 个矩形**。照原样写会让一个证据挂上百个高亮、糊成一片，正是要消除的"很多小块"。纵向重叠超过较短者 50% 的矩形并成一行；相邻行只重叠约 1pt（占行高 6%），不会被误并。一段回到若干整行。
- **页面钳制**（`_clamp`）：把越界矩形裁到页面 rect 内，避免高亮画到页外（见上，越界约 1%）。
- **覆盖率匹配**（`_match_paragraph`）：不用 IoU。证据常只是一个短语，与整段的 IoU 约 0.1，永远匹配不上；改为"段落覆盖了多少证据框"（≥ 0.35），短语落在段内即得 1.0。

读取时按文件名探测 `{pdf_stem}-map.json`，与 dual 探测逻辑并列放在 `bilingual.py`。

已知风险：

- PaperFlow 的 `core/site-packages` 是 vendored 目录，更新/重装会覆盖改动，因此 Gloss 必须能在 sidecar 缺失时正常工作（这就是保留近似路径的原因）。
- 记录默认常开、无页数上限（30 页约 3 万矩形），与排版同线程。开销只是每段一次 dict append，未做上限；若将来出现超大文档再评估。
- sidecar 以 PaperFlow 收到的文件名命名，URL 下载的 PDF 会是临时名，与源 PDF 不同名。Gloss 在按名探测落空时，接受同目录内**唯一**的 `*-map.json`（附件目录通常只放一篇论文）；存在多个则不猜，退回聚类。

### 4.6 测试

- `tests/test_bilingual_mapping.py`，全部用 fitz 造假 PDF，不真跑 pdf2zh：
  - 假 dual（2N 页、尺寸一致）：断言 `p → 2p` 且 rects 复用。
  - 尺寸不一致：断言回退 `locate_text`。
  - 译文页块并集：造一页内含 3 个相邻小块（模拟段落被拆开），断言投影候选区命中 3 个块、返回 3 个 rects。
  - 无命中：断言降级为投影矩形。
  - sidecar 碎片合并：一段给 60 个同行碎片 → 断言并成 3 行、且行宽覆盖整行而非单个碎片。
  - 短语命中：证据只是段内一句短语时仍能查到该段（覆盖率匹配，IoU 会漏）。
  - 越界钳制：sidecar 矩形超出页面 → 断言裁到页面宽度。

## 5. 项目 3：PaperFlow 外部集成

### 5.1 新模块 `backend/app/paperflow.py`

```python
def detect() -> dict    # {available: bool, mode: "cli"|"http"|None, detail: str}
async def translate(pdf_path, *, lang_out="zh", service="google", pages=None) -> dict
```

- 探测顺序：设置里的显式配置，然后 HTTP 探活，最后 CLI（`python -m pdf2zh.pdf2zh --version`，或 PATH 上的 `pdf2zh`）。
- CLI 优先：HTTP 通道依赖 celery + redis，桌面版默认不跑；CLI 只需找到解释器与包路径。
- 设置项：`paperflow.cli_path`、`paperflow.url`，用户可填，或由 Gloss 探测常见安装位置。

### 5.2 执行与状态

- `asyncio.create_subprocess_exec`，输出目录为源文件同目录。
- 完成后把 `-dual.pdf` 路径写入 `papers.dual_pdf`，UI 提示「双语版已生成」。
- 进度只报 `running / done / failed`（CLI 不提供可靠进度，不做百分比）。
- 超时与非零退出时捕获 stderr 摘要作为失败原因。

### 5.3 UI

- 工具栏加「生成双语版」。未检测到 PaperFlow 时隐藏，而不是灰掉报错。
- 生成成功后，项目 2 的批注目标选择里自动出现「双语」。

### 5.4 测试

- `tests/test_paperflow_detect.py`：monkeypatch `subprocess`，断言探测顺序、CLI 参数拼装、失败时的返回结构。不真跑 pdf2zh。

## 6. 实施顺序

1. **项目 1（Agent Chat）**：独立，收益最大，先做。
2. **项目 2（双语批注）**：独立，UI 上受益于项目 3 产出的 dual 文件，但不阻塞。
3. **项目 3（PaperFlow 外部集成）**：依赖项目 2 的 `dual_pdf` 落库与批注目标选择。

## 7. 风险与开放问题

- **dual 版面假设**：`2p` 映射来自 pdf2zh 当前实现。若用户启用 `--compatible`（PDF/A）或 OCR 模式，页面尺寸可能变化，靠 4.1 的尺寸校验兜底回退。
- **意图路由误判**：降级路径是普通回答，误判代价可控；动作执行前在卡片上展示将要做什么，用户可撤销。
- **PaperFlow 定位**：用户机器上的 pdf2zh 可能是打包版而非 pip 包，CLI 探测可能失败。因此设置项允许手填路径，探测不到时功能隐藏而不是报错。
- **翻译耗时**：整篇翻译可达数分钟，Gloss 侧只报三态进度，不做百分比。
