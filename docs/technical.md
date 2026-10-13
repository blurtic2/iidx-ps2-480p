# Technical notes

This document explains how the games draw their picture, what the patch changes and why, and how to extend or
debug it. For using the patch, see the [README](../README.md). Every changed word is listed, with a comment,
in [`patch480p.py`](../patch480p.py); this document explains the reasoning behind those lists.

Addresses are EE virtual addresses in the boot ELF (`SLPM_xxx.xx`). The ELF has one loadable segment that
starts at file offset `0x80` and is loaded at `0x00100000`, so file offset = address − `0x100000` + `0x80`.

## Contents

1. [Terms and units](#1-terms-and-units)
2. [How the original games draw a frame](#2-how-the-original-games-draw-a-frame)
3. [What the patch changes](#3-what-the-patch-changes)
4. [Video memory layouts](#4-video-memory-layouts)
5. [The texture pool](#5-the-texture-pool)
6. [Places that reference the buffers directly](#6-places-that-reference-the-buffers-directly)
7. [13th–15th: movie mode and the hybrid routine](#7-13th15th-movie-mode-and-the-hybrid-routine)
8. [The 480-line variant](#8-the-480-line-variant)
9. [Real hardware vs. PCSX2](#9-real-hardware-vs-pcsx2)
10. [How the script checks and patches an ISO](#10-how-the-script-checks-and-patches-an-iso)
11. [Adding a version or chasing a glitch](#11-adding-a-version-or-chasing-a-glitch)

## 1. Terms and units

- **GS**: the PS2 Graphics Synthesizer. It has 4 MB of video memory (VRAM).
- **Page**: 8 KB of VRAM, 512 pages in total. Frame buffer addresses (`FBP`, `ZBP`) are in pages.
  Texture addresses (`TBP`) are in 256-byte **blocks**, 32 blocks per page (page 70 = TBP 2240, page 352 = TBP 11264).
- A page holds 64×32 pixels of a 32/24-bit buffer (`PSMCT32`/`PSMCT24`) or 64×64 pixels of a 16-bit buffer
  (`PSMCT16`, `PSMZ16S`). Sizes used below:

  | Buffer | Pages |
  |---|---|
  | 640×224, 24-bit | 70 |
  | 640×448, 24-bit | 140 |
  | 640×480, 24-bit | 150 |
  | 640×448, 16-bit | 70 |
  | 640×480, 16-bit (or 16-bit Z) | 80 |

- **A**: the display buffer that the GS reads out to the TV. **B**: the buffer the game draws the scene into.
  **Z**: the depth buffer (10th and later).
- **libgraph**: Sony's `sceGs*` library, linked into every game. Its code is byte-identical in all supported
  ELFs; only its load address differs. Patch sites inside it are given relative to `sceGsResetGraph`.

## 2. How the original games draw a frame

1. At start-up the game calls `sceGsResetGraph(0, 1, 2, 1)`: interlaced, NTSC, FRAME mode (480i, each field
   shows every other line of a full frame buffer).
2. `sceGsSetDefDBuffDc(…, PSMCT24, 640, 224, …)` sets up a **640×224** 24-bit display buffer A at page 0.
   Both double-buffer halves point to the same FBP; only the drawing environments differ.
3. The game then rewrites the context-1 drawing environment so that the scene is drawn at **640×480** into
   buffer B at page 70 (scissor Y 0..479).
4. Once per field, at VBlank, the flip code draws one sprite with context 2: B as a texture, rows 16..463,
   shrunk 2:1 into A's 224 lines with **bilinear** filtering (`TEX1_2 = 0x60`).
   `sceGsSetHalfOffset` moves the sprite by half a line on odd fields, so the two fields sample different rows.
5. `sceGsSwapDBuffDc` switches the environments.

The result is a 480i picture that shows 448 of the 480 rendered lines. GSM's 480p mode can only line-double
the 224-line buffer A, which is why it looks stair-stepped: the full-resolution picture only ever exists in B.

## 3. What the patch changes

| Change | Where | Why |
|---|---|---|
| `sceGsResetGraph` args: interlace 1→0, mode NTSC (2)→480p (`0x50`) | game init | libgraph's `sceGsSetDefDispEnv` already supports mode `0x50` (DTV 480p) |
| A height 224→448 | game init (`sceGsSetDefDBuffDc` and the game's own `sceGsSetDefDrawEnv2` calls on 10th+) | A now holds the whole picture |
| `DISPLAY.DY` 35→51 | libgraph `sceGsSetDefDispEnv` | centres 448 lines in the 480p frame |
| B at page 352 instead of 70 | libgraph `sceGsSetDefDBuffDc` | a 24-bit 640×448 A (140 pages) does not fit in front of B (§4) |
| Z at page 140 instead of 352 (10th+) | game init | Z moves into the space B left |
| Copy sprite Y 1936..2160 → 1824..2272 | flip code (per-frame and init copies) | 1:1 copy of 448 rows instead of a 2:1 shrink |
| `TEX1_2` 0x60→0 | game init, the store right after `sceGsSetDefTexEnv` | bilinear sampling at 1:1 lands on texel edges and blurs every pixel; point sampling copies exactly |
| Field / half-line offset → 0 | flip code (9th: main loop field flag) | progressive output has no fields |

The copy coordinates are GS primitive coordinates in 12.4 fixed point with the context-2 offset applied, so
`0x7900` = 1936 is screen line 0 of A in the original 224-line setup.

Interlace off also makes the field-mode argument irrelevant, and the copy is still made at VBlank from the
finished frame in B, so frame pacing and timing are unchanged.

## 4. Video memory layouts

Pages, inclusive ranges. "pool" is the texture pool, which also holds CLUTs (§5).

### Original

| Game | Layout |
|---|---|
| 9th | A 0..69 · B 70..219 · pool 220..511 |
| 10th–12th, 16th | A 0..69 · B 70..219 · pool 220..351 · Z 352..431 · 432..511 unused |
| 13th–15th, mode 0 | as 10th |
| 13th–15th, mode 1 (full-screen movie) | A 0..69 · B 70..219 · pool 220..369 · Z 384..463 |

### Patched, 448 lines (default)

| Game | Layout |
|---|---|
| 9th | A 0..139 (24-bit) · pool 140..351 · B 352..501 |
| 10th–16th | A 0..139 (24-bit) · Z 140..219 · pool 220..351 · B 352..501 |
| 13th–15th, mode 1 | A 0..69 (**16-bit** 640×448) · B 70..219 · pool 220..369 · Z 384..463 |

### Patched, 480 lines

| Game | Layout |
|---|---|
| 9th | A 0..149 · pool 150..351 · B 352..501 |
| 10th–16th | A 0..149 · Z 150..229 · pool 230..351 · B 352..501 |
| 13th–15th, mode 1 | A 0..79 (16-bit 640×480) · B 80..229 · pool 230..379 · Z 384..463 |

Why B goes to 352 and not somewhere else: on 10th and later the pool end is hard-coded at page 352 (§5), and
the area 352..511 only ever held Z (352..431) and nothing else in any dumped scene. B (150 pages) fits at
352..501, and Z (80 pages) fits in B's old place 140..219 right behind the larger A. The pool keeps its
original 220..351 range on 10th+, so texture behaviour is exactly the original.

## 5. The texture pool

All versions use the same allocator design:

- The pool **start** is computed at init from the sizes of the buffers in front of it (the arguments of the
  pool-init call: 640×224 24-bit + 640×480 24-bit = page 220).
- The pool **end**, which is also the top of the CLUT stack (CLUTs are allocated downwards from it), is a
  constant: 11264 blocks (page 352) on 10th+, 16384 (page 512) on 9th.
- Textures are re-uploaded every frame. When an upload does not fit, the allocator wraps: the renderer draws
  what has been uploaded so far, then continues with a new batch from the start of the pool. This also happens
  in the unpatched games (e.g. music select while scrolling fast, DP play with screen-capture effects) and costs
  only a little extra upload time.

Consequences for the patch:

- **10th+**: the pool range is unchanged in the 448 variant. The 480 variant moves the start 10 pages up by
  changing the first buffer size passed to pool init from 640×224 to 640×256 (70 → 80 pages).
- **9th** has no Z buffer and an open-ended pool (220..511). With A growing to 140 pages, the pool is moved to
  140..351 (start: 70+70 pages instead of 70+150; end/CLUT top: 16384→11264 blocks). That is 212 pages, more
  than the 132 that 10th+ have. Because of the wrap behaviour above this is safe; the music select screen
  (the heaviest case, ~3.5 MB of uploads per frame while scrolling) simply draws in more batches. This was
  confirmed on real hardware.

## 6. Places that reference the buffers directly

Moving B and Z is not enough on its own: some code builds GS register values with hard-coded addresses.
These were found from glitches, then searched for in all versions.

| What | Symptom when missed | Versions | Fix |
|---|---|---|---|
| Game init sets `ZBP` 352 (`daddiu reg, zero, 352`) | — (found statically) | 10th–16th | 352→140 (480: 150) |
| 3D renderer writes `ZBUF_1` straight into its packets (`lui 0x0a00` + `ori 0x160`) | mode select top half white (16th) | 13th–16th | `ori` imm 0x160→140/150 |
| Screen-capture effect reads B as a texture: `TEX0` with TBP 2240 (`ori reg, reg, 0x88c0`) | DP BGA overlay broken (13th) | 11th–16th | TBP 2240→11264 (`0x88c0`→`0xac00`) |
| 13th–15th mode-switch function sets Z page 352 for mode 0 | — | 13th–15th | 352→140/150 |

Constants 11264 (`0x2c00`) and 352 (`0x160`) also appear elsewhere in the ELFs as sound volumes, loop counts
and input codes; each hit was checked by its use, not patched blindly.

## 7. 13th–15th: movie mode and the hybrid routine

These three games have a VRAM mode switch (13th: function at `0x1600c0`, called by the movie player). Mode 1
is used for full-screen 640×480 movies (opening, ending): pool end page 370, Z at 384..463. A 24-bit A in
mode 1 would need 140 + 150 (B) + 150 (pool) + 80 (Z) = 520 pages, more than the 512 that exist, and mode 1
does use Z (overlay sprites with depth tests). So during mode 1 the output switches to a **16-bit** A
(640×448×16 = 70 pages, the original layout), with dithering.

The switch is done by a small routine (`_emit_layout_switch` + `hybrid_patches` in the script):

- **Location**: the libgraph DMA-timeout message block (`0x200` bytes of strings that are only printed after a
  GS hang). Its first 16 bytes hold the DIMX value; the routine follows (`msg + 0x10`, limit `msg + 0x1f0`).
- **Hooks**: the last instruction of each branch of the game's mode-switch function becomes `j routine`.
  The mode-0 branch's last store is replayed as the routine's first instruction.
- **What it does**: reads the game's current mode variable (`gp`-relative), then rewrites in RAM:
  `DISPFB.PSM` of both display envs, `FRAME_2.PSM` of both context-2 draw envs (A), `FRAME_1.FBP` of both
  context-1 draw envs (B: 352 or 70/80), `TEX0_2.TBP0` of the copy texture env (B), and the `DTHE` data word of
  both context-2 envs (on only in 16-bit mode). It then calls `FlushCache(0)` and resends the copy texture env
  with `sceGsPutDrawEnv`, and returns with the function's own epilogue. The double-buffer envs take effect at the
  next swap.
- **DIMX**: the games never set the dither matrix (it stays 0), so 16-bit output would band. The DIMX value
  (`0x6071243571603524`, the standard 4×4 ordered matrix) is stored in the message block, and
  `sceGsSetDefDrawEnv2` is changed to send `DIMX` in the slot where it sent `PRMODECONT` for context 2.
  This is harmless while `DTHE` is off.

## 8. The 480-line variant

B always contains 480 rendered lines; the original copied rows 16..463. The 480-line variant:

- copies rows 0..480 (texture V 16→0 and 464→480, sprite Y 1808..2288), with A 640×480 (150 pages) and
  `DISPLAY.DY` left at 35;
- moves everything behind A by 10 pages: Z 150, pool start +10 (pool-init size 224→256 lines; 9th: start
  page 150), and in 13th–15th movie mode B at 80 and the pool end 370→380;
- disables the in-game vertical screen-position option: the game shifts the copied window by `2 × offset`
  (`sll a1, v0/s0, 1`), and with all rows copied there is nothing left to shift into. That instruction becomes
  `a1 = 0`. Horizontal adjustment is not affected.

It is built from the 448 list by `to480()` plus the per-version sites in `EXTRA480`.

## 9. Real hardware vs. PCSX2

- **The real GS dithers 24-bit frame buffers when `DTHE` = 1**; PCSX2 only dithers 16-bit ones. An early build
  turned `DTHE` on permanently and looked clean in PCSX2 but showed a dither pattern on real hardware.
  `DTHE` is now on only in the 16-bit movie layout. Anything that touches `DTHE`/`DIMX` must be checked on hardware.
- **pnach `patch=1` rewrites the patched words every VSync.** A routine must never keep mutable state inside
  patched memory; under PCSX2 the state would be reset every frame (and an ISO patch would behave differently).
- PCSX2's game CRC is the XOR of all 32-bit words of the boot ELF; the pnach file names use it.
- Some PCSX2 presentation behaviour (e.g. the window's picture size jumping on 16th before a song) is not the
  game: the GS output registers were identical in both dumps.

## 10. How the script checks and patches an ISO

- The boot ELF is found from `SYSTEM.CNF` (`BOOT2`) in the ISO9660 root directory, and patched in place.
  Only 4-byte words that change are written; the ISO size and every other file stay the same.
- Each patch entry is `(address, original word, new word, comment)`. Before writing, every site must hold either
  its original word or a value of one of the variants, and the ELF size must match (`ELF_INFO`). The routine
  area has no single original word; instead the whole `0x200`-byte message block must match its CRC32
  (`bc537649`, identical in all nine ELFs) unless the routine is already there.
- Switching variants: words used by the other variant but not by the chosen one are restored to their
  originals (`plan_words`).
- `tools/build_release.py` checks each ISO against its Redump hashes, patches a temporary copy, makes the xdelta
  for both variants with `xdelta3 -e -9`, and decodes each one again to check that it reproduces the patched ISO.

## 11. Adding a version or chasing a glitch

### Finding the sites in another ELF

- **libgraph**: search for the bytes of `sceGsResetGraph` from a known ELF. All libgraph sites
  (`lib_patches_24`, `_dither_words`, the `sceGsPutDrawEnv` address) are fixed offsets from it.
  The message block is libgraph's DMA-timeout strings; compare its CRC32.
- **Game init**: the call sequence `sceGsResetGraph` → `sceGsSetDefDBuffDc` with `li a1,1` / `li a2,2` and a
  height of 224 (`0x240700e0`); later `sceGsSetDefDrawEnv2` calls with the same height (10th+); the
  `TEX1_2 = 0x60` store after `sceGsSetDefTexEnv`; the Z page 352.
- **Flip code**: the copy sprite constants `0x7900` / `0x8700` (top / bottom Y), the V constants 16 / 464, and the
  `sceGsSetHalfOffset` call whose field argument is set to 0.
- **Pool init**: the call that passes 640×224 and 640×480 buffer sizes, and the 11264 (or 16384) pool end.
- **Direct references**: `ori …, 0x88c0` (TEX0 of B), `ori …, 0x160` after `lui 0x0a00` (ZBUF), and any other
  `352`/`0x2c00`/`2240` immediates, checked one by one.

### GS dumps

PCSX2 can save a GS dump (`.gs`, zstd-compressed in recent versions): a header (`0xFFFFFFFF` magic), the GS
state, the 8 KB privileged register block (`SMODE2`, `DISPFB`, `DISPLAY`, …) and the recorded GIF packets.
Replaying the packets gives every register write and every texture upload, which is enough to:

- read the output setup (`SMODE2`, `DISPFB2`, `DISPLAY2`) and confirm 480p and the buffer formats;
- map which VRAM pages are written per frame (frame buffers, Z, texture uploads, CLUTs) and find overlaps;
- measure pool usage and count wraps (exclude CLUT uploads when measuring the pool).

The analysis scripts used for this project were one-off and are not included in the repository.

### Test checklist

Test each version in both variants, on real hardware where possible:

- boot, title, mode select (16th: 3D background), options (screen position adjust)
- music select, including scrolling fast through the list
- SP and DP play, with BGA and with DP's screen-capture overlays
- result screen
- 13th–15th: opening movie and ending movie (switch to and from the 16-bit layout), menus afterwards
- check for dither patterns on flat gradients (real hardware only)
