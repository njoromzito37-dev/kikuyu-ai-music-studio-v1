"use client";

import { useEffect, useRef, useState } from "react";

export default function AudioPlayer({ src }: { src: string }) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const handleTimeUpdate = () => {
      const pct = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
      setProgress(Number.isFinite(pct) ? pct : 0);
    };

    audio.addEventListener("timeupdate", handleTimeUpdate);
    return () => audio.removeEventListener("timeupdate", handleTimeUpdate);
  }, []);

  const togglePlayback = async () => {
    const audio = audioRef.current;
    if (!audio) return;

    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
      return;
    }

    await audio.play();
    setIsPlaying(true);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Preview</p>
          <h3 className="mt-1 text-lg font-semibold text-white">Generated Track</h3>
        </div>
        <button
          type="button"
          onClick={togglePlayback}
          className="rounded-full bg-emerald-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-400"
        >
          {isPlaying ? "Pause" : "Play"}
        </button>
      </div>

      <div className="h-20 rounded-2xl border border-slate-700 bg-slate-950 p-3">
        <div className="flex h-full items-end gap-1">
          {Array.from({ length: 32 }).map((_, index) => {
            const height = 24 + ((index * 17) % 60);
            const active = index / 32 < progress / 100;

            return (
              <div
                key={index}
                className={`flex-1 rounded-t-md ${active ? "bg-gradient-to-t from-emerald-500 to-cyan-400" : "bg-slate-700"}`}
                style={{ height: `${height}%` }}
              />
            );
          })}
        </div>
      </div>

      <audio ref={audioRef} src={src} className="hidden" />
    </div>
  );
}
