# Changelog

## v0.1.0-alpha (2026-10-31)
First public alpha.
- 15 sounds: adds Wide Supersaw, Prophet Poly, Electric Piano, Glass Bells, Choir Pad, Acid Chord, Lofi Strings, Sub Pad
- Sounds load almost instantly from a disk cache. `factory_render.py` pre-renders all 15 stock sounds on a computer (copy `brickchord/cache` to the handheld); edited sounds render in the background only while nothing is playing, so play never crackles
- Fix: sound dropping out mid-play (notes are no longer rendered during play, voice count is capped, the audio stream restarts itself if it ever runs dry)
- Sound Editor (Settings > Edit Sound): wave, detune, sub, filter, envelopes, PWM; edits saved per sound
- Diatonic chord buttons, button and stick modifiers, 4 scales
- Analog-VA engine, filter and resonance controls
- Sample-accurate audio engine: shared clock for drums, strums, arps and harp sweeps
- Right stick: up/down = reverb/delay, left = live filter sweep, right = resonance sweep; click the stick to hold the effects
- Play modes: Chord, Strum Folk/Pop/Skank, Slop, Harp Up/Down, 5 arpeggiators
- Quantize, latch, spread, latency settings; per-launch log files
