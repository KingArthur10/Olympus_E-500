# Olympus E-500: build the modified firmware

This folder turns **your own copy** of the official Olympus E-500 firmware 1.3 into a modified firmware file with
long, ascending AE bracket presets (13 to 37 frames at 1/3 EV) in the AE BKT menu. It also skips frames the camera
can't expose and keeps shooting past a full buffer while the shutter is held. What changes, the menu and the
presets are described in the [top-level README](../README.md#the-modified-firmware).

The firmware file itself is **not** included. The scripts check your file by SHA-256 and refuse anything else.

> **Risk.** Flashing modified firmware can brick the camera, and no recovery method is known. This build has been
> flashed and used on one camera (the author's), and has been checked offline in detail, but it comes with no
> warranty. Read [`docs/safety.md`](../docs/safety.md) first. You flash at your own risk.

## What you need
- Python 3 (standard library only). Tested with Python 3.15 on Fedora Linux.
- The official E-500 firmware 1.3 file **`E0359999.BIN`**, which must have this SHA-256:
  `e9f5431cb47bf1c73395337256fba6eedf576c03b06c4ef7dea0d387ca7c69ae`
- Only for **your own presets** or rebuilding from the sources: GNU binutils for MN10300
  (`mn10300-linux-gnu-as`, `-ld`, `-objcopy`, `-nm`, `-objdump`; on Fedora the package `binutils-mn10300-linux-gnu`).

## Make the default build
Run from the repository root:
```
python3 "Olympus E-500/make_firmware.py" path/to/E0359999.BIN E0359999-ext_bkt.BIN
```
It checks your input file, applies the shipped patch (`patches/ext_bkt/patch.json`), and checks the result with an
independent decoder (only the declared bytes may differ, and the container checksum must be valid). The output
must be **bit for bit** the build the author flashed and tested (ext_bkt r5). The script stops with an error
otherwise. The expected output SHA-256 is:
`f03a644c5fa8cb497071c0638de469900a646766b47d84f45e016f17b2e85cc3`

Add `--rebuild` to also assemble the patch from the sources (needs binutils, about a minute) and confirm it equals
the shipped `patch.json`.

## Make your own presets
```
python3 "Olympus E-500/make_firmware.py" path/to/E0359999.BIN E0359999-custom.BIN --presets -2:2,-4:4,-6:6
```
- Each preset is `BOTTOM:TOP` in EV relative to the metered exposure, with BOTTOM ≤ 0 ≤ TOP, in multiples of 1/3
  written as whole numbers or fractions (`-3:4`, `-4/3:4/3`). Frames = 3 × (TOP − BOTTOM) + 1: 2 to 99, never 3 or 5
  (stock uses those), and no two presets with the same count.
- 1 to 8 presets (the grid has 12 cells, 4 used by the stock choices). Offsets up to ±6 EV.
- Labels are drawn automatically ("13F ±2", "22F -3+4") and must fit a 96-px slot. Uneven ranges with a
  fractional end ("11F -1.3+2") are usually too wide: the build then stops with an error naming the label.
- `--no-cont-resume` leaves out the keep-shooting-past-a-full-buffer change.
- The build runs the offline verifiers and writes the patch definition next to the output
  (`E0359999-custom.patch.json`). A custom build is **verified offline but has never been on a camera**: it
  differs from the tested build in its data, and frame counts other than the defaults have not been shot.

## Flash it
This is the procedure the author used. It follows
[Marc R's guide](https://marcrphoto.wordpress.com/2024/12/03/updating-your-olympus-om-system-camera-firmware-without-olympus-workspace-updated-2024/)
to updating Olympus firmware from a memory card. That guide is written for newer bodies, so two things differ for the
E-500: it says "SD card", and the E-500 takes CompactFlash or xD-Picture Card; and the file name on the card for the
E-500 is **`E0359999.BIN`**. The guide's example, "`OLY_E_068_….BIN` → `E0689999.BIN`", is for another camera.

1. Note your current firmware version: MENU → wrench (setup) menu → firmware version.
2. Format a memory card **in the camera**. Then, on a computer, create a folder named **`DCOLYMP`** at the top level
   of the card.
3. Copy the file you built into `DCOLYMP` and name it exactly **`E0359999.BIN`**. The card should now hold
   `DCOLYMP/E0359999.BIN`.
4. Charge the battery fully.
5. With the camera **off**, insert the card.
6. **Hold the OK button, turn the camera on, then release OK.**
7. The screen stays black and the LED on the front of the camera lights orange: the update is running.
8. Put the camera down and don't touch it. **Never turn it off during the update.**
9. Wait until the LED blinks quickly: the update is complete.
10. Turn the camera off, then on again. Check the firmware version in the wrench menu. The patch doesn't change the
    version number, so it still shows the stock version (1.3).

**Going back to stock:** set AE BKT to **OFF** first (a preset's menu value has no meaning to stock firmware), then
flash your original `E0359999.BIN` the same way.

## After flashing
Check the menu grid, a preset's frame count and the stock "3F 1.0EV" choice before relying on it. The on-camera
results so far are in the [top-level README](../README.md#on-camera-test-status-r5).

## What's in this folder
| Path | What |
|---|---|
| `make_firmware.py` | The one-step script above |
| `patches/ext_bkt/` | The main patch: sources (`*.S`, `menu_data.py`, `labelfont.py`), `build.py`, verifiers, the shipped `patch.json`. [`README.md`](patches/ext_bkt/README.md) lists every edit, the checks and the known risks |
| `patches/cont_resume/` | Keep shooting past a full buffer (included in ext_bkt by default) |


## How it was checked
- The new code runs as real firmware bytes in an MN10300 simulator (`tools/mn103_sim.py`), side by side with stock.
  This covers the exposure-offset code over every frame of every preset, the shutter-limit planning, the M-mode
  dial, and the burst-resume check.
- The menu lookups match stock for every id except the new ones (all 65,536 ids).
- Each label bitmap equals its text rendered in the camera's font. The same font rules rebuild the stock labels
  bit for bit.
- Deliberately planted bugs are caught (`negctl_skip.py`, `negctl_menu.py`).
- `tools/oly_diffcheck.py` re-decodes the output independently and confirms nothing changed outside the edits.
