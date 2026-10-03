"use client";

import { useEffect, useRef, useState } from "react";

type AudioPlayerProps = {
  src?: string | null;
  waveform?: number[];
};

const formatTime = (seconds: number) => {
  if (!Number.isFinite(seconds)) return "0:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
};

export default function AudioPlayer({ src, waveform }: AudioPlayerProps) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const progressRef = useRef<HTMLDivElement | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [volume, setVolume] = useState(0.8);
  const [isMuted, setIsMuted] = useState(false);

  const hasOutput = Boolean(src);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    const handleTimeUpdate = () => {
      setCurrentTime(audio.currentTime);
      const pct = audio.duration ? (audio.currentTime / audio.duration) * 100 : 0;
      setProgress(Number.isFinite(pct) ? pct : 0);
    };
    const handleLoadedMetadata = () => setDuration(audio.duration || 0);
    const handleEnded = () => {
      setIsPlaying(false);
      setProgress(0);
      setCurrentTime(0);
    };

    audio.addEventListener("timeupdate", handleTimeUpdate);
    audio.addEventListener("loadedmetadata", handleLoadedMetadata);
    audio.addEventListener("ended", handleEnded);
    return () => {
      audio.removeEventListener("timeupdate", handleTimeUpdate);
      audio.removeEventListener("loadedmetadata", handleLoadedMetadata);
      audio.removeEventListener("ended", handleEnded);
    };
  }, []);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    setIsPlaying(false);
    setProgress(0);
    setCurrentTime(0);
    setDuration(0);
    if (src) {
      audio.load();
    }
  }, [src]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.volume = volume;
    }
  }, [volume]);

  useEffect(() => {
    const audio = audioRef.current;
    if (audio) {
      audio.muted = isMuted;
    }
  }, [isMuted]);

  const togglePlayback = async () => {
    const audio = audioRef.current;
    if (!audio || !hasOutput) return;

    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
      return;
    }

    try {
      await audio.play();
      setIsPlaying(true);
    } catch (error) {
      console.error("Audio output failed to start", error);
      setIsPlaying(false);
    }
  };

  const handleSeek = (event: React.MouseEvent<HTMLDivElement>) => {
    const audio = audioRef.current;
    const bar = progressRef.current;
    if (!audio || !bar || !hasOutput || !audio.duration) return;

    const rect = bar.getBoundingClientRect();
    const ratio = Math.min(Math.max((event.clientX - rect.left) / rect.width, 0), 1);
    audio.currentTime = ratio * audio.duration;
    setProgress(ratio * 100);
    setCurrentTime(audio.currentTime);
  };

  const bars =
    waveform && waveform.length > 0
      ? waveform.slice(0, 64).map((peak) => 20 + Math.min(peak, 1) * 80)
      : Array.from({ length: 32 }).map((_, index) => 24 + ((index * 17) % 60));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">Audio Output</p>
          <h3 className="mt-1 text-lg font-semibold text-white">Generated Track</h3>
          <p className={`mt-1 text-xs ${hasOutput ? "text-emerald-400" : "text-slate-500"}`}>
            {hasOutput ? "Output enabled" : "Generate a song to enable output"}
          </p>
        </div>
        <button
          type="button"
          onClick={togglePlayback}
          disabled={!hasOutput}
          className="rounded-full bg-emerald-500 px-4 py-2 text-sm font-semibold text-white transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
        >
          {isPlaying ? "Pause" : "Play"}
        </button>
      </div>

      <div className="h-20 rounded-2xl border border-slate-700 bg-slate-950 p-3">
        <div className="flex h-full items-end gap-1">
          {bars.map((height, index) => {
            const active = index / bars.length < progress / 100;
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

      <div
        ref={progressRef}
        onClick={handleSeek}
        className={`h-2 w-full rounded-full bg-slate-800 ${hasOutput ? "cursor-pointer" : "cursor-not-allowed opacity-60"}`}
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress)}
      >
        <div
          className="h-full rounded-full bg-gradient-to-r from-emerald-500 to-cyan-400"
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>{formatTime(currentTime)}</span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIsMuted((prev) => !prev)}
            disabled={!hasOutput}
            className="rounded-full border border-slate-700 px-3 py-1 text-slate-300 transition hover:border-slate-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isMuted ? "Unmute" : "Mute"}
          </button>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={volume}
            disabled={!hasOutput}
            onChange={(event) => setVolume(Number(event.target.value))}
            className="h-1 w-24 accent-emerald-500 disabled:opacity-50"
            aria-label="Volume"
          />
        </div>
        <span>{formatTime(duration)}</span>
      </div>

      <audio ref={audioRef} src={src ?? undefined} className="hidden" preload="metadata" />
    </div>
  );
}
