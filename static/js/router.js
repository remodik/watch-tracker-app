export const nav = [
  ["/", "Обзор", "layout-dashboard"],
  ["/library", "Моя медиатека", "library-big"],
  ["/anime", "Аниме", "clapperboard"],
  ["/films", "Фильмы", "film"],
  ["/watching", "Смотрю сейчас", "circle-play"],
  ["/planned", "В планах", "bookmark"],
  ["/watched", "Просмотрено", "circle-check"],
  ["/favorites", "Избранное", "heart"],
  ["/calendar", "Календарь", "calendar-days"],
  ["/statistics", "Статистика", "chart-no-axes-column"],
  ["/settings", "Настройки", "settings"],
];

export const libraryRoutes = {
  "/library": {},
  "/anime": { type: "anime" },
  "/films": { type: "film" },
  "/watching": { active: "true" },
  "/planned": { status: "plan" },
  "/watched": { status: "watched" },
  "/favorites": { favorite: "true" },
};

export function go(href, { replace = false } = {}) {
  const url = new URL(href, location.href);
  if (url.origin !== location.origin) return;
  if (url.pathname + url.search !== location.pathname + location.search) {
    history[replace ? "replaceState" : "pushState"](null, "", url);
    window.dispatchEvent(new Event("watch:navigate"));
  }
}

export function listenNavigation(callback) {
  window.addEventListener("popstate", callback);
  window.addEventListener("watch:navigate", callback);
  document.addEventListener("click", (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.altKey ||
      event.shiftKey
    )
      return;
    const target =
      event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (
      !target ||
      target.target ||
      target.download ||
      !target.getAttribute("href").startsWith("/") ||
      target.pathname.startsWith("/api/") ||
      target.pathname.startsWith("/assets/")
    )
      return;
    event.preventDefault();
    go(target.href);
  });
}
