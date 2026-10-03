"use client";

import { useCallback, useEffect, useState } from "react";

const API_BASE = "/api";

type LibrarySong = {
  job_id: string;
  title: string;
  genre: string;
  engine: string;
  created_at: number;
  audio_url: string;
  download_url: string;
};

type SongLibraryProps = {
  refreshKey: number;
  onSelect: (audioUrl: string) => void;
  onReuse: (jobId: string) => void;
  onRemaster: (jobId: string) => void;
};

export default function SongLibrary({ refreshKey, onSelect, onReuse, onRemaster }: SongLibraryProps) {
  const [songs, setSongs] = useState<LibrarySong[]>([]);
  const [loading, setLoading] = useState(true);
  const [remastering, setRemastering] = useState<string | null>(null);

  const handleRemaster = async (jobId: string) => {
    setRemastering(jobId);
    try {
      await onRemaster(jobId);
    } finally {
      setRemastering(null);
    }
  };

  const load = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE}/songs`);
      if (!response.ok) return;
      const data = await response.json();
      setSongs(Array.isArray(data.songs) ? data.songs : []);
    } catch (error) {
      console.error("Library load failed", error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, refreshKey]);

  return (
    <div className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xl font-semibold text-white">Library</h2>
        <button
          type="button"
          onClick={load}
          className="rounded-full border border-slate-700 px-3 py-1 text-xs text-slate-300 transition hover:border-slate-500"
        >
          Refresh
        </button>
      </div>

      {loading ? (
        <p className="text-sm text-slate-400">Loading...</p>
      ) : songs.length === 0 ? (
        <p className="text-sm text-slate-400">No songs yet — generate one to fill your library.</p>
      ) : (
        <ul className="max-h-96 space-y-2 overflow-y-auto pr-1">
          {songs.map((song) => (
            <li
              key={song.job_id}
              className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-950/60 p-3"
            >
              <button
                type="button"
                onClick={() => onSelect(song.audio_url)}
                className="min-w-0 flex-1 text-left"
                title="Load into player"
              >
                <p className="truncate text-sm font-medium text-white">{song.title}</p>
                <p className="mt-0.5 text-xs capitalize text-slate-400">
                  {song.genre} • {song.engine}
                </p>
              </button>
              <button
                type="button"
                onClick={() => onReuse(song.job_id)}
                className="shrink-0 rounded-full border border-slate-600 px-3 py-1 text-xs text-slate-300 transition hover:border-slate-400"
                title="Load settings into composer"
              >
                Reuse
              </button>
              <button
                type="button"
                onClick={() => handleRemaster(song.job_id)}
                disabled={remastering === song.job_id}
                className="shrink-0 rounded-full border border-cyan-500/50 px-3 py-1 text-xs text-cyan-300 transition hover:border-cyan-400 disabled:opacity-50"
                title="Remaster this song"
              >
                {remastering === song.job_id ? "..." : "Remaster"}
              </button>
              <a
                href={song.download_url}
                download
                className="shrink-0 rounded-full border border-emerald-500/50 px-3 py-1 text-xs text-emerald-300 transition hover:border-emerald-400 hover:text-emerald-200"
                title="Download WAV"
              >
                Download
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
