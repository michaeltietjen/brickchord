# Changelog

## v0.1.0-alpha (2026-10-31)
First public alpha.
- 15 sounds: adds Wide Supersaw, Prophet Poly, Electric Piano, Glass Bells, Choir Pad, Acid Chord, Lofi Strings, Sub Pad
- Sounds load almost instantly: one note renders right away, background workers render the rest while you play, and every rendered sound is kept in a disk cache for next time
- Fix: sound dropping out mid-play (notes are no longer rendered during play, voice count is capped, the audio stream restarts itself if it ever runs dry)
- Sound Editor (Settings > Edit Sound): wave, detune, sub, filter, envelopes, PWM; edits saved per sound
- Diatonic chord buttons, button and stick modifiers, 4 scales
- Analog-VA engine, filter and resonance controls
- Sample-accurate audio engine: shared clock for drums, strums, arps and harp sweeps
- Reverb and tempo-synced ping-pong delay on the right stick
- Play modes: Chord, Strum Folk/Pop/Skank, Slop, Harp Up/Down, 5 arpeggiators
- Quantize, latch, spread, latency settings; per-launch log files
