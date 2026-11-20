# Olympus E-500 Firmware Mods

Firmware research and modifications for the Olympus E-500 (2005; Four Thirds DSLR, Kodak 8 MP CCD, Panasonic
MN10300 CPU). The main goal is long, ascending AE brackets for HDR, shot in the camera, in the field, by holding the
shutter button. There is no tethering or host-side control.

**Before flashing anything, read [`docs/safety.md`](docs/safety.md).** No recovery path is known for the E-500, and
a bad flash may brick the camera.

---

## The modified firmware

**On the camera:** `ext_bkt r5`, flashed 2026-11-19. It was built from the official firmware 1.3
(`E0359999.BIN`). Output SHA-256: `f03a644c5fa8cb497071c0638de469900a646766b47d84f45e016f17b2e85cc3`.

### What changes compared with stock
| Area | Stock E-500 | With r5 |
|---|---|---|
| AE BKT choices, 1/3 EV step | OFF, 3F 0.3EV, 3F 0.7EV, 3F 1.0EV | The same four, **plus six long presets** (13 to 37 frames) |
| AE BKT submenu, 1/3 EV step | One column of 4 rows | **3-column grid** (below) |
| Frame order | Metered, then −, then + | Stock choices: unchanged. **Presets: ascending, darkest first** |
| Frames the camera can't expose | Clamped (duplicate frames at the shutter limit) | Presets: **skipped**. Only frames the shutter or aperture range can reach are shot |
| Held shutter in continuous drive | Stops when the buffer fills (about 4 RAW frames) | **Keeps shooting** as the buffer drains, for as long as the button is held |
| M mode shutter dial with bracketing on | Works | Works with every preset (an early build had a stuck dial, fixed in r3) |
| 1/2 EV and 1 EV step modes | Stock | Unchanged |
| Everything else (other menus, playback, image size …) | Stock | Unchanged |

### Menu structure
The AE BKT menu item opens a submenu that depends on the camera's EV STEP setting. With **1/3 EV** selected, r5 replaces
the submenu with this grid:

```
 AE BKT (EV step 1/3)
 ┌────────────┬────────────┬────────────┐
 │ OFF        │ 13F ±2     │ 31F ±5     │
 │ 3F 0.3EV   │ 19F ±3     │ 37F ±6     │
 │ 3F 0.7EV   │ 22F -3+4   │            │
 │ 3F 1.0EV   │ 25F ±4     │            │
 └────────────┴────────────┴────────────┘
   stock         presets      presets
```

- **Up/down** walks through the choices in list order, one column at a time: OFF → 3F 0.3 → 3F 0.7 → 3F 1.0 → 13F →
  … → 37F. Confirmed on the camera. What left/right do is not reported yet.
- Column 1 holds the stock choices, which behave exactly as stock.
- The labels are drawn in the camera's own menu font. When a preset is chosen, the main menu row shows its label
  like a stock choice.
- With the **1/2 EV** or **1 EV** step the submenu is stock. If you switch the EV step while a preset is selected,
  the camera turns it into the stock "3F 0.5EV" or "3F 1.0EV". This is the camera's own remapping. Switching back
  to 1/3 EV does not restore the preset.

### The presets
All presets use 1/3 EV steps, from the bottom of the range to the top.

| Label | Frames | Range around the metered exposure | Spread |
|---|---|---|---|
| 13F ±2 | 13 | −2 → +2 EV | 4 EV |
| 19F ±3 | 19 | −3 → +3 EV | 6 EV |
| 22F -3+4 | 22 | −3 → +4 EV | 7 EV |
| 25F ±4 | 25 | −4 → +4 EV | 8 EV |
| 31F ±5 | 31 | −5 → +5 EV | 10 EV |
| 37F ±6 | 37 | −6 → +6 EV | 12 EV |

The preset list is chosen at **build time**. The default is `--presets -2:2,-3:3,-3:4,-4:4,-5:5,-6:6`, where each
entry is BOTTOM:TOP in EV, in multiples of 1/3. There can be 1 to 8 presets (the grid has 12 cells), up to ±6 EV.

### How exposure works per mode
- **A mode (recommended):** the run spreads BOTTOM…TOP around the metered exposure. Exposure compensation shifts the
  whole window. The aperture stays fixed and the shutter speed changes.
- **M mode:** the **shutter speed you set is the bottom of the run**, and the bracket climbs from there. Set the
  darkest exposure you want. This was seen on the camera (2026-11-19) and is accepted as is. Why M differs from the
  other modes hasn't been worked out.
- **S mode:** works, but the bracket moves the aperture, so depth of field changes between frames. Avoid it for HDR.
- **Skipping:** before each burst the camera plans which frames it can actually expose. In A, P and M that means
  within the shutter range (60 s … 1/4000 s, or the flash and slow-sync limits). In S it means within the lens's
  aperture range. It shoots from the first reachable frame to the last. If none is reachable, it shoots one frame at
  the nearer end. Skipping is off with flash, auto ISO, scene modes and Bulb, where the camera clamps as stock does.

### Using it in the field
1. MENU → AE BKT, with EV STEP at 1/3 EV. Pick a preset.
2. Set the drive mode to **continuous (sequential)**.
3. **Hold the shutter button** for the whole run. With cont_resume, the camera keeps firing while the buffer drains,
   so a long preset just takes longer.
4. If you release mid-run, the next press continues from the frame where it stopped. Finish a run (or shoot it
   again) before switching presets. A switch mid-run may cost one stray frame.
5. In single drive you get one frame per press.
6. **Set AE BKT to OFF before flashing stock firmware back.**

### On-camera test status (r5)
| Check | Result |
|---|---|
| Flash | OK (2026-11-19) |
| Grid menu, labels, up/down | OK |
| Presets fire the right count, ascending | 2 presets tested, OK. Others not yet tested |
| M mode with a preset | Dial works (you could set the speed). The run starts at the set shutter speed |
| Stock "3F 1.0EV" gives a 3-frame bracket | Not yet tested |
| Skipping, bright scene (1/4000 end) and dark scene (slow end; not yet tried past 30 s) | Not yet tested |
| Left/right in the grid; nothing else changed | Not yet tested |

Full checklist and risks: [`Olympus E-500/patches/ext_bkt/README.md`](Olympus%20E-500/patches/ext_bkt/README.md).

### Build history
| Build | Contents | Status |
|---|---|---|
| r1 | 22F ascending bracket in place of "3F 1.0EV" | Superseded |
| r2 | r1 + cont_resume (keep shooting past a full buffer) | Flashed 2026-11-18; M dial stuck |
| r3 | r2 + M-mode shutter-dial fix | Flashed 2026-11-18, working. **Known-good fallback** |
| r4 | r3 + skip unreachable frames | Never flashed |
| **r5** | r4 + the preset grid; "3F 1.0EV" back to stock | **On the camera since 2026-11-19, working** |

### Building it yourself
You need your own copy of the official firmware 1.3 file `E0359999.BIN`. The firmware isn't distributed here. Then:

```
python3 "Olympus E-500/make_firmware.py" path/to/E0359999.BIN E0359999-ext_bkt.BIN
```

This needs only Python. It checks the input by SHA-256, applies the shipped patch, and checks the result
independently. The output must be bit for bit the r5 build above, or the script stops. Own presets
(`--presets`) need GNU binutils for MN10300. Full instructions and the flashing notes are in
[`Olympus E-500/README.md`](Olympus%20E-500/README.md).

Each build is checked offline before it is flashed:
- The new code runs as real firmware bytes in an MN10300 simulator (`tools/mn103_sim.py`), side by side with stock.
- Menu lookups are proved to match stock for every id but the new ones.
- Each new label bitmap is compared with its text.
- A separate checker (`tools/oly_diffcheck.py`) confirms nothing changed outside the declared edits.
- Deliberately planted bugs are caught by the negative-control scripts.

### License
This repository's code and documentation are under the [MIT License](LICENSE). Olympus firmware is not included
and is not covered by it.

### Where to read more
- [`Olympus E-500/README.md`](Olympus%20E-500/README.md): building, custom presets, flashing.
- `Olympus E-500/patches/ext_bkt/` and `Olympus E-500/patches/cont_resume/`: patch sources, build and verify scripts,
  and READMEs.

---

## Repository layout and tools
```
docs/          shared methodology: firmware workflow, flashing safety, decompilation conventions, references
tools/         Python tools (stdlib only)
  oly_fw.py         unpack / repack the Olympus .BIN container (with checksum)
  oly_patch.py      apply a pinned JSON patch to the stock .BIN and check the result
  oly_diffcheck.py  independent stock-vs-patched check
  mn103_sim.py      MN10300 simulator for differential tests of patch code
  mn103_calls.py, xref.py, mn103_forms.py   call sites, references, instruction-form checks
  export_public.py  copy the repo for public release, without vendor firmware
Olympus E-500/
  make_firmware.py  one-step build from your own firmware file
  Firmware vX.Y/    official vendor files: in the author's private working copy only, never distributed
  notes/            dated research findings (author's working copy only)
  patches/          patch definitions (the source of truth for every modification)
  work/             generated output (gitignored)
```
Disassembly uses GNU binutils for MN10300 (`binutils-mn10300-linux-gnu`).
