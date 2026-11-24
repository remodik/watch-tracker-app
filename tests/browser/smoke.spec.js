import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

async function login(page) {
  await page.getByLabel("Ключ доступа").fill("browser-only-token");
  await page.getByRole("button", { name: "Войти", exact: true }).click();
  await expect(page.locator("#shell")).toBeVisible();
}

test("вход, добавление, поиск, фильтры, прогресс, статистика и выход", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await login(page);
  await expect(
    page.getByRole("heading", { name: "Watch Tracker" }),
  ).toBeVisible();
  await page.locator("#add").click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Название", { exact: true }).fill("Северный ветер");
  await dialog.getByLabel("Эпизодов всего").fill("12");
  await dialog.getByLabel("Жанры, через запятую").fill("Драма");
  const safeText = '<strong data-example="plain">Заметка</strong>';
  await dialog.getByLabel("Заметка", { exact: true }).fill(safeText);
  await dialog.getByRole("button", { name: "Добавить в медиатеку" }).click();
  await expect(
    page.getByRole("heading", { name: "Северный ветер" }),
  ).toBeVisible();
  await expect(page.getByText(safeText, { exact: true })).toBeVisible();
  await expect(page.locator("[data-example=plain]")).toHaveCount(0);
  await page.getByRole("button", { name: "Увеличить прогресс" }).click();
  await expect(page.getByText("1 / 12 эп.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Изменить", exact: true }).click();
  await dialog.getByLabel("Оценка от 1 до 10").fill("9");
  await dialog.getByRole("button", { name: "Сохранить изменения" }).click();
  await expect(page.getByText("9 / 10", { exact: true })).toBeVisible();
  await page
    .getByRole("searchbox", { name: "Поиск в медиатеке" })
    .fill("северный");
  await expect(page).toHaveURL(/library\?q=/);
  await expect(
    page.getByRole("link", { name: "Северный ветер", exact: true }).first(),
  ).toBeVisible();
  await page.getByText("Фильтры", { exact: true }).click();
  await page.getByLabel("Оценка от", { exact: true }).fill("10");
  await page.getByRole("button", { name: "Применить", exact: true }).click();
  await expect(page.getByText("Ничего не найдено")).toBeVisible();
  await page.getByRole("button", { name: "Сбросить", exact: true }).click();
  await page.getByRole("button", { name: "Таблица", exact: true }).click();
  await expect(page.getByRole("table")).toBeVisible();
  await page
    .locator("#sidebar-nav")
    .getByRole("link", { name: "Статистика" })
    .click();
  await expect(
    page.getByRole("heading", { name: "Статистика", exact: true }),
  ).toBeVisible();
  await expect(page.locator("canvas").first()).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(() =>
        Boolean(window.Chart?.getChart(document.querySelector("canvas"))),
      ),
    )
    .toBe(true);
  await page.locator("#quick-settings").click();
  await page.getByRole("button", { name: "Выйти", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Вход в медиатеку" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});

test("импорт с предпросмотром, экспорт и мобильная навигация", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/settings");
  await login(page);
  await page.getByRole("button", { name: "Импорт JSON" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("JSON-файл").setInputFiles({
    name: "watchlist.json",
    mimeType: "application/json",
    buffer: Buffer.from(
      JSON.stringify([
        {
          id: "old/fixture",
          title: "Старинный фильм",
          type: "film",
          status: "watched",
          added: 1450000000000,
          note: "Старая заметка",
        },
      ]),
    ),
  });
  await dialog.getByRole("button", { name: "Предпросмотр" }).click();
  await expect(dialog.getByText(/Новые: 1/)).toBeVisible();
  await dialog.getByRole("button", { name: "Применить импорт" }).click();
  await expect(dialog).not.toBeVisible();
  const downloaded = page.waitForEvent("download");
  await page.getByRole("button", { name: "Экспорт JSON" }).click();
  expect((await downloaded).suggestedFilename()).toBe("watchlist.json");
  const mobile = page.getByRole("navigation", { name: "Мобильная навигация" });
  await mobile.getByRole("link", { name: "Медиатека" }).click();
  await page.getByRole("button", { name: "Постеры", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Старинный фильм" }).first(),
  ).toBeVisible();
  await page.getByRole("heading", { name: "Старинный фильм" }).click();
  await expect(page).toHaveURL(/old%2Ffixture/);
  await expect(page.getByText("Старая заметка")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Старая заметка")).toBeVisible();
  await mobile.getByRole("link", { name: "Календарь" }).click();
  await page.getByRole("button", { name: "Месяц", exact: true }).click();
  await expect(page.getByText("Нет релизов на этот месяц")).toBeVisible();
  await page.goBack();
  await expect(
    page.getByRole("button", { name: "Список", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.goForward();
  await expect(page.getByText("Нет релизов на этот месяц")).toBeVisible();
});

test("размеры экранов и границы офлайн-кеша", async ({ page, context }) => {
  await page.goto("/");
  await login(page);
  for (const width of [320, 375, 390, 768, 1024, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(
      page.getByRole("heading", { name: "Watch Tracker" }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(width);
  }
  await page.evaluate(() => navigator.serviceWorker.ready);
  await expect
    .poll(() =>
      page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
    )
    .toBe(true);
  const cached = await page.evaluate(async () => {
    const keys = await caches.keys();
    const assets = await Promise.all(
      keys.map(async (key) =>
        (await (await caches.open(key)).keys()).map(
          (entry) => new URL(entry.url).pathname,
        ),
      ),
    );
    return assets.flat();
  });
  expect(
    cached.some((resource) =>
      /^\/assets\/[a-f0-9]{24}\/offline\.html$/.test(resource),
    ),
  ).toBe(true);
  expect(cached.filter((path) => path.startsWith("/api/"))).toHaveLength(0);
  await context.setOffline(true);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Нет подключения" }),
  ).toBeVisible();
});

test("доступность входа, навигации и формы", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const tags = ["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"];
  const audit = () => new AxeBuilder({ page }).withTags(tags).analyze();
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Вход в медиатеку" }),
  ).toBeVisible();
  expect((await audit()).violations).toEqual([]);
  await login(page);
  await expect(
    page.getByRole("heading", { name: "Watch Tracker" }),
  ).toBeVisible();
  expect((await audit()).violations).toEqual([]);
  await page.locator("#add").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect((await audit()).violations).toEqual([]);
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.locator("#add")).toBeFocused();
});

test("некорректная ссылка на запись и поиск в категории со слешем", async ({
  page,
}) => {
  await page.goto("/");
  await login(page);
  for (const path of ["/item", "/item?id=", "/item/%ZZ"]) {
    await page.goto(path);
    await expect(
      page.getByText(/Запись не найдена|Некорректная ссылка/),
    ).toBeVisible();
  }
  await page.goto("/anime/");
  await page.locator("#global-search input").fill("неизвестное");
  await expect(page).toHaveURL(/\/anime\?q=/);
});

test("PWA сохраняет согласованность двух версий и отката", async ({
  page,
  context,
  request,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await login(page);
  await page.evaluate(() => navigator.serviceWorker.ready);
  await expect
    .poll(() =>
      page.evaluate(() => Boolean(navigator.serviceWorker.controller)),
    )
    .toBe(true);
  const next = await context.newPage();
  next.on("pageerror", (error) => errors.push(error.message));
  try {
    await request.post("/_test/release-b");
    await page.evaluate(async () =>
      (await navigator.serviceWorker.ready).update(),
    );
    await expect(
      page.getByText("Доступно обновление Watch Tracker"),
    ).toBeVisible();
    await next.goto("/");
    await expect(next.locator("html")).toHaveAttribute(
      "data-test-release",
      "b",
    );
    await expect(
      next.getByRole("heading", { name: "Watch Tracker" }),
    ).toBeVisible();
    await expect(page.locator("html")).not.toHaveAttribute(
      "data-test-release",
      "b",
    );
    await page.getByRole("button", { name: "Обновить" }).click();
    await expect(page.locator("html")).toHaveAttribute(
      "data-test-release",
      "b",
    );
    await request.post("/_test/release-a");
    await next.reload();
    await expect(
      next.getByRole("heading", { name: "Watch Tracker" }),
    ).toBeVisible();
    await expect(next.locator("html")).not.toHaveAttribute(
      "data-test-release",
      "b",
    );
    await context.setOffline(true);
    await next.reload();
    await expect(
      next.getByRole("heading", { name: "Нет подключения" }),
    ).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await context.setOffline(false);
    await request.post("/_test/release-a");
  }
});

test("запоздалый ответ каталога не меняет новый диалог", async ({ page }) => {
  await page.route("**/api/catalog/status", (route) =>
    route.fulfill({ json: { anilist: true, tmdb: true } }),
  );
  await page.route("**/api/catalog/anilist/search?*", (route) =>
    route.fulfill({
      json: [
        { title: "Каталог A", type: "anime", metadata: { externalId: 7 } },
      ],
    }),
  );
  let finish;
  const delayed = new Promise((resolve) => {
    finish = resolve;
  });
  await page.route("**/api/catalog/anilist/7", async (route) => {
    await delayed;
    await route
      .fulfill({ json: { title: "Опоздавший ответ", type: "anime" } })
      .catch(() => {});
  });
  await page.goto("/");
  await login(page);
  await page.locator("#add").click();
  await page.getByRole("button", { name: "Поиск в каталоге" }).click();
  await page.getByLabel("Название в каталоге").fill("Каталог A");
  const requested = page.waitForRequest("**/api/catalog/anilist/7");
  await page.getByRole("button", { name: /Каталог A/ }).click();
  await requested;
  await page.keyboard.press("Escape");
  await page.locator("#add").click();
  await page.getByLabel("Название", { exact: true }).fill("Новый диалог");
  finish();
  await expect(page.getByLabel("Название", { exact: true })).toHaveValue(
    "Новый диалог",
  );
});
