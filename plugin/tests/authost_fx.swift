// The Logic MIDI FX build (Bricklab Studio MIDI): loads it as a host does, sends it keys and
// prints the notes it plays into the instrument after it, on the Chord, Lead and Drone pages.
import AVFoundation
import AudioToolbox

let desc = AudioComponentDescription(componentType: kAudioUnitType_MIDIProcessor, componentSubType: 0x42726b4d /* BrkM */,
                                     componentManufacturer: 0x4d746965 /* Mtie */, componentFlags: 0, componentFlagsMask: 0)
var unit: AUAudioUnit?
let sem = DispatchSemaphore(value: 0)
AUAudioUnit.instantiate(with: desc, options: []) { au, err in unit = au; if let err = err { print("load failed:", err) }; sem.signal() }
sem.wait()
guard let au = unit else { exit(1) }
print("outputs:", au.midiOutputNames, "buses out:", au.outputBusses.count)
print("loaded:", au.audioUnitName ?? "?", "by", au.manufacturerName ?? "?")
var sent: [String] = []
let lock = NSLock()
au.midiOutputEventBlock = { _, _, n, bytes in
    let b = (0..<n).map { bytes[$0] }
    var i = 0
    lock.lock()
    while i + 2 < b.count {
        let st = b[i] & 0xF0
        if st == 0x90 || st == 0x80 { sent.append("\(st == 0x90 && b[i + 2] > 0 ? "on" : "off") ch\(Int(b[i] & 0x0F) + 1) \(b[i + 1])") }
        i += 3
    }
    lock.unlock()
    return noErr
}
au.maximumFramesToRender = 512
try! au.allocateRenderResources()
let render = au.renderBlock
let midiIn = au.scheduleMIDIEventBlock!
var sampleTime = 0.0
let chans = au.outputBusses.count > 0 ? au.outputBusses[0].format.channelCount : 0
let store = (0..<2).map { _ in UnsafeMutableRawPointer.allocate(byteCount: 512 * 4, alignment: 16) }
print("channels:", chans)
func run(_ secs: Double, _ label: String) {
    for _ in 0..<Int(secs * 44100 / 512) {
        var ts = AudioTimeStamp(); ts.mSampleTime = sampleTime; ts.mFlags = .sampleTimeValid
        var flags = AudioUnitRenderActionFlags()
        let abl = AudioBufferList.allocate(maximumBuffers: Int(chans))
        for c in 0..<Int(chans) { abl[c] = AudioBuffer(mNumberChannels: 1, mDataByteSize: 512 * 4, mData: store[c]) }
        let st = render(&flags, &ts, 512, 0, abl.unsafeMutablePointer, nil); if st != noErr && sampleTime == 0 { print("render status", st) }
        sampleTime += 512
    }
    lock.lock(); let s = sent; sent = []; lock.unlock()
    print(String(format: "%-22@ ", label as NSString) + s.joined(separator: ", "))
}
func key(_ on: Bool, _ k: UInt8) { midiIn(AUEventSampleTimeImmediate, 0, 3, [on ? 0x90 : 0x80, k, on ? 100 : 0]) }
func param(_ name: String) -> AUParameter? { au.parameterTree?.allParameters.first { $0.displayName == name } }
RunLoop.main.run(until: Date().addingTimeInterval(1))
key(true, 62); run(0.5, "Chord page: D")
key(false, 62); run(0.5, "released")
param("Page")?.value = 1; run(0.1, "Lead page")
key(true, 69); run(0.3, "A4")
key(false, 69); run(0.3, "released")
param("Page")?.value = 2; run(0.1, "Drone page")
key(true, 62); key(false, 62); run(0.5, "D: drone")
key(true, 62); key(false, 62); run(0.5, "D again: stops")
