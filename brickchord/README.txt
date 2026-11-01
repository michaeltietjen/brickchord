BRICKCHORD  -  pocket chord machine with an analog-VA voice
(an original app; not affiliated with any hardware maker)

PLAY
  D-pad  <  ^  >  v    chords I  ii  iii  IV
  X  A  B              chords V  vi  vii
  hold Y / L1 / R1     flip / 7th / sus4   (L1+R1 = 9th)
  LEFT STICK           up 7, up-right maj7, right 9, down-right aug,
                       down flip, down-left dim, left sus4, up-left sus2
  RIGHT STICK          up = more REVERB + DELAY (wet), down = dry the synth out
                       left = FILTER (darker), right = RESONANCE sweep
  CLICK RIGHT STICK    hold the current effects; click again to release
  START                beat on/off
  SELECT               settings
  SELECT+START         quit

PLAY MODES (Settings > Play)
  Chord        hold to sustain
  Strum Folk / Strum Pop / Strum Skank   rhythmic guitar-style strums in tempo
  Slop         loose, human timing and velocity
  Harp Up / Harp Down                    glissando sweep through the chord
  Arp ...      5 arpeggiator patterns
  Arp Octaves (Settings) runs arps over 1 to 4 octaves (default 2)

BASS (Settings > Bass, Bass Level)
  A dedicated synth bass, an octave under the chords. It skips the reverb,
  delay and filter (like the drums) so it stays tight.
  Synth        holds the root under every chord (default)
  Pulse        root on every 8th
  Octaves      8ths jumping root / octave
  Walk         root, root, fifth, octave
  Sub + Patch  the sound's own bass note with the synth sub under it
  Patch        the sound's own bass note only (the old behaviour)
  Off          no bass
  Bass Level   0 to 200%

SOUND EDITOR (Settings > Edit Sound)
  Osc wave, detune, sub osc, cutoff, resonance, filter envelope (A/D/S),
  amp envelope (A/D/S), release, PWM depth. START auditions. Every sound
  remembers its edits (marked * in the list); Reset sound restores it.
  15 sounds: Juno Pad, Poly Brass, PWM Strings, Square Keys, Saw Pluck,
  Dark Sync-ish, Wide Supersaw, Prophet Poly, Electric Piano, Glass Bells,
  Choir Pad, Acid Chord, Lofi Strings, Sub Pad, Soft Tri Organ.

SETTINGS: key, scale, sound, filter, resonance, octave, play mode, arp octaves,
bass, bass level, reverb, reverb type, delay, delay type, delay time (synced to
tempo), beat, tempo, spread, latch, quantize, volume, latency.
  Filter / Resonance  baked into the sound. Leave them at 0 to use the
             pre-rendered sound pack (instant loading); use the right stick
             for live filter moves instead.
  Quantize   with the beat on, chords/strums/arps start on the next beat
  Latency    Low / Normal / Safe audio buffer (takes effect next launch).
             Use Safe if you ever hear crackles.
The CPU % at the bottom shows how hard the audio engine is working.
Log: brickchord.log in this folder.
Reverb/Delay in Settings set the resting amount; the right stick adds more.
Effects (reverb, delay, filter) only touch the synth; drums stay dry.
Reverb Type: Hall, Room, Plate, Big Hall, Spring, Reverse, Gated, Lo-fi Dark.
Delay Type: Ping-Pong, Straight, Tape (repeats get darker), Dub (long dark trails),
  Slapback (one quick echo), Multi-Tap (rhythmic repeats).
Delay Time adds 1/8 and 1/4 triplets.
Beats (27): Four Floor, Boom Bap, Synthpop, Half Time, House, Disco, Lo-fi, Trap, Funk,
  Breakbeat, Rock, Drum & Bass, Dembow, Bossa, Afrobeat, Shuffle, Electro, Tribal,
  Jungle, Techno, Minimal Techno, 2-Step Garage, UK Funky, Neo-Soul, Nu-Disco,
  Afro House, Footwork. Set Tempo to taste (Jungle/D&B/Footwork love 160-175).
Bundled NumPy is BSD-licensed (see _vendor/numpy-*.dist-info).

SCREEN
The logo animates at launch and plays the home chord of your key. Chord names
drop in letter by letter, struck tiles shatter into bricks, and a self-playing
Tetris well behind the chord name drops a piece on every chord (shape = chord
degree), clears lines in a burst of bricks and falls in time with the beat.
A live oscilloscope shows the output. The screen drops to 15 fps when nothing
moves and backs off further if the audio gets busy, so sound always wins.
