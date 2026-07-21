import { useState } from "react";
import type { PluginManifest } from "../api/client";
import { api } from "../api/client";
import { useOp } from "../api/ops";
import { useStore } from "../store";
import { Markdown } from "./Markdown";

export function PluginPanel({ plugin }: { plugin: PluginManifest }) {
  const current = useStore((s) => s.current);
  const uiLang = useStore((s) => s.uiLang);
  const active = useStore((s) => s.activeTab) === `plugin:${plugin.id}`;
  const loadPlugins = useStore((s) => s.loadPlugins);
  const setTab = useStore((s) => s.setTab);
  const notify = useStore((s) => s.notify);
  const [uninstalling, setUninstalling] = useState(false);
  const key = current ? `plugin:${plugin.id}:${plugin.version}:${current.id}` : null;
  const { data: markdown = "", loading, error, run } = useOp<string>(
    key,
    () => api.runPlugin(plugin.id, current!.id).then((r) => r.markdown),
    active,
  );
  const regenerate = () => run(
    () => api.runPlugin(plugin.id, current!.id, true).then((r) => r.markdown),
    true,
  );
  const T = uiLang === "zh"
    ? {
        run: "运行插件", rerun: "↻ 重新运行", running: "插件运行中…", copy: "⧉ 复制",
        uninstall: "卸载", uninstalling: "卸载中…", uninstalled: "插件已卸载",
        confirm: "卸载后将移除插件入口，并清除该插件生成的缓存内容。确定卸载吗？",
      }
    : {
        run: "Run plugin", rerun: "↻ Run again", running: "Running plugin…", copy: "⧉ Copy",
        uninstall: "Uninstall", uninstalling: "Uninstalling…", uninstalled: "Plugin uninstalled",
        confirm: "Uninstalling removes the plugin entry and its generated cache. Continue?",
      };

  async function uninstall() {
    if (!window.confirm(T.confirm)) return;
    setUninstalling(true);
    try {
      await api.uninstallPlugin(plugin.id);
      setTab("extensions");
      await loadPlugins();
      notify(T.uninstalled);
    } catch (error: any) {
      notify(String(error?.message || error));
    } finally {
      setUninstalling(false);
    }
  }

  return (
    <div className="panel-body">
      <div className="plugin-panel-head">
        <span className="plugin-icon">{plugin.icon}</span>
        <div>
          <strong>{uiLang === "zh" && plugin.name_zh ? plugin.name_zh : plugin.name}</strong>
          <div className="muted">{plugin.author} · v{plugin.version}</div>
        </div>
        <button className="danger-ghost plugin-uninstall" disabled={uninstalling || loading} onClick={() => void uninstall()}>
          {uninstalling ? T.uninstalling : T.uninstall}
        </button>
      </div>
      <div className="panel-actions">
        <button onClick={regenerate} disabled={loading || !current}>
          {loading ? T.running : markdown ? T.rerun : T.run}
        </button>
        <button
          onClick={() => navigator.clipboard?.writeText(markdown)}
          disabled={!markdown || loading}
        >
          {T.copy}
        </button>
      </div>
      {error && <div className="error">{error}</div>}
      {loading && !markdown && <div className="muted">{T.running}</div>}
      {markdown && <Markdown text={markdown} />}
    </div>
  );
}
