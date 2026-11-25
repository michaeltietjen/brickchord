// Loads the Bricklab Studio AU like a DAW does, plays MIDI into it offline and
// reports the level of what comes out: one key (a degree's chord), three keys (that chord), release.
import AVFoundation
import AudioToolbox

let desc = AudioComponentDescription(componentType: kAudioUnitType_MusicDevice, componentSubType: 0x42726b6c /* Brkl */,
                                     componentManufacturer: 0x4d746965 /* Mtie */, componentFlags: 0, componentFlagsMask: 0)
let engine = AVAudioEngine()
let sem = DispatchSemaphore(value: 0)
var inst: AVAudioUnitMIDIInstrument?
AVAudioUnit.instantiate(with: desc, options: []) { au, err in
    if let err = err { print("load failed:", err) }
    inst = au as? AVAudioUnitMIDIInstrument
    sem.signal()
}
sem.wait()
guard let inst = inst else { print("not an instrument"); exit(1) }
print("loaded:", inst.auAudioUnit.audioUnitName ?? "?", "by", inst.auAudioUnit.manufacturerName ?? "?")
let fmt = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 2)!
engine.attach(inst)
engine.connect(inst, to: engine.mainMixerNode, format: fmt)
try! engine.enableManualRenderingMode(.offline, format: fmt, maximumFrameCount: 512)
try! engine.start()
let buf = AVAudioPCMBuffer(pcmFormat: engine.manualRenderingFormat, frameCapacity: 512)!

func run(_ secs: Double, _ label: String) {
    var sum = 0.0, n = 0, peak: Float = 0
    for _ in 0..<Int(secs * 48000 / 512) {
        _ = try! engine.renderOffline(512, to: buf)
        let l = buf.floatChannelData![0]
        for i in 0..<Int(buf.frameLength) { sum += Double(l[i] * l[i]); n += 1; peak = max(peak, abs(l[i])) }
    }
    print(String(format: "%-28@ rms %.4f peak %.3f", label as NSString, sqrt(sum / Double(max(n, 1))), peak))
}
run(1.5, "silence, sounds rendering")
inst.startNote(62, withVelocity: 100, onChannel: 0)            // D: the 4th degree in A minor, Dm
run(2.0, "one key (D): Dm")
inst.stopNote(62, onChannel: 0)
run(2.0, "released")
for k: UInt8 in [55, 59, 62] { inst.startNote(k, withVelocity: 100, onChannel: 0) }   // G B D: G major
run(2.0, "three keys: G")
for k: UInt8 in [55, 59, 62] { inst.stopNote(k, onChannel: 0) }
run(3.0, "released")
