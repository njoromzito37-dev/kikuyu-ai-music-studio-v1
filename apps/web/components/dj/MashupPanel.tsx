"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { createMixJob, fetchMixJob, fetchSongs, resolveMediaUrl } from "@/lib/dj/api";
import type { DjMixJob, LibraryTrack, TransitionStyle } from "@/lib/dj/types";

interface MashupPanelProps {
  onSendToDeck: (deck: "A" | "B", url: string, name: string, bpm: number | null) => void;
}

const TRANSITIONS: { value: TransitionStyle; label: string; hint: string }[] = [
  { value: "cut", label: "Cut", hint: "Hard switch from A to B" },
  { value: "crossfade", label: "Smooth Crossfade", hint: "Equal-power blend over the transition bars" },
  { value: "drop_swap", label: "Drop Swap", hint: "A plays out, one-bar gap, B drops in" },
  { value: "echo_out", label: "Echo Out", hint: "A tails into feedback echo while B enters" },
];

const POLL_MS = 2500;

/**
 * Automated mashup & transition engine panel: pick two catalog tracks, choose
 * a transition style, and let the Celery worker tempo/key-match and render the
 * mix. The result can be sent straight onto a deck.
 */
export default function MashupPanel({ onSendToDeck }: MashupPanelProps) {
  const [songs, setSongs] = useState<LibraryTrack[]>([]);
  const [authProblem, setAuthProblem] = useState(false);
  const [trackA, setTrackA] = useState("");
  const [trackB, setTrackB] = useState("");
  const [transition, setTransition] = useState<TransitionStyle>("crossfade");
  const [bars, setBars] = useState(8);
  const [matchTempo, setMatchTempo] = useState(true);
  const [matchKey, setMatchKey] = useState(true);
  const [job, setJob] = useState<DjMixJob | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    fetchSongs()
      .then((list) => setSongs(list.filter((song) => song.status === "COMPLETED" && song.audio_url)))
      .catch(() => setAuthProblem(true));
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
  }, []);

  const stopPolling = () => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = useCallback((jobId: number) => {
    stopPolling();
    pollRef.current = window.setInterval(() => {
      fetchMixJob(jobId)
        .then((updated) => {
          setJob(updated);
          if (updated.status === "COMPLETED" || updated.status === "FAILED") {
            stopPolling();
            setBusy(false);
          }
        })
        .catch(() => {
          stopPolling();
          setBusy(false);
        });
    }, POLL_MS);
  }, []);

  const submit = async () => {
    if (!trackA || !trackB) return;
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const created = await createMixJob({
        track_a: Number(trackA),
        track_b: Number(trackB),
        transition,
        transition_bars: bars,
        match_tempo: matchTempo,
        match_key: matchKey,
      });
      setJob(created);
      startPolling(created.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Mix request failed");
      setBusy(false);
    }
  };

  const outputUrl = resolveMediaUrl(job?.output_url);
  const readySongs = songs;

  return (
    <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6">
      <header className="mb-4">
        <h2 className="text-lg font-bold text-white">
          Mashup &amp; Transition Engine <span className="text-emerald-400">— Kũgermania kwa Ngoma</span>
        </h2>
        <p className="mt-1 text-xs text-slate-400">
          The worker analyzes BPM &amp; key (Camelot), time-stretches and transposes track B onto track A, then renders
          the transition style you pick.
        </p>
      </header>

      {authProblem ? (
        <p className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-xs text-amber-200">
          Sign in to the Django API (session auth) to render server-side mashups. The decks above keep working with
          direct audio URLs.
        </p>
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {(
              [
                ["Track A (Ngoma ya Mbere)", trackA, setTrackA],
                ["Track B (Ngoma ya Keeri)", trackB, setTrackB],
              ] as const
            ).map(([labelText, value, setter]) => (
              <label key={labelText} className="block">
                <span className="mb-1 block text-[11px] font-semibold uppercase tracking-widest text-slate-400">
                  {labelText}
                </span>
                <select
                  value={value}
                  onChange={(event) => setter(event.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs text-slate-200 focus:border-emerald-500 focus:outline-none"
                >
                  <option value="">Choose a completed song…</option>
                  {readySongs.map((song) => (
                    <option key={song.id} value={song.id}>
                      #{song.id} — {song.title}
                      {song.tempo_bpm ? ` · ${song.tempo_bpm} BPM` : ""}
                      {song.camelot ? ` · ${song.camelot}` : ""}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>

          <div className="mt-3 grid gap-3 sm:grid-cols-4">
            {TRANSITIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                onClick={() => setTransition(option.value)}
                title={option.hint}
                className={`rounded-xl border px-3 py-2 text-left transition ${
                  transition === option.value
                    ? "border-emerald-400 bg-emerald-500/15 text-emerald-200"
                    : "border-slate-700 text-slate-300 hover:border-slate-500"
                }`}
              >
                <p className="text-xs font-bold">{option.label}</p>
                <p className="mt-0.5 text-[10px] leading-snug text-slate-500">{option.hint}</p>
              </button>
            ))}
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2 text-xs text-slate-300">
              Bars
              <select
                value={bars}
                onChange={(event) => setBars(Number(event.target.value))}
                className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs"
              >
                {[2, 4, 8, 16, 32].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-300">
              <input type="checkbox" checked={matchTempo} onChange={(event) => setMatchTempo(event.target.checked)} className="accent-emerald-400" />
              Match tempo (beatmatch)
            </label>
            <label className="flex items-center gap-2 text-xs text-slate-300">
              <input type="checkbox" checked={matchKey} onChange={(event) => setMatchKey(event.target.checked)} className="accent-emerald-400" />
              Match key (harmonic mix)
            </label>
            <button
              type="button"
              onClick={submit}
              disabled={busy || !trackA || !trackB || trackA === trackB}
              className="ml-auto rounded-xl bg-emerald-500 px-5 py-2 text-xs font-bold text-white transition hover:bg-emerald-400 disabled:opacity-40"
            >
              {busy ? "Mixing…" : "Render Mix"}
            </button>
          </div>

          {error && <p className="mt-3 text-xs text-rose-400">{error}</p>}

          {job && (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/60 p-4">
              <div className="flex flex-wrap items-center gap-3">
                <span
                  className={`rounded-full px-2.5 py-0.5 text-[10px] font-bold ${
                    job.status === "COMPLETED"
                      ? "bg-emerald-500/20 text-emerald-300"
                      : job.status === "FAILED"
                        ? "bg-rose-500/20 text-rose-300"
                        : "bg-amber-500/20 text-amber-300"
                  }`}
                >
                  {job.status}
                </span>
                <p className="text-xs text-slate-400">
                  mix #{job.id} · {job.transition} · {job.transition_bars} bars
                </p>
                {job.analysis?.track_a?.bpm && (
                  <p className="text-[10px] text-slate-500">
                    A: {Math.round(job.analysis.track_a.bpm)} BPM {job.analysis.track_a.key?.camelot ?? ""} · B:{" "}
                    {job.analysis.track_b?.bpm ? Math.round(job.analysis.track_b.bpm) : "?"} BPM{" "}
                    {job.analysis.track_b?.key?.camelot ?? ""}
                  </p>
                )}
              </div>
              {job.status === "FAILED" && <p className="mt-2 text-xs text-rose-400">{job.failure_reason}</p>}
              {outputUrl && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
                  <audio controls src={outputUrl} className="h-9 w-64" />
                  <button
                    type="button"
                    onClick={() => onSendToDeck("A", outputUrl, `Mix #${job.id}`, job.analysis?.track_a?.bpm ?? null)}
                    className="rounded-lg border border-emerald-500/60 px-3 py-1.5 text-xs text-emerald-300 hover:bg-emerald-500/20"
                  >
                    → Deck A
                  </button>
                  <button
                    type="button"
                    onClick={() => onSendToDeck("B", outputUrl, `Mix #${job.id}`, job.analysis?.track_a?.bpm ?? null)}
                    className="rounded-lg border border-sky-500/60 px-3 py-1.5 text-xs text-sky-300 hover:bg-sky-500/20"
                  >
                    → Deck B
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </section>
  );
}
