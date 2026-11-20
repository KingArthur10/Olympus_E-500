# Firmware workflow (all cameras)

1. **Ingest.** Copy the vendor file into `<Camera>/Firmware vX.Y/` and never edit it. Record
   its SHA-256, size and source URL in the camera's CLAUDE.md.
2. **Container.** Run `python3 tools/oly_fw.py info <file>` to get the header and trailer fields.
   Document the fields in the camera's CLAUDE.md, marking each [confirmed]/[hypothesis].
3. **Deobfuscate/decrypt** to `<Camera>/work/<ver>/decoded.bin`. Validate by finding plaintext
   strings (menu text, "OLYMPUS", copyright) and sane code statistics.
4. **Split** sections (bootloader / main / DSP / resources) if the decoded image has an internal
   table. Note load addresses.
5. **Identify the architecture.** Test instruction-pattern statistics for candidate ISAs and
   check where the code disassembles cleanly. Confirm with vector tables or prologues. Record
   the evidence.
6. **Analyze in Ghidra** (see `decompilation.md`).
7. **Locate the feature** via strings, UI tables, numeric constants and xrefs.
8. **Patch** → `patches/` definition → apply → re-encode → verify (see `safety.md`).
9. **Log** each step as `notes/YYYY-MM-DD-topic.md`. Update the findings index in CLAUDE.md.
