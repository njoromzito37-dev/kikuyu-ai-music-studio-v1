import Foundation

/// Codable models mirroring the Django REST API (apps/api/music/serializers.py).

public struct CuePoint: Codable, Hashable, Sendable {
    public let time: Double
    public let label: String
    public let kind: String
}

public struct Stem: Codable, Identifiable, Hashable, Sendable {
    public let id: Int
    public let kind: String
    public let audioUrl: URL?
    public let volume: Double
    public let pan: Double
    public let isMuted: Bool
    public let isSolo: Bool

    enum CodingKeys: String, CodingKey {
        case id, kind, volume, pan
        case audioUrl = "audio_url"
        case isMuted = "is_muted"
        case isSolo = "is_solo"
    }
}

public struct VoiceProfile: Codable, Identifiable, Hashable, Sendable {
    public let id: Int
    public let name: String
    public let slug: String
    public let vocalType: String
    public let promptTags: String

    enum CodingKeys: String, CodingKey {
        case id, name, slug
        case vocalType = "vocal_type"
        case promptTags = "prompt_tags"
    }
}

public struct StudioSong: Codable, Identifiable, Hashable, Sendable {
    public let id: Int
    public let title: String
    public let status: String
    public let audioUrl: URL?
    public let masteredUrl: URL?
    public let duration: Int
    public let tempoBpm: Int?
    public let musicalKey: String
    public let camelot: String
    public let cuePoints: [CuePoint]
    public let stems: [Stem]
    public let voice: VoiceProfile?
    public let lyricsEngine: String
    public let genre: Genre?
    public let waveform: [Double]

    enum CodingKeys: String, CodingKey {
        case id, title, status, duration, stems, voice, genre
        case audioUrl = "audio_url"
        case masteredUrl = "mastered_url"
        case tempoBpm = "tempo_bpm"
        case musicalKey = "musical_key"
        case camelot
        case cuePoints = "cue_points"
        case lyricsEngine = "lyrics_engine"
        case waveform = "audio_waveform_data"
    }
}

public struct Genre: Codable, Identifiable, Hashable, Sendable {
    public let id: Int
    public let name: String
    public let slug: String
}

/// DRF paginated list envelope.
public struct Paginated<T: Codable & Sendable>: Codable, Sendable {
    public let count: Int
    public let results: [T]
}

public struct DjMixJob: Codable, Identifiable, Hashable, Sendable {
    public let id: Int
    public let status: String
    public let transition: String
    public let transitionBars: Int
    public let outputUrl: URL?
    public let failureReason: String

    enum CodingKeys: String, CodingKey {
        case id, status, transition
        case transitionBars = "transition_bars"
        case outputUrl = "output_url"
        case failureReason = "failure_reason"
    }
}
