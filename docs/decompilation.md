# Decompilation conventions

- Tool: Ghidra (not yet installed; needs JDK 21+). Projects live in `Olympus E-500/work/ghidra/`
  (gitignored). Analysis that must survive goes into git as **exported artifacts**:
  - `Olympus E-500/notes/symbols-<ver>.csv` — `address,name,type,comment`. This is the source of
    truth for names. Re-importable via a script.
  - Short annotated disassembly excerpts in notes, for anything a patch touches.
- Naming: `subsystem_verb_object`, e.g. `drive_bracket_next_frame` or `ui_menu_bkt_count`.
  Unknown functions keep Ghidra defaults until understood. Prefix guesses with `maybe_`.
- Always record the **firmware version** alongside an address. Addresses differ between
  firmware versions.
- When porting a finding to another firmware version, find it again by byte signature or
  string xref and record the new address. Never translate addresses arithmetically.
