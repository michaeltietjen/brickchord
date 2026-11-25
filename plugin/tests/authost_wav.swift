// Records the Bricklab Studio AU holding a chord (Chord page, one key) to a WAV, to listen
// to or measure: authost_wav out.wav [sound index] [sample rate]
import AVFoundation
import AudioToolbox

let args = CommandLine.arguments
let outPath = args.count > 1 ? args[1] : "/tmp/brick.wav"
let sound = args.count > 2 ? Float(args[2]) ?? 0 : 0
let rate = args.count > 3 ? Double(args[3]) ?? 48000 : 48000
let desc = AudioComponentDescription(componentType: kAudioUnitType_MusicDevice, componentSubType: 0x42726b6c /* Brkl */,
                                     componentManufacturer: 0x4d746965 /* Mtie */, componentFlags: 0, componentFlagsMask: 0)
let engine = AVAudioEngine()
let sem = DispatchSemaphore(value: 0)
var inst: AVAudioUnitMIDIInstrument?
AVAudioUnit.instantiate(with: desc, options: []) { au, _ in inst = au as? AVAudioUnitMIDIInstrument; sem.signal() }
sem.wait()
guard let inst = inst else { print("not an instrument"); exit(1) }
inst.auAudioUnit.parameterTree?.allParameters.first { $0.displayName == "Sound" }?.value = sound
inst.auAudioUnit.parameterTree?.allParameters.first { $0.displayName == "Space" }?.value = 0
let fmt = AVAudioFormat(standardFormatWithSampleRate: rate, channels: 2)!
engine.attach(inst)
engine.connect(inst, to: engine.mainMixerNode, format: fmt)
try! engine.enableManualRenderingMode(.offline, format: fmt, maximumFrameCount: 512)
try! engine.start()
let buf = AVAudioPCMBuffer(pcmFormat: engine.manualRenderingFormat, frameCapacity: 512)!
let file = try! AVAudioFile(forWriting: URL(fileURLWithPath: outPath), settings: fmt.settings)
func run(_ secs: Double, write: Bool) {
    for _ in 0..<Int(secs * rate / 512) { _ = try! engine.renderOffline(512, to: buf); if write { try! file.write(from: buf) } }
}
run(0.1, write: false)
RunLoop.main.run(until: Date().addingTimeInterval(8))   // the sounds render (the plugin works on the main run loop)
inst.startNote(62, withVelocity: 100, onChannel: 0)
run(3.0, write: true)
inst.stopNote(62, onChannel: 0)
run(1.0, write: true)
print("wrote", outPath)
