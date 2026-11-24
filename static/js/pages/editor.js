import { api, itemApi } from "../api.js";
import {
  button,
  empty,
  field,
  h,
  icon,
  input,
  itemPath,
  link,
  poster,
  select,
  showDialog,
  toast,
} from "../components.js";
import { go } from "../router.js";
import { sources, statuses, types } from "../state.js";

const maxArchiveBytes = 16 * 1024 * 1024;

function errorText(error) {
  const issue = error.details?.issues?.[0];
  return issue
    ? issue.message + (issue.field ? " · " + issue.field : "")
    : error.message;
}

function textarea(name, value, max) {
  const node = h("textarea");
  node.name = name;
  node.value = value ?? "";
  node.maxLength = max;
  return node;
}

function manualForm(item, prefill, saved) {
  const data = item ?? prefill ?? {};
  const metadata = data.metadata ?? {};
  const form = h("form", "stack");
  const title = input("title", "text", data.title, {
    required: true,
    maxLength: 500,
    autofocus: true,
  });
  const type = select("type", Object.entries(types), data.type ?? "anime");
  if (metadata.provider) type.disabled = true;
  const number = (name, value, min, max) =>
    input(name, "number", value, { min, max });
  const episodesDone = number("episodesDone", data.episodesDone, 0, 100000);
  const seasonsDone = number("seasonsDone", data.seasonsDone, 0, 999);
  const seasonFields = h(
    "div",
    "fields-grid",
    field("Сезонов просмотрено", seasonsDone),
    field("Сезонов всего", number("seasonsTotal", data.seasonsTotal, 0, 999)),
    field("Эпизодов просмотрено", episodesDone),
    field(
      "Эпизодов всего",
      number("episodesTotal", data.episodesTotal, 0, 100000),
    ),
  );
  function paintType() {
    seasonFields.hidden = type.value !== "anime";
    for (const control of seasonFields.querySelectorAll("input"))
      control.disabled = seasonFields.hidden;
  }
  type.addEventListener("change", paintType);
  paintType();
  const advanced = h(
    "details",
    "",
    h("summary", "button", "Подробные сведения"),
    h(
      "div",
      "stack advanced-fields",
      field(
        "Оригинальное название",
        input("originalTitle", "text", metadata.originalTitle, {
          maxLength: 500,
        }),
      ),
      field(
        "Альтернативные названия, через точку с запятой",
        input("alternateTitles", "text", metadata.alternateTitles?.join("; "), {
          maxLength: 4000,
        }),
      ),
      h(
        "div",
        "fields-grid",
        field(
          "Постер (HTTPS)",
          input("poster", "url", metadata.poster, { maxLength: 2048 }),
        ),
        field(
          "Фон (HTTPS)",
          input("backdrop", "url", metadata.backdrop, { maxLength: 2048 }),
        ),
        field(
          "Длительность, мин. за фильм или эпизод",
          number("runtime", metadata.runtime, 1, 3000),
        ),
        field(
          "Дата выпуска",
          input("releaseDate", "date", metadata.releaseDate),
        ),
      ),
      field("Описание", textarea("description", metadata.description, 30000)),
    ),
  );
  const favorite = input("favorite", "checkbox", "", {
    checked: data.favorite ?? false,
  });
  const error = h("p", "form-error");
  error.setAttribute("role", "alert");
  const save = h(
    "button",
    "button primary",
    item ? "Сохранить изменения" : "Добавить в медиатеку",
  );
  save.type = "submit";
  form.append(
    field("Название", title),
    h(
      "div",
      "fields-grid",
      field("Тип", type),
      field("Год выпуска", number("year", data.year, 1870, 2200)),
      field(
        "Статус",
        select("status", Object.entries(statuses), data.status ?? "plan"),
      ),
      field("Оценка от 1 до 10", number("rating", data.rating, 1, 10)),
    ),
    field(
      "Жанры, через запятую",
      input("genres", "text", data.genres?.join(", "), { maxLength: 3300 }),
    ),
    seasonFields,
    h(
      "div",
      "fields-grid",
      field("Начало просмотра", input("started", "date", data.started)),
      field("Окончание просмотра", input("completed", "date", data.completed)),
    ),
    h("label", "row small", favorite, "В избранном"),
    field("Заметка", textarea("note", data.note, 30000)),
    advanced,
    error,
    h(
      "div",
      "dialog-actions",
      button("Отмена", () => document.querySelector("#dialog").close()),
      save,
    ),
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = new FormData(form);
    const get = (key) => values.get(key) || null;
    const integer = (key) => (get(key) === null ? null : Number(get(key)));
    const split = (key, separator) =>
      (get(key) ?? "")
        .split(separator)
        .map((value) => value.trim())
        .filter(Boolean);
    const changingType = item && item.type !== type.value;
    if (
      changingType &&
      !window.confirm(
        "Сменить тип? Текущий прогресс будет сброшен. История сохранится.",
      )
    )
      return;
    const payload = {
      title: get("title"),
      type: type.value,
      status: get("status"),
      genres: split("genres", ","),
      year: integer("year"),
      rating: integer("rating"),
      favorite: favorite.checked,
      note: get("note") ?? "",
      started: get("started"),
      completed: get("completed"),
      seasonsDone: integer("seasonsDone") ?? 0,
      seasonsTotal: integer("seasonsTotal") ?? 0,
      episodesDone: integer("episodesDone") ?? 0,
      episodesTotal: integer("episodesTotal") ?? 0,
      seasons: type.value === "anime" ? (data.seasons ?? []) : [],
      metadata: {
        ...metadata,
        originalTitle: get("originalTitle"),
        alternateTitles: split("alternateTitles", ";"),
        poster: get("poster"),
        backdrop: get("backdrop"),
        runtime: integer("runtime"),
        releaseDate: get("releaseDate"),
        description: get("description") ?? "",
      },
    };
    save.disabled = true;
    error.replaceChildren();
    try {
      const entry = await api(
        item
          ? itemApi("detail", item.id, {
              expected: item.revision,
              confirm_type_change: Boolean(changingType),
            })
          : "/api/items",
        { method: item ? "PUT" : "POST", data: payload },
      );
      document.querySelector("#dialog").close();
      toast(item ? "Изменения сохранены" : "Произведение добавлено");
      saved(entry);
    } catch (failure) {
      error.append(errorText(failure));
      if (failure.status === 409 && failure.details?.id) {
        const match = link(
          "Открыть существующую запись",
          itemPath(failure.details.id),
          "text-link",
        );
        match.addEventListener("click", () =>
          document.querySelector("#dialog").close(),
        );
        error.append(" · ", match);
      }
    } finally {
      save.disabled = false;
    }
  });
  return form;
}

export async function openEditor(item, saved) {
  if (item) {
    showDialog("Изменить произведение", manualForm(item, null, saved));
    return;
  }
  const body = h("div", "stack");
  const modes = h("div", "row");
  const panel = h("div", "stack");
  body.append(modes, panel);
  const dialog = showDialog("Добавить произведение", body);
  let request;
  let state = "manual";
  let prefill;
  const manual = button("Вручную", () => switchTo("manual"), {
    glyph: "pencil",
  });
  const catalog = button("Поиск в каталоге", () => switchTo("catalog"), {
    glyph: "search",
  });
  modes.append(manual, catalog);

  function switchTo(mode) {
    request?.abort();
    state = mode;
    manual.setAttribute("aria-pressed", String(mode === "manual"));
    catalog.setAttribute("aria-pressed", String(mode === "catalog"));
    if (mode === "manual") {
      panel.replaceChildren(manualForm(null, prefill, saved));
      return;
    }
    showCatalog();
  }

  async function showCatalog() {
    const loading = h("p", "muted", "Загрузка настроек каталогов…");
    panel.replaceChildren(loading);
    try {
      const available = await api("/api/catalog/status");
      if (state !== "catalog" || !dialog.open) return;
      const options = Object.keys(sources)
        .filter((name) => available[name])
        .map((name) => [name, sources[name]]);
      if (!options.length) {
        panel.replaceChildren(
          empty(
            "Каталоги отключены",
            "Заполните сведения вручную или проверьте настройки интеграций.",
          ),
        );
        return;
      }
      const provider = select("provider", options);
      const query = input("catalog-query", "search", "", {
        minLength: 2,
        maxLength: 150,
        required: true,
        autocomplete: "off",
      });
      const submit = h("button", "button primary", icon("search"), "Найти");
      submit.type = "submit";
      const results = h("div", "catalog-results");
      const status = h("p", "muted small");
      status.setAttribute("role", "status");
      const form = h(
        "form",
        "stack",
        h(
          "div",
          "fields-grid",
          field("Каталог", provider),
          field("Название в каталоге", query),
        ),
        submit,
      );
      panel.replaceChildren(form, status, results);
      let timer;
      const search = async () => {
        request?.abort();
        if (
          !dialog.open ||
          state !== "catalog" ||
          query.value.trim().length < 2
        ) {
          results.replaceChildren();
          status.textContent = "";
          return;
        }
        request = new AbortController();
        status.textContent = "Поиск…";
        results.replaceChildren();
        try {
          const entries = await api(
            "/api/catalog/" +
              provider.value +
              "/search?" +
              new URLSearchParams({ q: query.value.trim() }),
            { signal: request.signal },
          );
          status.textContent = entries.length
            ? "Найдено · " + entries.length
            : "Совпадений нет";
          results.replaceChildren(
            ...entries.map((entry) => {
              const choice = h(
                "button",
                "button catalog-result",
                poster(entry),
                h(
                  "span",
                  "stack",
                  entry.title,
                  h(
                    "span",
                    "small muted",
                    [entry.year, sources[provider.value]]
                      .filter(Boolean)
                      .join(" · "),
                  ),
                ),
                icon("chevron-right"),
              );
              choice.type = "button";
              choice.addEventListener("click", async () => {
                choice.disabled = true;
                try {
                  prefill = await api(
                    "/api/catalog/" +
                      provider.value +
                      "/" +
                      entry.metadata.externalId,
                  );
                  if (dialog.open && state === "catalog") switchTo("manual");
                } catch (failure) {
                  status.textContent = failure.message;
                } finally {
                  choice.disabled = false;
                }
              });
              return choice;
            }),
          );
        } catch (failure) {
          if (failure.name !== "AbortError")
            status.textContent = failure.message;
        }
      };
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        clearTimeout(timer);
        search();
      });
      query.addEventListener("input", () => {
        request?.abort();
        clearTimeout(timer);
        timer = setTimeout(search, 350);
      });
      provider.addEventListener("change", search);
    } catch (error) {
      panel.replaceChildren(
        empty(
          "Каталог недоступен",
          error.message,
          button("Повторить", showCatalog),
        ),
      );
    }
  }
  dialog.addEventListener(
    "close",
    () => {
      state = "closed";
      request?.abort();
    },
    { once: true },
  );
  switchTo("manual");
}

export function importDialog(initial, refreshed) {
  const file = input("archive", "file");
  file.accept = "application/json,.json";
  const mode = select(
    "mode",
    [
      ["merge", "Объединить и пропустить совпадения"],
      ["update", "Обновить совпадения"],
      ["replace", "Полностью заменить коллекцию"],
    ],
    initial ? "replace" : "merge",
  );
  const output = h("div", "stack");
  const error = h("p", "form-error");
  error.setAttribute("role", "alert");
  let archive = initial;
  let generation = 0;
  const preview = button(
    "Предпросмотр",
    async () => {
      const request = ++generation;
      preview.disabled = true;
      error.textContent = "";
      output.replaceChildren();
      try {
        if (!archive) {
          const chosen = file.files[0];
          if (!chosen) throw new Error("Выберите JSON-файл.");
          if (chosen.size > maxArchiveBytes)
            throw new Error("Файл превышает 16 МиБ.");
          archive = JSON.parse((await chosen.text()).replace(/^\uFEFF/, ""));
        }
        const payload = Array.isArray(archive)
          ? { mode: mode.value, items: archive }
          : {
              mode: mode.value,
              version: archive.version ?? 1,
              items: archive.items,
              events: archive.events ?? [],
            };
        const result = await api("/api/items/bulk-import/preview", {
          method: "POST",
          data: payload,
        });
        if (generation !== request) return;
        output.append(
          h(
            "p",
            "",
            "Новые: " +
              result.added +
              " · Совпадения: " +
              result.duplicates +
              " · Обновления: " +
              result.updated +
              " · Ошибки: " +
              result.invalid,
          ),
        );
        if (result.invalid) {
          output.append(
            h(
              "ul",
              "event-list",
              result.errors.map(({ index, record, issues }) =>
                h(
                  "li",
                  "",
                  (record === "event" ? "Событие " : "Запись ") +
                    index +
                    " · " +
                    issues
                      .map((issue) =>
                        [issue.field, issue.message].filter(Boolean).join(": "),
                      )
                      .join(", "),
                ),
              ),
            ),
          );
          return;
        }
        const replace = payload.mode === "replace";
        const confirm = input("replace-confirm", "checkbox");
        const apply = button(
          replace ? "Заменить коллекцию" : "Применить импорт",
          async () => {
            apply.disabled = true;
            try {
              await api("/api/items/bulk-import", {
                method: "POST",
                data: { ...payload, confirm: replace && confirm.checked },
              });
              dialog.close();
              toast("Импорт завершён");
              refreshed();
            } catch (failure) {
              error.textContent = errorText(failure);
            } finally {
              apply.disabled = replace && !confirm.checked;
            }
          },
          { variant: replace ? "danger" : "primary" },
        );
        apply.disabled = replace;
        confirm.addEventListener("change", () => {
          apply.disabled = !confirm.checked;
        });
        if (replace)
          output.append(
            h(
              "label",
              "row",
              confirm,
              "Подтверждаю замену всей коллекции. Сервер сохранит резервную копию.",
            ),
          );
        output.append(apply);
      } catch (failure) {
        if (generation === request)
          error.textContent =
            failure instanceof SyntaxError
              ? "Некорректный JSON."
              : errorText(failure);
      } finally {
        preview.disabled = false;
      }
    },
    { glyph: "scan-search" },
  );
  file.addEventListener("change", () => {
    archive = undefined;
    generation++;
    output.replaceChildren();
  });
  mode.addEventListener("change", () => {
    generation++;
    output.replaceChildren();
  });
  const dialog = showDialog(
    initial ? "Восстановить копию" : "Импорт коллекции",
    h(
      "div",
      "stack",
      !initial && field("JSON-файл", file),
      field("Режим импорта", mode),
      preview,
      output,
      error,
    ),
  );
}

export function openNewDetail(item, refresh) {
  const path = itemPath(item.id);
  if (location.pathname + location.search === path) refresh();
  else go(path);
}
