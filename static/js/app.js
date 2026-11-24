import { api, clearSession, currentSession, loadSession } from "./api.js";
import { $, errorPanel, h, icon, link, toast } from "./components.js";
import { go, libraryRoutes, listenNavigation, nav } from "./router.js";
import { applyPrefs, prefs, setPref } from "./state.js";
import { openEditor, openNewDetail } from "./pages/editor.js";

const routes = {
  "/": () => import("./pages/dashboard.js").then((page) => page.dashboardPage),
  "/calendar": () =>
    import("./pages/calendar.js").then((page) => page.calendarPage),
  "/statistics": () =>
    import("./pages/statistics.js").then((page) => page.statisticsPage),
  "/settings": () =>
    import("./pages/settings.js").then((page) => page.settingsPage),
};
const content = $("#content");
const form = $("#global-search");
const search = form.elements.q;
const collapse = $("#collapse");
let rendering;
let previousPath;
let searchTimer;

function brand() {
  return [
    h("span", "brand-mark", icon("clapperboard")),
    h("span", "brand-label", "Watch Tracker"),
  ];
}

function populateNavigation() {
  const makeLink = ([href, label, glyph]) => {
    const node = link("", href, "nav-link", glyph);
    node.append(h("span", "", label));
    node.title = label;
    node.setAttribute("aria-label", label);
    return node;
  };
  const groups = [
    ["Медиатека", nav.slice(0, 4)],
    ["Просмотр", nav.slice(4, 8)],
    ["Инструменты", nav.slice(8)],
  ];
  $("#sidebar-nav").replaceChildren(
    ...groups.map(([name, links]) =>
      h(
        "div",
        "nav-group",
        h("span", "nav-group-label", name),
        links.map(makeLink),
      ),
    ),
  );
  $("#bottom-nav").replaceChildren(
    ...[nav[0], ["/library", "Медиатека", "library-big"], ...nav.slice(8)].map(
      makeLink,
    ),
  );
  $("#brand").replaceChildren(...brand());
  $("#login-brand").replaceChildren(...brand());
  $("#profile-mark").replaceChildren(icon("user-round"));
  $("#profile-settings").replaceChildren(icon("settings"));
  $("#quick-settings").replaceChildren(icon("settings"));
  $("#search-icon").replaceChildren(icon("search"));
  $("#add").replaceChildren(icon("plus"), h("span", "", "Добавить"));
  collapse.replaceChildren(icon("panel-left-close"));
}

function paintNavigation(path) {
  for (const node of document.querySelectorAll(".nav-link")) {
    const selected =
      node.pathname === path ||
      (node.closest(".bottom-nav") &&
        node.pathname === "/library" &&
        (Object.hasOwn(libraryRoutes, path) || path.startsWith("/item/")));
    if (selected) node.setAttribute("aria-current", "page");
    else node.removeAttribute("aria-current");
  }
  collapse.setAttribute("aria-expanded", String(prefs.side === "open"));
  collapse.setAttribute(
    "aria-label",
    prefs.side === "open" ? "Свернуть панель" : "Развернуть панель",
  );
  collapse.title = collapse.getAttribute("aria-label");
}

function showLogin() {
  rendering?.stop();
  previousPath = undefined;
  content.replaceChildren();
  if ($("#dialog").open) $("#dialog").close();
  $("#boot").hidden = true;
  $("#shell").hidden = true;
  $("#login").hidden = false;
  $("#login-form").reset();
  $("#login-error").hidden = true;
  $("#login input").focus();
}

function showApp() {
  $("#boot").hidden = true;
  $("#login").hidden = true;
  $("#shell").hidden = false;
  render();
}

async function logout(all) {
  await api("/api/auth/logout" + (all ? "-all" : ""), { method: "POST" });
  clearSession();
  showLogin();
  toast(all ? "Все сессии завершены" : "Вы вышли из медиатеки");
}

function edit(item) {
  openEditor(item, (saved) => openNewDetail(saved, render));
}

async function render() {
  if (!currentSession()) return;
  clearTimeout(searchTimer);
  rendering?.stop();
  const abort = new AbortController();
  const disposables = [];
  const jobs = [];
  const path = location.pathname.replace(/\/$/, "") || "/";
  const params = new URLSearchParams(location.search);
  const changedPage = path !== previousPath;
  previousPath = path;
  rendering = {
    stop: () => {
      abort.abort();
      disposables.forEach((dispose) => dispose());
    },
  };
  const title = nav.find(([href]) => href === path)?.[1] ?? "Произведение";
  paintNavigation(path);
  $("#section-name").textContent = title;
  document.title = title + " · Watch Tracker";
  if (search.value !== (params.get("q") ?? ""))
    search.value = params.get("q") ?? "";
  const context = {
    title,
    edit,
    logout,
    refresh: () => {
      if (!abort.signal.aborted) render();
    },
    afterPaint: (callback) => jobs.push(callback),
    onDispose: (callback) => {
      if (abort.signal.aborted) callback();
      else disposables.push(callback);
    },
  };
  content.setAttribute("aria-busy", "true");
  if (changedPage || !content.firstChild) {
    const skeleton = h("div", "skeleton");
    skeleton.setAttribute("aria-label", "Загрузка раздела");
    content.replaceChildren(skeleton);
    window.scrollTo(0, 0);
  }
  try {
    const load = Object.hasOwn(routes, path)
      ? routes[path]
      : Object.hasOwn(libraryRoutes, path)
        ? () => import("./pages/library.js").then((page) => page.libraryPage)
        : () => import("./pages/detail.js").then((page) => page.detailPage);
    const paint = await load();
    if (abort.signal.aborted) return;
    const result = await paint(context, path, params, abort.signal);
    if (abort.signal.aborted) return;
    content.replaceChildren(...result.filter(Boolean));
    jobs.forEach((job) => job());
  } catch (error) {
    if (!abort.signal.aborted)
      content.replaceChildren(errorPanel(error, render));
  } finally {
    if (!abort.signal.aborted) {
      content.removeAttribute("aria-busy");
      if (changedPage && document.activeElement !== search)
        content.focus({ preventScroll: true });
    }
  }
}

function find(replace) {
  const q = search.value.trim();
  const current = location.pathname;
  const nextPath = Object.hasOwn(libraryRoutes, current) ? current : "/library";
  const params =
    current === nextPath
      ? new URLSearchParams(location.search)
      : new URLSearchParams();
  params.delete("page");
  if (q) params.set("q", q);
  else params.delete("q");
  const staysInSearch =
    current === nextPath && new URLSearchParams(location.search).has("q");
  go(nextPath + (params.size ? "?" + params : ""), {
    replace: replace && staysInSearch,
  });
}

async function start() {
  $("#boot").replaceChildren("Загрузка Watch Tracker…");
  try {
    await loadSession();
    showApp();
  } catch (error) {
    if (error.status === 401) showLogin();
    else $("#boot").replaceChildren(errorPanel(error, start));
  }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const input = form.elements.token;
  const submit = form.querySelector("button");
  const error = $("#login-error");
  error.hidden = true;
  submit.disabled = true;
  try {
    await api("/api/auth/login", {
      method: "POST",
      data: { token: input.value },
      login: true,
    });
    input.value = "";
    await loadSession();
    showApp();
  } catch (failure) {
    error.textContent = failure.message;
    error.hidden = false;
  } finally {
    input.value = "";
    submit.disabled = false;
  }
});

listenNavigation(render);
window.addEventListener("watch:unauthorized", showLogin);
form.addEventListener("submit", (event) => {
  event.preventDefault();
  clearTimeout(searchTimer);
  find(false);
});
search.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => find(true), 300);
});
$("#add").addEventListener("click", () => edit());
collapse.addEventListener("click", () => {
  setPref("side", prefs.side === "open" ? "collapsed" : "open");
  paintNavigation(previousPath);
});
document.addEventListener("keydown", (event) => {
  const editing =
    event.target instanceof Element &&
    event.target.matches("input, textarea, select, [contenteditable]");
  if (
    event.key === "/" &&
    !editing &&
    !event.altKey &&
    !event.ctrlKey &&
    !event.metaKey &&
    !$("#dialog").open &&
    currentSession()
  ) {
    event.preventDefault();
    search.focus();
  }
  if (event.key === "Escape") {
    const openMenu = document.activeElement?.closest(".context[open]");
    if (openMenu) {
      openMenu.open = false;
      openMenu.querySelector("summary").focus();
    }
  }
});
document.addEventListener("click", (event) => {
  for (const menu of document.querySelectorAll(".context[open]"))
    if (!menu.contains(event.target)) menu.open = false;
});

async function serviceWorker() {
  if (!("serviceWorker" in navigator)) return;
  try {
    const registration = await navigator.serviceWorker.register("/sw.js");
    const banner = $("#update-banner");
    const offer = () => {
      if (navigator.serviceWorker.controller && registration.waiting)
        banner.hidden = false;
    };
    offer();
    registration.addEventListener("updatefound", () =>
      registration.installing?.addEventListener("statechange", offer),
    );
    $("#dismiss-update").addEventListener("click", () => {
      banner.hidden = true;
    });
    $("#apply-update").addEventListener("click", () => {
      navigator.serviceWorker.addEventListener(
        "controllerchange",
        () => location.reload(),
        { once: true },
      );
      registration.waiting?.postMessage("activate");
    });
  } catch {
    // The online application remains available without installation support.
  }
}

applyPrefs();
populateNavigation();
start();
window.addEventListener(
  "load",
  () => {
    if ("requestIdleCallback" in window)
      requestIdleCallback(serviceWorker, { timeout: 1500 });
    else setTimeout(serviceWorker, 300);
  },
  { once: true },
);
