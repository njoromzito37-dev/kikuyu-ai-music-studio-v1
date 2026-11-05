import type { ApiStem, CuePoint, DjMixJob, DjRenderJob, LibraryTrack, TransitionStyle } from "./types";

/**
 * The Django API is proxied through Next.js rewrites:
 *   /dj-api/*  ->  {DJANGO_INTERNAL_URL}/api/*
 *   /media/*   ->  {DJANGO_INTERNAL_URL}/media/*
 * See next.config.mjs.
 */
export const DJ_API_BASE = "/dj-api";

/** Map an absolute backend URL (or media path) onto the same-origin proxy. */
export function resolveMediaUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("/")) return url;
  try {
    return new URL(url).pathname;
  } catch {
    return url;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DJ_API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      /* keep status text */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function unwrapList<T>(data: unknown): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === "object" && Array.isArray((data as { results?: unknown[] }).results)) {
    return (data as { results: T[] }).results;
  }
  return [];
}

export async function fetchSongs(): Promise<LibraryTrack[]> {
  return unwrapList<LibraryTrack>(await request<unknown>("/songs/"));
}

export async function fetchSong(id: number): Promise<LibraryTrack> {
  return request<LibraryTrack>(`/songs/${id}/`);
}

export async function fetchStems(songId: number): Promise<ApiStem[]> {
  return unwrapList<ApiStem>(await request<unknown>(`/songs/${songId}/stems/`));
}

export async function updateStem(
  stemId: number,
  patch: Partial<Pick<ApiStem, "volume" | "pan" | "is_muted" | "is_solo">>,
): Promise<ApiStem> {
  return request<ApiStem>(`/stems/${stemId}/`, { method: "PATCH", body: JSON.stringify(patch) });
}

export async function requestStemSplit(songId: number): Promise<{ detail: string }> {
  return request<{ detail: string }>(`/songs/${songId}/stems/auto-split/`, { method: "POST" });
}

export async function requestAnalysis(songId: number): Promise<{ detail: string }> {
  return request<{ detail: string }>(`/songs/${songId}/analyze/`, { method: "POST" });
}

export async function createMixJob(payload: {
  track_a: number;
  track_b: number;
  transition: TransitionStyle;
  transition_bars: number;
  match_tempo: boolean;
  match_key: boolean;
}): Promise<DjMixJob> {
  return request<DjMixJob>("/dj/mix/", { method: "POST", body: JSON.stringify(payload) });
}

export async function fetchMixJob(id: number): Promise<DjMixJob> {
  return request<DjMixJob>(`/dj/mix/${id}/`);
}

export async function fetchMixJobs(): Promise<DjMixJob[]> {
  return unwrapList<DjMixJob>(await request<unknown>("/dj/mix/"));
}

export async function createRenderJob(
  sourceSong: number,
  operations: Record<string, unknown>[],
): Promise<DjRenderJob> {
  return request<DjRenderJob>("/dj/process/", {
    method: "POST",
    body: JSON.stringify({ source_song: sourceSong, operations }),
  });
}

export async function fetchRenderJob(id: number): Promise<DjRenderJob> {
  return request<DjRenderJob>(`/dj/process/${id}/`);
}
