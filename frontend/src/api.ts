const BASE = import.meta.env.VITE_API_URL ?? "";

export async function api<T = any>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const resp = await fetch(`${BASE}/api${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    },
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : `HTTP ${resp.status}`);
  return data;
}