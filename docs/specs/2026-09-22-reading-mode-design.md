# 阅读模式（Reading Mode）设计规格

日期：2026-09-22
状态：待批准

## 概述

给 Gloss 增加一个「阅读模式」：把双栏排版（IEEE / ACM）的论文 PDF 重排成单栏、可缩放的连续文本视图，像读 Word 文档一样阅读，并在顶部切换**原文 / 译文**。

参照：Acrobat 的 Reading Mode、以及把 PDF 重排成 Markdown 的 Zotero 插件。核心是**重排（reflow）**，不是翻译。

## 目标用户与问题

读论文的人。双栏 PDF 在屏幕上是为打印排版设计的：字号小、两栏来回跳、页边距浪费、放大就得横向拖。长时间阅读很累，Gloss 又不能放弃 PDF 原有的标注与证据定位。

## 用户故事

1. 我在专注模式里读一篇双栏论文，点「阅读模式」→ 全屏打开单栏重排视图，字号可放大，纵向滚动即可读完整篇。
2. 重排后的文字顺序正确：左栏从上到下读完，再接右栏，而不是左右横跳。
3. 页眉页脚、页码、行号不出现在正文流里。
4. 被换行打断的段落合并成完整段落；行尾连字符（hyphenation）正确拼接。
5. 顶部切到「译文」→ 已翻译的句子显示译文，未翻译的句子保留原文，可一键翻译整篇。
6. 在阅读窗里选中一段文字 → 复用现有的「解释 / 翻译 / 加入聊天」。
7. 关闭（Esc 或按钮）回到原来的 PDF 视图；重排结果已缓存，第二次打开秒开。

## 功能需求

### 功能 1：后端重排服务

新增 `backend/app/pdf/reflow.py`：

- `build_reading_doc(paper_id, lang) -> ReadingDoc`
- 输入取 `annot_writer.target_path(paper_id)` 的 PDF（内部副本或关联的外部原件，二选一逻辑已存在）
- 布局分析步骤：
  1. **分栏检测**：按文本块 bbox 的 x 中心聚类；出现两个明显峰且间距显著 → 判为双栏，产出列边界。复用 `pdf/bilingual.py` 已有的列几何工具（`_column_offset` / `_column_lines`），不另写一套
  2. **阅读顺序**：按 (列, y, x) 排序，左列自顶向下接右列
  3. **页眉页脚剔除**：出现在页面顶部/底部固定区域、且在多数页重复出现的块 → 丢弃（保留第一页的标题块）
  4. **段落合并**：垂直间距小于阈值且字号一致 → 并为一段；行尾 `-` 视为连字符拼接；合并只发生在同页内，跨块合并时各句保留自己的 `rects`
  5. **标题识别**：字号显著大于正文且文本较短 → heading
  6. **图片/表格**：按原页区域裁剪为图片嵌入（`ingest_pdf` 已产出 `images`）
- 输出**结构化 JSON**，不拼 HTML 字符串（避免 XSS，也便于前端渲染与复用）：

```python
ReadingBlock = {
  "type": "p" | "heading" | "figure" | "caption",
  "page": int,
  "bbox": [x0, y0, x1, y1],
  "image": str | None,     # figure 的图片相对路径
  "segments": [Segment],   # p/heading 为句子片段序列；figure/caption 见 text
  "text": str,             # 纯文本全文（供复制/无障碍），figure 为空
}
Segment = {
  "text": str,             # 句子文本（已按行拼接、去连字符）
  "sent_id": str,          # 与翻译缓存 _sid 一致
  "rects": [[x0, y0, x1, y1], ...],  # 该句在 PDF 中的行片段矩形（页面坐标，一行一个）
}
```

句子在 PDF 里往往跨行、跨列，`rects` 按阅读顺序给出它占用的每段行矩形 —— 这与 Zotero 高亮标注的存储结构同构（页面坐标系、一行一个 rect 的矩形数组）。
- 结果缓存到 `paper_dir(paper_id)/reading.json`；源文件 mtime 变化时重建。
- **双语 PDF**：复用 `bilingual.detect_kind()` —— `side_by_side` 的页面只用原文半边做布局分析（译文半边是同一篇论文的第二遍，读它就重复了；译文在阅读窗里按需切换），`dual` 的交替译文页直接跳过。坐标始终是整页坐标，否则高亮会写错页。块的 `page` 记 PDF 页号，另有 `source_pages` 列出承载正文的页，供「翻译整篇」分批使用。

### 功能 2：后端接口

`routers/papers.py` 新增：

- `GET /api/papers/{paper_id}/reading?lang=zh` → `ReadingDoc`（含 `translated: bool` 标记各块译文是否就绪）

### 功能 3：前端阅读窗

新增 `frontend/src/components/ReadingMode.tsx`：

- 全屏浮层，照 `ExitConfirmDialog.tsx:64-65` 的 `.exit-dialog-backdrop` 模式自建（项目无通用 Modal 组件）
- 顶部工具条：原文/译文 切换、字号 A- / A+、关闭；Esc 关闭（`ExitConfirmDialog.tsx:37-43` 已有 Esc 处理写法）
- 正文区渲染 `ReadingBlock`（React 元素，非 `innerHTML`）
- 入场按钮放在 `PdfViewer.tsx:694-702` 的 `focus-btn` 旁边

### 功能 4：译文切换

- 复用 `features/translate.py` 的句子级缓存 `senttrans:{lang}`（`{page, original, translation}`）与 `paper_sentences()` 的句子切分
- 重排块每个句子片段携带 `sent_id`（即 `_sid`），译文模式按 id 取译文替换；未命中的句子保留原文
- 提供「翻译整篇」，复用现有 `translate_range()` 逐句批翻译

### 功能 5：选中交互 + 高亮 / 笔记（对齐 Zotero reader 的机制）

Zotero 内置阅读器（pdf.js fork）里，高亮标注 = 页面坐标系下「一行一个矩形」的 rects 数组；选取时矩形从文本层 DOM 的 `Range.getClientRects()` 现场算出，不需要字符级坐标表。阅读窗复刻同样的机制，只是文本层由我们自己搭建：

- **带坐标的文本层**：段落按 `segments` 渲染成连续 `<span>`（`data-page`、`data-sent-id`），句子内按行片段布局
- **选取 → 矩形**：`onMouseUp` + `window.getSelection()`，取选区覆盖的 span 集合（写法照 `PdfViewer.tsx:371-421` 的纯 DOM 部分）；行内多句共享一行时按字符占比截取该句矩形的 x 区间，得到与 Zotero 同构的 rects
- **写回**：rects 原样传入现有 `addUserHighlight` / `noteSelection`（`store.ts:470+`），高亮照常写入 PDF 标注体系（`page + rects`）
- **回显**：渲染时用 `annot_reader.list_annotations()` 的高亮 rects 与句子 rects 求交（中心点相交即命中），命中的 span 加高亮背景色；笔记沿用现有笔记面板
- **其余动作**：解释 / 翻译 / 加入聊天走 `store.askAboutText({ text, page, rects })`（`store.ts:455-461`）

## 非目标（明确不做）

- **公式重排**：数学公式按文本提取必乱，退化为所在区域的文本；不做 LaTeX 还原
- **表格结构化**：表格整块裁为图片
- **移动端布局**、**导出重排结果**

（高亮/笔记已纳入范围，见功能 5。）

## 关键决策

| 决策 | 选择 | 理由 |
|---|---|---|
| 输出形态 | 结构化 JSON 而非 HTML 字符串 | 前端用 React 渲染天然转义，无 XSS；译文切换只需替换字段 |
| 高亮坐标 | 句子级 rects（Zotero reader 同构） | 选取时从 DOM span 现场算矩形，行内多句按字符占比截取；无需字符级坐标表 |
| 分栏检测 | 复用 `bilingual.py` 列几何工具 | 已按列切分/行聚类，避免重复实现 |
| 输入源 | `annot_writer.target_path()` | 已有「外部原件优先、否则内部副本」的统一逻辑 |
| 译文粒度 | 句子级缓存 | 与现有翻译管线一致，无需新的对齐机制 |
| 缓存 | 落盘 `reading.json` | 重排耗时，二次打开应秒开 |

## 风险

- **重排质量依赖 PDF 质量**：扫描件无文本层 → 直接提示「该 PDF 无文本层，无法重排」，不做 OCR
- **复杂版面**（跨栏图表、边栏、脚注双列）可能顺序错乱 → 首版接受不完美，按块级 bbox 兜底
- **行内多句的矩形是估算值**（字符占比截取），高亮边界可能与 PDF 视图的精确高亮差几像素 → 可接受，Zotero 的行级高亮同样是矩形并集
- **PDF 被占用**：沿用 `pdf_io.open_path()` 的带锁打开

## 开放问题

1. 阅读窗里是否要显示页码分隔（便于对照原 PDF）？倾向：不显示，保持连续阅读感
2. 译文未就绪时，是「保留原文」还是「自动后台翻译全文」？倾向：保留原文 + 显式按钮，避免意外产生大量 token 消耗

## 成功标准

1. 一篇双栏 PDF 打开阅读模式，左栏内容完整先于右栏内容，无左右横跳
2. 页眉页脚不在正文流中；段落完整不被换行打断
3. 字号可调节，正文随窗口宽度重排
4. 已翻译的论文切到译文，段落顺序与原文一一对应
5. 选中文字可解释 / 翻译 / 加入聊天
6. 在阅读窗里选一段文字点高亮 → PDF 视图对应位置出现高亮标注；反向：PDF 里已有的高亮在阅读窗中以背景色显示
7. Esc 关闭回到 PDF 视图；第二次打开耗时 < 1s
