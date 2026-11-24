import { api } from "../api.js";
import {
  button,
  cards,
  empty,
  field,
  h,
  icon,
  input,
  numberFormat,
  select,
} from "../components.js";
import { go, libraryRoutes } from "../router.js";
import { prefs, setPref, statuses, types } from "../state.js";

const sortOptions = {
  added: "Недавно добавленные",
  updated: "Недавно обновлённые",
  title: "По названию",
  year: "По году",
  rating: "По оценке",
  progress: "По прогрессу",
};

export async function libraryPage(context, path, params, signal) {
  const fixed = libraryRoutes[path];
  const keys = new Set([
    "q",
    "type",
    "status",
    "genre",
    "year",
    "favorite",
    "rating_min",
    "rating_max",
    "unfinished",
    "sort",
    "page",
  ]);
  const filters = new URLSearchParams(
    [...params].filter(([key]) => keys.has(key)),
  );
  for (const [key, value] of Object.entries(fixed)) filters.set(key, value);
  const result = await api("/api/items?" + filters, { signal });
  const update = (changes) => {
    const next = new URLSearchParams(params);
    if (!Object.hasOwn(changes, "page")) next.delete("page");
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    go(path + (next.size ? "?" + next : ""));
  };
  const sort = select(
    "sort",
    Object.entries(sortOptions),
    filters.get("sort") ?? "added",
  );
  sort.setAttribute("aria-label", "Сортировка");
  sort.addEventListener("change", () => update({ sort: sort.value }));
  const modes = [
    ["grid", "Постеры", "grid-2x2"],
    ["list", "Список", "list"],
    ["table", "Таблица", "table"],
  ];
  const results = h("div", "section");
  const group = h("div", "row");
  const renderCards = () => {
    results.replaceChildren(
      result.items.length
        ? cards(result.items, prefs.view, context)
        : empty(
            "Ничего не найдено",
            "Измените фильтры или добавьте произведение.",
            button("Добавить", () => context.edit(), {
              glyph: "plus",
              variant: "primary",
            }),
          ),
    );
    for (const control of group.children)
      control.setAttribute(
        "aria-pressed",
        String(control.dataset.view === prefs.view),
      );
  };
  for (const [mode, label, glyph] of modes) {
    const control = button(
      label,
      () => {
        setPref("view", mode);
        renderCards();
      },
      { glyph, iconOnly: true },
    );
    control.dataset.view = mode;
    group.append(control);
  }
  renderCards();

  const form = h("form", "fields-grid");
  const fields = [
    ["type", "Тип", select("type", [["", "Любой"], ...Object.entries(types)])],
    [
      "status",
      "Статус",
      select("status", [["", "Любой"], ...Object.entries(statuses)]),
    ],
    [
      "genre",
      "Жанр",
      input("genre", "text", "", {
        maxLength: 80,
        placeholder: "Например, драма",
      }),
    ],
    [
      "year",
      "Год выпуска",
      input("year", "number", "", { min: 1870, max: 2200 }),
    ],
    [
      "rating_min",
      "Оценка от",
      input("rating_min", "number", "", { min: 1, max: 10 }),
    ],
    [
      "rating_max",
      "Оценка до",
      input("rating_max", "number", "", { min: 1, max: 10 }),
    ],
    [
      "favorite",
      "Избранное",
      select("favorite", [
        ["", "Все"],
        ["true", "В избранном"],
        ["false", "Вне избранного"],
      ]),
    ],
    [
      "unfinished",
      "Прогресс",
      select("unfinished", [
        ["", "Любой"],
        ["true", "Незавершённый"],
      ]),
    ],
  ];
  for (const [key, label, node] of fields) {
    if (Object.hasOwn(fixed, key)) continue;
    node.value = filters.get(key) ?? "";
    form.append(field(label, node));
  }
  const apply = h("button", "button primary", "Применить");
  apply.type = "submit";
  form.append(apply);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    update(Object.fromEntries(new FormData(form)));
  });
  const filterBox = h(
    "details",
    "filters panel",
    h("summary", "button", icon("sliders-horizontal"), "Фильтры"),
    form,
  );
  const active = fields.flatMap(([key, label, node]) =>
    filters.has(key) && !Object.hasOwn(fixed, key)
      ? [
          [
            key,
            label,
            node.selectedOptions?.[0]?.textContent ?? filters.get(key),
          ],
        ]
      : [],
  );
  if (filters.has("q")) active.unshift(["q", "Поиск", filters.get("q")]);
  const chips = h(
    "div",
    "row",
    active.map(([key, label, value]) => {
      const chip = button(label + " · " + value, () => update({ [key]: "" }), {
        glyph: "x",
      });
      chip.classList.add("chip");
      return chip;
    }),
  );
  if (active.length)
    chips.append(button("Сбросить", () => go(path), { variant: "subtle" }));
  const pages = Math.max(1, Math.ceil(result.total / result.limit));
  const pagination = h(
    "div",
    "pagination",
    h("span", "count", result.page + " / " + pages),
  );
  const previous = button(
    "Назад",
    () => update({ page: String(result.page - 1) }),
    { glyph: "chevron-left" },
  );
  const next = button(
    "Далее",
    () => update({ page: String(result.page + 1) }),
    { glyph: "chevron-right" },
  );
  previous.disabled = result.page <= 1;
  next.disabled = result.page >= pages;
  pagination.append(h("div", "row", previous, next));
  return [
    h("h1", "", context.title),
    filterBox,
    active.length ? chips : null,
    h(
      "div",
      "page-toolbar",
      h("span", "count", "Найдено · " + numberFormat.format(result.total)),
      h("div", "row", sort, group),
    ),
    results,
    (pages > 1 || result.page > 1) && pagination,
  ];
}
