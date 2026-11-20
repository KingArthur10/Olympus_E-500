# cont_resume: keep shooting past a full buffer (E-500 fw 1.3)

**Status: flashed by the owner on 2026-11-18 (in `E0359999-ext_bkt_cr.BIN`) and working:** held continuous bursts
continue past a full buffer.
Included by default in the `ext_bkt` build (one file to flash). Build it alone with `python3 cont_resume.py E0359999.BIN` (your stock file).

## Problem [confirmed on camera, owner 2026-11-18]
Stock continuous drive stops when the buffer fills, even with the shutter held: 4 RAW frames at 1/60 s, 8 at 1/2 s.
A release and re-press continues (and an AE bracket continues at the next EV).

## Mechanism [confirmed by disassembly]
When frames can't be fired, the last in-flight frame finishes, and the trigger moves PICTURE → TAKE_READY2. There it
re-enters PICTURE only when `trig_can_resume()` (0x400A30DC) passes. Its first two checks are:
- `0xB00F6725 == 1`: shutter state "fresh full press". PICTURE entry turns 1 into 2 ("held, shooting"). Release events
  set it to 0 (TAKE_READY2 0x400A2ED5; PICTURE 0x400A27F6). Only a new full-press event (0x400A2E81) sets 1 again.
- `0xB00F6736 == 1`: ready flag. TAKE_READY2 clears it at entry, and message 0x04080032 sets it.

So a held button (state 2) can never resume. That is the stock stop.

## Change (2 edits, 142 bytes)
| Addr | What |
|---|---|
| 0x400A30F7 (20 B) | those two checks → `call cont_resume_ok,[],4` / `cmp 0,d0` / `beq fail` + 9 `nop` (`site.S`) |
| 0x406F6A00 (122 B) | `cont_resume_ok` (`cont_resume.S`) in the 0xFF image tail (0x406F694C…0x4071FFE0, nothing references it) |

`cont_resume_ok` returns 1 exactly when the stock checks pass, or in this one new case:
- ready flag 6736 == 1 (unchanged requirement), and
- shutter state 6725 == 2 (full press held since the burst started; any release clears it), and
- continuous drive: 6743 (#62) == 1. Only continuous drive fires a second frame (`app_burst_continue` needs it), and #62
  is the PTP still-capture-mode mirror (1 normal → 0, 2 burst → 1, table @0x403544BC). Single drive is unchanged.
- not PC/remote capture (6749 != 1), and
- either no bracket is active (shot limit 6722 == −1), or an **unfinished** AE bracket (#88 == 1, #7 ≠ 0, no #305/#307
  bracket). A finished bracket keeps the stock behaviour, so holding past the last frame does **not** start a new
  bracket.

All later checks in `trig_can_resume` (AF/drive/#52/#3006) are untouched. The resume also requires a free frame buffer
(`get_take_state(1)` → 0x40137E4F counts free slots) and a non-full card. So the camera fires as card writes free
buffer slots.

## Verification
- `verify_cont_resume.py` (run by the build): an interpreter executes the real bytes from 0x400A30F7 in the stock and
  the patched image, over 124,416 combinations of the 5 RAM flags, 4 settings and junk in setting_get's upper bits.
  The stock image follows the stock rule, which validates the interpreter. The patched image follows the stock rule
  OR the new rule exactly. Negative controls (unpatched image, a mutated compare, a skipped #7 check) are all caught.
- `tools/oly_diffcheck.py`: no byte changed outside the declared edits. Brute-force scan: nothing jumps into the
  patched window, and nothing references the helper's range.
- All 8 callers of `trig_can_resume` are TAKE_READY2 functions (0x400A2C13…0x400A3077). The helper never runs at boot
  or in menus, only after a shot, while the trigger is in TAKE_READY2.

## Risks / unknowns
1. **First code executed from the image tail.** All stock code lies below ≈0x40167000. The tail is the same flash
   window the CPU already reads data from, with no MMU in use [hypothesis, strong]. If fetching code there failed, the
   symptom would appear right after a shot in TAKE_READY2, not at boot, so a card re-flash would stay possible.
2. **The ready flag (0x04080032) may not arrive without a re-press.** Then nothing resumes and behaviour equals stock
   (inert, harmless). Owner pre-test: after the burst stops, keep the button **half**-pressed, ease to half, then press
   fully again. If it continues immediately, the TAKE_READY2 path works, and cont_resume should resume on its own.
3. **AE bracket with setting #228 == 1:** stock then ignores a full-press *release* during PICTURE (flag 6732 = 0), so
   if you lift to half-press mid-burst, the bracket may resume while you're half-pressed. Releasing fully always stops
   it (6724 / 0x02010100 → END). This matches stock bracket semantics in that configuration.
4. Each resume fires at least one frame or goes to END (PICTURE entry checks free slots), so there is no loop that
   makes no progress. Card full → NG3 → no resume.
