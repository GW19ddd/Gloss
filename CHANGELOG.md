# 版本记录 / Changelog

本项目 **Gloss（旁注）** 的更新记录。English summary follows each section.

---

## v0.1.0 — 2026-07-17

首个完整版本：从对 [Moonlight](https://www.themoonlight.io/) 的本地重构起步，逐步长成一个功能完整的本地 AI 论文阅读器。
*First full release — a complete local AI paper reader.*

### 📖 阅读器 / Reader
- 采用 **pdf.js 官方文本层**，选中体验与浏览器一致（修复部分文本选不中）。*Official pdf.js TextLayer for browser-quality selection.*
- 渲染**超采样**（≥2×）更清晰；修复"只有第一页缩放"的 bug。*Supersampled render; fixed zoom-only-page-1.*
- **阅读模式**：正常 / 护眼(Sepia) / 夜间(反色)。*Reading modes: Normal / Sepia / Night.*
- 大纲栏可**拖动、折叠**并修正章节标题识别；PDF 与侧栏之间**可拖动分隔**；深色滚动条；**显示/隐藏批注**开关。
- 选中文字弹出菜单：Explain / Translate / 加入会话 / 高亮，紧贴选区显示。

### 🌐 翻译 / Translate
- **逐句翻译 + 持久缓存 + 跨页复用**，重进自动恢复；每句独立方框，默认只显示中文、可切换显示原文。
- **点击译文 → 在 PDF 中闪烁定位**原文。*Click a sentence to flash-locate it in the PDF.*
- **从 LaTeX 源翻译（arXiv）**：按解析出的章节（Abstract / Results …）逐节翻译或一次全部，补齐 PDF 提取漏掉的文本。*Translate arXiv LaTeX source by section or all — nothing missed.*

### 💬 对话与面板 / Chat & panels
- 对话**按论文保存历史**、支持**多会话**、可新建/删除；**加入会话**（PDF 或各面板选中→送入 Chat 并作答）。
- **速览 / 研读笔记 / 思维导图（交互式 React Flow：类型化节点+摘要+详情抽屉）**；LaTeX 公式用 KaTeX 正确渲染。
- **参考文献**解析+补全+可点击；**学术搜索/相关推荐**；**技能**运行 Claude/Codex skills。

### 🧩 arXiv
- **TeX 源码标签**：读取 arXiv 的 LaTeX 源（精确、无提取损失）。*Read arXiv LaTeX source in a TeX tab.*

### 🤖 提供方 / Providers
- `local_claude`（默认，免 key）/ `local_codex`（免 key）/ `anthropic` / `openai`，后两者均可填 **base_url**（兼容端点/代理）。
- 进阶设置：模型 + 思考深度（effort）；**测试连通性**按钮。*Model + reasoning effort; a Test-connection button.*

### 🎨 界面 / UI
- **7 套配色主题**；**界面语言**默认英文、可在设置切换中文（仅界面文案，内容/翻译按你的语言设置）。
- 品牌更名 **Moonlight → Gloss（旁注）**，新 logo 与封面海报。

### ⚙️ 质量 / Quality
- **异步操作不被打断**：总结/笔记/导图/翻译/解析/学术检索在切换标签后仍继续。*Long ops survive tab switches.*
- **侧栏常驻**：切换标签保留滚动位置与思维导图视图。*Panels stay mounted — scroll & mind-map viewport preserved.*
- 生成结果持久缓存，重进不重生成。

---

> 完整功能说明见 [README.md](./README.md) / [中文文档](./README.zh.md)。
