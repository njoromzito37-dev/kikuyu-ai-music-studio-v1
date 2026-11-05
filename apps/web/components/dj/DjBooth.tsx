"use client";

import { useEffect, useState } from "react";

import Crossfader from "@/components/dj/Crossfader";
import Deck from "@/components/dj/Deck";
import MashupPanel from "@/components/dj/MashupPanel";
import { useDeck } from "@/lib/dj/useDeck";

/**
 * Dual-deck virtual DJ booth ("Kĩyũĩ kĩa DJ" — the DJ's deck/table).
 *
 * Two DeckEngines feed one master bus through an equal-power crossfader.
 * Everything runs client-side in the Web Audio API for low-latency control;
 * heavy renders (mashups, effects chains, stem separation) are delegated to
 * the Django/Celery backend via the mashup panel.
 */
export default function DjBooth() {
  const deckA = useDeck();
  const deckB = useDeck();
  const [crossfade, setCrossfade] = useState(0);

  // Equal-power crossfade: constant perceived loudness across the sweep.
  useEffect(() => {
    const angle = ((crossfade + 1) * Math.PI) / 4; // 0 .. π/2
    deckA.engine.setCrossfadeGain(Math.cos(angle));
    deckB.engine.setCrossfadeGain(Math.sin(angle));
  }, [crossfade, deckA.engine, deckB.engine]);

  const sendToDeck = (deck: "A" | "B", url: string, name: string, bpm: number | null) => {
    const controller = deck === "A" ? deckA : deckB;
    void controller.load({ urls: [url], name, bpm });
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.25em] text-fuchsia-400">Live Mixing</p>
          <h2 className="mt-1 text-2xl font-bold text-white">
            Gĩkũyũ DJ Booth <span className="text-slate-400">— Kĩyũĩ kĩa Ngoma</span>
          </h2>
        </div>
        <div className="rounded-full border border-fuchsia-500/30 bg-fuchsia-500/10 px-3 py-1 text-sm text-fuchsia-300">
          Decks + Stems + Mashups
        </div>
      </header>

      <div className="flex flex-col gap-4 xl:flex-row">
        <Deck deck={deckA} label="Deck A" subtitle="Ngoma ya Mbere" accent="#34d399" otherDeckBpm={deckB.engine.getEffectiveBpm()} />
        <Deck deck={deckB} label="Deck B" subtitle="Ngoma ya Keeri" accent="#38bdf8" otherDeckBpm={deckA.engine.getEffectiveBpm()} />
      </div>

      <div className="mx-auto max-w-xl">
        <Crossfader value={crossfade} onChange={setCrossfade} />
      </div>

      <MashupPanel onSendToDeck={sendToDeck} />
    </div>
  );
}
