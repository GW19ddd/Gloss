import { useEffect, useState } from "react";

const THEMES: { id: string; name: string }[] = [
  { id: "midnight", name: "Midnight" },
  { id: "graphite", name: "Graphite" },
  { id: "nord", name: "Nord" },
  { id: "solarized", name: "Solarized" },
  { id: "rose", name: "Rosé" },
  { id: "emerald", name: "Emerald" },
  { id: "daylight", name: "Daylight" },
];

const STORAGE_KEY = "moonlight.theme";

export function ThemePicker() {
  const [theme, setTheme] = useState(
    () => localStorage.getItem(STORAGE_KEY) || "midnight"
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  return (
    <label className="theme-picker" title="Color theme">
      🎨
      <select value={theme} onChange={(e) => setTheme(e.target.value)}>
        {THEMES.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
    </label>
  );
}
