"use client";

interface CrossfaderProps {
  value: number; // -1 (full A) .. 0 (center) .. +1 (full B)
  onChange: (value: number) => void;
}

/**
 * Physical-style crossfader linking Deck A and Deck B.
 * The parent applies equal-power gains: cos/sin over a quarter circle.
 */
export default function Crossfader({ value, onChange }: CrossfaderProps) {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/70 px-6 py-4">
      <div className="mb-2 flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.2em]">
        <span className="text-emerald-400">Deck A</span>
        <span className="text-slate-400">Crossfader</span>
        <span className="text-sky-400">Deck B</span>
      </div>
      <input
        type="range"
        min={-100}
        max={100}
        step={1}
        value={Math.round(value * 100)}
        onChange={(event) => onChange(Number(event.target.value) / 100)}
        onDoubleClick={() => onChange(0)}
        className="h-2 w-full cursor-ew-resize accent-fuchsia-400"
        aria-label="Crossfader"
        title="Drag to blend Deck A and Deck B — double-click to center"
      />
      <div className="mt-1 flex justify-between text-[10px] text-slate-500">
        <span>A</span>
        <span className="tabular-nums">{value === 0 ? "center" : value < 0 ? `A ${Math.round(-value * 100)}%` : `B ${Math.round(value * 100)}%`}</span>
        <span>B</span>
      </div>
    </div>
  );
}
