export type StemKind = "vocals" | "bass" | "drums" | "melody";

export interface CuePoint {
  time: number;
  label: string;
  kind: string;
}

export interface ApiStem {
  id: number;
  kind: StemKind | string;
  audio_url: string | null;
  volume: number;
  pan: number;
  is_muted: boolean;
  is_solo: boolean;
}

/** Minimal shape of the Django Song resource used by the DJ booth. */
export interface LibraryTrack {
  id: number;
  title: string;
  status: string;
  audio_url: string | null;
  tempo_bpm: number | null;
  musical_key: string;
  camelot: string;
  cue_points: CuePoint[];
  stems: ApiStem[];
}

export type TransitionStyle = "cut" | "crossfade" | "drop_swap" | "echo_out";

export interface MixAnalysisTrack {
  bpm?: number | null;
  key?: { key?: string; camelot?: string } | null;
}

export interface DjMixJob {
  id: number;
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
  transition: TransitionStyle;
  transition_bars: number;
  match_tempo: boolean;
  match_key: boolean;
  output_url: string | null;
  mix_waveform_data: number[];
  analysis: { track_a?: MixAnalysisTrack; track_b?: MixAnalysisTrack };
  failure_reason: string;
  created_at: string;
}

export interface DjRenderJob {
  id: number;
  source_song: number;
  operations: Record<string, unknown>[];
  status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED";
  output_url: string | null;
  failure_reason: string;
}

export interface TrackLoadRequest {
  urls: string[];
  name: string;
  bpm: number | null;
  cuePoints?: CuePoint[];
  stems?: ApiStem[];
}
