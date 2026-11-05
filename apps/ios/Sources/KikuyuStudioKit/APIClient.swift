import Foundation

/// Async API client for the Kikuyu AI Music Studio Django backend.
///
/// Uses HTTP Basic auth (enabled in the API's DRF authentication classes) —
/// fine for a private studio app; move to token auth before public release.
public final class APIClient: Sendable {
    public struct Configuration: Sendable {
        public var baseURL: URL
        public var username: String
        public var password: String

        public init(baseURL: URL, username: String, password: String) {
            self.baseURL = baseURL
            self.username = username
            self.password = password
        }
    }

    public enum APIError: Error, LocalizedError {
        case httpStatus(Int, String)
        case decoding(Error)

        public var errorDescription: String? {
            switch self {
            case let .httpStatus(code, detail): return "API \(code): \(detail)"
            case let .decoding(error): return "Decoding failed: \(error.localizedDescription)"
            }
        }
    }

    private let configuration: Configuration
    private let session: URLSession

    public init(configuration: Configuration, session: URLSession = .shared) {
        self.configuration = configuration
        self.session = session
    }

    private var authHeader: String {
        let credentials = "\(configuration.username):\(configuration.password)"
        let encoded = Data(credentials.utf8).base64EncodedString()
        return "Basic \(encoded)"
    }

    @discardableResult
    private func request<T: Decodable & Sendable>(
        _ method: String,
        _ path: String,
        body: (any Encodable & Sendable)? = nil
    ) async throws -> T {
        var request = URLRequest(url: configuration.baseURL.appendingPathComponent(path))
        request.httpMethod = method
        request.setValue(authHeader, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONEncoder().encode(AnyEncodable(body))
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw APIError.httpStatus(-1, "Not an HTTP response")
        }
        guard (200..<300).contains(http.statusCode) else {
            let detail = String(data: data, encoding: .utf8) ?? http.description
            throw APIError.httpStatus(http.statusCode, detail)
        }
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }

    private struct Empty: Codable, Sendable {}

    // MARK: - Catalog

    public func fetchSongs() async throws -> [StudioSong] {
        let page: Paginated<StudioSong> = try await request("GET", "songs/")
        return page.results
    }

    public func fetchSong(id: Int) async throws -> StudioSong {
        try await request("GET", "songs/\(id)/")
    }

    public func fetchVoices() async throws -> [VoiceProfile] {
        let page: Paginated<VoiceProfile> = try await request("GET", "voices/")
        return page.results
    }

    // MARK: - Actions (all queue Celery work; poll fetchSong/fetchMixJob)

    public func requestMaster(songId: Int) async throws {
        let _: Empty = try await request("POST", "songs/\(songId)/master/", body: Empty())
    }

    public func requestAnalysis(songId: Int) async throws {
        let _: Empty = try await request("POST", "songs/\(songId)/analyze/", body: Empty())
    }

    public func requestStemSplit(songId: Int) async throws {
        let _: Empty = try await request("POST", "songs/\(songId)/stems/auto-split/", body: Empty())
    }

    public struct MixRequest: Encodable, Sendable {
        public let track_a: Int
        public let track_b: Int
        public let transition: String
        public let transition_bars: Int
        public let match_tempo: Bool
        public let match_key: Bool
    }

    public func createMix(trackA: Int, trackB: Int, transition: String = "crossfade", bars: Int = 8) async throws -> DjMixJob {
        try await request(
            "POST", "dj/mix/",
            body: MixRequest(track_a: trackA, track_b: trackB, transition: transition,
                             transition_bars: bars, match_tempo: true, match_key: true)
        )
    }

    public func fetchMixJob(id: Int) async throws -> DjMixJob {
        try await request("GET", "dj/mix/\(id)/")
    }
}

/// Type-erased Encodable wrapper for request bodies.
private struct AnyEncodable: Encodable {
    private let encodeClosure: (Encoder) throws -> Void
    init(_ wrapped: any Encodable) { encodeClosure = wrapped.encode }
    func encode(to encoder: Encoder) throws { try encodeClosure(encoder) }
}
