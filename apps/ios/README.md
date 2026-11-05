# Kikuyu AI Music Studio — iOS Companion

Native SwiftUI client for the Django studio backend, plus a reusable AU
instrument host for live playing (MIDI controllers / AUv3 synths).

## Layout

```
apps/ios/
├── Package.swift                         # SwiftPM package (iOS 16 / macOS 13)
├── Sources/KikuyuStudioKit/
│   ├── Models.swift                      # Codable models mirroring the DRF serializers
│   ├── APIClient.swift                   # async/await client (HTTP Basic auth)
│   ├── TrackPlayerEngine.swift           # AVAudioEngine mastered-track player
│   └── AUMusicMaker.swift                # AU MIDI instrument host (hardened)
├── App/                                  # SwiftUI app sources (drag into Xcode target)
│   ├── KikuyuStudioApp.swift             # @main entry point
│   ├── StudioViewModel.swift             # library + actions (master/analyze/poll)
│   ├── LibraryView.swift                 # Ngoma library with BPM/key/Camelot badges
│   └── PlayerView.swift                  # waveform, transport, hot-cue chips
└── Tests/KikuyuStudioKitTests/           # model decoding tests
```

## Setup

1. **Create the app project**: Xcode → New Project → iOS App ("KikuyuStudio",
   SwiftUI). Delete its template `ContentView`.
2. **Add the package**: File → Add Package Dependencies → Add Local… → pick
   `apps/ios`. Link the `KikuyuStudioKit` library to the app target.
3. **Add the app sources**: drag `App/*.swift` into the app target (they are
   not part of the SwiftPM target because `@main`/assets belong to the app).
4. **Configure the backend** in the app's `Info.plist`:

   | Key | Example |
   |---|---|
   | `STUDIO_API_URL` | `https://studio.example.com/api` |
   | `STUDIO_API_USER` | `studio` |
   | `STUDIO_API_PASSWORD` | `••••••` |

   For the simulator against local dev: `http://127.0.0.1:8001/api` (Django
   must run with `DJANGO_ALLOWED_HOSTS` including the host). Basic auth maps
   to the DRF `BasicAuthentication` class — use a dedicated low-privilege
   Django user, and prefer token auth + TLS before shipping.

5. **Live instrument hosting**: `AUMusicMaker` is standalone — feed it any
   `AVAudioUnitComponent` (e.g. from `AVAudioUnitComponentManager`'s
   `components(matching:)` for AUv3 synths). It handles engine restarts on
   route changes/interruptions and serializes instrument hot-swaps. For
   traditional timbres, load an `AVAudioUnitSampler` with SF2 packs and drive
   it via `noteOn`/`pitchBend`.

## Notes

- Playback prefers `mastered_url` (the −14 LUFS master) and falls back to the
  raw `audio_url`. Cue chips come from the API's auto-cue analysis
  (`POST /api/songs/<id>/analyze/`).
- Master/Analyze buttons queue Celery work and poll the song endpoint until
  the report lands.
- Swift can't be compiled in this repo's Linux container — run
  `swift test` in `apps/ios` or build in Xcode to validate.
