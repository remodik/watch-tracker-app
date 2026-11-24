import { api, browserTimeZone } from "../api.js";
import {
  empty,
  field,
  h,
  numberFormat,
  select,
  section,
} from "../components.js";
import { go } from "../router.js";
import { statuses, types } from "../state.js";
import { duration } from "./dashboard.js";

const tones = [
  "#aa91fc",
  "#69aaf6",
  "#54d9af",
  "#efb75f",
  "#d58cdf",
  "#ef8fa1",
  "#7891d8",
  "#98b18e",
];
let chartScript;

function loadChart() {
  if (!chartScript) {
    chartScript = new Promise((resolve, reject) => {
      const script = h("script");
      script.src = new URL(
        "../../vendor/chart.umd.min.js",
        import.meta.url,
      ).href;
      script.addEventListener("load", () => resolve(window.Chart), {
        once: true,
      });
      script.addEventListener(
        "error",
        () => {
          script.remove();
          chartScript = undefined;
          reject(new Error("Chart.js недоступен"));
        },
        { once: true },
      );
      document.head.append(script);
    });
  }
  return chartScript;
}

function chart(title, rows, type, context) {
  if (!rows.length || rows.every(([, value]) => value === 0)) {
    return section(
      title,
      empty("Нет данных для графика", null, null, "chart-no-axes-column"),
    );
  }
  const canvas = h("canvas");
  canvas.setAttribute("aria-hidden", "true");
  const labels = rows.map(([key]) => key);
  const values = rows.map(([, value]) => value);
  const info = h(
    "details",
    "chart-data",
    h("summary", "", "Данные графика"),
    h(
      "ul",
      "",
      rows.map(([name, value]) =>
        h("li", "", name + " · " + numberFormat.format(value)),
      ),
    ),
  );
  const box = h("div", "chart-box", canvas);
  context.afterPaint(async () => {
    try {
      const Chart = await loadChart();
      if (!canvas.isConnected) return;
      const chart = new Chart(canvas, {
        type,
        data: {
          labels,
          datasets: [
            {
              data: values,
              backgroundColor:
                type === "doughnut" ? tones.slice(0, labels.length) : tones[0],
              borderColor: type === "line" ? tones[0] : "#16161f",
              borderWidth: type === "line" ? 2 : 1,
              tension: 0.24,
            },
          ],
        },
        options: {
          animation: false,
          responsive: true,
          maintainAspectRatio: false,
          color: "#d0d0dc",
          plugins: {
            legend: {
              display: type === "doughnut",
              position: "bottom",
              labels: { color: "#d0d0dc" },
            },
          },
          scales:
            type === "doughnut"
              ? {}
              : {
                  x: {
                    ticks: {
                      color: "#adadbf",
                      maxRotation: 48,
                      autoSkip: true,
                    },
                    grid: { color: "#242431" },
                  },
                  y: {
                    beginAtZero: true,
                    ticks: { color: "#adadbf", precision: 0 },
                    grid: { color: "#242431" },
                  },
                },
        },
      });
      context.onDispose(() => chart.destroy());
    } catch (error) {
      if (canvas.isConnected)
        box.replaceChildren(h("p", "muted", error.message));
    }
  });
  return section(title, h("div", "panel", box, info));
}

function plotEntries(data, map = {}) {
  return Object.entries(data).map(([key, value]) => [
    Object.hasOwn(map, key) ? map[key] : key,
    value,
  ]);
}

function trend(values, year) {
  const formatter = new Intl.DateTimeFormat("ru-RU", { month: "short" });
  return Array.from({ length: 12 }, (_, index) => [
    formatter.format(new Date(year, index, 1)),
    values[year + "-" + String(index + 1).padStart(2, "0")] ?? 0,
  ]);
}

function activityCalendar(activity, year) {
  const months = [];
  const formatter = new Intl.DateTimeFormat("ru-RU", { month: "long" });
  for (let month = 0; month < 12; month++) {
    const date = new Date(year, month, 1);
    const cells = h("div", "heat-grid");
    for (let day = 1; day <= new Date(year, month + 1, 0).getDate(); day++) {
      const key =
        year +
        "-" +
        String(month + 1).padStart(2, "0") +
        "-" +
        String(day).padStart(2, "0");
      const visits = activity[key] ?? 0;
      const cell = h("span", visits ? "active" : "", visits ? day + "·" : day);
      cell.title = key + " · " + visits + " действий";
      cell.setAttribute("aria-label", cell.title);
      cells.append(cell);
    }
    months.push(
      h("div", "panel stack", h("h3", "", formatter.format(date)), cells),
    );
  }
  return h("div", "activity-grid", months);
}

export async function statisticsPage(context, path, params, signal) {
  const currentYear = new Date().getFullYear();
  const selected = Number(params.get("year")) || currentYear;
  const year = selected >= 1870 && selected <= 2200 ? selected : currentYear;
  const timezone = browserTimeZone();
  const stats = await api(
    "/api/statistics?" + new URLSearchParams({ year, tz: timezone }),
    { signal },
  );
  const years = [
    ...new Set([
      currentYear,
      year,
      ...Object.values(stats.months).flatMap((months) =>
        Object.keys(months).map((key) => +key.slice(0, 4)),
      ),
    ]),
  ].sort((a, b) => b - a);
  const control = select(
    "year",
    years.map((value) => [value, value]),
    String(year),
  );
  control.addEventListener("change", () => go(path + "?year=" + control.value));
  const annual = stats.annual;
  const metric = (label, value) =>
    h(
      "div",
      "metric",
      h(
        "b",
        "",
        typeof value === "number" ? numberFormat.format(value) : value,
      ),
      label,
    );
  return [
    h(
      "div",
      "page-toolbar",
      h("h1", "", "Статистика"),
      field("Год отчёта", control),
    ),
    section(
      "Итоги за " + year,
      h(
        "div",
        "metrics",
        metric("Добавлено", annual.added),
        metric("Завершений", annual.completed),
        metric("Эпизодов по истории", annual.episodes),
        metric("Повторных просмотров", annual.rewatches),
        metric("Время, оценка", duration(annual.estimatedMinutes)),
      ),
    ),
    section(
      "За всё время",
      h(
        "div",
        "stack",
        h(
          "div",
          "metrics",
          metric("Произведений", stats.total),
          metric("Эпизодов", stats.episodes),
          metric("Повторных просмотров", stats.rewatches),
          metric("Время, оценка", duration(stats.estimatedMinutes)),
        ),
        h(
          "p",
          "muted small",
          stats.knownDurationUnits
            ? "Время рассчитано для " +
                stats.knownDurationUnits +
                " из " +
                stats.trackedUnits +
                " просмотров фильмов и эпизодов с указанной длительностью."
            : "Для оценки времени нужна длительность фильмов или эпизодов.",
        ),
        h(
          "p",
          "muted small",
          "Динамика и годовой отчёт используют зарегистрированную историю. Дата добавления учитывается отдельно.",
        ),
      ),
    ),
    h(
      "div",
      "columns",
      chart(
        "Аниме и фильмы",
        plotEntries(stats.types, types),
        "doughnut",
        context,
      ),
      chart(
        "Статусы просмотров",
        plotEntries(stats.statuses, statuses),
        "doughnut",
        context,
      ),
      chart(
        "Жанры",
        plotEntries(stats.genres)
          .sort((a, b) => b[1] - a[1])
          .slice(0, 15),
        "bar",
        context,
      ),
      chart("Годы выпуска", plotEntries(stats.years), "bar", context),
      chart("Личные оценки", plotEntries(stats.ratings), "bar", context),
      chart(
        "Добавления по месяцам",
        trend(stats.months.additions, year),
        "line",
        context,
      ),
      chart(
        "Эпизоды по месяцам",
        trend(stats.months.episodes, year),
        "line",
        context,
      ),
      chart(
        "Завершения по месяцам",
        trend(stats.months.completed, year),
        "line",
        context,
      ),
    ),
    section(
      "Календарь активности",
      Object.keys(stats.activity).length
        ? activityCalendar(stats.activity, year)
        : empty(
            "Нет записанной активности",
            "Изменения прогресса и завершения просмотра отобразятся здесь.",
            null,
            "calendar-days",
          ),
    ),
  ];
}
