"use client";

import { useEffect, useState } from "react";
import AudioPlayer from "@/components/AudioPlayer";
import SongLibrary from "@/components/SongLibrary";

// Call the API through the Next.js proxy (same origin as the page) so the
// browser never talks to the backend port directly; works in Codespaces.
const API_BASE = "/api";

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
  const [topic, setTopic] = useState("Wendo wa mũtũranĩri");
  const [lyrics, setLyrics] = useState(
    "Nĩngũtũma wendo waku rũrĩrĩ\nNĩngũgũthaithana na ngoro yaku"
  );
  const [language, setLanguage] = useState("gikuyu");
  const [genre, setGenre] = useState("mugithi");
  const [mood, setMood] = useState("romantic");
  const [instruments, setInstruments] = useState(["acoustic guitar", "bass"]);
  const [loading, setLoading] = useState(false);
  const [lyricsLoading, setLyricsLoading] = useState(false);
  const [styleLoading, setStyleLoading] = useState(false);
  const [stylePrompt, setStylePrompt] = useState("");
  const [useSunoStyle, setUseSunoStyle] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [waveform, setWaveform] = useState<number[]>([]);
  const [references, setReferences] = useState<string[]>([]);
  const [suno, setSuno] = useState<{ enabled: boolean; functions: string[] } | null>(null);
  const [libraryRefresh, setLibraryRefresh] = useState(0);
  const [instrumentCatalog, setInstrumentCatalog] = useState<{ slug: string; name: string; category: string }[]>([]);

  useEffect(() => {
    fetch(`${API_BASE}/suno/enabled`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setSuno(data))
      .catch(() => setSuno(null));
    fetch(`${API_BASE}/instruments`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => data && setInstrumentCatalog(data.instruments ?? []))
      .catch(() => setInstrumentCatalog([]));
  }, []);

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
        if (Array.isArray(data.references) && data.references.length > 0) {
          setReferences(data.references);
        }
        if (data.status === "completed" && data.audio_url) {
          const url = data.audio_url.startsWith("/") ? `${API_BASE}${data.audio_url}` : data.audio_url;
          setAudioUrl(url);
          setWaveform(Array.isArray(data.waveform) ? data.waveform : []);
          setLibraryRefresh((key) => key + 1);
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
    const subject = topic.trim() || prompt.trim();
    if (!subject) return;
    setLyricsLoading(true);
    try {
      const response = await fetch(`${API_BASE}/generate-lyrics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: subject, language, genre, mood }),
      });
      if (!response.ok) throw new Error(`Lyrics request failed: ${response.status}`);
      const data = await response.json();
      if (data.lyrics) {
        setLyrics(data.lyrics);
      }
      if (Array.isArray(data.references)) {
        setReferences(data.references);
      }
    } catch (error) {
      console.error("Lyrics generation failed", error);
    } finally {
      setLyricsLoading(false);
    }
  };

  const handleStylePrompt = async () => {
    setStyleLoading(true);
    try {
      const response = await fetch(`${API_BASE}/style-prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ genre, mood, instruments, language, topic: topic.trim() || prompt.trim(), use_suno: useSunoStyle }),
      });
      if (!response.ok) throw new Error(`Style prompt failed: ${response.status}`);
      const data = await response.json();
      if (data.style_prompt) {
        setStylePrompt(data.style_prompt);
      }
    } catch (error) {
      console.error("Style prompt failed", error);
    } finally {
      setStyleLoading(false);
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
          topic,
          style_prompt: stylePrompt || undefined,
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

  const handleReuse = async (reuseJobId: string) => {
    try {
      const response = await fetch(`${API_BASE}/songs/${reuseJobId}`);
      if (!response.ok) return;
      const data = await response.json();
      const req = data.request;
      if (!req) return;
      setPrompt(req.prompt ?? "");
      setTopic(req.topic ?? "");
      setLyrics(req.lyrics ?? "");
      setLanguage(req.language ?? "gikuyu");
      setGenre(req.genre ?? "mugithi");
      setMood(req.mood ?? "joyful");
      setInstruments(Array.isArray(req.instruments) ? req.instruments : []);
      window.scrollTo({ top: 0, behavior: "smooth" });
    } catch (error) {
      console.error("Reuse failed", error);
    }
  };

  const handleRemaster = async (sourceJobId: string) => {
    try {
      const response = await fetch(`${API_BASE}/songs/${sourceJobId}/remaster`, { method: "POST" });
      if (!response.ok) return;
      const data = await response.json();
      if (data.job_id) {
        setJobId(data.job_id);
        setJobStatus("queued");
        setAudioUrl(null);
      }
    } catch (error) {
      console.error("Remaster failed", error);
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

          <div>
            <label className="mb-2 block text-sm text-slate-300">Topic</label>
            <input
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              placeholder="What the song is about, e.g. Wendo wa mũtũranĩri"
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-white outline-none ring-0 transition focus:border-emerald-500"
            />
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="block text-sm text-slate-300">Style Prompt</label>
              <div className="flex items-center gap-3">
                <label className="flex cursor-pointer items-center gap-1.5 text-xs text-slate-400" title="Self-generate an enhanced style via Suno">
                  <input
                    type="checkbox"
                    checked={useSunoStyle}
                    onChange={(e) => setUseSunoStyle(e.target.checked)}
                    className="h-3.5 w-3.5 accent-emerald-500"
                  />
                  Self-generate
                </label>
                <button
                  type="button"
                  onClick={handleStylePrompt}
                  disabled={styleLoading}
                  className="rounded-full border border-emerald-500/50 px-3 py-1 text-xs text-emerald-300 transition hover:border-emerald-400 hover:text-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
                  title="Compose a style prompt from the genre, mood, and instruments"
                >
                  {styleLoading ? "Building..." : "Style Prompt"}
                </button>
              </div>
            </div>
            <textarea
              rows={3}
              value={stylePrompt}
              onChange={(e) => setStylePrompt(e.target.value)}
              placeholder="Build a style prompt, or type your own..."
              className="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none transition focus:border-emerald-500"
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
            {instrumentCatalog.length === 0 ? (
              <p className="text-sm text-slate-500">Loading instruments...</p>
            ) : (
              ["traditional", "modern"].map((category) => {
                const items = instrumentCatalog.filter((item) => item.category === category);
                if (items.length === 0) return null;
                return (
                  <div key={category} className="mb-3">
                    <p className="mb-1.5 text-xs uppercase tracking-[0.15em] text-slate-500">{category}</p>
                    <div className="flex flex-wrap gap-2">
                      {items.map((instrument) => (
                        <button
                          key={instrument.slug}
                          type="button"
                          onClick={() => toggleInstrument(instrument.slug)}
                          className={`rounded-full border px-3 py-2 text-sm transition ${
                            instruments.includes(instrument.slug)
                              ? "border-cyan-500 bg-cyan-500/20 text-cyan-200"
                              : "border-slate-700 bg-slate-950 text-slate-300 hover:border-slate-500"
                          }`}
                        >
                          {instrument.name}
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })
            )}
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="block text-sm text-slate-300">Lyrics</label>
              <button
                type="button"
                onClick={handleGenerateLyrics}
                disabled={lyricsLoading || (!topic.trim() && !prompt.trim())}
                className="rounded-full border border-cyan-500/50 px-3 py-1 text-xs text-cyan-300 transition hover:border-cyan-400 hover:text-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
                title="Generate lyrics from the topic"
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
            {references.length > 0 && (
              <div className="mt-2 rounded-xl border border-slate-700/60 bg-slate-950/60 p-3">
                <p className="mb-1 text-xs uppercase tracking-[0.15em] text-slate-400">Mũgithi style references</p>
                <ul className="space-y-1 text-xs text-slate-300">
                  {references.map((ref) => (
                    <li key={ref}>• {ref}</li>
                  ))}
                </ul>
              </div>
            )}
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
            <span
              className={`rounded-full border px-2 py-0.5 text-xs ${
                suno?.enabled
                  ? "border-emerald-500/50 text-emerald-300"
                  : "border-slate-700 text-slate-400"
              }`}
              title={suno?.enabled ? `Enabled: ${suno.functions.join(", ")}` : "Set SUNO_API_KEY on the API to enable"}
            >
              {suno?.enabled ? `Suno: ${suno.functions.length} functions on` : "Suno: local engine"}
            </span>
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
          <AudioPlayer src={audioUrl} waveform={waveform} />
        </div>

        <SongLibrary
          refreshKey={libraryRefresh}
          onSelect={(url) => {
            setAudioUrl(url);
            setWaveform([]);
          }}
          onReuse={handleReuse}
          onRemaster={handleRemaster}
        />

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
