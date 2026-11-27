const DEFAULT_API_BASE = "https://seive-w41e.vercel.app";
const RAW_BASE = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE;
const SESSION_STORAGE_KEY = "seive_session";

export const API_BASE = String(RAW_BASE).trim().replace(/\/+$/, "");

export function buildApiUrl(path = "") {
  const cleanPath = String(path).trim().replace(/^\/+/, "");
  return cleanPath ? `${API_BASE}/${cleanPath}` : API_BASE;
}

export function saveSession(sessionData) {
  if (typeof window === "undefined" || !window.localStorage) return;
  try {
    window.localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(sessionData ?? null));
  } catch {}
}

export function getSession() {
  if (typeof window === "undefined" || !window.localStorage) return null;
  try {
    const raw = window.localStorage.getItem(SESSION_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function clearSession() {
  if (typeof window === "undefined" || !window.localStorage) return;
  try {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
  } catch {}
}

export async function apiFetch(path, options = {}, timeoutMs = 60000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const url = buildApiUrl(path);
  const session = getSession();
  const token = session?.access_token || session?.token || null;

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    });

    if (!response.ok) {
      const errorText = await response.text().catch(() => "");
      throw new Error(`HTTP ${response.status} on ${url}: ${errorText || response.statusText}`);
    }

    return response;
  } catch (err) {
    if (err?.name === "AbortError") {
      throw new Error(`Request to ${url} timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    throw new Error(`Network error calling ${url}: ${err?.message || err}`);
  } finally {
    clearTimeout(timer);
  }
}