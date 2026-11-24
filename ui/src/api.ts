// Token arrives once in the URL fragment (never sent to the server), then
// lives in sessionStorage for reloads of this window.
const fromHash = new URLSearchParams(location.hash.slice(1)).get("token");
if (fromHash) {
  sessionStorage.setItem("speakit-token", fromHash);
  history.replaceState(null, "", location.pathname + location.search);
}
const token = sessionStorage.getItem("speakit-token") ?? "";

export async function api<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const r = await fetch(`/api/${path}`, {
    method: init?.method ?? "GET",
    headers: { "X-Speakit-Token": token, "Content-Type": "application/json" },
    body: init?.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error ?? r.statusText);
  return data as T;
}

export type Value = string | number | boolean;
export interface Setting {
  name: string; section: string; default: Value; label: string; help: string;
  restart: boolean; choices: string[]; min: number | null; max: number | null;
}
export interface Settings { schema: Setting[]; values: Record<string, Value>; env: string[]; path: string }
export interface Status { state: string; model: string; device: string; model_ready: boolean; llm: boolean }
export interface HistoryItem { time: number; mode: "raw" | "clean" | "command"; app: string; text: string }
