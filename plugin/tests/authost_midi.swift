// MIDI out check: loads the Bricklab Studio AU, turns MIDI out on, plays one key and
// three keys, and prints the notes it sends out, then turns the built-in sound off
// and checks the audio goes quiet while the notes still go out.
import AVFoundation
import AudioToolbox

let desc = AudioComponentDescription(componentType: kAudioUnitType_MusicDevice, componentSubType: 0x42726b6c /* Brkl */,
                                     componentManufacturer: 0x4d746965 /* Mtie */, componentFlags: 0, componentFlagsMask: 0)
let engine = AVAudioEngine()
let sem = DispatchSemaphore(value: 0)
var inst: AVAudioUnitMIDIInstrument?
AVAudioUnit.instantiate(with: desc, options: []) { au, _ in inst = au as? AVAudioUnitMIDIInstrument; sem.signal() }
sem.wait()
guard let inst = inst else { print("not an instrument"); exit(1) }
let au = inst.auAudioUnit
var sent: [String] = []
let lock = NSLock()
au.midiOutputEventBlock = { _, _, n, bytes in
    let b = (0..<n).map { bytes[$0] }
    var i = 0
    lock.lock()
    while i + 2 < b.count {                              // several messages can arrive together
        let st = b[i] & 0xF0
        if st == 0x90 || st == 0x80 { sent.append("\(st == 0x90 && b[i + 2] > 0 ? "on" : "off") ch\(Int(b[i] & 0x0F) + 1) \(b[i + 1])") }
        i += 3
    }
    lock.unlock()
    return noErr
}
func param(_ name: String) -> AUParameter? { au.parameterTree?.allParameters.first { $0.displayName == name } }
param("MIDI out")?.value = 1
let fmt = AVAudioFormat(standardFormatWithSampleRate: 48000, channels: 2)!
engine.attach(inst)
engine.connect(inst, to: engine.mainMixerNode, format: fmt)
try! engine.enableManualRenderingMode(.offline, format: fmt, maximumFrameCount: 512)
try! engine.start()
let buf = AVAudioPCMBuffer(pcmFormat: engine.manualRenderingFormat, frameCapacity: 512)!
func run(_ secs: Double, _ label: String) {
    var sum = 0.0, n = 0
    for _ in 0..<Int(secs * 48000 / 512) {
        _ = try! engine.renderOffline(512, to: buf)
        let l = buf.floatChannelData![0]
        for i in 0..<Int(buf.frameLength) { sum += Double(l[i] * l[i]); n += 1 }
    }
    lock.lock(); let s = sent; sent = []; lock.unlock()
    print(String(format: "%-26@ rms %.4f  ", label as NSString, sqrt(sum / Double(max(n, 1)))) + s.joined(separator: ", "))
}
run(1.5, "silence")
inst.startNote(62, withVelocity: 100, onChannel: 0)
run(1.0, "one key (D): Dm")
inst.stopNote(62, onChannel: 0)
run(1.0, "released")
for k: UInt8 in [55, 59, 62] { inst.startNote(k, withVelocity: 100, onChannel: 0) }
run(1.0, "three keys: G")
for k: UInt8 in [55, 59, 62] { inst.stopNote(k, onChannel: 0) }
run(2.5, "released")
param("Built-in sound")?.value = 0
inst.startNote(64, withVelocity: 100, onChannel: 0)
run(1.0, "sound off, one key (E)")
inst.stopNote(64, onChannel: 0)
run(1.0, "released")
param("Built-in sound")?.value = 1
for (mode, bass, label) in [(7, 0, "Arp 1/8 Up, Synth bass"), (1, 3, "Strum Folk, Walk bass"), (5, 6, "Harp Up, no bass")] {
    param("Play mode")?.value = AUValue(mode)
    param("Bass")?.value = AUValue(bass)
    run(0.2, "settle")
    inst.startNote(62, withVelocity: 100, onChannel: 0)
    run(2.0, label as String)
    inst.stopNote(62, onChannel: 0)
    run(1.6, "released")
}
param("Play mode")?.value = 7
param("Bass")?.value = 0
param("Latch")?.value = 1
inst.startNote(57, withVelocity: 100, onChannel: 0)
run(0.3, "latch on, A pressed")
inst.stopNote(57, onChannel: 0)
run(1.2, "A let go: still playing")
param("Latch")?.value = 0
run(0.5, "latch off: stops")
