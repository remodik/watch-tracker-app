import { api, itemApi } from "./api.js";
import { statuses, types } from "./state.js";

export const $ = (selector) => document.querySelector(selector);
const svg = "http://www.w3.org/2000/svg";
export const dateFormat = new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "medium",
});
export const timeFormat = new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "medium",
  timeStyle: "short",
});
export const numberFormat = new Intl.NumberFormat("ru-RU");

export function h(tag, classes, ...children) {
  const node = document.createElement(tag);
  if (classes) node.className = classes;
  node.append(
    ...children
      .flat()
      .filter(
        (value) => value !== null && value !== undefined && value !== false,
      ),
  );
  return node;
}

export function icon(name) {
  const node = document.createElementNS(svg, "svg");
  node.setAttribute("aria-hidden", "true");
  node.setAttribute("class", "icon");
  const use = document.createElementNS(svg, "use");
  use.setAttribute("href", "/assets/icons/lucide.svg#" + name);
  node.append(use);
  return node;
}

export function button(
  label,
  action,
  { glyph, variant = "", iconOnly = false } = {},
) {
  const node = h(
    "button",
    "button " + variant + (iconOnly ? " icon-button" : ""),
    glyph && icon(glyph),
    !iconOnly && label,
  );
  node.type = "button";
  node.setAttribute("aria-label", label);
  if (iconOnly) node.title = label;
  if (action) node.addEventListener("click", action);
  return node;
}

export function link(label, href, classes = "", glyph) {
  const node = h("a", classes, glyph && icon(glyph), label);
  node.href = href;
  return node;
}

export function itemPath(id) {
  if (id === "." || id === "..") return "/item?" + new URLSearchParams({ id });
  return "/item/" + encodeURIComponent(id);
}

export function image(url, alt = "", lazy = true) {
  if (!url) return null;
  try {
    const safe = new URL(url);
    if (safe.protocol !== "https:" || safe.username || safe.password)
      return null;
    const node = h("img");
    node.alt = alt;
    node.loading = lazy ? "lazy" : "eager";
    node.decoding = "async";
    node.addEventListener("error", () => node.remove(), { once: true });
    node.src = safe.href;
    return node;
  } catch {
    return null;
  }
}

export function poster(item) {
  return h(
    "div",
    "poster",
    icon(item.type === "film" ? "film" : "clapperboard"),
    image(item.metadata?.poster, "Постер «" + item.title + "»"),
  );
}

export function badge(status) {
  return h(
    "span",
    "badge " + (Object.hasOwn(statuses, status) ? status : ""),
    Object.hasOwn(statuses, status) ? statuses[status] : "Неизвестный статус",
  );
}

export function field(label, node) {
  return h("label", "field", h("span", "", label), node);
}

export function input(name, type, value = "", attrs = {}) {
  const node = h("input");
  node.name = name;
  node.type = type;
  node.value = value ?? "";
  Object.assign(node, attrs);
  return node;
}

export function select(name, entries, value) {
  const node = h("select");
  node.name = name;
  for (const [key, label] of entries) {
    const option = h("option", "", label);
    option.value = key;
    node.append(option);
  }
  if (value !== undefined) node.value = value;
  return node;
}

export function empty(title, description, action, glyph = "inbox") {
  return h(
    "div",
    "empty",
    icon(glyph),
    h("h3", "", title),
    description && h("p", "", description),
    action,
  );
}

export function section(title, children, action) {
  return h(
    "section",
    "section",
    h("div", "section-heading", h("h2", "", title), action),
    children,
  );
}

export function formatDate(value, time = false) {
  const date = new Date(
    typeof value === "string" && value.length === 10
      ? value + "T12:00:00"
      : value,
  );
  if (value == null || !Number.isFinite(date.getTime())) return "—";
  return (time ? timeFormat : dateFormat).format(date);
}

export function progressLabel(item) {
  if (item.type === "film") return "";
  const episodes =
    item.episodesTotal || item.episodesDone || item.seasons?.length;
  const done = episodes ? item.episodesDone : item.seasonsDone;
  const total = episodes ? item.episodesTotal : item.seasonsTotal;
  return episodes
    ? total
      ? done + " / " + total + " эп."
      : done + " эп."
    : total
      ? done + " / " + total + " сез."
      : done
        ? done + " сез."
        : "";
}

export function progress(item) {
  const label = progressLabel(item);
  if (!label) return null;
  const episodes =
    item.episodesTotal || item.episodesDone || item.seasons?.length;
  const total = episodes ? item.episodesTotal : item.seasonsTotal;
  const bar = total ? h("progress") : null;
  if (bar) {
    bar.max = total;
    bar.value = Math.min(
      total,
      episodes ? item.episodesDone : item.seasonsDone,
    );
    bar.setAttribute("aria-label", label);
  }
  const seasons =
    episodes && item.seasonsDone
      ? " · " +
        item.seasonsDone +
        (item.seasonsTotal ? " / " + item.seasonsTotal : "") +
        " сез."
      : "";
  return h("div", "progress", h("span", "", label + seasons), bar);
}

let toastTimer;
export function toast(message) {
  const target = $("#toasts");
  target.textContent = message;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    target.textContent = "";
  }, 4200);
}

export function errorPanel(error, retry) {
  return empty(
    "Не удалось загрузить данные",
    error.message,
    retry && button("Повторить", retry, { glyph: "refresh-cw" }),
    "circle-alert",
  );
}

export function showDialog(title, body) {
  const dialog = $("#dialog");
  if (dialog.open) dialog.close();
  const label = h("h2", "", title);
  label.id = "dialog-title";
  dialog.replaceChildren(
    h(
      "header",
      "dialog-head",
      label,
      button("Закрыть", () => dialog.close(), {
        glyph: "x",
        iconOnly: true,
        variant: "subtle",
      }),
    ),
    h("div", "dialog-content", body),
  );
  dialog.showModal();
  return dialog;
}

export function confirmDialog(title, message, action, callback) {
  const error = h("p", "form-error");
  error.setAttribute("role", "alert");
  const submit = button(
    action,
    async () => {
      submit.disabled = true;
      try {
        await callback();
        dialog.close();
      } catch (failure) {
        error.textContent = failure.message;
      } finally {
        submit.disabled = false;
      }
    },
    { variant: "danger" },
  );
  const dialog = showDialog(title, [
    h("p", "", message),
    error,
    h(
      "div",
      "dialog-actions",
      button("Отмена", () => dialog.close()),
      submit,
    ),
  ]);
}

export async function changeItem(action, item, data, done, control) {
  if (control) control.disabled = true;
  try {
    const result = await api(itemApi(action, item.id), {
      method: "POST",
      data,
    });
    done(result);
  } catch (error) {
    toast(error.message);
  } finally {
    if (control) control.disabled = false;
  }
}

function actions(item, context, table = false) {
  const favorite = button(
    item.favorite ? "Убрать из избранного" : "В избранное",
    (event) => {
      changeItem(
        "favorite",
        item,
        { favorite: !item.favorite },
        context.refresh,
        event.currentTarget,
      );
    },
    { glyph: "heart", iconOnly: true },
  );
  favorite.setAttribute("aria-pressed", String(item.favorite));
  if (table)
    return h(
      "div",
      "card-actions",
      favorite,
      button("Изменить", () => context.edit(item), {
        glyph: "pencil",
        iconOnly: true,
      }),
    );
  const summary = h("summary", "button icon-button", icon("ellipsis"));
  summary.setAttribute("aria-label", "Действия с произведением");
  summary.title = "Действия";
  const menu = h("details", "context", summary);
  const edit = button(
    "Изменить",
    () => {
      menu.open = false;
      context.edit(item);
    },
    { glyph: "pencil", variant: "subtle" },
  );
  menu.append(
    h(
      "div",
      "context-menu",
      edit,
      link("Подробнее", itemPath(item.id), "button subtle"),
    ),
  );
  return h("div", "card-actions", favorite, menu);
}

function cardTitle(item) {
  const title = link(item.title, itemPath(item.id), "card-title");
  title.title = item.title;
  return h("h3", "", title);
}

export function cards(items, view, context) {
  if (view === "table") {
    const headings = [
      "Постер",
      "Название",
      "Тип",
      "Год",
      "Статус",
      "Прогресс",
      "Оценка",
      "Добавлено",
      "Действия",
    ];
    const table = h(
      "table",
      "",
      h(
        "thead",
        "",
        h(
          "tr",
          "",
          headings.map((heading) => h("th", "", heading)),
        ),
      ),
    );
    table.append(
      h(
        "tbody",
        "",
        items.map((item) =>
          h(
            "tr",
            "",
            [
              poster(item),
              cardTitle(item),
              types[item.type] ?? "—",
              item.year ?? "—",
              badge(item.status),
              progressLabel(item) || "—",
              item.rating ?? "—",
              formatDate(item.added),
              actions(item, context, true),
            ].map((value) => h("td", "", value)),
          ),
        ),
      ),
    );
    const wrap = h("div", "table-wrap", table);
    wrap.tabIndex = 0;
    wrap.setAttribute("aria-label", "Таблица медиатеки");
    return wrap;
  }
  return h(
    "div",
    view === "list" ? "card-list" : "poster-grid",
    items.map((item) => {
      const art = link("", itemPath(item.id));
      art.setAttribute("aria-label", item.title);
      art.append(poster(item));
      const meta = [
        types[item.type],
        item.year,
        item.rating && item.rating + "/10",
      ]
        .filter(Boolean)
        .join(" · ");
      const body = h(
        "div",
        "card-body",
        cardTitle(item),
        h("div", "muted small", meta),
        h("div", "row", badge(item.status)),
        progress(item),
        view === "list" &&
          item.genres.length > 0 &&
          h("div", "muted small", item.genres.join(", ")),
      );
      return h(
        "article",
        view === "list" ? "panel list-card" : "poster-card",
        art,
        body,
        actions(item, context),
      );
    }),
  );
}
