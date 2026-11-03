# Changelog

## Unreleased: modes, engines, effects rack, Bricklab
- Two FX buses (Bricklab). Settings > FX now has bus A and bus B, each with its own reverb type, delay type and delay time. Every track picks its bus on the track page (SENDS > FX bus), so one group of tracks can sit in a Hall with a ping-pong delay while another gets a Plate and a tape delay. A bus that nothing feeds costs nothing. Reverb types now go to the audio process by name (it renders the impulse itself), which also removes the last big message on the pipe.
- Record quantize (Bricklab): Settings > Global > Rec quantize: Off, 1/16, 1/8 or 1/4. Notes, bass and drum hits snap to that grid as they are recorded; X on the GRID page quantizes an existing track to the same grid.
- Bricklab: the play-along beat is gone. START is play/stop for the song in every mode (drums are track 1), the beat row and the logo follow the transport, Settings > Global has no Beat row, and quantize locks live chords to the transport. Brickchord keeps its START beat.
- Recording is explicit now (Bricklab). A on the Pattern page just takes you to the track to play it; nothing records unless you turn REC on with SELECT+A (and SELECT+A again turns it off). The REC chip in the header shows when a track is recording.
- A UI watchdog writes the stuck call stack to the log if the screen loop stalls for 2 seconds, and the metronome sound is now rendered on the audio side instead of being sent over the pipe (a message that large could wedge the two processes).
- One track page (Bricklab). Effects mode and SONG > X are now the same screen: the selected track of the playing pattern, with its sound, mix (level, pan, mute), sends (reverb, delay), live filter (cutoff, resonance) and the effects rack, in sections. LEFT/RIGHT sets a value, A toggles an effect (or mute, or hears the sound on the Sound row), Y+LEFT/RIGHT sets an effect's rate, L1/R1 moves between tracks, X randomizes the rack, Y+X clears it, and a tap of Y copies the whole track setup to the same track in every pattern. Before, Effects mode edited a separate live rack that was swapped under you when the pattern changed, so what you tweaked and what the track played could drift apart; Glide has moved to Settings > Chords > Lead glide.
- New drum kits. All five built-in kits (Classic, 808, 909, Lo-fi, Acoustic) were redesigned: tuned kick bodies with proper pitch drops and beater clicks, snares with shell modes and filtered wires, real 808/909-style metal for the hats, layered claps, and a small room on the Acoustic kit. They are rendered offline at 44.1 kHz by `tools/make_kits.py` and ship as WAVs in `brickchord/kits/`, so they cost the Brick nothing to play and load faster than before. Levels still follow the old Classic kit, so songs keep their mix.
- Metronome (Bricklab): Settings > Global > Metronome: Off, When recording (count-in, armed or recording) or Always (whenever the transport runs), with Click sound (Click, Wood, Beep, Rim) and Click level. It clicks quarter notes with an accent on each bar, on its own dry bus, so it is never recorded and works the same on every track. The count-in uses the same sound.
- Settings has pages now: Global, Chords, Drums (Bricklab) and FX. L1/R1 flips between them, and Settings opens on the page for what you are doing (Drums from Drums mode or the track 1 grid, FX from Effects).
- Settings > Drums, for the playing pattern's drum track: kit (this pattern or all patterns), rescan samples (new WAV kit folders show up without a relaunch), preset beat (A loads it, undoable), pattern length, swing amount and whether it swings 16ths or 8ths, accent and ghost depth, humanize (small timing and level drift), hat choke (closed hat cuts the open hat), drum level, and a mixer row per lane: LEFT/RIGHT level, Y+LEFT/RIGHT tune (+/-12 semitones), A mute, X to hear it.
- Bricklab drum machine: track 1 of every pattern is now a drum track with an 8-lane step grid (kick, snare, clap, rim, tom, hat, open hat, shaker). On SONG > GRID with track 1 selected: A toggles a step, B cycles accent / ghost, X loads the next preset beat as a starting point, Y+X changes kit, Y+UP/DOWN sets a lane's level, Y+A mutes a lane, Y+B clears it, Y+LEFT/RIGHT sets swing. Every pattern keeps its own drums, so songs get real verses and fills. The Drums pads play and record into track 1, through its effects.
- Drum kits: Classic, 808, 909, Lo-fi and Acoustic, plus your own WAV kits in `samples/<kit name>/` (kick.wav, snare.wav, hat.wav ...; levels matched automatically). See samples_README.txt.
- The START beat steps aside while a pattern's drum track is playing, so the two never double up.
- Older songs: notes recorded on track 1 move to the first empty track.
- Brickchord: Drums mode removed (it didn't connect to the beat). The preset beat stays on START.
- Mode wheel: click the left stick (L3) to open it, push the stick toward Play, Lead, Drone, Drums, Sequencer or Effects, let go to switch. L3 is learned once on first launch.
- New synth engines: FM (FM Keys, FM Bell, FM Brass), Karplus-Strong plucked strings (Nylon Guitar, Steel Guitar), Drawbar Organ, Vox Pad (formant vowels that morph) and Air Pad (shaped noise). 23 sounds in total.
- Effects rack with LFOs, stackable: Drive, Lo-fi, Chorus, Flanger, Vibrato, Tremolo, Gate, Auto-Pan, Wide (stereo) and Filter LFO, each with an amount and a tempo-synced rate (1/16 to 4 bars), plus Glide. Randomize with X. Runs alongside the existing reverbs and delays.
- Lead mode: single-note melodies on the 7 chord buttons, Y/L1 octave up/down, R1 sharp, left stick bends and adds vibrato, legato glide.
- Drone mode: tap a degree to sustain a drone of that chord root (Y adds the 3rd), play other modes on top.
- Drums mode: 8 finger-drum pads (kick, snare, hats, clap, tom, rim, shaker), L1 soft, R1 accent.
- Repeat play modes: Repeat 1/4, 1/8, 1/16 retrigger the held chord in time.
- Two apps from one codebase: Brickchord (the chord machine, no song mode) and Bricklab (Brickchord plus song mode). A file `brickchord/edition.txt` containing `lab` makes a folder run as Bricklab; Bricklab.sh launches it from `ports/bricklab/`, sharing Brickchord's sound cache.
- Bricklab: count-in for recording (Settings > Count-in: Off, 1 or 2 bars). With a count-in, clicks play and recording starts on the one; if the transport is already running it starts at the next pattern.
- Reverb runs at half the sample rate (about twice as fast; it was the biggest cost on the Brick).
- Song mode (replaces the looper): 16 patterns of 1 to 8 bars, each with 6 tracks that record what you play. Every track in every pattern keeps its own sound, effects rack, filter, level, pan and sends. Pages: PATTERN (mixer, Y+LEFT/RIGHT length, Y+A copy to the next empty pattern), GRID (step edit: add, delete, transpose, length, quantize, all undoable), SONG (chain patterns with repeats). Patterns switch at the end of the bar, Digitone style.
- Live playing goes through the selected track, so the Effects page, Settings > Sound / Reverb / Delay and the right stick act on that track and what you hear is what it records. (Before, recorded tracks ignored the Effects page.)
- Hold SELECT in any mode: A record, B undo/redo, X play/stop, Y mute, UP/DOWN track, LEFT/RIGHT pattern. A tap on SELECT still opens Settings.
- The audio engine now runs in its own process (audio_proc.py) so drawing can't make the sound drop out. The log's status lines include per-stage engine timings.
- Songs are saved to brickchord_song.json.
- Fix: harp sweeps, chord spread and strums could raise an engine error (a sequencer variable overwrote the event counter).
- Not yet tested on hardware.

## v0.1.0-alpha (2026-10-31)
First public alpha.
- 15 sounds: adds Wide Supersaw, Prophet Poly, Electric Piano, Glass Bells, Choir Pad, Acid Chord, Lofi Strings, Sub Pad
- Sounds load almost instantly from a disk cache. `factory_render.py` pre-renders all 15 stock sounds on a computer (copy `brickchord/cache` to the handheld); edited sounds render in the background only while nothing is playing, so play never crackles
- Fix: sound dropping out mid-play (notes are no longer rendered during play, voice count is capped, the audio stream restarts itself if it ever runs dry)
- Sound Editor (Settings > Edit Sound): wave, detune, sub, filter, envelopes, PWM; edits saved per sound
- Diatonic chord buttons, button and stick modifiers, 4 scales
- Analog-VA engine, filter and resonance controls
- Sample-accurate audio engine: shared clock for drums, strums, arps and harp sweeps
- 8 reverb types (Hall, Room, Plate, Big Hall, Spring, Reverse, Gated, Lo-fi Dark) and 6 delay types (Ping-Pong, Straight, Tape, Dub, Slapback, Multi-Tap), plus triplet delay times
- Effects only touch the synth; drums stay dry
- 27 beats incl. Jungle, Techno, 2-Step Garage, UK Funky, Neo-Soul, Afro House, Footwork; new clap, rim, tom and shaker sounds; per-beat swing
- Right stick: up = more reverb and delay together, down = dry, left = live filter sweep, right = resonance sweep; click the stick to hold the effects
- Play modes: Chord, Strum Folk/Pop/Skank, Slop, Harp Up/Down, 5 arpeggiators
- Quantize, latch, spread, latency settings; per-launch log files

## Logo
- New button-grid logo (eight keys, one orange), shown on the loading screen and in the EmulationStation ports list. Source SVGs in docs/.
- The logo animates at launch: keys pop in like a strum, the chord is struck, then a step light walks the keys while sounds load. Any button skips it.
- Startup sound is now a strummed chord in your key (home chord with its 7th, bell/e-piano tone through reverb and delay), landing when the logo keys are struck. Replaces the two-tone beep.
- Everything animates: chord names drop in letter by letter, struck tiles shatter into bricks, a self-playing Tetris well behind the chord name hard-drops a piece on every chord (shape = chord degree), clears lines in a burst of bricks and falls in time with the beat. Live oscilloscope, gliding FX bars, keys that fade out, menus whose rows drop in.
- Faster drawing: cached text, bricks and keyboard, a much cheaper Tetris AI, 15 fps at rest, and the UI backs off when the audio gets busy. Fixes the lag and crackles the animations caused.
- Bass: a dedicated synth bass on the dry bus (plucky saw + solid sine fundamental), with Bass modes Synth, Pulse, Octaves, Walk, Sub + Patch, Patch, Off and a Bass Level. Arp Octaves setting (1 to 4, default 2).

## R36Max port
- Square 720x720 layout (bigger brick well, taller keys and keyboard, more menu rows), picked automatically from the screen size.
- `vendor.py` finds NumPy and pygame: bundled wheels for aarch64 Python 3.7-3.12 are unpacked on first launch; system pygame is preferred.
- `r36/` holds the ArkOS-family launcher, install notes and `build_zip.sh`.
