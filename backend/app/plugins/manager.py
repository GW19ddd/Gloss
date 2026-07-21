"""Safe, manifest-driven plugin installation and execution.

Gloss plugins are declarative paper-analysis modules. They may read the current
paper and request an AI completion when those permissions are declared, but they
do not execute downloaded Python or JavaScript inside the desktop application.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..config import PLUGINS_DIR, output_language
from ..features.common import text_complete, truncate_to_tokens
from ..library import store
from ..platform_support import read_utf8_text

_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][a-zA-Z0-9.-]+)?$")
_ALLOWED_PERMISSIONS = {"paper:read", "ai:complete"}
PLUGIN_API_VERSION = 1
CONTRIBUTION_POINTS = [
    {
        "id": "paper.sidebar.panel",
        "status": "stable",
        "description": "Adds a manifest-defined panel to the paper reader sidebar.",
    },
    {
        "id": "paper.toolbar.action",
        "status": "planned",
        "description": "Adds an action to the paper toolbar.",
    },
    {
        "id": "pdf.annotation.layer",
        "status": "planned",
        "description": "Adds a persistent, independently toggleable PDF layer.",
    },
    {
        "id": "library.view",
        "status": "planned",
        "description": "Adds a custom paper-library view.",
    },
]

PLUGIN_TEMPLATE = {
    "api_version": PLUGIN_API_VERSION,
    "id": "example.claim-checker",
    "name": "Claim Checker",
    "version": "1.0.0",
    "author": "Your Name",
    "description": "Checks the evidence supplied for the paper's central claims.",
    "permissions": ["paper:read", "ai:complete"],
    "contributes": {
        "paper_sidebar": {
            "tab_name": "Claims",
            "icon": "🔎",
        }
    },
    "prompt": "List the central claims and evaluate the evidence supplied for each one.",
}

PLUGIN_MANIFEST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/computersniper/gloss/plugin.schema.v1.json",
    "title": "Gloss plugin manifest",
    "type": "object",
    "additionalProperties": True,
    "required": ["id", "name", "version", "description", "permissions", "prompt"],
    "properties": {
        "api_version": {"type": "integer", "const": PLUGIN_API_VERSION, "default": 1},
        "id": {"type": "string", "pattern": _ID.pattern, "maxLength": 64},
        "name": {"type": "string", "minLength": 1, "maxLength": 80},
        "name_zh": {"type": "string", "maxLength": 80},
        "version": {"type": "string", "pattern": _VERSION.pattern},
        "author": {"type": "string", "maxLength": 80},
        "icon": {"type": "string", "maxLength": 8},
        "description": {"type": "string", "minLength": 1, "maxLength": 500},
        "description_zh": {"type": "string", "maxLength": 500},
        "permissions": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": {"enum": sorted(_ALLOWED_PERMISSIONS)},
        },
        "contributes": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "paper_sidebar": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["tab_name"],
                    "properties": {
                        "tab_name": {"type": "string", "minLength": 1, "maxLength": 24},
                        "tab_name_zh": {"type": "string", "maxLength": 24},
                        "icon": {"type": "string", "maxLength": 8},
                    },
                }
            },
        },
        "prompt": {"type": "string", "minLength": 1, "maxLength": 12000},
    },
    "examples": [PLUGIN_TEMPLATE],
}

CORE_EXTENSIONS = [
    {
        "id": "core.summary", "name": "Summary", "name_zh": "速览",
        "icon": "✦", "description": "Built-in structured paper summary.",
        "description_zh": "内置的结构化论文速览。", "builtin": True,
    },
    {
        "id": "core.notes", "name": "Deep Paper Note", "name_zh": "深度论文笔记",
        "icon": "📑", "description": "AI deep-reading note with a one-sentence overview.",
        "description_zh": "AI 深度阅读笔记，包含一句话概述。", "builtin": True,
    },
    {
        "id": "core.personal-notes", "name": "Notes", "name_zh": "我的笔记",
        "icon": "📝", "description": "Your own notes, stored separately for each paper.",
        "description_zh": "你为每篇论文记录的个人笔记，与 AI 笔记分开保存。", "builtin": True,
    },
    {
        "id": "core.mindmap", "name": "Mind Map", "name_zh": "思维导图",
        "icon": "⌘", "description": "Built-in interactive paper concept map.",
        "description_zh": "内置的交互式论文概念图。", "builtin": True,
    },
]

MARKETPLACE = [
    {
        "id": "gloss.critical-review",
        "name": "Critical Review",
        "name_zh": "批判性审阅",
        "version": "1.0.0",
        "author": "Gloss",
        "icon": "⚖",
        "description": "Review assumptions, evidence, limitations, and threats to validity.",
        "description_zh": "审查论文假设、证据、局限与有效性威胁。",
        "tab_name": "Review",
        "tab_name_zh": "审阅",
        "permissions": ["paper:read", "ai:complete"],
        "prompt": (
            "Write a rigorous critical review of the paper. Separate major strengths, "
            "unsupported or weakly supported claims, methodological risks, missing "
            "baselines, threats to validity, and concrete follow-up experiments. Cite "
            "sections, figures, tables, and reported numbers when available."
        ),
    },
    {
        "id": "gloss.reproducibility-checklist",
        "name": "Reproducibility Checklist",
        "name_zh": "复现检查表",
        "version": "1.0.0",
        "author": "Gloss",
        "icon": "✓",
        "description": "Extract a practical checklist for reproducing the paper.",
        "description_zh": "提取可执行的论文复现检查表。",
        "tab_name": "Reproduce",
        "tab_name_zh": "复现",
        "permissions": ["paper:read", "ai:complete"],
        "prompt": (
            "Create an actionable reproducibility checklist for this paper. Include "
            "datasets, preprocessing, model details, objectives, hyperparameters, "
            "randomness, compute, evaluation, expected outputs, and every missing detail. "
            "Use Markdown checkboxes and clearly label facts versus inferred requirements."
        ),
    },
    {
        "id": "gloss.equation-guide",
        "name": "Equation Guide",
        "name_zh": "公式导读",
        "version": "1.0.0",
        "author": "Gloss",
        "icon": "∑",
        "description": "Explain the important equations and their role in the method.",
        "description_zh": "解释关键公式及其在方法中的作用。",
        "tab_name": "Equations",
        "tab_name_zh": "公式",
        "permissions": ["paper:read", "ai:complete"],
        "prompt": (
            "Build a guided tour of the paper's important equations. Define every symbol, "
            "explain the intuition, connect each equation to the algorithm, and point out "
            "implementation-sensitive details. Preserve mathematical notation in LaTeX."
        ),
    },
]

COMING_SOON = [
    {
        "id": "gloss.citation-graph",
        "name": "Citation Graph",
        "name_zh": "引用关系图",
        "icon": "🕸️",
        "description": "Explore the papers, authors, and ideas connected to the current work.",
        "description_zh": "探索与当前论文相关的论文、作者和观点网络。",
        "planned_contribution": "library.view",
    },
    {
        "id": "gloss.compare-papers",
        "name": "Compare Papers",
        "name_zh": "论文对比",
        "icon": "⇄",
        "description": "Compare methods, assumptions, datasets, and results across papers.",
        "description_zh": "横向对比多篇论文的方法、假设、数据集与结果。",
        "planned_contribution": "paper.sidebar.panel",
    },
    {
        "id": "gloss.figure-lab",
        "name": "Figure Lab",
        "name_zh": "图表工作台",
        "icon": "▧",
        "description": "Explain, extract, and organize important figures and tables.",
        "description_zh": "解释、提取并整理关键图表。",
        "planned_contribution": "paper.toolbar.action",
    },
    {
        "id": "gloss.reproduction-workspace",
        "name": "Reproduction Workspace",
        "name_zh": "复现工作区",
        "icon": "🧪",
        "description": "Turn a paper into an executable reproduction plan and evidence log.",
        "description_zh": "将论文整理为可执行的复现计划与证据记录。",
        "planned_contribution": "paper.sidebar.panel",
    },
    {
        "id": "gloss.dataset-explorer",
        "name": "Dataset Explorer",
        "name_zh": "数据集浏览器",
        "icon": "◫",
        "description": "Inspect dataset provenance, splits, licenses, and known limitations.",
        "description_zh": "检查数据集来源、划分、许可证与已知局限。",
        "planned_contribution": "paper.sidebar.panel",
    },
    {
        "id": "gloss.annotation-canvas",
        "name": "Annotation Canvas",
        "name_zh": "批注画布",
        "icon": "✎",
        "description": "Add shapes, callouts, stamps, and collaborative annotation layers.",
        "description_zh": "增加图形、标注框、印章与协作批注图层。",
        "planned_contribution": "pdf.annotation.layer",
    },
]


def _clean_text(value: Any, field: str, *, maximum: int, required: bool = True) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"plugin {field} is required")
    if len(text) > maximum:
        raise ValueError(f"plugin {field} is too long")
    return text


def validate_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("plugin manifest must be an object")
    api_version = payload.get("api_version", PLUGIN_API_VERSION)
    if api_version != PLUGIN_API_VERSION:
        raise ValueError(
            f"unsupported plugin api_version {api_version}; expected {PLUGIN_API_VERSION}"
        )
    plugin_id = _clean_text(payload.get("id"), "id", maximum=64)
    if not _ID.fullmatch(plugin_id) or plugin_id.startswith("core."):
        raise ValueError("plugin id must be a safe lowercase identifier")
    version = _clean_text(payload.get("version"), "version", maximum=40)
    if not _VERSION.fullmatch(version):
        raise ValueError("plugin version must use semantic versioning")
    permissions = payload.get("permissions") or ["paper:read", "ai:complete"]
    if not isinstance(permissions, list) or not permissions:
        raise ValueError("plugin permissions must be a non-empty list")
    permissions = list(dict.fromkeys(str(item) for item in permissions))
    unsupported = set(permissions) - _ALLOWED_PERMISSIONS
    if unsupported:
        raise ValueError(f"unsupported plugin permissions: {', '.join(sorted(unsupported))}")
    if "paper:read" not in permissions or "ai:complete" not in permissions:
        raise ValueError("analysis plugins require paper:read and ai:complete")

    name = _clean_text(payload.get("name"), "name", maximum=80)
    name_zh = _clean_text(payload.get("name_zh"), "name_zh", maximum=80, required=False)
    icon = _clean_text(payload.get("icon") or "🧩", "icon", maximum=8)
    raw_contributes = payload.get("contributes")
    if raw_contributes is None:
        raw_contributes = {
            "paper_sidebar": {
                "tab_name": payload.get("tab_name") or name,
                "tab_name_zh": payload.get("tab_name_zh") or name_zh,
                "icon": icon,
            }
        }
    if not isinstance(raw_contributes, dict):
        raise ValueError("plugin contributes must be an object")
    unsupported_contributions = set(raw_contributes) - {"paper_sidebar"}
    if unsupported_contributions:
        raise ValueError(
            "unsupported plugin contribution points: "
            + ", ".join(sorted(unsupported_contributions))
        )
    paper_sidebar = raw_contributes.get("paper_sidebar")
    if not isinstance(paper_sidebar, dict):
        raise ValueError("analysis plugins must contribute a paper_sidebar panel")
    tab_name = _clean_text(
        paper_sidebar.get("tab_name") or payload.get("tab_name") or name,
        "contributes.paper_sidebar.tab_name",
        maximum=24,
    )
    tab_name_zh = _clean_text(
        paper_sidebar.get("tab_name_zh") or payload.get("tab_name_zh") or name_zh,
        "contributes.paper_sidebar.tab_name_zh",
        maximum=24,
        required=False,
    )
    panel_icon = _clean_text(
        paper_sidebar.get("icon") or icon,
        "contributes.paper_sidebar.icon",
        maximum=8,
    )

    return {
        "api_version": PLUGIN_API_VERSION,
        "id": plugin_id,
        "name": name,
        "name_zh": name_zh,
        "version": version,
        "author": _clean_text(payload.get("author") or "Community", "author", maximum=80),
        "icon": icon,
        "description": _clean_text(payload.get("description"), "description", maximum=500),
        "description_zh": _clean_text(
            payload.get("description_zh"), "description_zh", maximum=500, required=False
        ),
        "tab_name": tab_name,
        "tab_name_zh": tab_name_zh,
        "contributes": {
            "paper_sidebar": {
                "tab_name": tab_name,
                "tab_name_zh": tab_name_zh,
                "icon": panel_icon,
            }
        },
        "permissions": permissions,
        "prompt": _clean_text(payload.get("prompt"), "prompt", maximum=12000),
        "output": "markdown",
        "builtin": False,
    }


def _manifest_path(plugin_id: str) -> Path:
    if not _ID.fullmatch(plugin_id) or plugin_id.startswith("core."):
        raise ValueError("invalid plugin id")
    return PLUGINS_DIR / plugin_id / "manifest.json"


def _write_manifest(manifest: dict[str, Any]) -> None:
    path = _manifest_path(manifest["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def list_installed() -> list[dict[str, Any]]:
    installed = []
    if not PLUGINS_DIR.exists():
        return installed
    for path in sorted(PLUGINS_DIR.glob("*/manifest.json")):
        try:
            installed.append(validate_manifest(json.loads(read_utf8_text(path))))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    return installed


def get_installed(plugin_id: str) -> dict[str, Any] | None:
    try:
        path = _manifest_path(plugin_id)
    except ValueError:
        return None
    if not path.is_file():
        return None
    try:
        return validate_manifest(json.loads(read_utf8_text(path)))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def marketplace_snapshot() -> dict[str, Any]:
    installed = list_installed()
    installed_ids = {plugin["id"] for plugin in installed}
    marketplace = [
        {**validate_manifest(plugin), "installed": plugin["id"] in installed_ids}
        for plugin in MARKETPLACE
    ]
    return {
        "api_version": PLUGIN_API_VERSION,
        "permissions": sorted(_ALLOWED_PERMISSIONS),
        "contribution_points": CONTRIBUTION_POINTS,
        "core": CORE_EXTENSIONS,
        "marketplace": marketplace,
        "installed": installed,
        "coming_soon": COMING_SOON,
    }


def install_marketplace(plugin_id: str) -> dict[str, Any]:
    source = next((plugin for plugin in MARKETPLACE if plugin["id"] == plugin_id), None)
    if not source:
        raise ValueError("plugin was not found in the marketplace")
    manifest = validate_manifest(source)
    _write_manifest(manifest)
    return manifest


def install_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_manifest(payload)
    _write_manifest(manifest)
    return manifest


def uninstall(plugin_id: str) -> None:
    path = _manifest_path(plugin_id)
    if not path.exists():
        raise ValueError("plugin is not installed")
    path.unlink()
    store.cache_delete_prefix(f"plugin:{plugin_id}:")
    try:
        path.parent.rmdir()
    except OSError:
        pass


async def run_plugin(
    paper_id: str,
    plugin_id: str,
    *,
    refresh: bool = False,
    language: str | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    manifest = get_installed(plugin_id)
    if not manifest:
        raise ValueError("plugin is not installed")
    lang = language or output_language()
    prompt_revision = hashlib.sha256(manifest["prompt"].encode("utf-8")).hexdigest()[:12]
    cache_key = f"plugin:{plugin_id}:{manifest['version']}:{prompt_revision}:{lang}"
    if not refresh:
        cached = store.cache_get(paper_id, cache_key)
        if cached:
            return cached
    parsed = store.load_parsed(paper_id)
    if not parsed:
        raise ValueError("paper not parsed")
    paper_text = truncate_to_tokens(parsed.get("full_text", ""), 60000)
    instructions = manifest["prompt"].replace("{{language}}", lang)
    system = (
        f"You are running the Gloss plugin '{manifest['name']}' version "
        f"{manifest['version']}. Follow its instructions faithfully, use only the "
        f"provided paper, and write entirely in {lang}. Return Markdown."
    )
    user = f"=== PLUGIN INSTRUCTIONS ===\n{instructions}\n\n=== PAPER ===\n{paper_text}"
    result = await text_complete(system, user, provider=provider, model=model)
    store.cache_set(paper_id, cache_key, result)
    return result
