# Brickchord (alpha)

A pocket chord machine with an analog-style synth voice, built for the **TrimUI Brick Pro** running **KNULLI**.
One button plays one chord in your key, the left stick bends it, the right stick adds reverb or delay,
and everything plays on a single sample-accurate clock with a built-in drum machine.

> Alpha software. Tested on a TrimUI Brick Pro with a KNULLI beta build. Expect rough edges.

## Features
- **7 chord buttons** (D-pad + X/A/B) play the diatonic chords of your key: Major, Minor, Dorian, Mixolydian
- **Chord modifiers**: hold Y (flip major/minor), L1 (7th), R1 (sus4), L1+R1 (9th)
- **Left stick** bends the held chord 8 ways: 7, maj7, 9, aug, flip, dim, sus4, sus2
- **Right stick** for effects: up = reverb, down = tempo-synced ping-pong delay
- **Analog-VA engine**: detuned saws, PWM, sub oscillator, resonant low-pass with its own envelope (15 sounds, plus a Sound Editor to tweak each one)
- **Play modes**: Chord, Strum (Folk / Pop / Skank), Slop, Harp sweeps, 5 arpeggiator patterns
- **Drum machine** with 4 beats; strums and arps lock to its clock (with optional quantize)
- Settings for key, scale, sound, filter, resonance, octave, tempo, spread, latch, volume and latency

## Install (KNULLI)
1. Download the release zip from **Releases** (it bundles the ARM64 NumPy that Brickchord needs).
2. Copy `brickchord/` and `Brickchord.sh` into `/userdata/roms/ports/` (on the SD card: `roms/ports/`).
3. On the device: Start → Game Settings → Update Gamelists, then open **Ports → Brickchord**.
4. First launch asks you to press each button once and push each stick once.

The source in this repo does not include NumPy. To run from source, put an aarch64 / CPython 3.12 build of
NumPy in `brickchord/_vendor/` (or have NumPy available to the system Python).

## Controls
| Input | Action |
|---|---|
| D-pad ← ↑ → ↓ | Chords I, ii, iii, IV |
| X, A, B | Chords V, vi, vii |
| Y / L1 / R1 (hold) | Flip / 7th / sus4 (L1+R1 = 9th) |
| Left stick | Chord bends |
| Right stick | Reverb (up) / Delay (down) |
| Start | Beat on/off |
| Select | Settings |
| Select + Start | Quit |

## How it works
- `engine.py` mixes one continuous stereo stream in NumPy and schedules every note, strum and drum hit in
  sample time, with partitioned-FFT reverb and a ping-pong delay on the whole mix.
- `synth.py` renders each note as band-limited wavetables shaped by a resonant filter response, split into
  an attack segment and a seamless sustain loop.
- `host.py` renders all notes up front behind a loading bar, then streams audio from a dedicated thread.

## Credits and notice
Brickchord is an original, independent project. It is not affiliated with or endorsed by TrimUI, the
KNULLI project, Pocket Audio (HiChord) or Telepathic Instruments (Orchid); its workflow was inspired by
chord instruments like those. The release zip bundles NumPy (BSD-3-Clause); see its license files in
`_vendor/`.

## License
MIT, see `LICENSE`.

## Instant sound loading (optional)
On a computer with Python 3 and NumPy, run `python3 brickchord/factory_render.py` from the release folder before copying it to the SD card. It pre-renders all 15 stock sounds (about 355 MB) into `brickchord/cache`, so every stock sound opens instantly. Without it, the Brick renders each sound the first time you use it, during quiet moments, and keeps it for next time.
