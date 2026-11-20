# ext_bkt: ascending AE bracket presets (E-500 fw 1.3)

**Status:** **r5 (skip unreachable frames + bracket presets in the menu) is on the camera** (flashed 2026-11-19,
owner). Menu and navigation work as expected, and two presets were tested and work.
 r3 (single 22F bracket as "3F 1.0EV", M-mode dial fix, cont_resume) is the
known-good fallback. r4 was never flashed.

## What it does
- **AE BKT menu, 1/3-EV step mode**: the submenu becomes a 3-column grid. Up/down moves through it column by column:
  ```
  OFF        13F ±2     31F ±5
  3F 0.3EV   19F ±3     37F ±6
  3F 0.7EV   22F -3+4
  3F 1.0EV   25F ±4
  ```
  Column 1 is the stock choices, which behave as stock ("3F 1.0EV" is a stock bracket again). Each preset shoots
  **N frames ascending from BOTTOM to TOP EV in 1/3 EV steps** while the shutter is held:
  13F −2…+2, 19F −3…+3, 22F −3…+4, 25F −4…+4, 31F −5…+5, 37F −6…+6.
  Labels are bitmaps in the camera's own font. The parent menu row shows the chosen label like a stock choice.
  The 1/2-EV and 1-EV modes are unchanged.
- Offsets are added to exposure compensation, so comp shifts the window.
- **Skipping unreachable frames**: before each burst the camera plans which frames it can actually expose. That
  means frames within the shutter range (60 s…1/4000 s, or flash/slow limits) in A/P/M, and within the lens aperture
  range in S. Only those are shot, from the first reachable to the last. If none is reachable it shoots one frame at
  the nearer end. Not applied with flash, auto ISO, scene modes or Bulb.
- **M-mode shutter dial** works with every preset (`m_tv_ref.S`).
- **Manual (M) mode runs from the set shutter speed** [owner observation, 2026-11-19]: the shutter speed you set is
  the **bottom of the run**. In A (and the other auto modes) the run is spread around the metered exposure as
  described above. Intended for now: the owner is fine with it. Why M differs from the offline model is not checked
  yet.
- **cont_resume** (default): a held continuous burst continues past a full buffer.



## Building
The one-step way is `../../make_firmware.py` (see `../../README.md`). By hand, with `FW` = your copy of the official
`E0359999.BIN` (checked by SHA-256):
```
python3 "Olympus E-500/patches/ext_bkt/build.py" "$FW"      # default presets, writes patch.json (~45 s, verifies)
python3 tools/oly_patch.py "$FW" "Olympus E-500/patches/ext_bkt/patch.json" E0359999-ext_bkt.BIN
```
- `--presets -2:2,-3:3,-3:4,-4:4,-5:5,-6:6` (default): BOTTOM:TOP in EV, multiples of 1/3. 1 to 8 presets (the grid
  has 12 cells). N = 3·(TOP − BOTTOM) + 1, at most 99 and never 3 or 5. Frame counts must differ (labels and the
  preset table are keyed by N). Offsets up to ±6 EV. A label must fit in 96 px (the build fails otherwise).
- r5 default output SHA-256: **`f03a644c5fa8cb497071c0638de469900a646766b47d84f45e016f17b2e85cc3`**.
  Earlier: r4 `ee27a2dc…4267` (not flashed), r3 `E0359999-ext_bkt_r3.BIN` `fcc9e8c6…313b` (on camera),
  r2 `4904d0d4…9c4e`, r1 `001a9918…abd5`.

## Edits (r5: 28 edits, 6953 decoded bytes, including cont_resume's 2)
All patch sources assemble under `.mn10300` (base ISA). Every instruction form in them also occurs in the stock
code, except the 32-bit `jmp` (base MN10300, accepted in that mode).
| Addr | What |
|---|---|
| 0x40124B1C (40 B) | `bkt_offset` → `jmp bkt_offset2` (skip.S): preset n: `(F+idx−LO)·step` over the planned frames, else stock |
| 0x406F6C00 (823 B) | `skip.S`: preset table {n, LO}, plan getters, `bkt_offset2`, `counter_next`, `n_eff`, `plan_tramp`/`plan_hook` |
| 0x40133288 / 0x400A1044 / 0x40133359 | counter wrap at C, `app_seq_limit` count (limit ≥ 1), `cam_capture_prep` tail → planning |
| 0x406F6B00 / 0x406F6B80 (73 B each) + 8 dial sites | `m_tv_ref` (live / shadow): #5 dial reference = #5 in M with a preset |
| 0x406F7000 (159 B) | `menu.S`: `res_hook`, `lay_hook`, `val_n6`, `fmt_n6` |
| 0x406F7100 (5820 B) | menu data: option list + codes, 6 label bitmaps + headers, 3 button styles (100 px), 6 value layouts, the grid, the #6 value-display table |
| 0x400FBA8D (6 B) | resource lookup → `res_hook`: ids 0x7E00–0x7E05 = preset labels |
| 0x40076A4A (6 B) | layout lookup → `lay_hook`: ids 0x7F00–0x7F08 = new layouts |
| 0x40224318 (10 B) | 1/3-EV #6 option descriptor → 10-entry list (values, codes, size) |
| 0x4020750C (6 B) | #6 value-display entry → 39-entry table |
| 0x4020093C / 0x40200FA8 | layout-table slots 1183 / 1594 (the 1/3-EV AE BKT submenu, two contexts) → the grid |
| 0x4006071C (9 B) | `ae_bkt_validate` get(6) → `val_n6` (a preset uses the stock 5F 0.3EV row) |
| 0x4006231F / 0x4006233F (9 B each) | `ui_fmt_bkt_count`: a preset prints its two digits |
| 0x400A30F7 + 0x406F6A00 | cont_resume (see `../cont_resume/README.md`) |
r1–r4's data edits (menu entry 3, validator row 10, the "5F" text record, formatter immediates) are gone: all stock again.

## Verification (run by build.py; re-run on the output with the commands below)
- `verify_menu.py`: resource and layout lookup (stock vs patched real bytes in `tools/mn103_sim.py`) over **every u16
  id**. Validator and formatter differentials. The data read back as the firmware reads it: option list and codes,
  the grid (geometry, rows, each label bitmap equal to the font rendering of its text), the value display, and id
  collisions. `--png` writes a preview of the grid from the patched records.
- `verify_skip.py` (per preset; `--exhaustive`: bkt_offset over every n and idx), `verify_m_tv_ref.py` (96,768
  cases), `../cont_resume/verify_cont_resume.py`.
- Negative controls: `negctl_skip.py` (7/7 caught), `negctl_menu.py` (12/12 caught). `labelfont.selftest`: the font
  rules rebuild the stock "3F x.xEV" labels bit for bit.
```
FW=E0359999.BIN; OUT=E0359999-ext_bkt.BIN; W=work      # your stock file, the build, a scratch directory
python3 tools/oly_diffcheck.py "$FW" "$OUT" "Olympus E-500/patches/ext_bkt/patch.json"
python3 tools/oly_fw.py decode "$FW" "$W/decoded.bin"
python3 tools/oly_fw.py decode "$OUT" "$W/decoded-ext_bkt.bin"
python3 "Olympus E-500/patches/ext_bkt/verify_menu.py" "$W/decoded.bin" "$W/decoded-ext_bkt.bin" --png "$W/grid.png"
python3 "Olympus E-500/patches/ext_bkt/verify_skip.py" "$W/decoded.bin" "$W/decoded-ext_bkt.bin" --exhaustive
python3 "Olympus E-500/patches/ext_bkt/verify_m_tv_ref.py" "$W/decoded.bin" "$W/decoded-ext_bkt.bin"
python3 "Olympus E-500/patches/cont_resume/verify_cont_resume.py" "$W/decoded.bin" "$W/decoded-ext_bkt.bin"
python3 "Olympus E-500/patches/ext_bkt/negctl_skip.py" "$FW"
python3 "Olympus E-500/patches/ext_bkt/negctl_menu.py" "$FW"
python3 tools/mn103_forms.py "$W/decoded.bin" "$W/decoded-ext_bkt.bin" 0x40124b1c:0x40124b44 0x40133288:0x40133290 \
    0x400a1044:0x400a104d 0x40133359:0x40133361 0x406f6c0e:0x406f6f37 0x406f6a00:0x406f6a7a 0x400a30f7:0x400a310b \
    0x406f6b00:0x406f6b49 0x406f6b80:0x406f6bc9 0x406f7000:0x406f709f 0x400fba8d:0x400fba93 0x40076a4a:0x40076a50 \
    0x4006071c:0x40060725 0x4006231f:0x40062328 0x4006233f:0x40062348      # expect only the jmp d32
```

## Using it
- **A mode**: the run spreads BOTTOM…TOP around the metered exposure. **M mode**: the run starts at the shutter
  speed you set (that speed is the bottom of the run), so set the darkest exposure you want.
- Prefer **A mode** and **continuous (sequential) drive**: hold the shutter for the whole preset. In single drive
  expect one frame per press. Avoid S mode (the offset moves the aperture).
- With a preset selected, switching AE BKT's EV step to 1/2 or 1 EV turns it into the stock "3F 0.5EV" / "3F 1.0EV"
  (stock remap by step value). Switching back does not restore the preset.
- Releasing mid-sequence and pressing again continues where it stopped. The frame counter is not reset by
  changing preset [hypothesis, see risk 5]. A changed preset then continues from the same frame number, or, if that
  is past its end, shoots one stray frame and resets. Finish (or re-run) a sequence before switching to be safe.
- Turn bracketing **OFF before re-flashing stock**.

## On-camera checklist for r5
Results so far (owner, 2026-11-19). Please report the open ones.
| # | Check | Result |
|---|---|---|
| 0 | Flash r5 | **OK** |
| 1 | MENU → AE BKT with 1/3 EV step: the grid as above, labels readable, nothing clipped. Up/down walks the list | **OK** (as expected). Left/right: not reported |
| 2 | Each preset: parent row shows its label; a burst shoots N frames ascending | **2 presets OK** (which: not reported). Others open |
| 3 | "3F 1.0EV": a stock 3-frame bracket (metered, −1, +1) | open |
| 4 | Skipping, A mode. Bright: starts at the first frame that fits 1/4000. Dark: stops at the last frame within the slowest shutter (60 s per the notes) | open (owner: what happens past 30 s not yet tried) |
| 5 | M mode: shutter dial turns with a preset selected | works by implication (owner set the speed in M). **Run starts at the set speed** (see above) |
| 6 | Everything else unchanged (other menus, playback, image-size menu) | open |

## Open risks

1. **New menu code on every screen draw**: `res_hook` and `lay_hook` run on every resource and layout lookup. Both
   are short, branch-only code that gives stock results for every id but the new ones (proven over all u16 ids).
2. **New geometry**: 100-px button styles are copies of the stock 168-px styles with only widths changed. Colours and
   exact on-screen look are predicted from the records [unverified on camera]. The preview is approximate.
3. **Highlight default**: if the current setting matches no entry, a stock struct list highlights its last entry.
   That is now "37F ±6" (stock: "3F 1.0EV"). Display only. In normal use every state matches an entry.
4. Labels are 96-px bitmaps like stock. The '±' and '9' glyphs are drawn here (no stock glyph).
5. Whether stock resets #7 when the menu choice changes is unknown (menu-record slot 11 sets #7 = 0; caller not
   found). Either way the limit is now never < 1, so a preset change mid-sequence costs at most one stray frame.
6. Skipping (from r4): new code runs after every exposure prep; RAM = 5 bytes of alignment padding in the trigger
   globals; a plan made at full press is kept for the burst.
7. **M mode differs from the model** [open]: the offline reading has frame 0 at set − LO, but on the camera the set
   speed is the bottom of the run. Not investigated (owner: document only). An M-mode run's EXIF shutter speeds
   (first, last, set speed, preset) would show the cause. Two candidates: the fast-side frames were skipped as past
   1/4000, or M applies the offset differently from the disassembly reading.
8. Manual mode moves the user shutter value by up to the full spread (stock max 1 EV), now up to ±6 EV. It is clamped by
   `ae_prog_M` (r4 skips frames outside the range).
