"use client";

import { useEffect, useState } from "react";

import StemMixer from "@/components/dj/StemMixer";
import WaveformCanvas from "@/components/dj/WaveformCanvas";
import { fetchSong, updateStem } from "@/lib/dj/api";
import { formatDeckTime, type DeckController } from "@/lib/dj/useDeck";
import type { ApiStem } from "@/lib/dj/types";

interface DeckProps {
  deck: DeckController;
  label: string;
  subtitle: string; // Gĩkũyũ deck name, e.g. "Ngoma ya Mbere"
  accent: string;
  otherDeckBpm: number | null;
}

const STEM_LABELS = ["vocals", "bass", "drums", "melody"];

/**
 * One virtual DJ deck: transport, tempo/pitch-bend, beat loops, 3-band EQ,
 * filter sweep, channel gain, stem remix controls and waveform display.
 */
export default function Deck({ deck, label, subtitle, accent, otherDeckBpm }: DeckProps) {
  const { engine, state } = deck;
  const [urlInput, setUrlInput] = useState("");
  const [songIdInput, setSongIdInput] = useState("");
  const [stemIds, setStemIds] = useState<(number | null)[]>([]);
  const [localError, setLocalError] = useState<string | null>(null);
  const [, setTick] = useState(0);

  // Low-frequency UI ticker for the time/BPM readouts (canvas runs at rAF).
  useEffect(() => {
    const id = window.setInterval(() => setTick((tick) => tick + 1), 200);
    return () => window.clearInterval(id);
  }, []);

  const loadFromUrl = async () => {
    const url = urlInput.trim();
    if (!url) return;
    setStemIds([]);
    await deck.load({ urls: [url], name: url.split("/").pop() ?? url, bpm: null });
  };

  const loadFromCatalog = async () => {
    const id = Number(songIdInput);
    if (!Number.isInteger(id) || id <= 0) return;
    setLocalError(null);
    try {
      const song = await fetchSong(id);
      const stems = (song.stems ?? []).filter((stem) => stem.audio_url);
      if (stems.length > 1) {
        const urls = stems.map((stem) => stem.audio_url as string);
        await deck.load({ urls, name: song.title, bpm: song.tempo_bpm });
        stems.forEach((stem, index) => {
          deck.setStemVolume(index, stem.volume);
          if (stem.is_muted) deck.toggleStemMute(index);
          if (stem.is_solo) deck.toggleStemSolo(index);
        });
        setStemIds(stems.map((stem) => stem.id));
      } else if (song.audio_url) {
        setStemIds([]);
        await deck.load({ urls: [song.audio_url], name: song.title, bpm: song.tempo_bpm });
      } else {
        throw new Error("Song has no audio yet.");
      }
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : "Catalog load failed");
    }
  };

  const persistStem = (stemId: number, patch: Partial<Pick<ApiStem, "volume" | "is_muted" | "is_solo">>) => {
    void updateStem(stemId, patch).catch(() => undefined);
  };

  const effectiveBpm = engine.getEffectiveBpm();
  const position = engine.getPosition();

  return (
    <section className="flex-1 rounded-3xl border border-slate-800 bg-slate-900/70 p-5">
      <header className="mb-4 flex items-baseline justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-white">{label}</h2>
          <p className="text-xs text-slate-400">{subtitle}</p>
        </div>
        <div className="text-right">
          <p className="font-mono text-2xl tabular-nums" style={{ color: accent }}>
            {effectiveBpm !== null ? effectiveBpm.toFixed(1) : "---.-"}
          </p>
          <p className="text-[10px] uppercase tracking-widest text-slate-500">BPM</p>
        </div>
      </header>

      {/* Track loader */}
      <div className="mb-3 space-y-2">
        <div className="flex gap-2">
          <input
            value={urlInput}
            onChange={(event) => setUrlInput(event.target.value)}
            placeholder="Audio URL (generated mix, mp3/wav)…"
            className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={loadFromUrl}
            disabled={state.loading}
            className="shrink-0 rounded-lg border border-emerald-500/60 px-3 py-1.5 text-xs font-medium text-emerald-300 transition hover:bg-emerald-500/20 disabled:opacity-50"
          >
            {state.loading ? "Loading…" : "Load"}
          </button>
        </div>
        <div className="flex gap-2">
          <input
            value={songIdInput}
            onChange={(event) => setSongIdInput(event.target.value)}
            placeholder="Catalog song # (loads stems if split)…"
            inputMode="numeric"
            className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-sky-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={loadFromCatalog}
            disabled={state.loading}
            className="shrink-0 rounded-lg border border-sky-500/60 px-3 py-1.5 text-xs font-medium text-sky-300 transition hover:bg-sky-500/20 disabled:opacity-50"
          >
            Load Song
          </button>
        </div>
        {(localError ?? state.error) && <p className="text-xs text-rose-400">{localError ?? state.error}</p>}
        {state.trackName && <p className="truncate text-xs text-slate-400">▸ {state.trackName}</p>}
      </div>

      <WaveformCanvas engine={engine} accent={accent} />

      {/* Transport row */}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => {
            engine.jumpToCue();
          }}
          onDoubleClick={() => engine.setCueHere()}
          title="Jump to cue — double-click to set cue at playhead"
          className="rounded-lg border border-cyan-500/60 px-4 py-2 text-xs font-bold text-cyan-300 transition hover:bg-cyan-500/20"
        >
          CUE
        </button>
        <button
          type="button"
          onClick={deck.togglePlay}
          disabled={!state.loaded}
          className={`rounded-lg px-6 py-2 text-sm font-bold transition disabled:opacity-40 ${
            state.playing ? "bg-amber-400 text-slate-950" : "bg-emerald-500 text-white hover:bg-emerald-400"
          }`}
        >
          {state.playing ? "PAUSE" : "PLAY"}
        </button>
        <button
          type="button"
          onClick={() => deck.syncTo(otherDeckBpm)}
          disabled={!state.loaded || otherDeckBpm === null}
          title="Match this deck's tempo to the other deck"
          className="rounded-lg border border-fuchsia-500/60 px-4 py-2 text-xs font-bold text-fuchsia-300 transition hover:bg-fuchsia-500/20 disabled:opacity-40"
        >
          SYNC
        </button>
        <div className="mx-1 h-6 w-px bg-slate-700" />
        {[4, 8].map((beats) => (
          <button
            key={beats}
            type="button"
            onClick={() => deck.toggleLoop(beats)}
            disabled={!state.loaded || state.bpm === null}
            title={state.bpm === null ? "BPM unknown — load a catalog track for beat loops" : `${beats}-beat loop`}
            className={`rounded-lg px-3 py-2 text-xs font-bold transition disabled:opacity-40 ${
              state.loopBeats === beats
                ? "bg-amber-400 text-slate-950"
                : "border border-slate-600 text-slate-300 hover:border-amber-300"
            }`}
          >
            {beats}-beat
          </button>
        ))}
        {state.loopBeats !== null && (
          <button
            type="button"
            onClick={() => deck.toggleLoop(state.loopBeats as number)}
            className="rounded-lg border border-slate-600 px-3 py-2 text-xs text-slate-300 hover:border-slate-400"
          >
            Loop off
          </button>
        )}
        <span className="ml-auto font-mono text-xs tabular-nums text-slate-400">
          {formatDeckTime(position)} / {formatDeckTime(engine.duration)}
        </span>
      </div>

      {/* Tempo + pitch bend */}
      <div className="mt-4 grid grid-cols-[auto_1fr_auto] items-center gap-3">
        <button
          type="button"
          onMouseDown={() => engine.bendStart(0.94)}
          onMouseUp={() => engine.bendEnd()}
          onMouseLeave={() => engine.bendEnd()}
          onTouchStart={() => engine.bendStart(0.94)}
          onTouchEnd={() => engine.bendEnd()}
          className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-bold text-slate-200 transition hover:border-emerald-400 active:bg-slate-800"
          title="Pitch bend − (hold)"
        >
          −−
        </button>
        <div>
          <input
            type="range"
            min={0.92}
            max={1.08}
            step={0.001}
            value={state.rate}
            onChange={(event) => deck.setRate(Number(event.target.value))}
            onDoubleClick={() => deck.setRate(1)}
            className="h-1.5 w-full cursor-ns-resize accent-emerald-400"
            aria-label="Tempo"
            title="Tempo — double-click to reset"
          />
          <p className="mt-0.5 text-center text-[10px] tabular-nums text-slate-500">
            tempo {(state.rate * 100 - 100).toFixed(1)}%
          </p>
        </div>
        <button
          type="button"
          onMouseDown={() => engine.bendStart(1.06)}
          onMouseUp={() => engine.bendEnd()}
          onMouseLeave={() => engine.bendEnd()}
          onTouchStart={() => engine.bendStart(1.06)}
          onTouchEnd={() => engine.bendEnd()}
          className="rounded-lg border border-slate-600 px-3 py-1.5 text-sm font-bold text-slate-200 transition hover:border-emerald-400 active:bg-slate-800"
          title="Pitch bend + (hold)"
        >
          ++
        </button>
      </div>

      {/* EQ + filter + gain */}
      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">
        {(
          [
            ["LOW", "low", state.eq.low],
            ["MID", "mid", state.eq.mid],
            ["HIGH", "high", state.eq.high],
          ] as const
        ).map(([labelText, band, value]) => (
          <div key={band} className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2">
            <p className="mb-1 text-center text-[10px] font-semibold tracking-widest text-slate-400">{labelText}</p>
            <input
              type="range"
              min={-26}
              max={6}
              step={0.5}
              value={value}
              onChange={(event) => deck.setEq(band, Number(event.target.value))}
              onDoubleClick={() => deck.setEq(band, 0)}
              className="h-1 w-full cursor-pointer accent-emerald-400"
              aria-label={`${labelText} EQ`}
            />
            <p className="mt-0.5 text-center text-[10px] tabular-nums text-slate-500">{value.toFixed(1)} dB</p>
          </div>
        ))}
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2">
          <p className="mb-1 text-center text-[10px] font-semibold tracking-widest text-slate-400">FILTER</p>
          <input
            type="range"
            min={-100}
            max={100}
            step={1}
            value={Math.round(state.filterValue * 100)}
            onChange={(event) => deck.setFilter(Number(event.target.value) / 100)}
            onDoubleClick={() => deck.setFilter(0)}
            className="h-1 w-full cursor-pointer accent-fuchsia-400"
            aria-label="Filter sweep"
            title="Left: low-pass · Right: high-pass"
          />
          <p className="mt-0.5 text-center text-[10px] text-slate-500">
            {state.filterValue < -0.03 ? "LP" : state.filterValue > 0.03 ? "HP" : "open"}
          </p>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-3 py-2">
          <p className="mb-1 text-center text-[10px] font-semibold tracking-widest text-slate-400">GAIN</p>
          <input
            type="range"
            min={0}
            max={1.5}
            step={0.01}
            value={state.gain}
            onChange={(event) => deck.setGain(Number(event.target.value))}
            onDoubleClick={() => deck.setGain(1)}
            className="h-1 w-full cursor-pointer accent-sky-400"
            aria-label="Channel gain"
          />
          <p className="mt-0.5 text-center text-[10px] tabular-nums text-slate-500">{state.gain.toFixed(2)}</p>
        </div>
      </div>

      {/* Stem remix deck */}
      <div className="mt-4">
        <StemMixer
          engine={engine}
          stemLabels={STEM_LABELS.slice(0, state.stemCount)}
          stemIds={stemIds}
          stems={state.stems}
          onVolume={deck.setStemVolume}
          onToggleMute={deck.toggleStemMute}
          onToggleSolo={deck.toggleStemSolo}
          onPersist={persistStem}
        />
      </div>
    </section>
  );
}
