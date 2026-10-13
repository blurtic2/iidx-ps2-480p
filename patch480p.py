"""beatmania IIDX (PS2) 480p patch, 24-bit output.

Usage:
  py patch480p.py iso <game.iso> [<game.iso> ...] [--480]
        patch the game's executable in place inside the ISO (the game is detected from SYSTEM.CNF)
  py patch480p.py elf <SLPM_xxx.xx> <out file> [--480]
        write a patched copy of an executable
  py patch480p.py pnach [<out dir>]
        write PCSX2 .pnach files for all supported games
  default: 24-bit output, 448 lines (as the original game)
  --480:   24-bit output showing all 480 rendered lines
  Re-running on an already patched ISO switches it between the two variants. Nothing is written if the
  executable is not one of the supported ones (or has been modified by something else).

What the game does originally:
  draws the scene at 640x480 into buffer B (FBP 70), then each field shrinks rows 16..463 of it into a
  640x224 display buffer A (FBP 0) with a half-line offset, output as 480i FRAME mode.
What the patch does:
  480p output; A becomes 640x448 (or 640x480) PSMCT24 and B is copied 1:1 into it. To make room, B moves
  to page 352 and (10th+) the Z buffer moves into B's old place; see the plan comments below.
  (An earlier 16-bit plan kept the original VRAM layout with a PSMCT16 A; it was dropped for image quality.)
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ELF_BASE_VA, ELF_BASE_OFF = 0x00100000, 0x80

def lib_patches_24(reset_graph):
    """Plan 2a (10th-12th, 16th): keep A in 24-bit. Only B moves; no PSM/DIMX changes."""
    r = lambda va9: va9 - 0x100330 + reset_graph
    return [
        (r(0x101ab8), 0x30a501ff, 0x24050160, 'sceGsSetDefDBuffDc: draw buffer B -> FBP 352 (pages 352..501, old Z area + unused)'),
        (r(0x100900), 0x24840023, 0x24840033, 'sceGsSetDefDispEnv 480p: DY 35 -> 51 (center 448 lines)'),
    ]

def oldb_tex(va, orig):
    """Screen-capture effects (e.g. BGA overlays in DP) read the draw buffer B as a texture with a hard-coded
    TEX0 (TBP 2240 = page 70, TBW 10, PSM 24). B lives at page 352 in the 24-bit layout -> TBP 11264."""
    return [(va, orig, (orig & 0xffff0000) | 0xac00, 'effect TEX0 reading draw buffer B: TBP 2240 -> 11264')]

def z_patch(va, reg):
    """The game's hard-coded Z buffer page 352 -> 140 (old B area, 640x480 PSMZ16S = 80 pages: 140..219)."""
    return [(va, 0x64000160 | (reg << 16), 0x6400008c | (reg << 16), 'game init: Z buffer ZBP 352 -> 140')]

def _emit_layout_switch(a, db, texenv, packet, flushcache, put_draw_env, b16=70):
    """t0 = 0 -> 24-bit layout (B at 352, A PSMCT24); t0 != 0 -> 16-bit layout (B at 70, A PSMCT16).
    Rewrites the double-buffer env words in RAM (used from the next swap) and resends the B->A texture env."""
    from mipsasm import hi_lo
    a.addiu('t1', 'zero', 352)
    a.beq('t0', 'zero', 'ls24')
    a.addiu('t2', 'zero', 1)
    a.addiu('t1', 'zero', b16)
    a.addiu('t2', 'zero', 2)
    a.label('ls24')
    def rmw(addr, mask_reg, val_reg):
        hi, lo = hi_lo(addr)
        a.lui('t3', hi)
        a.lw('t4', lo, 't3'); a.and_('t4', 't4', mask_reg); a.or_('t4', 't4', val_reg); a.sw('t4', lo, 't3')
    a.lui('t5', 0xfff0); a.ori('t5', 't5', 0x7fff); a.sll('t6', 't2', 15)       # DISPFB.PSM
    rmw(db + 0x10, 't5', 't6'); rmw(db + 0x38, 't5', 't6')
    a.lui('t5', 0xc0ff); a.ori('t5', 't5', 0xffff); a.sll('t6', 't2', 24)       # ctx2 FRAME.PSM (A)
    rmw(db + 0xe0, 't5', 't6'); rmw(db + 0x250, 't5', 't6')
    a.addiu('t5', 'zero', -512)                                                  # ctx1 FRAME.FBP (B)
    rmw(db + 0x60, 't5', 't1'); rmw(db + 0x1d0, 't5', 't1')
    a.addiu('t5', 'zero', -16384); a.sll('t6', 't1', 5)                         # copy TEX0_2.TBP0 (B)
    rmw(texenv + 0x20, 't5', 't6')
    # DTHE (sent with the ctx2 env, after ctx1's): on only in the 16-bit layout. The real GS dithers
    # 24-bit frame buffers too (PCSX2 does not), so it must be off in the 24-bit layout.
    a.addiu('t7', 't2', -1)
    for addr in (db + 0xe0 + 0x60, db + 0x250 + 0x60):
        hi, lo = hi_lo(addr)
        a.lui('t3', hi); a.sw('t7', lo, 't3')
    a.jal(flushcache); a.daddu('a0', 'zero', 'zero')                             # write back D-cache
    hi, lo = hi_lo(packet)
    a.lui('a0', hi); a.jal(put_draw_env); a.addiu('a0', 'a0', lo)                # resend the texture env

def _cave_words(a, dimx_va, note):
    words = a.finish()
    assert a.origin + 4 * len(words) <= dimx_va + 0x1f0, 'cave overflow (%d words)' % len(words)
    return [(a.origin + 4 * i, None, w, note) for i, w in enumerate(words)]

def _dither_words(r, dimx_va):
    """DIMX in the ctx2 env (harmless while DTHE is off). DTHE itself is switched by the layout routine."""
    from mipsasm import hi_lo
    return [
        (dimx_va, 0x47656373, 0x71603524, 'DIMX value low word (16-bit mode dithering)'),
        (dimx_va + 4, 0x66654473, 0x60712435, 'DIMX value high word'),
        (r(0x101564), 0xde030040, 0x3c030000 | hi_lo(dimx_va)[0], 'sceGsSetDefDrawEnv2: v1 = upper half of DIMX address'),
        (r(0x101584), 0x006b1825, 0xdc630000 | (hi_lo(dimx_va)[1] & 0xffff), 'sceGsSetDefDrawEnv2: v1 = DIMX value'),
        (r(0x101590), 0x2408001a, 0x24080044, 'sceGsSetDefDrawEnv2: register PRMODECONT(0x1a) -> DIMX(0x44)'),
        # earlier builds forced DTHE on here (0x24020002); keep/restore the original instruction
        (r(0x1015a4), 0x32820002, 0x32820002, 'sceGsSetDefDrawEnv2: DTHE from PSM (original)'),
    ]

LEGACY_WORDS = {0x24020002}  # values written by earlier builds that a re-patch may find and overwrite

# Plan 2a for 9th. 9th has no Z buffer and its texture pool normally runs from page 220 to the end of VRAM,
# but its allocator (same as 10th's) wraps when the pool is full and the renderer then uploads and draws the
# rest in another batch (verified on the music select screen). So the pool can simply shrink:
#   A 640x448x24 0..139 | pool 140..351 (212 pages, 10th+ only have 132) | B 352..501
POOL24_9TH = [
    (0x0015de60, 0x240901e0, 0x240900e0, 'texture pool init: start = 70+70 pages (140) instead of 70+150 (220)'),
    (0x0015e48c, 0x24034000, 0x24032c00, 'texture pool init: CLUT top / pool end 512 -> 352 pages'),
    (0x0015e564, 0x24044000, 0x24042c00, 'texture pool init: CLUT top / pool end 512 -> 352 pages'),
]

def hybrid_patches(reset_graph, dimx_va, db, texenv, packet, flushcache, modevar_gp,
                   hook1, hook0, z_consts, zbuf3d, b16=70):
    """Plan 2b (13th-15th): 24-bit layout normally; the game's own VRAM mode switch (mode 1 = full-screen
    640x480 movie, which needs the texture pool up to page 370 and Z at 384) also flips the display to the
    plan-1 16-bit layout. The switch routine lives over the libgraph DMA-timeout message strings.
      mode 0: A 640x448x24 0..139 | Z 140..219 | pool 220..351 | B 352..501
      mode 1: A 640x448x16 0..69  | B 70..219  | pool 220..369 | Z 384..463 (game's original mode-1 values)
    hook1 / hook0 = (address, original word) of the last instruction of each branch of the mode-switch
    function; both become 'j cave' (hook1 keeps its delay-slot store, hook0's store is replayed by the cave)."""
    from mipsasm import Asm, j_word
    r = lambda va9: va9 - 0x100330 + reset_graph
    cave = dimx_va + 0x10
    a = Asm(cave)
    a.word(hook0[1])                              # replay the mode-0 branch's last store
    a.lw('t0', modevar_gp, 'gp')                  # current mode (0/1), already updated by the game
    _emit_layout_switch(a, db, texenv, packet, flushcache, r(0x100dd8), b16)
    a.ld('ra', 0, 'sp'); a.jr('ra'); a.addiu('sp', 'sp', 16)                     # mode-switch epilogue
    p = _cave_words(a, dimx_va, 'hybrid mode-switch routine (over libgraph DMA-timeout messages)')
    p += [
        (hook1[0], hook1[1], j_word(cave), 'mode switch, mode-1 branch: -> hybrid routine'),
        (hook0[0], hook0[1], j_word(cave), 'mode switch, mode-0 branch: -> hybrid routine (store replayed there)'),
    ] + _dither_words(r, dimx_va)
    p += [(va, old, (old & 0xffff0000) | 140, 'Z buffer ZBP 352 -> 140 (mode 0)') for va, old in z_consts]
    p += [(va, old, (old & 0xffff0000) | 0x8c, '3D packet ZBUF_1: ZBP 352 -> 140') for va, old in zbuf3d]
    return p

def game_patches(reset_a1, reset_a2, dbuf_h, drawenv2_h, copy_top, copy_bottom, tex1, half_a3):
    """Game-side words for 10th and later (same code shape, different addresses/registers).
    copy_top / copy_bottom: [(address, original word)] of the 'li reg,0x7900' / 'li reg,0x8700' in the flip code."""
    p = [
        (reset_a1, 0x24050001, 0x24050000, 'sceGsResetGraph: interlace 1 -> 0 (progressive), ffmode follows a1 -> 0'),
        (reset_a2, 0x24060002, 0x24060050, 'sceGsResetGraph: omode NTSC(2) -> 480p(0x50)'),
        (dbuf_h, 0x240700e0, 0x240701c0, 'sceGsSetDefDBuffDc: height 224 -> 448 (display buffer A, DISPLAY DH)'),
    ]
    # the game re-initialises both ctx2 draw envs itself (without Z) after sceGsSetDefDBuffDc
    p += [(a, 0x240700e0, 0x240701c0, 'sceGsSetDefDrawEnv2 (ctx2): height 224 -> 448') for a in drawenv2_h]
    p += [(a, w, (w & 0xffff0000) | 0x7200, 'B->A copy sprite top Y 1936 -> 1824') for a, w in copy_top]
    p += [(a, w, (w & 0xffff0000) | 0x8e00, 'B->A copy sprite bottom Y 2160 -> 2272 (448 lines, 1:1)') for a, w in copy_bottom]
    p += [
        (tex1, 0x24030060, 0x24030000, 'B->A copy TEX1_2 0x60 (bilinear) -> 0 (nearest)'),
        (half_a3[0], half_a3[1], 0x0000382d, 'flip: sceGsSetHalfOffset field arg -> 0 (no per-field half-line offset)'),
    ]
    return p

V1, V0 = 0x24037900, 0x24027900  # li v1/v0,0x7900
O_V0, O_V1, O_A0 = 0x34028700, 0x34038700, 0x34048700  # ori v0/v1/a0,zero,0x8700

GAME9 = [
    (0x0015d9a0, 0x24050001, 0x24050000, 'sceGsResetGraph: interlace 1 -> 0 (progressive), ffmode follows a1 -> 0'),
    (0x0015d9a8, 0x24060002, 0x24060050, 'sceGsResetGraph: omode NTSC(2) -> 480p(0x50)'),
    (0x0015d9c4, 0x240700e0, 0x240701c0, 'sceGsSetDefDBuffDc: height 224 -> 448 (display buffer A, ctx2 scissor/offset, DISPLAY DH)'),
    (0x0015d884, 0x24037900, 0x24037200, 'per-frame B->A copy sprite top Y 1936 -> 1824'),
    (0x0015d8ac, 0x34028700, 0x34028e00, 'per-frame B->A copy sprite bottom Y 2160 -> 2272 (448 lines, 1:1)'),
    (0x0015ddd4, 0x24037900, 0x24037200, 'init B->A copy sprite top Y'),
    (0x0015ddfc, 0x34028700, 0x34028e00, 'init B->A copy sprite bottom Y'),
    # The B->A copy texture env (TEX1_2) was bilinear: right for the original 2:1 shrink, but a 1:1 copy
    # with bilinear samples on texel edges and blurs every pixel half-and-half. Point sampling = exact copy.
    # (the game overwrites the TEX1_2 word right after sceGsSetDefTexEnv, so patch that store)
    (0x0015dd28, 0x24030060, 0x24030000, 'B->A copy TEX1_2 0x60 (bilinear) -> 0 (nearest)'),
    (0x00138f7c, 0x8784840c, 0x0000202d, 'main loop: field flag -> 0 (no per-field half-line offset)'),
]
GAME10 = [
    (0x00163204, 0x24050001, 0x24050000, 'sceGsResetGraph: interlace 1 -> 0 (progressive), ffmode follows a1 -> 0'),
    (0x00163210, 0x24060002, 0x24060050, 'sceGsResetGraph: omode NTSC(2) -> 480p(0x50)'),
    (0x0016322c, 0x240700e0, 0x240701c0, 'sceGsSetDefDBuffDc: height 224 -> 448 (display buffer A, DISPLAY DH)'),
    # 10th re-initialises both ctx2 draw envs itself (without Z) after sceGsSetDefDBuffDc
    (0x00163358, 0x240700e0, 0x240701c0, 'sceGsSetDefDrawEnv2 (draw0 ctx2): height 224 -> 448'),
    (0x0016338c, 0x240700e0, 0x240701c0, 'sceGsSetDefDrawEnv2 (draw1 ctx2): height 224 -> 448'),
    (0x0016313c, 0x24037900, 0x24037200, 'per-frame B->A copy sprite top Y 1936 -> 1824'),
    (0x00163164, 0x34028700, 0x34028e00, 'per-frame B->A copy sprite bottom Y 2160 -> 2272 (448 lines, 1:1)'),
    (0x0016379c, 0x24037900, 0x24037200, 'init B->A copy sprite top Y'),
    (0x001637c4, 0x34028700, 0x34028e00, 'init B->A copy sprite bottom Y'),
    (0x001636f0, 0x24030060, 0x24030000, 'B->A copy TEX1_2 0x60 (bilinear) -> 0 (nearest)'),
    (0x001631b8, 0x0220382d, 0x0000382d, 'flip: sceGsSetHalfOffset field arg -> 0 (no per-field half-line offset)'),
]
GAME11 = game_patches(0x1674d4, 0x1674e0, 0x1674fc, [0x167628, 0x16765c],
                      [(0x16740c, V1), (0x167a6c, V1)], [(0x167434, O_V0), (0x167a94, O_V0)],
                      0x1679c0, (0x167488, 0x0220382d))
GAME12 = game_patches(0x15d334, 0x15d340, 0x15d35c, [0x15d488, 0x15d4bc],
                      [(0x15d268, V1), (0x15d2e4, V1)], [(0x15d290, O_V0), (0x15d300, O_A0)],
                      0x15d81c, (0x15d18c, 0x0200382d))
GAME13 = game_patches(0x15fb54, 0x15fb60, 0x15fb7c, [0x15fc7c, 0x15fc90],
                      [(0x15fa18, V1), (0x15fa28, V1), (0x15fac0, V1)], [(0x15fa44, O_A0), (0x15fae8, O_V0)],
                      0x15ff5c, (0x15f9ac, 0x0200382d))
GAME14 = game_patches(0x138b04, 0x138b10, 0x138b2c, [0x138c2c, 0x138c40],
                      [(0x1389d0, V0), (0x1389e0, V0), (0x138a78, V1)], [(0x1389fc, O_V1), (0x138aa0, O_V0)],
                      0x138f0c, (0x13892c, 0x0200382d))
GAME15 = game_patches(0x138bd4, 0x138be0, 0x138bfc, [0x138cfc, 0x138d10],
                      [(0x138aa0, V0), (0x138ab0, V0), (0x138b48, V1)], [(0x138acc, O_V1), (0x138b70, O_V0)],
                      0x138fdc, (0x1389fc, 0x0200382d))
GAME16 = game_patches(0x139df4, 0x139e00, 0x139e1c, [0x139eac, 0x139f30],
                      [(0x139cec, V1), (0x139da0, V0)], [(0x139d14, O_V0), (0x139dbc, O_V1)],
                      0x13a1fc, (0x139c0c, 0x0200382d))

# 'patches24'  = plan 2a: 24-bit display buffer by swapping B and the Z buffer (10th-12th, 16th; 9th see POOL24_9TH):
#     A 640x448x24 pages 0..139 | Z 140..219 | texture pool 220..351 (end hard-coded at 352) | B 352..501
#                (13th-15th: plan 2b hybrid, see hybrid_patches)
# 'patches480' = the same with all 480 lines shown (built from patches24 by to480 below)
VERSIONS = {
    'SLPM_659.46': dict(
        title='beatmania IIDX 9th style', serial='SLPM-65946', crc='519805E0',
        patches24=GAME9 + lib_patches_24(0x100330) + POOL24_9TH),
    'SLPM_661.80': dict(
        title='beatmania IIDX 10th style', serial='SLPM-66180', crc='B308CA2F',
        patches24=GAME10 + lib_patches_24(0x1002f0) + z_patch(0x16325c, 7)),
    'SLPM_664.26': dict(
        title='beatmania IIDX 11th style IIDX RED', serial='SLPM-66426', crc='98CEF49B',
        patches24=GAME11 + lib_patches_24(0x100310) + z_patch(0x16752c, 7) + oldb_tex(0x16488c, 0x346f88c0)),
    'SLPM_666.21': dict(
        title='beatmania IIDX 12th style HAPPY SKY', serial='SLPM-66621', crc='6D8DB060',
        patches24=GAME12 + lib_patches_24(0x1002f0) + z_patch(0x15d38c, 7) + oldb_tex(0x15a83c, 0x346f88c0)),
    'SLPM_668.28': dict(
        title='beatmania IIDX 13th style DistorteD', serial='SLPM-66828', crc='26BC121E',
        patches24=GAME13 + lib_patches_24(0x100310) + hybrid_patches(
            0x100310, 0x232590, db=0x42b8a0, texenv=0x42b860, packet=0x42b800, flushcache=0x10ed20,
            modevar_gp=-30836, hook1=(0x160130, 0x1000001d), hook0=(0x1601a4, 0xa464b910),
            z_consts=[(0x15fbd8, 0x64060160), (0x160178, 0x64080160)],
            zbuf3d=[(0x15c5f4, 0x34420160), (0x15c614, 0x34630160)]) + oldb_tex(0x15d440, 0x346a88c0)),
    'SLPM_669.95': dict(
        title='beatmania IIDX 14th style GOLD', serial='SLPM-66995', crc='40EB926F',
        patches24=GAME14 + lib_patches_24(0x1004f0) + hybrid_patches(
            0x1004f0, 0x23f210, db=0x380180, texenv=0x380510, packet=0x3804b0, flushcache=0x10eee0,
            modevar_gp=-31636, hook1=(0x1390e0, 0x1000001d), hook0=(0x139154, 0xa46401f0),
            z_consts=[(0x138b88, 0x64060160), (0x139128, 0x64080160)],
            zbuf3d=[(0x135a54, 0x34420160), (0x135a74, 0x34630160)]) + oldb_tex(0x136700, 0x346a88c0)),
    'SLPM_551.17': dict(
        title='beatmania IIDX 15th style DJ TROOPERS', serial='SLPM-55117', crc='1393B807',
        patches24=GAME15 + lib_patches_24(0x1004f0) + hybrid_patches(
            0x1004f0, 0x258110, db=0x39a580, texenv=0x39a910, packet=0x39a8b0, flushcache=0x10eee0,
            modevar_gp=-31764, hook1=(0x1391b0, 0x1000001d), hook0=(0x139224, 0xa464a5f0),
            z_consts=[(0x138c58, 0x64060160), (0x1391f8, 0x64080160)],
            zbuf3d=[(0x135af4, 0x34420160), (0x135b14, 0x34630160)]) + oldb_tex(0x1367a0, 0x346a88c0)),
    'SLPM_552.21': dict(
        title='beatmania IIDX 16th style EMPRESS', serial='SLPM-55221', crc='44111A43',
        patches24=GAME16 + lib_patches_24(0x1004f0) + z_patch(0x139e4c, 7) + oldb_tex(0x13794c, 0x346f88c0) + [
            # 16th's 3D renderer (fn 0x1369a0) also writes ZBUF_1 = ZBP 352 straight into its packets
            (0x00136b44, 0x34420160, 0x3442008c, '3D packet ZBUF_1: ZBP 352 -> 140 (ZMSK=1 branch)'),
            (0x00136b64, 0x34630160, 0x3463008c, '3D packet ZBUF_1: ZBP 352 -> 140'),
        ]),
    # Disc 2 of 16th. Its own ELF, but every game-side site sits at the same address as on the EMPRESS disc;
    # only the libgraph message string (DIMX / unused here) moved.
    'SLPM_552.22': dict(
        title='beatmania IIDX 16 EMPRESS + PREMIUM BEST (Premium Best disc)', serial='SLPM-55222', crc='57E9E985',
        patches24=GAME16 + lib_patches_24(0x1004f0) + z_patch(0x139e4c, 7) + oldb_tex(0x13794c, 0x346f88c0) + [
            (0x00136b44, 0x34420160, 0x3442008c, '3D packet ZBUF_1: ZBP 352 -> 140 (ZMSK=1 branch)'),
            (0x00136b64, 0x34630160, 0x3463008c, '3D packet ZBUF_1: ZBP 352 -> 140'),
        ]),
}

# ---- 480-line variant ('patches480', test group) ---------------------------------------------------------
# The game draws a full 640x480 frame into B but copies only rows 16..463. This variant copies all 480 rows
# into a 640x480 A and shows 480 lines in 480p. A grows by 10 pages, so everything behind it shifts by 10:
#   24-bit (9th):      A 0..149 | pool 150..351 | B 352..501
#   24-bit (10th+):    A 0..149 | Z 150..229 | pool 230..351 | B 352..501
#   16-bit (13th-15th movie mode): A 0..79 | B 80..229 | pool 230..379 | Z 384..463
# The game's vertical screen-position adjust shifts the copied window; with all 480 rows copied there is no
# room for it, so it is ignored.
SLL_V0, SLL_S0 = 0x00022840, 0x00102840          # sll a1,v0,1 / sll a1,s0,1 (position adjust * 2)
EXTRA480 = {  # version: (adjust sll sites, V=16 sites, V=464 sites, pool-init a2 sites, mode-1 pool-end sites)
    'SLPM_659.46': ([(0x15d840, SLL_V0), (0x15dd90, SLL_V0)], [0x15d844, 0x15dd94], [0x15d854, 0x15dda4], [], []),
    'SLPM_661.80': ([(0x1630f8, SLL_V0), (0x163758, SLL_V0)], [0x1630fc, 0x16375c], [0x16310c, 0x16376c], [0x163818], []),
    'SLPM_664.26': ([(0x1673c8, SLL_V0), (0x167a28, SLL_V0)], [0x1673cc, 0x167a2c], [0x1673dc, 0x167a3c], [0x167ae8], []),
    'SLPM_666.21': ([(0x15d224, SLL_V0)], [0x15d228], [0x15d238], [0x15d880], []),
    'SLPM_668.28': ([(0x15fa7c, SLL_V0)], [0x15fa80], [0x15fa90], [0x1600e8, 0x15ffc0, 0x160154], [0x16073c, 0x160830]),
    'SLPM_669.95': ([(0x138a34, SLL_S0)], [0x138a38], [0x138a48], [0x139098, 0x138f70, 0x139104], [0x1395fc, 0x1396f0]),
    'SLPM_551.17': ([(0x138b04, SLL_S0)], [0x138b08], [0x138b18], [0x139168, 0x139040, 0x1391d4], [0x1396cc, 0x1397c0]),
    'SLPM_552.21': ([(0x139ca8, SLL_S0)], [0x139cac], [0x139cbc], [0x13a260], []),
    'SLPM_552.22': ([(0x139ca8, SLL_S0)], [0x139cac], [0x139cbc], [0x13a260], []),
}

def to480(name, p24):
    out = []
    for va, old, new, note in p24:
        if 'DY 35 -> 51' in note:
            continue                                                  # 480 lines fill 480p: keep DY 35
        if 'copy sprite top Y' in note:
            new, note = (new & 0xffff0000) | 0x7100, 'B->A copy sprite top Y 1936 -> 1808 (480 lines)'
        elif 'copy sprite bottom Y' in note:
            new, note = (new & 0xffff0000) | 0x8f00, 'B->A copy sprite bottom Y 2160 -> 2288 (480 lines)'
        elif new == 0x240701c0:
            new, note = 0x240701e0, note.replace('448', '480')
        elif 'ZBP 352 -> 140' in note:
            new, note = (new & 0xffff0000) | 150, note.replace('140', '150')
        elif 'start = 70+70' in note:
            new, note = 0x24090100, 'texture pool init: start = 70+80 pages (150) instead of 70+150 (220)'
        elif 'routine' in note and new == 0x24090046:
            new = 0x24090050                                           # 16-bit layout: B at 80
        out.append((va, old, new, note))
    adj, v16, v464, a2, m1end = EXTRA480[name]
    out += [(va, w, 0x0000282d, 'copy: ignore vertical screen-position adjust (no room with 480 rows)') for va, w in adj]
    out += [(va, 0x24020010, 0x24020000, 'B->A copy V top 16 -> 0') for va in v16]
    out += [(va, 0x240301d0, 0x240301e0, 'B->A copy V bottom 464 -> 480') for va in v464]
    out += [(va, 0x240600e0, 0x24060100, 'texture pool init: first buffer 640x224 -> 640x256 (start +10 pages)') for va in a2]
    out += [(va, 0x24032e40, 0x24032f80, 'movie-mode texture pool end 370 -> 380 pages') for va in m1end]
    return out

for _name, _v in VERSIONS.items():
    if 'patches24' in _v:
        _v['patches480'] = to480(_name, _v['patches24'])

PLAN_KEYS = ('patches24', 'patches480')

# Per-version facts needed to work from an ISO alone: ELF size and the libgraph message block address.
# The 0x200-byte libgraph message block (DMA-timeout strings; DIMX + the hybrid routine are written over it)
# is byte-identical in every supported ELF, so a CRC of it stands in for the original words of the cave.
ELF_INFO = {  # name: (ELF size, libgraph message block address)
    'SLPM_659.46': (907952, 0x1bed10),  'SLPM_661.80': (1204656, 0x209310), 'SLPM_664.26': (1940144, 0x2bfa90),
    'SLPM_666.21': (1419056, 0x213690), 'SLPM_668.28': (1846064, 0x232590), 'SLPM_669.95': (1967792, 0x23f210),
    'SLPM_551.17': (2075312, 0x258110), 'SLPM_552.21': (1757744, 0x261910), 'SLPM_552.22': (1777968, 0x266b10),
}
MSG_BLOCK_SIZE, MSG_BLOCK_CRC32 = 0x200, 0xbc537649

def _word(d, va):
    return struct.unpack_from('<I', d, va - ELF_BASE_VA + ELF_BASE_OFF)[0]

def find_in_iso(iso, name):
    """Return (byte offset, size) of a file in the ISO9660 root directory."""
    with open(iso, 'rb') as f:
        f.seek(16 * 2048)
        pvd = f.read(2048)
        if pvd[1:6] != b'CD001':
            sys.exit('not an ISO9660 image')
        root = pvd[156:156 + 34]
        lba, size = struct.unpack_from('<I', root, 2)[0], struct.unpack_from('<I', root, 10)[0]
        f.seek(lba * 2048)
        dirdata = f.read(size)
    p = 0
    while p < len(dirdata):
        n = dirdata[p]
        if n == 0:
            p = (p // 2048 + 1) * 2048
            continue
        flen = dirdata[p + 32]
        fname = dirdata[p + 33:p + 33 + flen].decode('latin1').split(';')[0]
        if fname.upper() == name.upper():
            return struct.unpack_from('<I', dirdata, p + 2)[0] * 2048, struct.unpack_from('<I', dirdata, p + 10)[0]
        p += n
    sys.exit('%s not found in ISO root' % name)

def boot_elf_name(iso):
    """Name of the boot ELF from the ISO's SYSTEM.CNF (BOOT2 = cdrom0:\\NAME;1)."""
    import re
    off, size = find_in_iso(iso, 'SYSTEM.CNF')
    with open(iso, 'rb') as f:
        f.seek(off)
        cnf = f.read(size).decode('latin1')
    m = re.search(r'BOOT2\s*=\s*cdrom0:\\([^;\r\n]+)', cnf)
    if not m:
        sys.exit('no BOOT2 line in SYSTEM.CNF')
    return m.group(1).upper()

def plan_words(v, plan_key):
    """Full word list for one plan, including words of the other plan restored to their originals,
    so an image patched with one plan can be switched to the other."""
    chosen = v[plan_key]
    used = {va for va, _, _, _ in chosen}
    restore = []
    for key in PLAN_KEYS:
        for va, old, new, note in v.get(key, []):
            if va not in used and old is not None:
                used.add(va)
                restore.append((va, old, old, 'restore original (%s)' % note))
    return chosen + restore

def verify(d, name, v):
    """True if d is this version's ELF, unpatched or patched by any variant of this patch."""
    size, msg_va = ELF_INFO[name]
    if len(d) != size:
        print('ELF size %d, expected %d' % (len(d), size)); return False
    allowed, cave = {}, {}
    for key in PLAN_KEYS:
        for va, old, new, note in v.get(key, []):
            if old is None:                       # hybrid routine word (code cave)
                cave.setdefault(va, set()).add(new)
                continue
            allowed.setdefault(va, {old}).add(new)
            if old == new:
                allowed[va] |= LEGACY_WORDS
    if cave:
        first = min(cave)
        if _word(d, first) in cave[first]:
            pass                                  # our routine (any build) is there
        else:
            o = msg_va - ELF_BASE_VA + ELF_BASE_OFF
            import zlib
            if zlib.crc32(bytes(d[o:o + MSG_BLOCK_SIZE])) != MSG_BLOCK_CRC32:
                print('libgraph message block (code cave) is not original'); return False
    ok = True
    for va, vals in allowed.items():
        cur = _word(d, va)
        if cur not in vals:
            print('MISMATCH %08x: %08x (expected one of %s)' % (va, cur, ', '.join('%08x' % x for x in sorted(vals)))); ok = False
    return ok

def apply(d, words):
    for va, old, new, note in words:
        struct.pack_into('<I', d, va - ELF_BASE_VA + ELF_BASE_OFF, new)

def write_pnach(name, v, out_dir='.'):
    out = os.path.join(out_dir, '%s_%s.pnach' % (v['serial'], v['crc']))
    groups = [('480p', 'Native 480p, 24-bit output, 448 lines (as the original). Enable only one 480p group.', v['patches24']),
              ('480p 480 lines', 'Native 480p, 24-bit output, all 480 rendered lines (no top/bottom crop). Enable only one 480p group.', v['patches480'])]
    with open(out, 'w', encoding='utf-8') as f:
        f.write('gametitle=%s (%s)\n' % (v['title'], v['serial']))
        for title, desc, plist in groups:
            f.write('\n[%s]\nauthor=iidx-ps2-480p\ndescription=%s\n' % (title, desc))
            for va, old, new, note in plist:
                f.write('// %s\npatch=1,EE,%08x,word,%08x\n' % (note, va, new))
    return out

def patch_iso(iso, plan_key):
    """Patch the boot ELF in place inside an ISO9660 image (same size, only changed words are written)."""
    name = boot_elf_name(iso)
    if name not in VERSIONS:
        sys.exit('unsupported game: boot ELF %s (supported: %s)' % (name, ', '.join(VERSIONS)))
    v = VERSIONS[name]
    off, size = find_in_iso(iso, name)
    with open(iso, 'r+b') as f:
        f.seek(off)
        img = bytearray(f.read(size))
        if not verify(img, name, v):
            sys.exit('%s inside the ISO does not match the expected executable; nothing was written' % name)
        target = bytearray(img)
        apply(target, plan_words(v, plan_key))
        for i in range(0, size, 4):
            if target[i:i + 4] != img[i:i + 4]:
                f.seek(off + i)
                f.write(target[i:i + 4])
        f.seek(off)
        if f.read(size) != bytes(target):
            sys.exit('verify failed')
    print('patched %s: %s, %s (%d words)' % (os.path.basename(iso), v['title'],
          '480 lines' if plan_key == 'patches480' else '448 lines', len(v[plan_key])))

def main():
    flags = {a for a in sys.argv[1:] if a.startswith('--')}
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    plan_key = 'patches480' if '--480' in flags else 'patches24'
    if not args:
        sys.exit(__doc__)
    mode = args[0]
    if mode == 'iso' and len(args) >= 2:
        for iso in args[1:]:
            patch_iso(iso, plan_key)
    elif mode == 'elf' and len(args) == 3:
        name = os.path.basename(args[1]).upper()
        if name not in VERSIONS:
            sys.exit('unknown ELF %s (supported: %s)' % (name, ', '.join(VERSIONS)))
        v = VERSIONS[name]
        d = bytearray(open(args[1], 'rb').read())
        if not verify(d, name, v):
            sys.exit('ELF does not match; nothing was written')
        apply(d, plan_words(v, plan_key))
        open(args[2], 'wb').write(d)
        print('wrote', args[2])
    elif mode == 'pnach':
        out_dir = args[1] if len(args) > 1 else '.'
        os.makedirs(out_dir, exist_ok=True)
        for name, v in VERSIONS.items():
            print('wrote', write_pnach(name, v, out_dir))
    else:
        sys.exit(__doc__)

if __name__ == '__main__':
    main()
