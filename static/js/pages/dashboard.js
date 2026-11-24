import { api } from "../api.js";
import {
  badge,
  button,
  changeItem,
  empty,
  formatDate,
  h,
  icon,
  image,
  itemPath,
  link,
  numberFormat,
  poster,
  progress,
  section,
} from "../components.js";
import { sources } from "../state.js";

export function duration(minutes) {
  if (minutes == null) return "—";
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  return [
    hours ? numberFormat.format(hours) + " ч" : "",
    remainder || !hours ? remainder + " мин" : "",
  ]
    .filter(Boolean)
    .join(" ");
}

export function releaseList(releases) {
  return releases.length
    ? h(
        "div",
        "release-list",
        releases.map((release) =>
          h(
            "article",
            "panel release-row",
            h(
              "div",
              "stack",
              link(release.title, itemPath(release.id), "text-link"),
              h(
                "span",
                "muted small",
                "Эпизод " +
                  release.episode +
                  " · " +
                  (Object.hasOwn(sources, release.source)
                    ? sources[release.source]
                    : "Неизвестный источник") +
                  " · Запланирован",
              ),
            ),
            h("time", "small", formatDate(release.at, true)),
          ),
        ),
      )
    : empty(
        "Нет подтверждённых релизов",
        "Здесь появятся даты выхода отслеживаемых эпизодов из каталога.",
        null,
        "calendar-days",
      );
}

function watchCard(item, context) {
  const cover = link("", itemPath(item.id));
  cover.setAttribute("aria-label", item.title);
  cover.append(poster(item));
  const plus =
    item.type === "anime" &&
    button(
      "Увеличить прогресс",
      (event) =>
        changeItem(
          "progress",
          item,
          { delta: 1 },
          context.refresh,
          event.currentTarget,
        ),
      { glyph: "plus", iconOnly: true },
    );
  const nextSeason =
    item.seasons?.find(
      (season) =>
        !season.episodesTotal || season.episodesDone < season.episodesTotal,
    )?.number ??
    (item.seasonsTotal
      ? Math.min(item.seasonsTotal, item.seasonsDone + 1)
      : null);
  return h(
    "article",
    "panel continue-card",
    cover,
    h(
      "div",
      "stack",
      link(item.title, itemPath(item.id), "text-link"),
      progress(item),
      h(
        "div",
        "muted small",
        [nextSeason && "Сезон " + nextSeason, formatDate(item.updated)]
          .filter(Boolean)
          .join(" · "),
      ),
    ),
    plus,
  );
}

function miniList(items, timestamp) {
  return h(
    "div",
    "card-list",
    items.map((item) => {
      const cover = link("", itemPath(item.id));
      cover.setAttribute("aria-label", item.title);
      cover.append(poster(item));
      return h(
        "article",
        "panel list-card",
        cover,
        h(
          "div",
          "stack",
          link(item.title, itemPath(item.id), "text-link"),
          h(
            "div",
            "row",
            badge(item.status),
            h(
              "span",
              "muted small",
              timestamp ? formatDate(timestamp(item)) : (item.year ?? ""),
            ),
          ),
        ),
      );
    }),
  );
}

export async function dashboardPage(context, _path, _params, signal) {
  const dashboard = await api("/api/dashboard", { signal });
  const { stats, continuing, recent, completed, favorites, releases } =
    dashboard;
  const art = [...continuing, ...favorites, ...recent].find(
    (item) => item.metadata?.backdrop,
  );
  const summary =
    "Ваша персональная коллекция аниме и фильмов начинается здесь.";
  const active =
    (stats.statuses.watching ?? 0) + (stats.statuses.rewatching ?? 0);
  const metrics = [
    ["Всего", stats.total, "library-big", "/library"],
    ["Аниме", stats.types.anime ?? 0, "clapperboard", "/anime"],
    ["Фильмы", stats.types.film ?? 0, "film", "/films"],
    ["Просмотрено", stats.statuses.watched ?? 0, "circle-check", "/watched"],
    ["Смотрю сейчас", active, "circle-play", "/watching"],
    ["В планах", stats.statuses.plan ?? 0, "bookmark", "/planned"],
    ["Эпизоды", stats.episodes, "layers", "/statistics"],
    [
      "Время, оценка",
      duration(stats.estimatedMinutes),
      "clock-3",
      "/statistics",
    ],
  ];
  return [
    h(
      "section",
      "hero",
      image(art?.metadata.backdrop, "", false),
      h(
        "div",
        "hero-copy",
        h("span", "hero-label", "Личная медиатека"),
        h("h1", "", "Watch Tracker"),
        h(
          "p",
          "",
          stats.total
            ? "В коллекции · " +
                numberFormat.format(stats.total) +
                "   /   В процессе · " +
                numberFormat.format(active)
            : summary,
        ),
        stats.total
          ? link("К текущим просмотрам", "/watching", "button primary", "play")
          : button("Добавить произведение", () => context.edit(), {
              variant: "primary",
              glyph: "plus",
            }),
      ),
    ),
    h(
      "section",
      "metrics dashboard-metrics",
      metrics.map(([label, value, glyph, href]) => {
        const card = link("", href, "metric");
        card.append(
          icon(glyph),
          h(
            "b",
            "",
            typeof value === "number" ? numberFormat.format(value) : value,
          ),
          h("span", "", label),
        );
        return card;
      }),
    ),
    section(
      "Продолжить просмотр",
      continuing.length
        ? h(
            "div",
            "continue-grid",
            continuing.map((item) => watchCard(item, context)),
          )
        : empty(
            "Нет текущих просмотров",
            "Отметьте произведение статусом «Смотрю», чтобы видеть его прогресс здесь.",
            null,
            "circle-play",
          ),
      link("Все просмотры", "/watching"),
    ),
    h(
      "div",
      "columns",
      section(
        "Недавно добавленные",
        recent.length
          ? miniList(recent, (item) => item.added)
          : empty(
              "Медиатека пока пуста",
              "Добавьте аниме или фильм вручную либо найдите его в каталоге.",
            ),
        link("Медиатека", "/library"),
      ),
      section(
        "Ближайшие релизы",
        releaseList(releases),
        link("Календарь", "/calendar"),
      ),
      section(
        "Недавно просмотренные",
        completed.length
          ? miniList(completed, (item) => item.completed)
          : empty(
              "Нет дат завершения",
              "Завершите просмотр или укажите дату в записи.",
              null,
              "circle-check",
            ),
        link("Просмотрено", "/watched"),
      ),
      section(
        "Избранное",
        favorites.length
          ? miniList(favorites)
          : empty(
              "В избранном пока пусто",
              "Добавляйте любимые произведения сердцем на карточке.",
              null,
              "heart",
            ),
        link("Все избранное", "/favorites"),
      ),
    ),
  ];
}
