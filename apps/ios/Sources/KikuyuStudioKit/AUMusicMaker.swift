import AVFoundation

/// Hosts an Audio Unit MIDI instrument (synth/sampler) inside an
/// AVAudioEngine, with safe instrument hot-swapping.
///
/// Hardened versus the naive version:
///  * graph mutations are serialized on a dedicated queue (instantiate
///    callbacks arrive on arbitrary threads),
///  * engine configuration changes and audio-session interruptions
///    automatically restart the engine,
///  * connections use the instrument's own render format,
///  * panic() uses stop -> reset -> reload -> start and never swallows
///    errors silently.
public final class AUMusicMaker {
    public let engine = AVAudioEngine()
    public private(set) var instrument: AVAudioUnitMIDIInstrument?

    /// Serializes graph mutations (attach/detach/connect/swap).
    private let graphQueue = DispatchQueue(label: "AUMusicMaker.graph")

    public enum MusicMakerError: Error {
        case notAMidiInstrument
        case engineStartFailed(Error)
    }

    public init() {
        observeEngineLifecycle()
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    // MARK: - Engine lifecycle

    public func startEngine() throws {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .default)
        try session.setActive(true)
        #endif

        graphQueue.sync {
            let output = engine.outputNode
            let format = output.inputFormat(forBus: 0)
            engine.connect(engine.mainMixerNode, to: output, format: format)
        }

        engine.prepare()
        do {
            try engine.start()
        } catch {
            throw MusicMakerError.engineStartFailed(error)
        }
    }

    /// Restart after route changes (headphone unplug, AirPods) and
    /// audio-session interruptions (phone call ends, etc.).
    private func observeEngineLifecycle() {
        NotificationCenter.default.addObserver(
            forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main
        ) { [weak self] _ in
            guard let self, !self.engine.isRunning else { return }
            try? self.engine.start()
        }
        #if os(iOS)
        NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification, object: nil, queue: .main
        ) { [weak self] note in
            guard let self,
                  let info = note.userInfo,
                  let raw = info[AVAudioSessionInterruptionTypeKey] as? UInt,
                  AVAudioSession.InterruptionType(rawValue: raw) == .ended
            else { return }
            try? AVAudioSession.sharedInstance().setActive(true)
            if !self.engine.isRunning { try? self.engine.start() }
        }
        #endif
    }

    // MARK: - Instrument management

    public func loadInstrument(
        component: AVAudioUnitComponent,
        completion: @escaping (Result<AVAudioUnitMIDIInstrument, Error>) -> Void
    ) {
        allNotesOff()

        AVAudioUnit.instantiate(with: component, options: []) { [weak self] unit, error in
            guard let self else { return }
            if let error {
                completion(.failure(error))
                return
            }
            guard let midiInstrument = unit as? AVAudioUnitMIDIInstrument else {
                completion(.failure(MusicMakerError.notAMidiInstrument))
                return
            }

            // Serialize the swap; detach the old instrument after the new one
            // is connected so no render cycle hits a dangling node.
            self.graphQueue.sync {
                self.engine.attach(midiInstrument)
                let format = midiInstrument.outputFormat(forBus: 0)
                self.engine.connect(midiInstrument, to: self.engine.mainMixerNode, format: format)
                if let old = self.instrument {
                    self.engine.detach(old)
                }
                self.instrument = midiInstrument
            }
            completion(.success(midiInstrument))
        }
    }

    // MARK: - MIDI performance

    public func noteOn(_ note: UInt8, velocity: UInt8 = 100, channel: UInt8 = 0) {
        instrument?.startNote(note, withVelocity: velocity, onChannel: channel)
    }

    public func noteOff(_ note: UInt8, channel: UInt8 = 0) {
        instrument?.stopNote(note, onChannel: channel)
    }

    /// Pitch bend for Mũgithi-style lead slides (14-bit, center 8192).
    public func pitchBend(_ value: UInt16, channel: UInt8 = 0) {
        instrument?.sendPitchBend(value, onChannel: channel)
    }

    public func programChange(_ program: UInt8, channel: UInt8 = 0) {
        instrument?.sendProgramChange(program, onChannel: channel)
    }

    public func allNotesOff(channel: UInt8 = 0) {
        instrument?.sendController(123, withValue: 0, onChannel: channel) // CC 123
    }

    /// Full reset: silence everything, stop, reset nodes, restart.
    /// The instrument's program must be reloaded after this — reset() clears it.
    public func panic() throws {
        for channel in 0..<16 {
            instrument?.sendController(123, withValue: 0, onChannel: UInt8(channel))
        }
        engine.stop()
        engine.reset()
        engine.prepare()
        try engine.start()
    }
}
