import { useRef, useState } from "react";
import type { PluginManifest } from "../api/client";
import { api } from "../api/client";
import { useStore } from "../store";

export function ExtensionsPanel() {
  const snapshot = useStore((s) => s.pluginSnapshot);
  const loadPlugins = useStore((s) => s.loadPlugins);
  const setTab = useStore((s) => s.setTab);
  const notify = useStore((s) => s.notify);
  const uiLang = useStore((s) => s.uiLang);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [developerOpen, setDeveloperOpen] = useState(false);
  const [template, setTemplate] = useState<Record<string, unknown> | null>(null);
  const [templateCopied, setTemplateCopied] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const T = uiLang === "zh"
    ? {
        title: "插件市场", installed: "已安装", builtIn: "内置模块", market: "推荐插件", comingSoon: "即将推出",
        install: "安装", uninstall: "卸载", open: "打开", import: "导入自定义插件",
        developer: "插件 API", apiVersion: "插件 API 版本", copyTemplate: "复制示例 manifest", copied: "已复制", schema: "打开 JSON Schema",
        safe: "插件采用声明式清单，只能在授权后读取当前论文并调用 AI，不执行任意脚本。",
        imported: "插件已安装", uninstalled: "插件已卸载", uninstallConfirm: "卸载后将移除插件入口，并清除该插件生成的缓存内容。确定卸载吗？", failed: "插件操作失败",
      }
    : {
        title: "Extension Marketplace", installed: "Installed", builtIn: "Built-in modules", comingSoon: "Coming soon",
        market: "Featured extensions", install: "Install", uninstall: "Uninstall", open: "Open", developer: "Plugin API",
        apiVersion: "Plugin API version", copyTemplate: "Copy sample manifest", copied: "Copied", schema: "Open JSON Schema",
        import: "Import custom plugin", safe: "Plugins use declarative manifests. They can read the current paper and call AI only with declared permissions; arbitrary scripts are not executed.",
        imported: "Plugin installed", uninstalled: "Plugin uninstalled", uninstallConfirm: "Uninstalling removes the plugin entry and its generated cache. Continue?", failed: "Plugin operation failed",
      };

  async function install(plugin: PluginManifest) {
    setBusy(plugin.id);
    setError("");
    try {
      await api.installMarketplacePlugin(plugin.id);
      await loadPlugins();
      notify(T.imported);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setBusy(null);
    }
  }

  async function uninstall(plugin: PluginManifest) {
    if (!window.confirm(T.uninstallConfirm)) return;
    setBusy(plugin.id);
    setError("");
    try {
      await api.uninstallPlugin(plugin.id);
      setTab("extensions");
      await loadPlugins();
      notify(T.uninstalled);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setBusy(null);
    }
  }

  async function importManifest(file: File | undefined) {
    if (!file) return;
    setBusy("import");
    setError("");
    try {
      const manifest = JSON.parse(await file.text());
      await api.installPluginManifest(manifest);
      await loadPlugins();
      notify(T.imported);
    } catch (err: any) {
      setError(String(err?.message || err));
    } finally {
      setBusy(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function toggleDeveloper() {
    const next = !developerOpen;
    setDeveloperOpen(next);
    if (!next || template) return;
    try {
      setTemplate(await api.getPluginManifestTemplate());
    } catch (err: any) {
      setError(String(err?.message || err));
    }
  }

  async function copyTemplate() {
    if (!template) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(template, null, 2));
      setTemplateCopied(true);
      window.setTimeout(() => setTemplateCopied(false), 1400);
    } catch {
      setError(T.failed);
    }
  }

  const card = (plugin: PluginManifest, source: "market" | "installed") => (
    <div className="extension-card" key={`${source}:${plugin.id}`}>
      <div className="extension-icon">{plugin.icon || "🧩"}</div>
      <div className="extension-main">
        <div className="extension-title">
          <strong>{uiLang === "zh" && plugin.name_zh ? plugin.name_zh : plugin.name}</strong>
          <span>v{plugin.version}</span>
        </div>
        <div className="extension-author">{plugin.author}</div>
        <div className="extension-desc">
          {uiLang === "zh" && plugin.description_zh ? plugin.description_zh : plugin.description}
        </div>
        <div className="extension-permissions">
          {plugin.permissions.map((permission) => <code key={permission}>{permission}</code>)}
        </div>
      </div>
      <div className="extension-actions">
        {source === "installed" || plugin.installed ? (
          <>
            <button onClick={() => setTab(`plugin:${plugin.id}`)}>{T.open}</button>
            <button className="danger-ghost" disabled={busy === plugin.id} onClick={() => uninstall(plugin)}>
              {T.uninstall}
            </button>
          </>
        ) : (
          <button disabled={busy === plugin.id} onClick={() => install(plugin)}>{T.install}</button>
        )}
      </div>
    </div>
  );

  return (
    <div className="panel-body extensions-panel">
      <div className="extensions-heading">
        <div><span className="extensions-mark">▦</span><strong>{T.title}</strong></div>
        <button onClick={() => void toggleDeveloper()}>{T.developer}</button>
        <button onClick={() => fileRef.current?.click()} disabled={busy === "import"}>{T.import}</button>
        <input ref={fileRef} type="file" accept="application/json,.json" hidden onChange={(e) => importManifest(e.target.files?.[0])} />
      </div>
      <p className="extension-safety">🔒 {T.safe}</p>
      {error && <div className="error">{T.failed}: {error}</div>}
      {developerOpen && (
        <div className="extension-developer">
          <div className="extension-dev-head">
            <strong>{T.apiVersion} v{snapshot.api_version}</strong>
            <div>
              <button onClick={() => void copyTemplate()} disabled={!template}>
                {templateCopied ? T.copied : T.copyTemplate}
              </button>
              <a href="/api/plugins/schema" target="_blank" rel="noreferrer">{T.schema} ↗</a>
            </div>
          </div>
          <div className="extension-points">
            {snapshot.contribution_points.map((point) => (
              <span key={point.id} className={point.status} title={point.description}>
                <code>{point.id}</code> · {point.status}
              </span>
            ))}
          </div>
          {template && <pre>{JSON.stringify(template, null, 2)}</pre>}
        </div>
      )}

      <h5>{T.builtIn}</h5>
      <div className="extension-grid">
        {snapshot.core.map((item) => (
          <div className="extension-card builtin" key={item.id}>
            <div className="extension-icon">{item.icon}</div>
            <div className="extension-main">
              <div className="extension-title"><strong>{uiLang === "zh" ? item.name_zh : item.name}</strong><span>Core</span></div>
              <div className="extension-desc">{uiLang === "zh" ? item.description_zh : item.description}</div>
            </div>
          </div>
        ))}
      </div>

      {snapshot.installed.length > 0 && <><h5>{T.installed}</h5><div className="extension-grid">{snapshot.installed.map((plugin) => card(plugin, "installed"))}</div></>}
      <h5>{T.market}</h5>
      <div className="extension-grid">{snapshot.marketplace.filter((plugin) => !plugin.installed).map((plugin) => card(plugin, "market"))}</div>
      <h5>{T.comingSoon}</h5>
      <div className="extension-grid coming-grid">
        {snapshot.coming_soon.map((plugin) => (
          <div className="extension-card coming" key={plugin.id}>
            <div className="extension-icon">{plugin.icon}</div>
            <div className="extension-main">
              <div className="extension-title">
                <strong>{uiLang === "zh" ? plugin.name_zh : plugin.name}</strong>
                <span className="extension-soon">{T.comingSoon}</span>
              </div>
              <div className="extension-desc">{uiLang === "zh" ? plugin.description_zh : plugin.description}</div>
              <div className="extension-permissions"><code>{plugin.planned_contribution}</code></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
