let session;

export class ApiError extends Error {
  constructor(status, details) {
    super(
      typeof details === "string"
        ? details
        : (details?.message ?? "Запрос не выполнен"),
    );
    this.status = status;
    this.details = details;
  }
}

export function currentSession() {
  return session;
}

export function clearSession() {
  session = undefined;
}

export async function api(
  path,
  { method = "GET", data, signal, login = false, file = false } = {},
) {
  const headers = new Headers({ Accept: "application/json" });
  if (data !== undefined) headers.set("Content-Type", "application/json");
  if (login) headers.set("X-Watch-Login", "1");
  if (session?.csrf && method !== "GET")
    headers.set("X-CSRF-Token", session.csrf);
  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: data === undefined ? undefined : JSON.stringify(data),
      cache: "no-store",
      credentials: "same-origin",
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new ApiError(0, "Нет связи с сервером. Проверьте подключение.");
  }
  if (!response.ok) {
    const details = (await response.json().catch(() => ({}))).detail;
    if (response.status === 401 && session && !login) {
      clearSession();
      window.dispatchEvent(new Event("watch:unauthorized"));
    }
    throw new ApiError(response.status, details);
  }
  return file ? response.blob() : response.json();
}

export async function loadSession() {
  session = await api("/api/auth/session");
  return session;
}

export function itemApi(action, id, extra = {}) {
  return "/api/items/" + action + "?" + new URLSearchParams({ id, ...extra });
}

export async function download(path, name) {
  const blob = await api(path, { file: true });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
