"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { DeckEngine } from "./audioEngine";
import type { TrackLoadRequest } from "./types";

export interface DeckUiState {
  loaded: boolean;
  loading: boolean;
  playing: boolean;
  trackName: string;
  bpm: number | null;
  rate: number;
  loopBeats: number | null;
  filterValue: number;
  eq: { low: number; mid: number; high: number };
  gain: number;
  stemCount: number;
  stems: { volume: number; muted: boolean; solo: boolean }[];
  error: string | null;
}

const INITIAL_STATE: DeckUiState = {
  loaded: false,
  loading: false,
  playing: false,
  trackName: "",
  bpm: null,
  rate: 1,
  loopBeats: null,
  filterValue: 0,
  eq: { low: 0, mid: 0, high: 0 },
  gain: 1,
  stemCount: 0,
  stems: [],
  error: null,
};

/**
 * React binding around a DeckEngine. The engine instance is stable per hook;
 * state refreshes happen on explicit user actions (the waveform canvas pulls
 * per-frame data straight from the engine to avoid 60fps React renders).
 */
export function useDeck() {
  const engineRef = useRef<DeckEngine | null>(null);
  if (engineRef.current === null) {
    engineRef.current = new DeckEngine();
  }
  const engine = engineRef.current;
  const [state, setState] = useState<DeckUiState>(INITIAL_STATE);

  useEffect(() => () => engine.dispose(), [engine]);

  const patch = useCallback((partial: Partial<DeckUiState>) => {
    setState((previous) => ({ ...previous, ...partial }));
  }, []);

  const load = useCallback(
    async (request: TrackLoadRequest) => {
      patch({ loading: true, error: null });
      try {
        await engine.loadUrls(request.urls, request.name, request.bpm);
        patch({
          loading: false,
          loaded: true,
          playing: false,
          trackName: request.name,
          bpm: request.bpm,
          rate: 1,
          loopBeats: null,
          stemCount: engine.stemCount,
          stems: engine.getStemState(),
        });
      } catch (error) {
        patch({ loading: false, loaded: false, error: error instanceof Error ? error.message : "Load failed" });
      }
    },
    [engine, patch],
  );

  const togglePlay = useCallback(() => {
    if (engine.playing) {
      engine.pause();
      patch({ playing: false });
    } else if (engine.isLoaded) {
      engine.play();
      patch({ playing: true });
    }
  }, [engine, patch]);

  const setRate = useCallback(
    (rate: number) => {
      engine.setRate(rate);
      patch({ rate: engine.getRate() });
    },
    [engine, patch],
  );

  const syncTo = useCallback(
    (targetBpm: number | null) => {
      engine.syncToBpm(targetBpm);
      patch({ rate: engine.getRate() });
    },
    [engine, patch],
  );

  const toggleLoop = useCallback(
    (beats: number) => {
      engine.setLoopBeats(engine.loopBeats === beats ? null : beats);
      patch({ loopBeats: engine.loopBeats });
    },
    [engine, patch],
  );

  const setEq = useCallback(
    (band: "low" | "mid" | "high", value: number) => {
      setState((previous) => {
        const eq = { ...previous.eq, [band]: value };
        engine.setEq(eq.low, eq.mid, eq.high);
        return { ...previous, eq };
      });
    },
    [engine],
  );

  const setFilter = useCallback(
    (value: number) => {
      engine.setFilterSweep(value);
      patch({ filterValue: value });
    },
    [engine, patch],
  );

  const setGain = useCallback(
    (value: number) => {
      engine.setChannelGain(value);
      patch({ gain: value });
    },
    [engine, patch],
  );

  const setStemVolume = useCallback(
    (index: number, volume: number) => {
      engine.setStemVolume(index, volume);
      patch({ stems: engine.getStemState() });
    },
    [engine, patch],
  );

  const toggleStemMute = useCallback(
    (index: number) => {
      const current = engine.getStemState()[index];
      engine.setStemMuted(index, !current?.muted);
      patch({ stems: engine.getStemState() });
    },
    [engine, patch],
  );

  const toggleStemSolo = useCallback(
    (index: number) => {
      const current = engine.getStemState()[index];
      engine.setStemSoloed(index, !current?.solo);
      patch({ stems: engine.getStemState() });
    },
    [engine, patch],
  );

  return {
    engine,
    state,
    load,
    togglePlay,
    setRate,
    syncTo,
    toggleLoop,
    setEq,
    setFilter,
    setGain,
    setStemVolume,
    toggleStemMute,
    toggleStemSolo,
  };
}

export type DeckController = ReturnType<typeof useDeck>;

/** Format seconds as m:ss for deck readouts. */
export function formatDeckTime(seconds: number): string {
  if (!Number.isFinite(seconds)) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
