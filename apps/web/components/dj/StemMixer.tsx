"use client";

import { useEffect, useState } from "react";

import type { DeckEngine } from "@/lib/dj/audioEngine";
import { formatDeckTime } from "@/lib/dj/useDeck";
import type { ApiStem } from "@/lib/dj/types";

interface StemMixerProps {
  engine: DeckEngine;
  stemLabels: string[];
  stemIds: (number | null)[]; // Django stem ids when known (enables persistence)
  stems: { volume: number; muted: boolean; solo: boolean }[];
  onVolume: (index: number, volume: number) => void;
  onToggleMute: (index: number) => void;
  onToggleSolo: (index: number) => void;
  onPersist?: (stemId: number, patch: Partial<Pick<ApiStem, "volume" | "is_muted" | "is_solo">>) => void;
}

const STEM_BADGES: Record<string, string> = {
  vocals: "bg-rose-500/20 text-rose-300 border-rose-500/40",
  bass: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  drums: "bg-sky-500/20 text-sky-300 border-sky-500/40",
  melody: "bg-violet-500/20 text-violet-300 border-violet-500/40",
};

/**
 * Per-stem remix control strip: volume fader plus mute/solo, applied live to
 * the deck's Web Audio gain nodes and (when the stems came from the Django
 * catalog) persisted back to the API.
 */
export default function StemMixer({
  engine,
  stemLabels,
  stemIds,
  stems,
  onVolume,
  onToggleMute,
  onToggleSolo,
  onPersist,
}: StemMixerProps) {
  const [, setTick] = useState(0);

  // Keep the visible position/meters fresh without re-rendering at 60fps.
  useEffect(() => {
    const id = window.setInterval(() => setTick((tick) => tick + 1), 250);
    return () => window.clearInterval(id);
  }, []);

  if (stems.length <= 1) return null;

  return (
    <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-950/60 p-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">
        Stem Deck <span className="text-emerald-400">(Mũtī wa Ngoma)</span>
      </p>
      {stems.map((stem, index) => {
        const label = stemLabels[index] ?? `stem ${index + 1}`;
        const badge = STEM_BADGES[label] ?? "bg-slate-700/40 text-slate-300 border-slate-600";
        const stemId = stemIds[index] ?? null;
        return (
          <div key={`${label}-${index}`} className="flex items-center gap-2">
            <span className={`w-16 rounded-full border px-2 py-0.5 text-center text-[10px] font-medium capitalize ${badge}`}>
              {label}
            </span>
            <input
              type="range"
              min={0}
              max={1.5}
              step={0.01}
              value={stem.volume}
              onChange={(event) => {
                const volume = Number(event.target.value);
                onVolume(index, volume);
                if (stemId !== null) onPersist?.(stemId, { volume });
              }}
              className="h-1 flex-1 cursor-pointer accent-emerald-400"
              aria-label={`${label} volume`}
            />
            <button
              type="button"
              onClick={() => {
                onToggleMute(index);
                if (stemId !== null) onPersist?.(stemId, { is_muted: !stem.muted });
              }}
              className={`h-6 w-7 rounded text-[10px] font-bold transition ${
                stem.muted ? "bg-rose-500 text-white" : "border border-slate-600 text-slate-300 hover:border-rose-400"
              }`}
              title={stem.muted ? "Unmute" : "Mute"}
            >
              M
            </button>
            <button
              type="button"
              onClick={() => {
                onToggleSolo(index);
                if (stemId !== null) onPersist?.(stemId, { is_solo: !stem.solo });
              }}
              className={`h-6 w-7 rounded text-[10px] font-bold transition ${
                stem.solo ? "bg-amber-400 text-slate-950" : "border border-slate-600 text-slate-300 hover:border-amber-300"
              }`}
              title={stem.solo ? "Unsolo" : "Solo"}
            >
              S
            </button>
          </div>
        );
      })}
      <p className="text-right text-[10px] tabular-nums text-slate-500">{formatDeckTime(engine.getPosition())}</p>
    </div>
  );
}
