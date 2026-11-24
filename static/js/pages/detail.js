import { api, itemApi } from "../api.js";
import {
  badge,
  button,
  changeItem,
  confirmDialog,
  empty,
  field,
  formatDate,
  h,
  image,
  input,
  itemPath,
  link,
  poster,
  progress,
  section,
  select,
  showDialog,
  toast,
} from "../components.js";
import { go } from "../router.js";
import { sources, statuses, types } from "../state.js";

const releases = {
  FINISHED: "Завершён",
  RELEASING: "Выходит",
  NOT_YET_RELEASED: "Ожидается",
  CANCELLED: "Отменён",
  HIATUS: "На паузе",
  Released: "Выпущен",
  "Post Production": "Постпроизводство",
  "In Production": "В производстве",
  Planned: "Запланирован",
  Rumored: "Предполагается",
  Canceled: "Отменён",
};
const relations = {
  PREQUEL: "Предыстория",
  SEQUEL: "Продолжение",
  SIDE_STORY: "Побочная история",
  ALTERNATIVE: "Альтернатива",
  ADAPTATION: "Адаптация",
  SPIN_OFF: "Спин-офф",
  OTHER: "Связано",
  PARENT: "Основное произведение",
};

function detailFields(entries) {
  return h(
    "dl",
    "",
    entries
      .filter(([, value]) => value != null && value !== "")
      .flatMap(([label, value]) => [h("dt", "", label), h("dd", "", value)]),
  );
}

function updateSeason(item, context) {
  const form = h("form", "stack");
  const seasonNumber = input(
    "number",
    "number",
    item.seasons?.[0]?.number ?? 1,
    { required: true, min: 1, max: item.seasonsTotal || 999 },
  );
  const total = input(
    "episode-count",
    "number",
    item.seasons?.[0]?.episodesTotal ?? 0,
    { required: true, min: 0, max: 100000 },
  );
  const error = h("p", "form-error");
  error.setAttribute("role", "alert");
  const save = h("button", "button primary", "Сохранить сезон");
  save.type = "submit";
  form.append(
    field("Номер сезона", seasonNumber),
    field("Эпизодов в сезоне (0 — неизвестно)", total),
    error,
    save,
  );
  seasonNumber.addEventListener("change", () => {
    total.value =
      item.seasons.find((season) => season.number === +seasonNumber.value)
        ?.episodesTotal ?? 0;
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const number = +seasonNumber.value;
    const count = +total.value;
    const season = item.seasons.find((entry) => entry.number === number);
    if (
      count &&
      season &&
      (count < season.episodesDone ||
        season.watchedEpisodes.some((episode) => episode > count))
    ) {
      error.textContent =
        "Указанное количество меньше уже отмеченного прогресса.";
      return;
    }
    const seasons = [
      ...item.seasons.filter((entry) => entry.number !== number),
      {
        number,
        episodesTotal: count,
        episodesDone: season?.episodesDone ?? 0,
        watchedEpisodes: season?.watchedEpisodes ?? [],
      },
    ].sort((a, b) => a.number - b.number);
    const {
      id,
      added: _added,
      updated: _updated,
      revision: _revision,
      legacyDuplicate: _legacy,
      ...data
    } = item;
    save.disabled = true;
    try {
      const knownTotal = seasons.reduce(
        (sum, entry) => sum + entry.episodesTotal,
        0,
      );
      await api(itemApi("detail", id, { expected: item.revision }), {
        method: "PUT",
        data: {
          ...data,
          seasons,
          episodesTotal: Math.max(knownTotal, item.episodesTotal),
        },
      });
      dialog.close();
      context.refresh();
    } catch (failure) {
      error.textContent = failure.message;
    } finally {
      save.disabled = false;
    }
  });
  const dialog = showDialog("Настроить сезон", form);
}

function trackingControls(item, context) {
  const unit = select(
    "progress-unit",
    [
      ["auto", "Авто"],
      ["episode", "Эпизоды"],
      ["season", "Сезоны"],
    ],
    "auto",
  );
  unit.setAttribute("aria-label", "Шаг прогресса");
  const plus = button(
    "Увеличить прогресс",
    (event) =>
      changeItem(
        "progress",
        item,
        { delta: 1, unit: unit.value },
        context.refresh,
        event.currentTarget,
      ),
    { glyph: "plus", iconOnly: true },
  );
  const minus = button(
    "Уменьшить прогресс",
    (event) =>
      changeItem(
        "progress",
        item,
        { delta: -1, unit: unit.value },
        context.refresh,
        event.currentTarget,
      ),
    { glyph: "minus", iconOnly: true },
  );
  const list = h(
    "div",
    "stack",
    item.seasons.map((season) => {
      const form = h("form", "row");
      const episode = input("episode", "number", "", {
        min: 1,
        max: season.episodesTotal || 100000,
        required: true,
        placeholder: "Эпизод",
      });
      const action = select("mark", [
        ["watched", "Отметить"],
        ["unwatched", "Снять отметку"],
      ]);
      action.setAttribute("aria-label", "Действие с эпизодом");
      const save = h("button", "button", "Применить");
      save.type = "submit";
      form.append(field("Номер эпизода", episode), action, save);
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        changeItem(
          "progress",
          item,
          {
            unit: "episode",
            season: season.number,
            episode: +episode.value,
            watched: action.value === "watched",
          },
          context.refresh,
          save,
        );
      });
      const marks = season.watchedEpisodes.length
        ? h(
            "p",
            "muted small",
            "Отмечены: " + season.watchedEpisodes.join(", "),
          )
        : null;
      return h(
        "details",
        "panel",
        h(
          "summary",
          "",
          "Сезон " +
            season.number +
            " · " +
            season.episodesDone +
            (season.episodesTotal ? " / " + season.episodesTotal : "") +
            " эп.",
        ),
        marks,
        form,
      );
    }),
  );
  return h(
    "div",
    "stack",
    progress(item) ?? h("p", "muted", "Прогресс ещё не указан."),
    h(
      "div",
      "row",
      unit,
      minus,
      plus,
      button("Настроить сезон", () => updateSeason(item, context), {
        glyph: "layers",
      }),
    ),
    list,
  );
}

function eventLabel(event) {
  if (event.kind === "status")
    return (
      (statuses[event.data.status] ?? "Изменён статус") +
      (event.data.rewatch ? " · повторный просмотр" : "")
    );
  return (
    [
      ["эп.", event.data.episodes],
      ["сез.", event.data.seasons],
    ]
      .filter(([, number]) => number)
      .map(([key, number]) => (number > 0 ? "+" : "") + number + " " + key)
      .join(" · ") || "Изменён прогресс"
  );
}

export async function detailPage(context, path, _params, signal) {
  const id =
    path === "/item"
      ? _params.get("id")
      : decodeURIComponent(path.slice("/item/".length));
  const { item, events } = await api(itemApi("detail", id), { signal });
  const metadata = item.metadata ?? {};
  const provider = sources[metadata.provider];
  const set = select("status", Object.entries(statuses), item.status);
  if (!Object.hasOwn(statuses, item.status)) set.value = "";
  set.setAttribute("aria-label", "Статус просмотра");
  const doStatus = (status) =>
    changeItem("status", item, { status }, context.refresh, set);
  set.addEventListener("change", () => {
    const status = set.value;
    set.value = item.status;
    if (status === "rewatching" && !item.rewatchInProgress) {
      confirmDialog(
        "Начать повторный просмотр?",
        "Текущий прогресс начнётся с нуля. Прежние просмотренные эпизоды сохранятся в статистике.",
        "Начать просмотр",
        () =>
          api(itemApi("status", item.id), {
            method: "POST",
            data: { status },
          }).then(context.refresh),
      );
    } else doStatus(status);
  });
  const favorite = button(
    item.favorite ? "Убрать из избранного" : "В избранное",
    (event) =>
      changeItem(
        "favorite",
        item,
        { favorite: !item.favorite },
        context.refresh,
        event.currentTarget,
      ),
    { glyph: "heart" },
  );
  favorite.setAttribute("aria-pressed", String(item.favorite));
  const refresh =
    provider &&
    button(
      "Обновить метаданные",
      async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        try {
          await api("/api/catalog/refresh?" + new URLSearchParams({ id }), {
            method: "POST",
          });
          toast("Метаданные обновлены");
          context.refresh();
        } catch (failure) {
          toast(failure.message);
        } finally {
          button.disabled = false;
        }
      },
      { glyph: "refresh-cw" },
    );
  const remove = button(
    "Удалить",
    () =>
      confirmDialog(
        "Удалить произведение?",
        "«" +
          item.title +
          "» будет удалено из медиатеки. Сервер сохранит резервную копию.",
        "Удалить запись",
        async () => {
          await api(itemApi("detail", id), { method: "DELETE" });
          toast("Произведение удалено");
          go("/library");
        },
      ),
    { glyph: "trash-2", variant: "danger" },
  );
  const related = metadata.related?.length
    ? section(
        "Связанные произведения",
        h(
          "div",
          "stack panel",
          metadata.related.map((entry) =>
            h(
              "div",
              "row",
              link(
                entry.title,
                "https://anilist.co/anime/" + entry.id,
                "text-link",
              ),
              h("span", "badge", relations[entry.relation] ?? "Связано"),
            ),
          ),
        ),
      )
    : null;

  return [
    link("К медиатеке", "/library", "text-link row", "chevron-left"),
    h(
      "header",
      "detail-banner",
      image(metadata.backdrop, "", false),
      poster(item),
      h(
        "div",
        "stack",
        h(
          "div",
          "row",
          badge(item.status),
          h("span", "badge", types[item.type] ?? "—"),
        ),
        h("h1", "", item.title),
        metadata.originalTitle &&
          metadata.originalTitle !== item.title &&
          h("p", "muted", metadata.originalTitle),
        h(
          "div",
          "row",
          item.year && h("span", "badge", item.year),
          item.genres.map((genre) => h("span", "badge", genre)),
        ),
      ),
    ),
    h(
      "div",
      "row",
      set,
      favorite,
      button("Изменить", () => context.edit(item), { glyph: "pencil" }),
      refresh,
      remove,
    ),
    h(
      "div",
      "columns",
      section(
        "О произведении",
        h(
          "div",
          "stack panel",
          metadata.description && h("p", "wrap-text", metadata.description),
          detailFields([
            [
              "Выпуск",
              releases[metadata.releaseStatus] ?? metadata.releaseStatus,
            ],
            [
              "Дата выпуска",
              metadata.releaseDate ? formatDate(metadata.releaseDate) : null,
            ],
            [
              "Длительность",
              metadata.runtime
                ? metadata.runtime +
                  " мин." +
                  (item.type === "anime" ? " / эпизод" : "")
                : null,
            ],
            [
              "Личная оценка",
              item.rating != null ? item.rating + " / 10" : "Не выставлена",
            ],
            [
              "Рейтинг " + (provider ?? "сообщества"),
              metadata.communityRating != null
                ? metadata.communityRating + " / 10"
                : null,
            ],
            ["Добавлено", formatDate(item.added)],
            ["Начало", item.started ? formatDate(item.started) : null],
            ["Завершение", item.completed ? formatDate(item.completed) : null],
            ["Повторные просмотры", item.rewatches || null],
          ]),
        ),
      ),
      section(
        item.type === "anime" ? "Прогресс просмотра" : "Заметки",
        h(
          "div",
          "stack panel",
          item.type === "anime"
            ? trackingControls(item, context)
            : h(
                "p",
                item.note ? "wrap-text" : "muted",
                item.note || "Заметок пока нет.",
              ),
        ),
      ),
    ),
    item.type === "anime" &&
      section(
        "Заметки",
        h(
          "p",
          "panel " + (item.note ? "wrap-text" : "muted"),
          item.note || "Заметок пока нет.",
        ),
      ),
    section(
      "История просмотров",
      events.length
        ? h(
            "ul",
            "event-list panel",
            events.map((event) =>
              h(
                "li",
                "",
                h("span", "", eventLabel(event)),
                h("time", "muted small", formatDate(event.at, true)),
              ),
            ),
          )
        : empty(
            "История пока пуста",
            "Здесь появятся зарегистрированные изменения статуса и прогресса.",
            null,
            "history",
          ),
    ),
    related,
  ];
}
