import { api } from "../api.js";
import {
  button,
  empty,
  h,
  link,
  itemPath,
  section,
  toast,
} from "../components.js";
import { go } from "../router.js";
import { releaseList } from "./dashboard.js";

const weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
const monthFormat = new Intl.DateTimeFormat("ru-RU", {
  month: "long",
  year: "numeric",
});
const hours = new Intl.DateTimeFormat("ru-RU", {
  hour: "2-digit",
  minute: "2-digit",
});

export async function calendarPage(context, path, params, signal) {
  const [releases, providers] = await Promise.all([
    api("/api/calendar", { signal }),
    api("/api/catalog/status", { signal }),
  ]);
  const monthMode = params.get("view") === "month";
  const mode = (view, month) => {
    const search = new URLSearchParams();
    if (view === "month") search.set("view", view);
    if (month)
      search.set(
        "month",
        month.getFullYear() +
          "-" +
          String(month.getMonth() + 1).padStart(2, "0"),
      );
    go(path + (search.size ? "?" + search : ""));
  };
  const list = button("Список", () => mode("list"), { glyph: "list" });
  const calendar = button("Месяц", () => mode("month"), {
    glyph: "calendar-days",
  });
  list.setAttribute("aria-pressed", String(!monthMode));
  calendar.setAttribute("aria-pressed", String(monthMode));
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const refresh =
    providers.anilist &&
    button(
      "Обновить релизы",
      async (event) => {
        const control = event.currentTarget;
        control.disabled = true;
        try {
          const result = await api(
            "/api/catalog/refresh-batch?provider=anilist",
            { method: "POST" },
          );
          toast(
            result.updated
              ? "Обновлено: " +
                  result.updated +
                  (result.failed ? " · Ошибок: " + result.failed : "")
              : result.failed
                ? "Каталог не смог обновить релизы"
                : "Даты уже актуальны или в коллекции нет связанных произведений",
          );
          context.refresh();
        } catch (error) {
          toast(error.message);
        } finally {
          control.disabled = false;
        }
      },
      { glyph: "refresh-cw" },
    );
  const content = [
    h("h1", "", "Календарь релизов"),
    h(
      "div",
      "page-toolbar",
      h("p", "muted small", "Местное время · " + timezone),
      h("div", "row", list, calendar, refresh),
    ),
  ];
  if (!monthMode) return [...content, releaseList(releases)];

  const fromUrl = params.get("month")?.match(/^(20\d{2})-(0[1-9]|1[0-2])$/);
  const now = new Date();
  const month = fromUrl
    ? new Date(+fromUrl[1], +fromUrl[2] - 1, 1)
    : new Date(now.getFullYear(), now.getMonth(), 1);
  const grid = h(
    "div",
    "calendar-grid",
    weekdays.map((day) => h("b", "muted small", day)),
  );
  const events = new Map();
  for (const release of releases) {
    const date = new Date(release.at);
    if (
      date.getMonth() === month.getMonth() &&
      date.getFullYear() === month.getFullYear()
    ) {
      const day = date.getDate();
      const scheduled = events.get(day) ?? [];
      scheduled.push(release);
      events.set(day, scheduled);
    }
  }
  const offset = (month.getDay() + 6) % 7;
  for (let i = 0; i < offset; i++) grid.append(h("div"));
  const days = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  for (let day = 1; day <= days; day++) {
    const titles = events.get(day)?.map((release) => {
      const work = link(
        "Эп. " + release.episode,
        itemPath(release.id),
        "release",
      );
      work.setAttribute(
        "aria-label",
        release.title +
          ", эпизод " +
          release.episode +
          ", " +
          hours.format(release.at),
      );
      work.title = release.title + " · " + hours.format(release.at);
      return work;
    });
    grid.append(h("div", "calendar-cell", h("time", "", day), titles ?? []));
  }
  const monthChange = (delta) =>
    mode("month", new Date(month.getFullYear(), month.getMonth() + delta, 1));
  content.push(
    h(
      "div",
      "page-toolbar",
      button("Предыдущий месяц", () => monthChange(-1), {
        glyph: "chevron-left",
        iconOnly: true,
      }),
      h("h2", "", monthFormat.format(month)),
      button("Следующий месяц", () => monthChange(1), {
        glyph: "chevron-right",
        iconOnly: true,
      }),
    ),
    grid,
  );
  content.push(
    events.size
      ? section("Релизы месяца", releaseList([...events.values()].flat()))
      : empty(
          "Нет релизов на этот месяц",
          "Проверьте другие даты или переключитесь на список.",
          null,
          "calendar-days",
        ),
  );
  return content;
}
