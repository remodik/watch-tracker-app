import { api, currentSession, download } from "../api.js";
import {
  button,
  confirmDialog,
  empty,
  field,
  formatDate,
  h,
  link,
  section,
  select,
  toast,
} from "../components.js";
import { prefs, setPref } from "../state.js";
import { importDialog } from "./editor.js";

const reasons = {
  manual: "Вручную",
  replace: "Перед заменой",
  update: "Перед обновлением",
  delete: "Перед удалением",
  restore: "Перед восстановлением",
  "type-change": "Перед сменой типа",
};

export async function settingsPage(context, _path, _params, signal) {
  const [provides, backups] = await Promise.all([
    api("/api/catalog/status", { signal }),
    api("/api/backups", { signal }),
  ]);
  const choices = [
    [
      "accent",
      "Акцентный цвет",
      [
        ["purple", "Фиолетовый"],
        ["blue", "Синий"],
        ["rose", "Розовый"],
      ],
    ],
    [
      "density",
      "Плотность",
      [
        ["normal", "Стандартная"],
        ["compact", "Компактная"],
      ],
    ],
    [
      "cards",
      "Размер карточек",
      [
        ["medium", "Средний"],
        ["small", "Малый"],
        ["large", "Большой"],
      ],
    ],
    [
      "view",
      "Вид медиатеки",
      [
        ["grid", "Постеры"],
        ["list", "Список"],
        ["table", "Таблица"],
      ],
    ],
    [
      "motion",
      "Анимации",
      [
        ["on", "Включены"],
        ["off", "Отключены"],
      ],
    ],
  ];
  const appearance = h(
    "div",
    "panel fields-grid",
    choices.map(([key, label, entries]) => {
      const control = select(key, entries, prefs[key]);
      control.addEventListener("change", () => setPref(key, control.value));
      return field(label, control);
    }),
  );
  appearance.prepend(h("p", "muted small", "Тема · Cinematic Dark"));
  const saveBackup = button(
    "Создать копию",
    async () => {
      saveBackup.disabled = true;
      try {
        await api("/api/backups", { method: "POST" });
        toast("Резервная копия создана");
        context.refresh();
      } catch (failure) {
        toast(failure.message);
      } finally {
        saveBackup.disabled = false;
      }
    },
    { glyph: "archive" },
  );
  const exportButton = button(
    "Экспорт JSON",
    () =>
      download("/api/export", "watchlist.json")
        .then(() => toast("Файл готов"))
        .catch((failure) => toast(failure.message)),
    { glyph: "download" },
  );
  const sizeLabel = (bytes) =>
    new Intl.NumberFormat("ru").format(bytes) + " байт";
  const backupList = h(
    "div",
    "stack",
    h("p", "muted small", "Общий размер: " + sizeLabel(backups.total_bytes)),
  );
  let page = 1;
  function appendBackups(result) {
    if (!result.items.length && page === 1) {
      backupList.append(
        empty(
          "Резервных копий пока нет",
          "Копия создаётся автоматически перед заменой, обновлением совпадений и удалением.",
        ),
      );
    } else {
      for (const entry of result.items) {
        const path = "/api/backups/" + encodeURIComponent(entry.id);
        backupList.append(
          h(
            "article",
            "panel",
            h(
              "div",
              "page-toolbar",
              h(
                "div",
                "stack",
                h("strong", "", formatDate(entry.created, true)),
                h(
                  "span",
                  "muted small",
                  (reasons[entry.reason] ?? entry.reason) +
                    " · " +
                    sizeLabel(entry.size_bytes),
                ),
              ),
              h(
                "div",
                "row",
                button(
                  "Скачать",
                  () =>
                    download(path, "watchlist-" + entry.id + ".json").catch(
                      (failure) => toast(failure.message),
                    ),
                  { glyph: "download" },
                ),
                button(
                  "Восстановить",
                  async () => {
                    try {
                      const preview = await api(path + "/restore-preview");
                      if (preview.invalid) {
                        toast(
                          "Копия содержит некорректные записи: " +
                            preview.invalid,
                        );
                        return;
                      }
                      confirmDialog(
                        "Восстановить копию?",
                        "Текущая коллекция будет заменена. Записей: " +
                          preview.added +
                          ", событий: " +
                          preview.events +
                          ".",
                        "Восстановить",
                        async () => {
                          await api(path + "/restore", {
                            method: "POST",
                            data: { preview: preview.preview, confirm: true },
                          });
                          context.refresh();
                        },
                      );
                    } catch (failure) {
                      toast(failure.message);
                    }
                  },
                  { glyph: "history" },
                ),
                button(
                  "Удалить",
                  () =>
                    confirmDialog(
                      "Удалить резервную копию?",
                      "Эта копия будет удалена без возможности восстановления.",
                      "Удалить",
                      async () => {
                        await api(path, { method: "DELETE" });
                        context.refresh();
                      },
                    ),
                  { glyph: "trash-2" },
                ),
              ),
            ),
          ),
        );
      }
    }
    if (result.more) {
      const more = button("Показать ещё", async () => {
        more.disabled = true;
        try {
          const next = await api("/api/backups?page=" + (page + 1));
          page += 1;
          more.remove();
          appendBackups(next);
        } catch (failure) {
          more.disabled = false;
          toast(failure.message);
        }
      });
      backupList.append(more);
    }
  }
  appendBackups(backups);
  const session = currentSession();
  const tmdb = h("img", "source-logo");
  tmdb.src = "/assets/icons/tmdb.svg";
  tmdb.alt = "TMDB";
  const tmdbLink = link("", "https://www.themoviedb.org");
  tmdbLink.append(tmdb);
  const refreshMetadata = (provider, label) =>
    button(
      label,
      async (event) => {
        const control = event.currentTarget;
        control.disabled = true;
        try {
          const result = await api(
            "/api/catalog/refresh-batch?" + new URLSearchParams({ provider }),
            { method: "POST" },
          );
          toast(
            result.updated
              ? "Обновлено: " +
                  result.updated +
                  (result.failed ? " · Ошибок: " + result.failed : "")
              : result.failed
                ? "Каталог не смог обновить метаданные"
                : "Сведения уже актуальны или нет связанных произведений",
          );
        } catch (failure) {
          toast(failure.message);
        } finally {
          control.disabled = false;
        }
      },
      { glyph: "refresh-cw" },
    );
  const integrations = h(
    "div",
    "stack panel",
    h(
      "div",
      "row",
      link("AniList", "https://anilist.co", "text-link"),
      h("span", "badge", provides.anilist ? "Включён" : "Отключён"),
    ),
    h(
      "div",
      "row",
      tmdbLink,
      h("span", "badge", provides.tmdb ? "Включён" : "Отключён"),
    ),
    h(
      "p",
      "muted small",
      "This product uses the TMDB API but is not endorsed or certified by TMDB.",
    ),
    h(
      "p",
      "muted small",
      "Метаданные обновляются на странице произведения, связанного с каталогом.",
    ),
    h(
      "div",
      "row",
      provides.anilist && refreshMetadata("anilist", "Обновить AniList"),
      provides.tmdb && refreshMetadata("tmdb", "Обновить TMDB"),
    ),
    link("Открыть медиатеку", "/library", "text-link"),
  );
  return [
    h("h1", "", "Настройки"),
    section("Внешний вид", appearance),
    section(
      "Данные",
      h(
        "div",
        "stack",
        h(
          "div",
          "row",
          exportButton,
          button("Импорт JSON", () => importDialog(null, context.refresh), {
            glyph: "upload",
          }),
          saveBackup,
        ),
        backupList,
      ),
    ),
    section("Интеграции", integrations),
    section(
      "Безопасность",
      h(
        "div",
        "stack panel",
        h(
          "p",
          "muted",
          session.local
            ? "Локальный режим. Авторизация явно отключена на сервере."
            : "Сессия действует до " +
                formatDate(session.expires * 1000, true) +
                ".",
        ),
        !session.local &&
          h(
            "div",
            "row",
            button(
              "Выйти",
              () =>
                context.logout(false).catch((error) => toast(error.message)),
              { glyph: "log-out" },
            ),
            button(
              "Завершить все сессии",
              () =>
                confirmDialog(
                  "Завершить все сессии?",
                  "Watch Tracker запросит ключ доступа на всех устройствах.",
                  "Завершить",
                  () => context.logout(true),
                ),
              { glyph: "shield", variant: "danger" },
            ),
          ),
      ),
    ),
  ];
}
