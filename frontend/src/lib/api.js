const DEFAULT_API_BASE = "https://seive-1.onrender.com";
const RAW_BASE = import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE;

export const API_BASE = String(RAW_BASE).trim().replace(/\/+$/, "");

export function buildApiUrl(path = "") {
  const cleanPath = String(path).replace(/^\/+/, "");
  return cleanPath ? `${API_BASE}/${cleanPath}` : API_BASE;
}

export async function apiRequest(path, options = {}, timeoutMs = 45000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const url = buildApiUrl(path);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        ...(options.body ? { "Content-Type": "application/json" } : {}),
        ...(options.headers || {}),
      },
    });

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(`HTTP ${response.status} from ${url}: ${text || response.statusText}`);
    }

    return response;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error(`Request to ${url} timed out after ${timeoutMs / 1000}s`);
    }
    throw new Error(`Network error calling ${url}: ${err.message}`);
  } finally {
    clearTimeout(timer);
  }
}