export const types = { anime: "Аниме", film: "Фильм" };
export const statuses = {
  plan: "В планах",
  watching: "Смотрю",
  watched: "Просмотрено",
  paused: "Отложено",
  dropped: "Брошено",
  rewatching: "Пересматриваю",
};
export const sources = { anilist: "AniList", tmdb: "TMDB" };
const options = {
  side: ["open", "collapsed"],
  accent: ["purple", "blue", "rose"],
  density: ["normal", "compact"],
  cards: ["medium", "small", "large"],
  motion: ["on", "off"],
  view: ["grid", "list", "table"],
};

export const prefs = {};
for (const [key, values] of Object.entries(options)) {
  try {
    const value = localStorage.getItem("watch.pref." + key);
    prefs[key] = values.includes(value) ? value : values[0];
  } catch {
    prefs[key] = values[0];
  }
}
try {
  localStorage.removeItem("watchlist_token");
} catch {
  // Storage is optional for UI preferences.
}

export function applyPrefs() {
  for (const [key, value] of Object.entries(prefs))
    document.documentElement.dataset[key] = value;
}

export function setPref(key, value) {
  if (!options[key]?.includes(value)) return;
  prefs[key] = value;
  try {
    localStorage.setItem("watch.pref." + key, value);
  } catch {
    // Changes still apply for this tab.
  }
  applyPrefs();
}
