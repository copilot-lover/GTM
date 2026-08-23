const TOKEN_KEY = "orbit_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const resp = await fetch(`/api${path}`, { ...options, headers });
  if (resp.status === 401) {
    clearToken();
    window.location.href = "/login";
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : `HTTP ${resp.status}`);
  return data;
}
