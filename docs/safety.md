# Flashing safety

The E-500 has no known recovery path (no public bootloader/JTAG unbrick procedure).
A bad flash may permanently brick the camera.

**If you are building a firmware from this repository for your own camera:** use only the official firmware file
the scripts accept (they check its SHA-256), prefer the default build (it is bit for bit the one flashed and tested
on the author's camera), flash with a full battery using the camera's official update method, and keep your
original firmware file. Custom builds are verified offline only. There is no warranty: you flash at your own risk.

Rules for the analysis work in this repository:

1. **Claude never flashes and never tells the owner a build is ready to flash** until all of
   the following hold:
   - The patch is expressed in `patches/` and applied by a tool. The output is reproducible from
     the original firmware plus the patch.
   - A byte diff between the original and patched decoded images shows *only* the intended changes.
   - The container (header, length, trailer checksum) has been re-generated, and the stock file
     round-trips: decode → encode reproduces the original **bit for bit**.
   - Every patched code path has been reviewed in the disassembly. Where possible, also
     exercised in emulation.
2. **Round-trip first.** Before attempting any patch, prove that the toolchain can rebuild the
   unmodified firmware identically. If the updater's checksum is not understood, stop.
3. **Smallest possible patches.** Change constants and branches in place. Avoid relocating code
   unless free space and every reference are both understood.
4. Flash with a full battery, the official update method only, and the camera on mains/AC if
   available.
5. Keep the stock firmware file to hand so it can be re-flashed if the camera still boots.
