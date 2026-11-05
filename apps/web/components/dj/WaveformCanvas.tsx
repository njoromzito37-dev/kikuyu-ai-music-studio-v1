"use client";

import { useEffect, useRef } from "react";

import type { DeckEngine } from "@/lib/dj/audioEngine";

interface WaveformCanvasProps {
  engine: DeckEngine;
  accent: string; // tailwind-compatible hex, e.g. "#10b981"
  height?: number;
  onSeek?: () => void;
}

/**
 * In-browser waveform + live spectrum visualizer.
 *
 * Renders the downsampled peak waveform, the real-time frequency spectrum from
 * the deck's AnalyserNode, the loop region, the cue marker, and the playback
 * head. Draws imperatively via requestAnimationFrame so no React re-render
 * happens per frame. Click/drag seeks.
 */
export default function WaveformCanvas({ engine, accent, height = 96, onSeek }: WaveformCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const peaksRef = useRef<number[]>([]);
  const trackSignatureRef = useRef("");
  const seekingRef = useRef(false);

  // Recompute static peaks whenever a different track lands on the deck.
  useEffect(() => {
    const id = window.setInterval(() => {
      const signature = engine.isLoaded ? `${engine.trackName}:${engine.duration.toFixed(3)}` : "";
      if (signature !== trackSignatureRef.current) {
        trackSignatureRef.current = signature;
        peaksRef.current = signature ? engine.getPeaks(240) : [];
      }
    }, 400);
    return () => window.clearInterval(id);
  }, [engine]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const spectrum = new Uint8Array(128);
    let raf = 0;

    const draw = () => {
      raf = window.requestAnimationFrame(draw);
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      const { width, height: h } = canvas;
      ctx.clearRect(0, 0, width, h);
      ctx.fillStyle = "rgba(2, 6, 23, 0.9)";
      ctx.fillRect(0, 0, width, h);

      const peaks = peaksRef.current;
      const duration = engine.duration;
      const position = engine.getPosition();
      const playX = duration > 0 ? (position / duration) * width : 0;

      // Waveform (played portion brighter).
      if (peaks.length > 0) {
        const barWidth = width / peaks.length;
        for (let i = 0; i < peaks.length; i += 1) {
          const x = i * barWidth;
          const amplitude = Math.max(2, peaks[i] * (h * 0.72));
          ctx.fillStyle = x <= playX ? accent : "rgba(100, 116, 139, 0.55)";
          ctx.fillRect(x, h / 2 - amplitude / 2, Math.max(1, barWidth - 0.5), amplitude);
        }
      }

      // Loop region.
      const loop = engine.getLoopRegion();
      if (loop && duration > 0) {
        ctx.fillStyle = "rgba(245, 158, 11, 0.16)";
        ctx.fillRect((loop.start / duration) * width, 0, ((loop.end - loop.start) / duration) * width, h);
      }

      // Cue marker.
      if (engine.cuePoint > 0 && duration > 0) {
        ctx.strokeStyle = "#22d3ee";
        ctx.beginPath();
        ctx.moveTo((engine.cuePoint / duration) * width, 0);
        ctx.lineTo((engine.cuePoint / duration) * width, h);
        ctx.stroke();
      }

      // Live spectrum along the bottom edge.
      if (engine.readSpectrum(spectrum)) {
        const bins = spectrum.length;
        const barWidth = width / bins;
        ctx.fillStyle = "rgba(52, 211, 153, 0.5)";
        for (let i = 0; i < bins; i += 1) {
          const magnitude = (spectrum[i] / 255) * h * 0.35;
          ctx.fillRect(i * barWidth, h - magnitude, Math.max(1, barWidth - 0.5), magnitude);
        }
      }

      // Playback head.
      if (engine.isLoaded) {
        ctx.strokeStyle = "#f8fafc";
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(playX, 0);
        ctx.lineTo(playX, h);
        ctx.stroke();
        ctx.lineWidth = 1;
      }
    };

    raf = window.requestAnimationFrame(draw);
    return () => window.cancelAnimationFrame(raf);
  }, [engine, accent]);

  const seekFromEvent = (clientX: number) => {
    const canvas = canvasRef.current;
    if (!canvas || !engine.isLoaded) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    engine.seek(ratio * engine.duration);
    onSeek?.();
  };

  return (
    <canvas
      ref={canvasRef}
      width={720}
      height={height}
      className="h-24 w-full cursor-crosshair rounded-xl border border-slate-800"
      onMouseDown={(event) => {
        seekingRef.current = true;
        seekFromEvent(event.clientX);
      }}
      onMouseMove={(event) => {
        if (seekingRef.current) seekFromEvent(event.clientX);
      }}
      onMouseUp={() => {
        seekingRef.current = false;
      }}
      onMouseLeave={() => {
        seekingRef.current = false;
      }}
      aria-label="Waveform — click to seek"
    />
  );
}
