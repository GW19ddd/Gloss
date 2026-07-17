import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useStore } from "../store";

const LANGS = [
  "中文 (Simplified Chinese)",
  "English",
  "日本語",
  "한국어",
  "Français",
  "Deutsch",
  "Español",
];

// reasoning-depth options per local CLI (controlled via the standard CLI flags)
const CLAUDE_EFFORT = ["", "low", "medium", "high", "xhigh", "max"];
const CODEX_EFFORT = ["", "minimal", "low", "medium", "high"];
const CLAUDE_MODELS = ["sonnet", "opus", "haiku"];

export function SettingsPanel() {
  const loadSettings = useStore((s) => s.loadSettings);
  const notify = useStore((s) => s.notify);
  const [cfg, setCfg] = useState<any>(null);
  const [providers, setProviders] = useState<string[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getSettings().then((s) => {
      setCfg(s.config);
      setProviders(s.available_providers);
    });
  }, []);

  if (!cfg) return <div className="panel-body muted">Loading…</div>;

  function setProv(name: string, field: string, val: any) {
    setCfg((c: any) => ({
      ...c,
      providers: { ...c.providers, [name]: { ...c.providers[name], [field]: val } },
    }));
  }

  async function save() {
    setSaving(true);
    try {
      await api.updateSettings({
        provider: cfg.provider,
        output_language: cfg.output_language,
        target_language: cfg.target_language,
        providers: cfg.providers,
      });
      await loadSettings();
      notify("Settings saved");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel-body settings">
      <label>Active AI provider</label>
      <select value={cfg.provider} onChange={(e) => setCfg({ ...cfg, provider: e.target.value })}>
        {providers.map((p) => (
          <option key={p} value={p}>{p}</option>
        ))}
      </select>

      <label>Answer language (summary / explain / chat)</label>
      <select
        value={cfg.output_language}
        onChange={(e) => setCfg({ ...cfg, output_language: e.target.value })}
      >
        {LANGS.map((l) => <option key={l}>{l}</option>)}
      </select>

      <label>Translation target (translate feature)</label>
      <select
        value={cfg.target_language}
        onChange={(e) => setCfg({ ...cfg, target_language: e.target.value })}
      >
        {LANGS.map((l) => <option key={l}>{l}</option>)}
      </select>

      <div className="adv-head">Advanced — local CLI models &amp; thinking depth</div>

      <fieldset>
        <legend>local_claude — subscription (no key)</legend>
        <label>model</label>
        <input list="claude-models" value={cfg.providers.local_claude.model}
          onChange={(e) => setProv("local_claude", "model", e.target.value)} />
        <datalist id="claude-models">
          {CLAUDE_MODELS.map((m) => <option key={m} value={m} />)}
        </datalist>
        <label>thinking depth (--effort)</label>
        <select value={cfg.providers.local_claude.effort || ""}
          onChange={(e) => setProv("local_claude", "effort", e.target.value)}>
          {CLAUDE_EFFORT.map((v) => <option key={v} value={v}>{v || "(default)"}</option>)}
        </select>
      </fieldset>

      <fieldset>
        <legend>local_codex — ChatGPT subscription (no key)</legend>
        <label>model (blank = codex default)</label>
        <input value={cfg.providers.local_codex?.model || ""}
          onChange={(e) => setProv("local_codex", "model", e.target.value)} />
        <label>reasoning effort (model_reasoning_effort)</label>
        <select value={cfg.providers.local_codex?.effort || ""}
          onChange={(e) => setProv("local_codex", "effort", e.target.value)}>
          {CODEX_EFFORT.map((v) => <option key={v} value={v}>{v || "(default)"}</option>)}
        </select>
      </fieldset>

      <fieldset>
        <legend>anthropic API</legend>
        <label>model</label>
        <input value={cfg.providers.anthropic.model}
          onChange={(e) => setProv("anthropic", "model", e.target.value)} />
        <label>api key</label>
        <input type="password" placeholder={cfg.providers.anthropic.api_key === "set" ? "•••• saved" : "sk-ant-…"}
          onChange={(e) => setProv("anthropic", "api_key", e.target.value)} />
      </fieldset>

      <fieldset>
        <legend>openai-compatible</legend>
        <label>base_url</label>
        <input value={cfg.providers.openai.base_url}
          onChange={(e) => setProv("openai", "base_url", e.target.value)} />
        <label>model</label>
        <input value={cfg.providers.openai.model}
          onChange={(e) => setProv("openai", "model", e.target.value)} />
        <label>api key</label>
        <input type="password" placeholder={cfg.providers.openai.api_key === "set" ? "•••• saved" : "sk-…"}
          onChange={(e) => setProv("openai", "api_key", e.target.value)} />
      </fieldset>

      <button className="primary" onClick={save} disabled={saving}>
        {saving ? "Saving…" : "Save settings"}
      </button>
    </div>
  );
}
