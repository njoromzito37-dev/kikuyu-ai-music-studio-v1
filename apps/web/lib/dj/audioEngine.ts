/**
 * DeckEngine — one virtual DJ deck built on the Web Audio API.
 *
 * Graph per deck:
 *   source(s) -> per-stem GainNode -> input GainNode
 *     -> lowshelf -> peaking -> highshelf (3-band EQ)
 *     -> sweep BiquadFilterNode (DJ HP/LP filter knob)
 *     -> channel GainNode -> crossfade GainNode -> AnalyserNode -> destination
 *
 * Supports multi-buffer stem playback (all stems started sample-aligned),
 * tempo via playbackRate, pitch-bend, cue points and beat-quantized loops.
 */
export class DeckEngine {
  private ctx: AudioContext | null = null;
  private input: GainNode | null = null;
  private eqLow: BiquadFilterNode | null = null;
  private eqMid: BiquadFilterNode | null = null;
  private eqHigh: BiquadFilterNode | null = null;
  private sweep: BiquadFilterNode | null = null;
  private channelGain: GainNode | null = null;
  private xfGain: GainNode | null = null;
  private analyser: AnalyserNode | null = null;

  private buffers: AudioBuffer[] = [];
  private sources: AudioBufferSourceNode[] = [];
  private stemGainNodes: GainNode[] = [];
  private stemVolumes: number[] = [];
  private stemMuted: boolean[] = [];
  private stemSoloed: boolean[] = [];

  private startedAt = 0;
  private offset = 0;
  private rate = 1;
  private bendFactor = 1;
  private loopStart = 0;
  private loopEnd = 0;

  playing = false;
  loopBeats: number | null = null;
  cuePoint = 0;
  trackName = "";
  baseBpm: number | null = null;

  /** Lazily create the AudioContext (must happen after a user gesture). */
  private ensureContext(): AudioContext {
    if (!this.ctx) {
      const Ctor: typeof AudioContext | undefined =
        typeof window !== "undefined"
          ? window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
          : undefined;
      if (!Ctor) throw new Error("Web Audio API is not available in this browser.");
      const ctx = new Ctor();
      this.input = ctx.createGain();
      this.eqLow = ctx.createBiquadFilter();
      this.eqLow.type = "lowshelf";
      this.eqLow.frequency.value = 320;
      this.eqMid = ctx.createBiquadFilter();
      this.eqMid.type = "peaking";
      this.eqMid.frequency.value = 1000;
      this.eqMid.Q.value = 0.9;
      this.eqHigh = ctx.createBiquadFilter();
      this.eqHigh.type = "highshelf";
      this.eqHigh.frequency.value = 3200;
      this.sweep = ctx.createBiquadFilter();
      this.sweep.type = "lowpass";
      this.sweep.frequency.value = 22050;
      this.channelGain = ctx.createGain();
      this.xfGain = ctx.createGain();
      this.analyser = ctx.createAnalyser();
      this.analyser.fftSize = 512;
      this.analyser.smoothingTimeConstant = 0.78;

      this.input.connect(this.eqLow);
      this.eqLow.connect(this.eqMid);
      this.eqMid.connect(this.eqHigh);
      this.eqHigh.connect(this.sweep);
      this.sweep.connect(this.channelGain);
      this.channelGain.connect(this.xfGain);
      this.xfGain.connect(this.analyser);
      this.analyser.connect(ctx.destination);
      this.ctx = ctx;
    }
    return this.ctx;
  }

  // --------------------------------------------------------------- loading

  async loadUrls(urls: string[], name: string, bpm: number | null = null): Promise<void> {
    const ctx = this.ensureContext();
    this.stopSources();
    this.playing = false;
    this.offset = 0;
    this.cuePoint = 0;
    this.loopBeats = null;
    const decoded = await Promise.all(
      urls.map(async (url) => {
        const response = await fetch(url);
        if (!response.ok) throw new Error(`Could not load audio (${response.status})`);
        return ctx.decodeAudioData(await response.arrayBuffer());
      }),
    );
    this.buffers = decoded;
    this.stemVolumes = decoded.map(() => 1);
    this.stemMuted = decoded.map(() => false);
    this.stemSoloed = decoded.map(() => false);
    this.trackName = name;
    this.baseBpm = bpm;
  }

  get isLoaded(): boolean {
    return this.buffers.length > 0;
  }

  get stemCount(): number {
    return this.buffers.length;
  }

  get duration(): number {
    return this.buffers[0]?.duration ?? 0;
  }

  // -------------------------------------------------------------- transport

  getPosition(): number {
    if (!this.ctx || !this.playing) return this.offset;
    let pos = this.offset + (this.ctx.currentTime - this.startedAt) * this.rate * this.bendFactor;
    if (this.loopBeats !== null && this.loopEnd > this.loopStart) {
      const loopLen = this.loopEnd - this.loopStart;
      if (pos >= this.loopEnd) pos = this.loopStart + ((pos - this.loopStart) % loopLen);
    }
    return Math.max(0, Math.min(pos, this.duration));
  }

  private effectiveStemGain(index: number): number {
    const anySolo = this.stemSoloed.some(Boolean);
    if (anySolo && !this.stemSoloed[index]) return 0;
    if (this.stemMuted[index]) return 0;
    return this.stemVolumes[index] ?? 1;
  }

  private currentPlaybackRate(): number {
    return this.rate * this.bendFactor;
  }

  play(): void {
    if (!this.isLoaded || this.playing) return;
    const ctx = this.ensureContext();
    if (ctx.state === "suspended") void ctx.resume();
    const when = ctx.currentTime + 0.04;
    this.startedAt = when;
    let offset = Math.min(this.offset, this.duration - 0.02);
    if (this.loopBeats !== null && this.loopEnd > this.loopStart) {
      const loopLen = this.loopEnd - this.loopStart;
      offset = this.loopStart + (((offset - this.loopStart) % loopLen) + loopLen) % loopLen;
    }
    this.sources = this.buffers.map((buffer, index) => {
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.playbackRate.value = this.currentPlaybackRate();
      const gain = ctx.createGain();
      gain.gain.value = this.effectiveStemGain(index);
      this.stemGainNodes[index] = gain;
      source.connect(gain);
      gain.connect(this.input as GainNode);
      source.loop = this.loopBeats !== null;
      if (this.loopBeats !== null) {
        source.loopStart = this.loopStart;
        source.loopEnd = Math.min(this.loopEnd, buffer.duration);
      }
      source.start(when, offset);
      return source;
    });
    this.playing = true;
  }

  private stopSources(): void {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
      source.disconnect();
    }
    for (const node of this.stemGainNodes) {
      node.disconnect();
    }
    this.sources = [];
    this.stemGainNodes = [];
  }

  pause(): void {
    if (!this.playing) return;
    this.offset = this.getPosition();
    this.stopSources();
    this.playing = false;
  }

  stop(): void {
    this.pause();
    this.offset = 0;
  }

  seek(seconds: number): void {
    const clamped = Math.max(0, Math.min(seconds, Math.max(0, this.duration - 0.02)));
    const wasPlaying = this.playing;
    if (wasPlaying) this.pause();
    this.offset = clamped;
    if (wasPlaying) this.play();
  }

  /** Re-anchor the clock after a rate change so the playhead stays continuous. */
  private reanchor(): void {
    if (!this.ctx || !this.playing) return;
    this.offset = this.getPosition();
    this.startedAt = this.ctx.currentTime;
    for (const source of this.sources) {
      source.playbackRate.setTargetAtTime(this.currentPlaybackRate(), this.ctx.currentTime, 0.015);
    }
  }

  // ------------------------------------------------------------------ tempo

  setRate(rate: number): void {
    this.rate = Math.min(1.2, Math.max(0.8, rate));
    this.reanchor();
  }

  getRate(): number {
    return this.rate;
  }

  /** Effective BPM of the audio leaving the deck right now. */
  getEffectiveBpm(): number | null {
    return this.baseBpm === null ? null : this.baseBpm * this.rate * this.bendFactor;
  }

  /** Match this deck's tempo to a target effective BPM (BPM sync assist). */
  syncToBpm(targetBpm: number | null): void {
    if (targetBpm === null || this.baseBpm === null || this.baseBpm <= 0) return;
    this.setRate(targetBpm / this.baseBpm);
  }

  bendStart(factor: number): void {
    this.bendFactor = factor;
    this.reanchor();
  }

  bendEnd(): void {
    this.bendFactor = 1;
    this.reanchor();
  }

  // --------------------------------------------------------------- cue/loop

  setCueHere(): void {
    this.cuePoint = this.getPosition();
  }

  jumpToCue(): void {
    this.seek(this.cuePoint);
  }

  /** Toggle a beat-quantized loop starting at the playhead (4, 8, ... beats). */
  setLoopBeats(beats: number | null): void {
    if (beats === null || this.baseBpm === null) {
      this.loopBeats = null;
    } else {
      const loopLen = (beats * 60) / this.baseBpm; // loop points live in buffer time
      const start = this.getPosition();
      if (start + loopLen <= this.duration) {
        this.loopBeats = beats;
        this.loopStart = start;
        this.loopEnd = start + loopLen;
      } else {
        this.loopBeats = null;
      }
    }
    for (const source of this.sources) {
      source.loop = this.loopBeats !== null;
      if (this.loopBeats !== null) {
        source.loopStart = this.loopStart;
        source.loopEnd = this.loopEnd;
      }
    }
  }

  getLoopRegion(): { start: number; end: number } | null {
    return this.loopBeats !== null ? { start: this.loopStart, end: this.loopEnd } : null;
  }

  // ------------------------------------------------------------- mixer/EQ/FX

  setEq(lowDb: number, midDb: number, highDb: number): void {
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.eqLow?.gain.setTargetAtTime(lowDb, t, 0.02);
    this.eqMid?.gain.setTargetAtTime(midDb, t, 0.02);
    this.eqHigh?.gain.setTargetAtTime(highDb, t, 0.02);
  }

  /**
   * DJ filter sweep knob, -1 (full low-pass) .. 0 (open) .. +1 (full high-pass).
   */
  setFilterSweep(value: number): void {
    if (!this.ctx || !this.sweep) return;
    const clamped = Math.min(1, Math.max(-1, value));
    const t = this.ctx.currentTime;
    if (Math.abs(clamped) < 0.03) {
      this.sweep.type = "lowpass";
      this.sweep.frequency.setTargetAtTime(22050, t, 0.02);
      this.sweep.Q.setTargetAtTime(0.7, t, 0.02);
    } else if (clamped < 0) {
      this.sweep.type = "lowpass";
      const cutoff = 80 * Math.pow(22050 / 80, clamped + 1); // 22050 -> 80 Hz
      this.sweep.frequency.setTargetAtTime(cutoff, t, 0.02);
      this.sweep.Q.setTargetAtTime(1.1, t, 0.02);
    } else {
      this.sweep.type = "highpass";
      const cutoff = 20 * Math.pow(8000 / 20, clamped); // 20 Hz -> 8 kHz
      this.sweep.frequency.setTargetAtTime(cutoff, t, 0.02);
      this.sweep.Q.setTargetAtTime(1.1, t, 0.02);
    }
  }

  setChannelGain(value: number): void {
    if (!this.ctx || !this.channelGain) return;
    this.channelGain.gain.setTargetAtTime(Math.max(0, value), this.ctx.currentTime, 0.02);
  }

  /** Crossfader gain for this deck (computed by the mixer, equal-power). */
  setCrossfadeGain(value: number): void {
    if (!this.ctx || !this.xfGain) return;
    this.xfGain.gain.setTargetAtTime(Math.max(0, value), this.ctx.currentTime, 0.015);
  }

  setStemVolume(index: number, volume: number): void {
    this.stemVolumes[index] = volume;
    this.applyStemGain(index);
  }

  setStemMuted(index: number, muted: boolean): void {
    this.stemMuted[index] = muted;
    this.applyAllStemGains();
  }

  setStemSoloed(index: number, soloed: boolean): void {
    this.stemSoloed[index] = soloed;
    this.applyAllStemGains();
  }

  getStemState(): { volume: number; muted: boolean; solo: boolean }[] {
    return this.buffers.map((_, index) => ({
      volume: this.stemVolumes[index] ?? 1,
      muted: this.stemMuted[index] ?? false,
      solo: this.stemSoloed[index] ?? false,
    }));
  }

  private applyStemGain(index: number): void {
    const node = this.stemGainNodes[index];
    if (node && this.ctx) node.gain.setTargetAtTime(this.effectiveStemGain(index), this.ctx.currentTime, 0.02);
  }

  private applyAllStemGains(): void {
    this.stemGainNodes.forEach((_, index) => this.applyStemGain(index));
  }

  // ------------------------------------------------------------- monitoring

  /** Fill `target` with 0-255 frequency magnitudes for the spectrum display. */
  readSpectrum(target: Uint8Array): boolean {
    if (!this.analyser) return false;
    this.analyser.getByteFrequencyData(target);
    return true;
  }

  /** Downsampled peak waveform (0..1) of the mixed program material. */
  getPeaks(count: number): number[] {
    if (!this.isLoaded) return [];
    const length = this.buffers[0].length;
    const channels = this.buffers[0].numberOfChannels;
    const left = this.buffers[0].getChannelData(0);
    const right = channels > 1 ? this.buffers[0].getChannelData(1) : left;
    // Include extra stem buffers (they play in parallel).
    const extra = this.buffers.slice(1).map((buffer) => buffer.getChannelData(0));
    const peaks = new Array<number>(count).fill(0);
    const bucket = Math.max(1, Math.floor(length / count));
    for (let i = 0; i < count; i += 1) {
      const start = i * bucket;
      let peak = 0;
      for (let j = start; j < Math.min(start + bucket, length); j += 16) {
        const mixed = Math.abs(left[j]) + Math.abs(right[j]) + extra.reduce((sum, data) => sum + Math.abs(data[j] ?? 0), 0);
        if (mixed > peak) peak = mixed;
      }
      peaks[i] = Math.min(1, peak / 2);
    }
    return peaks;
  }

  dispose(): void {
    this.stopSources();
    if (this.ctx) void this.ctx.close();
    this.ctx = null;
  }
}
