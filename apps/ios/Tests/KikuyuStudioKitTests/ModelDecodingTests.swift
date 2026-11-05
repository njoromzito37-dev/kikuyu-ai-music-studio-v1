import XCTest
@testable import KikuyuStudioKit

final class ModelDecodingTests: XCTestCase {
    func testPaginatedSongDecoding() throws {
        let json = """
        {
          "count": 1,
          "results": [{
            "id": 7,
            "title": "Wendo Wakwa",
            "status": "COMPLETED",
            "audio_url": "http://localhost:8001/media/generated/2026/11/05/song-7.wav",
            "mastered_url": "http://localhost:8001/media/mastered/2026/11/05/song-7-master.wav",
            "duration": 120,
            "tempo_bpm": 98,
            "musical_key": "G major",
            "camelot": "9B",
            "cue_points": [{"time": 12.0, "label": "breakdown", "kind": "hotcue"}],
            "stems": [{
              "id": 3, "kind": "vocals",
              "audio_url": "http://localhost:8001/media/stems/v.wav",
              "volume": 0.9, "pan": 0.1, "is_muted": false, "is_solo": false
            }],
            "voice": {"id": 1, "name": "Mũgithi Male Lead", "slug": "mugithi-male-lead",
                      "vocal_type": "male_lead", "prompt_tags": "powerful male lead vocalist"},
            "lyrics_engine": "deepseek",
            "genre": {"id": 1, "name": "Mũgithi", "slug": "mugithi"},
            "audio_waveform_data": [0.1, 0.8, 0.4]
          }]
        }
        """.data(using: .utf8)!

        let page = try JSONDecoder().decode(Paginated<StudioSong>.self, from: json)
        XCTAssertEqual(page.count, 1)
        let song = try XCTUnwrap(page.results.first)
        XCTAssertEqual(song.tempoBpm, 98)
        XCTAssertEqual(song.camelot, "9B")
        XCTAssertEqual(song.cuePoints.first?.label, "breakdown")
        XCTAssertEqual(song.stems.first?.kind, "vocals")
        XCTAssertEqual(song.voice?.slug, "mugithi-male-lead")
        XCTAssertEqual(song.lyricsEngine, "deepseek")
        XCTAssertEqual(song.masteredUrl?.pathExtension, "wav")
    }

    func testMixJobDecoding() throws {
        let json = """
        {"id": 2, "status": "COMPLETED", "transition": "echo_out", "transition_bars": 8,
         "output_url": "http://localhost:8001/media/dj/mixes/mix-2.wav", "failure_reason": ""}
        """.data(using: .utf8)!
        let job = try JSONDecoder().decode(DjMixJob.self, from: json)
        XCTAssertEqual(job.transition, "echo_out")
        XCTAssertEqual(job.transitionBars, 8)
        XCTAssertNotNil(job.outputUrl)
    }
}
