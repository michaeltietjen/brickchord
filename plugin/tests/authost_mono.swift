// Lead and Drone pages: loads the Bricklab Studio AU with MIDI out on, plays the lead
// (a legato line, the mod wheel, release) and the drone (a key, a second key, the same
// key again to stop, the mod wheel pulsing it), printing the level and the MIDI it sends.
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
var exprs = 0
let lock = NSLock()
au.midiOutputEventBlock = { _, _, n, bytes in
    let b = (0..<n).map { bytes[$0] }
    var i = 0
    lock.lock()
    while i + 2 < b.count {
        let st = b[i] & 0xF0
        if st == 0x90 || st == 0x80 { sent.append("\(st == 0x90 && b[i + 2] > 0 ? "on" : "off") \(b[i + 1])") }
        else if st == 0xB0 && b[i + 1] == 11 { exprs += 1 }
        else if st == 0xB0 { sent.append("cc\(b[i + 1])=\(b[i + 2])") }
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
func settle(_ secs: Double) { RunLoop.main.run(until: Date().addingTimeInterval(secs)) }   // the plugin renders its notes meanwhile
func run(_ secs: Double, _ label: String) {
    var sum = 0.0, n = 0
    for _ in 0..<Int(secs * 48000 / 512) {
        _ = try! engine.renderOffline(512, to: buf)
        let l = buf.floatChannelData![0]
        for i in 0..<Int(buf.frameLength) { sum += Double(l[i] * l[i]); n += 1 }
    }
    lock.lock(); let s = sent; let e = exprs; sent = []; exprs = 0; lock.unlock()
    print(String(format: "%-30@ rms %.4f  ", label as NSString, sqrt(sum / Double(max(n, 1)))) + s.joined(separator: ", ")
          + (e > 0 ? "  (\(e) expression)" : ""))
}
param("Page")?.value = 1
settle(6)
run(0.5, "Lead page")
inst.startNote(69, withVelocity: 100, onChannel: 0)
run(0.5, "A4")
inst.startNote(72, withVelocity: 100, onChannel: 0)
run(0.5, "C5 over it (legato)")
inst.stopNote(72, onChannel: 0)
run(0.5, "C5 up: back to A4")
inst.sendController(1, withValue: 100, onChannel: 0)
run(0.5, "mod wheel: vibrato")
inst.stopNote(69, onChannel: 0)
inst.sendController(1, withValue: 0, onChannel: 0)
run(1.0, "released")
param("Page")?.value = 2
settle(6)
run(0.5, "Drone page")
inst.startNote(62, withVelocity: 100, onChannel: 0); inst.stopNote(62, onChannel: 0)
run(2.0, "D: drone")
inst.startNote(57, withVelocity: 100, onChannel: 0); inst.stopNote(57, onChannel: 0)
run(2.0, "A: slides there")
inst.sendController(1, withValue: 110, onChannel: 0)
run(1.0, "mod wheel: pulse")
inst.sendController(1, withValue: 0, onChannel: 0)
inst.startNote(57, withVelocity: 100, onChannel: 0); inst.stopNote(57, onChannel: 0)
run(2.0, "A again: stops")
param("Page")?.value = 0
settle(6)
run(0.5, "back to Chord")
inst.startNote(62, withVelocity: 100, onChannel: 0)
run(1.0, "Chord page: D")
inst.stopNote(62, onChannel: 0)
run(1.0, "released")
