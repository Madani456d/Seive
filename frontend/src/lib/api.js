const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

export function getSession() {
  try {
    return JSON.parse(localStorage.getItem("lead_platform_session") || "null");
  } catch {
    return null;
  }
}

export function saveSession(data) {
  localStorage.setItem("lead_platform_session", JSON.stringify(data));
}

export function clearSession() {
  localStorage.removeItem("lead_platform_session");
}

export async function apiFetch(path, options = {}) {
  const session = getSession();
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (session?.access_token) {
    headers.Authorization = `Bearer ${session.access_token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearSession();
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || `Request failed (${res.status})`);
  }
  return data;
}
