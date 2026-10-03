"use client";

import { useEffect, useState } from "react";
import AudioPlayer from "@/components/AudioPlayer";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const genreOptions = [
  "mugithi",
  "gospel",
  "benga",
  "mwomboko",
  "afro-pop",
  "acoustic-folk",
];

const moodOptions = ["joyful", "romantic", "reflective", "energetic", "nostalgic"];

export default function PromptComposer() {
  const [prompt, setPrompt] = useState(
    "Warm Mugithi love song with acoustic guitar and glowing vocals"
  );
  const [lyrics, setLyrics] = useState(
    "Nĩngũtũma wendo waku rũrĩrĩ\nNĩngũgũthaithana na ngoro yaku"
  );
  const [language, setLanguage] = useState("gikuyu");
  const [genre, setGenre] = useState("mugithi");
  const [mood, setMood] = useState("romantic");
  const [instruments, setInstruments] = useState(["acoustic guitar", "bass"]);
  const [loading, setLoading] = useState(false);
  const [lyricsLoading, setLyricsLoading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  const toggleInstrument = (instrument: string) => {
    setInstruments((prev) =>
      prev.includes(instrument)
        ? prev.filter((item) => item !== instrument)
        : [...prev, instrument]
    );
  };

  useEffect(() => {
    if (!jobId) return;

    let cancelled = false;
    const poll = async () => {
      try {
        const response = await fetch(`${API_BASE}/jobs/${jobId}`);
        if (!response.ok) return;
        const data = await response.json();
        if (cancelled) return;
        setJobStatus(data.status ?? null);
        if (data.lyrics) {
          setLyrics((prev) => (prev.trim() ? prev : data.lyrics));
        }
        if (data.status === "completed" && data.audio_url) {
          setAudioUrl(data.audio_url);
          window.clearInterval(timer);
        } else if (data.status === "failed") {
          window.clearInterval(timer);
        }
      } catch (error) {
        console.error("Job status poll failed", error);
      }
    };

    const timer = window.setInterval(poll, 3000);
    poll();
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [jobId]);

  const handleGenerateLyrics = async () => {
    if (!prompt.trim()) return;
    setLyricsLoading(true);
    try {
      const response = await fetch(`${API_BASE}/generate-lyrics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: prompt, language, genre, mood }),
      });
      if (!response.ok) throw new Error(`Lyrics request failed: ${response.status}`);
      const data = await response.json();
      if (data.lyrics) {
        setLyrics(data.lyrics);
      }
    } catch (error) {
      console.error("Lyrics generation failed", error);
    } finally {
      setLyricsLoading(false);
    }
  };

  const handleGenerate = async () => {
    setLoading(true);
    setAudioUrl(null);
    setJobStatus("queued");
    try {
      const response = await fetch(`${API_BASE}/generate-song`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          lyrics,
          language,
          genre,
          mood,
          instruments,
          duration_sec: 120,
        }),
      });

      const data = await response.json();
      setJobId(data.job_id ?? null);
      setJobStatus(data.status ?? "queued");
    } catch (error) {
      console.error("Generation request failed", error);
      setJobStatus("failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[1.2fr_0.8fr]">
      <section className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6 shadow-glow">
        <div className="space-y-6">
          <div>
            <label className="mb-2 block text-sm text-slate-300">Prompt</label>
            <input
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Warm Mugithi love song with acoustic guitar and heartfelt vocals"
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none ring-0 transition focus:border-emerald-500"
            />
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm text-slate-300">Language</label>
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none focus:border-emerald-500"
              >
                <option value="gikuyu">Gĩkũyũ</option>
                <option value="swahili">Swahili</option>
                <option value="english">English</option>
              </select>
            </div>

            <div>
              <label className="mb-2 block text-sm text-slate-300">Genre</label>
              <select
                value={genre}
                onChange={(e) => setGenre(e.target.value)}
                className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none focus:border-emerald-500"
              >
                {genreOptions.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm text-slate-300">Mood</label>
            <div className="flex flex-wrap gap-2">
              {moodOptions.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => setMood(option)}
                  className={`rounded-full border px-3 py-2 text-sm transition ${
                    mood === option
                      ? "border-emerald-500 bg-emerald-500 text-white"
                      : "border-slate-700 bg-slate-950 text-slate-300 hover:border-slate-500"
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="mb-2 block text-sm text-slate-300">Instruments</label>
            <div className="flex flex-wrap gap-2">
              {[
                "acoustic guitar",
                "bass",
                "djembe",
                "keyboard",
                "marimba",
                "choir",
              ].map((instrument) => (
                <button
                  key={instrument}
                  type="button"
                  onClick={() => toggleInstrument(instrument)}
                  className={`rounded-full border px-3 py-2 text-sm transition ${
                    instruments.includes(instrument)
                      ? "border-cyan-500 bg-cyan-500/20 text-cyan-200"
                      : "border-slate-700 bg-slate-950 text-slate-300 hover:border-slate-500"
                  }`}
                >
                  {instrument}
                </button>
              ))}
            </div>
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="block text-sm text-slate-300">Lyrics</label>
              <button
                type="button"
                onClick={handleGenerateLyrics}
                disabled={lyricsLoading || !prompt.trim()}
                className="rounded-full border border-cyan-500/50 px-3 py-1 text-xs text-cyan-300 transition hover:border-cyan-400 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
                title="Generate lyrics from the prompt topic"
              >
                {lyricsLoading ? "Writing lyrics..." : "Generate from topic"}
              </button>
            </div>
            <textarea
              rows={12}
              value={lyrics}
              onChange={(e) => setLyrics(e.target.value)}
              className="w-full rounded-2xl border border-slate-700 bg-slate-950 p-4 text-white outline-none focus:border-emerald-500"
              placeholder="Type lyrics in Gĩkũyũ, Swahili, or English..."
            />
          </div>

          <div className="flex items-center justify-between gap-3">
            <button
              type="button"
              onClick={handleGenerate}
              disabled={loading}
              className="rounded-2xl bg-gradient-to-r from-emerald-500 to-cyan-500 px-6 py-3 font-semibold text-white shadow-lg shadow-emerald-500/20 transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {loading ? "Generating..." : "Generate Song"}
            </button>

            <span className="text-xs text-slate-400">Phonetic assist enabled</span>
          </div>

          {jobId && (
            <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-200">
              Job {jobId}: {jobStatus ?? "queued"}
              {jobStatus !== "completed" && jobStatus !== "failed" && (
                <span className="ml-2 text-emerald-300/70">rendering audio output...</span>
              )}
            </div>
          )}
        </div>
      </section>

      <aside className="space-y-6">
        <div className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6">
          <h2 className="mb-4 text-xl font-semibold text-white">Audio Output</h2>
          <AudioPlayer src={audioUrl} />
        </div>

        <div className="rounded-3xl border border-slate-800 bg-slate-900/70 p-6">
          <h2 className="mb-3 text-xl font-semibold text-white">Preset</h2>
          <div className="space-y-3 text-sm text-slate-300">
            <div className="flex justify-between">
              <span>Genre</span>
              <span className="capitalize text-white">{genre}</span>
            </div>
            <div className="flex justify-between">
              <span>Language</span>
              <span className="capitalize text-white">{language}</span>
            </div>
            <div className="flex justify-between">
              <span>Mood</span>
              <span className="capitalize text-white">{mood}</span>
            </div>
          </div>
        </div>
      </aside>
    </div>
  );
}
