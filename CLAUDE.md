# Brickchord / Bricklab: notes for Claude sessions

Read this first. It is the handoff from the session that built the app (Nov 2026).

## What this is
- **Brickchord**: a HiChord-style pocket chord machine for the TrimUI Brick Pro running KNULLI (also an R36Max / ArkOS port in `r36/`). Python + pygame + NumPy.
- **Bricklab**: the same code with song mode switched on (patterns into songs, Digitone style). The edition is chosen by `brickchord/edition.txt` (contains `lab`); no file means Brickchord. See `brickchord/edition.py`.
- Public site: https://michaeltietjen.github.io/brickchord/ (served from `docs/`).

## House rules (from Michael)
- No em dashes in any output: code comments, docs, commit messages, UI text, chat.
- Never type passwords or credentials. If the SMB share needs a login, Michael clicks Connect himself.
- Don't install untrusted software on his Mac.
- Commit messages end with the attribution lines the session provides.

## Code map (`brickchord/`)
- `main.py`: the App (UI, input, settings menu, drawing, config). `LAYOUTS` "4:3" (Brick 1024x768) and "square" (R36 720x720).
- `modes.py`: `ModesMixin`: the L3 mode wheel and the Lead, Drone, Drums, Effects modes.
- `song.py`: `SongMixin`: song mode UI (PATTERN / GRID / SONG / track FX pages), SELECT-hold combos, selected-track sync, `brickchord_song.json` save/load.
- `engine.py`: the audio engine. Pre-rendered notes mixed in NumPy blocks (22050 Hz, block 1024 = 46 ms budget). Shared 16th clock (`_on_step`). Effects rack + filter per `_Chain`. 16 `_Pattern`s x 6 `_Track`s, each track with its own chain; live notes route through the selected track (`route`). Recording captures the notes the engine actually sounds (so strums/arps replay exactly). Count-in, cueing, song chaining, undo snapshots, grid edits (`_edit`).
- `synth.py`: note rendering (VA, FM, pluck, organ, vox, noise engines), patches, synth bass, drum kit, reverb IRs, beats.
- `host.py`: `LocalHost` (engine + disk note cache + background `render_worker.py` processes), `SplitHost` + `Mirror` (UI side), `Ref` (note key standing in for samples).
- `audio_proc.py`: the engine's own process. The UI talks to it over a pipe; it sends a state snapshot ~30x/s. This fixed the dropouts (UI and audio no longer share one interpreter lock).
- `vendor.py` / `launch.py`: find NumPy/pygame (bundled `_vendor` or system).

## Device and deploy
- Brick share: `smb://root@192.168.86.236/share`, mounted on the Mac at `/Volumes/share`. Apps live in `/Volumes/share/roms/ports/brickchord/` and `/roms/ports/bricklab/` with launchers `Brickchord.sh` and `Bricklab.sh`. Bricklab shares Brickchord's `cache/`. The share drops sometimes: `open 'smb://root@192.168.86.236/share'` and ask Michael to click Connect.
- Mac paths: build copy `~/BrickchordBuild/brickchord`, git repo `~/brickchord-repo` (remote github.com/michaeltietjen/brickchord, push from the Mac).
- Logs on the device: `brickchord.log` / `bricklab.log` (+ `.prev.log`). Every 20 s a `status:` line and a `profile ms/block:` line (per-stage engine timings).
- Last measured on the Brick (split process): ~3 underruns in 9 minutes, load ~0.35; reverb was the biggest stage (~11 ms/block) and now runs at half rate (about 2x cheaper).
- Testing without hardware: headless pygame (`SDL_VIDEODRIVER=dummy`, `SDL_AUDIODRIVER=dummy`) driving `main.App` with fake inputs works well.

## Where things stand
- Brickchord: Play (chords, strum, harp, arps, repeat), Lead (glide, bend, vibrato), Drone, Drums pads, Effects rack (Drive, Lo-fi, Chorus, Flanger, Vibrato, Tremolo, Gate, Auto-Pan, Wide, Filter LFO, Glide) with randomize, 23 sounds, synth bass, 27 beats.
- Bricklab adds song mode: 16 patterns x 6 tracks, per-pattern sounds and effects, grid edit, song chain, count-in (Settings > Count-in: Off / 1 / 2 bars), SELECT-hold combos (A rec, B undo, X play, Y mute, UP/DOWN track, LEFT/RIGHT pattern).
- Drum track (Nov 2026): track 1 (`song.DT`) of each pattern is a drum track. UI state in `pm[p][0]["drum"]` (kit, swing, lanes {part: [level, mute]}, beat); pushed with the `lp drum` op; engine `_Track.drum/kit/lanes/swing`. Grid edits: `ed dtog/dvel/dlane/dset`. Kits: `synth.all_kits(samples_dir)` (built-ins + WAV folders, loudness-matched), loaded in the audio process; `synth.kit_names()` gives the UI the list. Brickchord has no Drums mode now.
- Settings pages (Nov 2026): `main.MENU_PAGES` lists rows per page (Global, Chords, Drums, FX); `all_menu_items()` builds every row, `menu_items()` filters to `self.menu_pg`. `open_menu()` picks the page from context. The Drums page lives in `song.py` (`drum_menu_items/change/activate/hear`) and edits `pm[e.cur][DT]["drum"]`: kit, swing, swres (16 or 8), acc, ghost, human, choke, lanes {part: [level, mute, tune]}; `kit_all` is song-level. Engine: `_Track.swres/acc/ghost/human/choke`, `_tuned()` resamples pitched lanes once, `_choke()`, `c_dhit(p, part, gain)` auditions a lane, host `rescan_kits()`.
- Next agreed: a Bass track (track 2) filled by chord-following bass or a mono Bass mode (live + grid). Euclidean generator later.
- Known gaps: lead bends/vibrato aren't recorded; switching to a track with a different sound loads that sound (a short pause); Drone's left stick does nothing yet (offered: filter/brightness + swell).

## Michael's roadmap for Bricklab (next)
- Instrument "environments", each with its own screen, controls and settings menu, all feeding song-mode tracks:
  - Chords (the current Brickchord core).
  - Drums: pads plus a Euclidean / modular (Eurorack-style) rhythm generator.
  - Bass: mono analog engine (Moog-style ladder, glide, accent).
  - Lead: analog, FM, wavetable engines.
  - Drone: evolving textures (and the stick controls above).
  - Samples: record/load, granular, time stretch, LFOs. Note: Michael also has a separate app, GrainBrick, in `/roms/ports/grainbrick-beta/`, built with native .so modules (granular, SoundTouch). Heavy DSP like that likely needs compiled code on this CPU.
- Earlier ideas: MIDI in/out over USB-C (needs checking whether KNULLI supports USB gadget mode), Chord Hero rhythm game, Ear Trainer.
- Before adding heavy real-time DSP, check the Brick's `profile` lines for headroom.
