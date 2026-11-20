# skip: plan which extended-bracket frames are reachable, and shoot only those (E-500 fw 1.3).
# Design: notes/2026-11-18-skip-unreachable-design.md. Placed in free space by build.py.
#
# Frame j of an extended choice (n frames, LO frames below metered) has offset (j - LO) * step.
# A plan (F = first frame, C = count) is computed from each camera exposure prep while idle,
# latched by the trigger at full press, and used for the burst:
#   bkt_offset2   offset of logical frame idx = (F + idx - LO) * step        (stock n: stock formula)
#   counter_next  frame counter wraps at C                                   (stock n: wraps at n)
#   n_eff         app_seq_limit's frame count = C, so limit = C - #7 (at least 1) (stock n: #6)
#   plan_hook     after ae_calc: plan, re-run AE once if F changed, then store the AE outputs
#                 (reached from cam_capture_prep through plan_tramp)
#
# RAM (alignment padding in the trigger globals, see the design note):
        .equ    WP,    0xb00f675a       # u16 working plan F | C << 8, written only by plan_hook (camera task)
        .equ    FL,    0xb00f6729       # u8 latched F       \  written only by n_eff (trigger task),
        .equ    CL,    0xb00f6737       # u8 latched C        > LT last, so a reader that sees LT == 1
        .equ    LT,    0xb00f6753       # u8 latch valid     /  also sees FL and CL
        .equ    STATE, 0xb00f671c       # u16 trigger state: 2 PICTURE, 3 TAKE_READY2
# Camera-side store contexts and keys (as the stock camera code reads them):
        .equ    CTX6,  0xb0164500       # #6 frames      key 0x8281
        .equ    CTX7,  0xb0164504       # #7 counter     key 0x8291
        .equ    CTX8,  0xb0164508       # #8 step        key 0x80EA
        .equ    CTX88, 0xb01644fc       # #88 AE BKT on  key 0x85F1
# setting_get_addr, store_get_addr, expo_build_addr, ae_calc_addr and ae_store_addr come
# from `ld --defsym`. The preset table comes from presets.inc (build.py).

# LIMITS a, b, c, d: a0 = out[a] + out[b] (min), a1 = out[c] + out[d] (max), as s16 sums; then scan.
        .macro  LIMITS a, b, c, d
        movhu   (\a,a2),d0
        exth    d0
        movhu   (\b,a2),d1
        exth    d1
        add     d1,d0
        mov     d0,a0
        movhu   (\c,a2),d0
        exth    d0
        movhu   (\d,a2),d1
        exth    d1
        add     d1,d0
        mov     d0,a1
        jmp     ph_scan
        .endm

        .mn10300                        # base MN10300 only: AM33 extensions are an error
        .text
ext_table:                              # {n, LO} pairs, terminated by n == 0
        .include "presets.inc"          # written by build.py: one `.byte n, LO` per preset
        .byte   0, 0

# ext_lo: d0 = n -> d0 = LO, or -1 if n is not an extended choice. Changes d1, a0.
# call ext_lo,[],4
ext_lo:
        extbu   d0
        mov     ext_table,a0
el_loop:
        movbu   (a0),d1
        cmp     0,d1
        beq     el_no
        cmp     d0,d1
        beq     el_yes
        add     2,a0
        bra     el_loop
el_yes:
        movbu   (1,a0),d0
        ret     [],4
el_no:
        mov     -1,d0
        ret     [],4

# wp_get / latched_get: d0 = n -> d0 = F, d1 = C, validated (C >= 1 and F + C <= n,
# otherwise F = 0, C = n). latched_get prefers the latched plan when LT == 1.
# call wp_get,[d2,d3],12 (or latched_get)
latched_get:
        extbu   d0
        mov     d0,d3
        movbu   (LT),d1
        cmp     1,d1
        bne     lg_wp
        movbu   (FL),d2
        movbu   (CL),d1
        bra     validate
wp_get:
        extbu   d0
        mov     d0,d3
lg_wp:
        movhu   (WP),d1
        mov     d1,d2
        extbu   d2
        lsr     8,d1
validate:                               # d2 = F, d1 = C, d3 = n
        cmp     0,d1
        beq     v_bad
        mov     d2,d0
        add     d1,d0
        cmp     d3,d0
        bgt     v_bad
        mov     d2,d0
        ret     [d2,d3],12
v_bad:
        clr     d0
        mov     d3,d1
        ret     [d2,d3],12

# bkt_offset2: replaces bkt_offset 0x40124B1C (reached by a jmp, so the caller's
# `call ...,[d2,d3],8` frame applies). d0 = n, d1 = idx, a0 = step -> d0 = s16 offset.
bkt_offset2:
        mov     d0,d2
        extbu   d2                      # n
        mov     d1,d3
        extbu   d3                      # idx
        mov     a0,a1                   # step
        mov     d2,d0
        call    ext_lo,[],4
        cmp     -1,d0
        beq     bo_stock
        mov     d0,a0                   # LO
        cmp     0,d3
        bne     bo_latched              # mid-burst
        movhu   (STATE),d0
        cmp     2,d0
        beq     bo_latched
        cmp     3,d0
        beq     bo_latched
        mov     d2,d0
        call    wp_get,[d2,d3],12
        bra     bo_have
bo_latched:
        mov     d2,d0
        call    latched_get,[d2,d3],12
bo_have:                                # d0 = F
        add     d3,d0
        mov     a0,d1
        sub     d1,d0                   # F + idx - LO
        mov     a1,d1
        exth    d1
        mul     d1,d0
        exth    d0
        ret     [d2,d3],8
bo_stock:                               # stock: idx == 0 -> 0; d = idx - n/2; if d <= 0: d -= 1
        clr     d1
        cmp     d1,d3
        beq     bo_done
        mov     d3,d1
        lsr     1,d2
        sub     d2,d1
        cmp     0,d1
        bgt     bo_scale
        add     -1,d1
bo_scale:
        mov     a1,d2
        exth    d2
        mul     d2,d1
bo_done:
        mov     d1,d0
        exth    d0
        ret     [d2,d3],8

# counter_next: replaces the "#7 + 1, wrap at #6" step of cam_bkt_counter_advance.
# d0 = #7 (raw), d2 = #6 (u8, non-zero) -> d0 = next #7. call counter_next,[d2,d3],12
counter_next:
        extbu   d0
        mov     d0,d3                   # idx
        mov     d2,d0
        call    ext_lo,[],4
        cmp     -1,d0
        beq     cn_stock
        mov     d2,d0
        call    latched_get,[d2,d3],12  # d1 = C
        bra     cn_cmp
cn_stock:
        mov     d2,d1
cn_cmp:
        mov     d3,d0
        inc     d0
        cmp     d1,d0
        blt     cn_ret
        clr     d0
cn_ret:
        ret     [d2,d3],12

# n_eff: replaces `mov 6,d0` + `call setting_get` in app_seq_limit (trigger task).
# -> d0 = frame count used for limit = d0 - #7. call n_eff,[d2,d3],12
n_eff:
        mov     6,d0
        call    setting_get_addr,[d2,d3],12
        mov     d0,d2                   # raw #6
        call    ext_lo,[],4
        cmp     -1,d0
        bne     ne_ext
        mov     d2,d0                   # stock choice: unchanged
        ret     [d2,d3],12
ne_ext:
        movhu   (STATE),d0
        cmp     2,d0
        beq     ne_pic
        cmp     3,d0
        beq     ne_pic
        clr     d0                      # not shooting (trigger start): drop any latch
        movbu   d0,(LT)
        mov     d2,d0
        call    wp_get,[d2,d3],12
        mov     d1,d0
        ret     [d2,d3],12
ne_pic:
        mov     7,d0
        call    setting_get_addr,[d2,d3],12
        extbu   d0
        cmp     0,d0
        bne     ne_resume
        mov     d2,d0                   # fresh burst: latch the working plan
        call    wp_get,[d2,d3],12
        clr     d3
        movbu   d3,(LT)
        movbu   d0,(FL)
        movbu   d1,(CL)
        mov     1,d3
        movbu   d3,(LT)
        mov     d1,d0
        ret     [d2,d3],12
ne_resume:                              # continuing a bracket (#7 != 0)
        mov     d0,d3                   # #7
        mov     d2,d0
        call    latched_get,[d2,d3],12
        mov     d1,d0                   # C
        cmp     d3,d0
        bgt     ne_ret                  # C > #7: limit C - #7 >= 1
        mov     d3,d0                   # counter left past C (preset changed mid-sequence):
        inc     d0                      # limit 1, then the counter wraps to 0
ne_ret:
        ret     [d2,d3],12

# plan_tramp: cam_capture_prep ends with `call ae_store_outputs,[d2,d3,a2,a3],76` (5-byte d16
# call at 0x40133359) and `ret [d2,d3,a2,a3],136`. Both are replaced by `jmp plan_tramp`, which
# calls plan_hook and then performs that same return.
plan_tramp:
        call    plan_hook,[d2,d3,a2,a3],56
        ret     [d2,d3,a2,a3],136

# plan_hook: does what the replaced ae_store_outputs call did, after planning.
# a0 = out, d0 = p1 (exposure params), a1 = p0 (AE in). The {p0, p1, p2, out} array that
# ae_calc takes sits at out - 16 in cam_capture_prep's frame. call plan_hook,[d2,d3,a2,a3],56
# Locals: (4) out, (8) p1, (12) p0, (16) n, (20) LO, (24) step, (28) Fcur, (32) F, (36) L
plan_hook:
        mov     a0,(4,sp)
        mov     d0,(8,sp)
        mov     a1,(12,sp)
        mov     0x85f1,d0               # #88 first, as cam_expo_params_build does
        mov     (CTX88),a0
        clr     d1
        call    store_get_addr,[d2,d3],12
        extbu   d0
        cmp     1,d0
        beq     ph_bkt
        jmp     ph_store                # AE BKT off
ph_bkt:
        mov     0x8281,d0
        mov     (CTX6),a0
        clr     d1
        call    store_get_addr,[d2,d3],12
        extbu   d0
        mov     d0,(16,sp)
        call    ext_lo,[],4
        cmp     -1,d0
        bne     ph_ext
        jmp     ph_store                # stock choice
ph_ext:
        mov     d0,(20,sp)
        mov     0x8291,d0
        mov     (CTX7),a0
        clr     d1
        call    store_get_addr,[d2,d3],12
        extbu   d0
        cmp     0,d0
        beq     ph_idle
        jmp     ph_store                # mid-bracket: plan frozen
ph_idle:
        movhu   (STATE),d0
        cmp     2,d0
        bne     ph_not2
        jmp     ph_store                # shooting: plan frozen
ph_not2:
        cmp     3,d0
        bne     ph_plan
        jmp     ph_store
ph_plan:
        mov     0x80ea,d0
        mov     (CTX8),a0
        clr     d1
        call    store_get_addr,[d2,d3],12
        exth    d0
        mov     d0,(24,sp)              # step
        mov     (16,sp),d0
        call    wp_get,[d2,d3],12       # the F this prep was built with
        mov     d0,(28,sp)
        mov     (20,sp),d1
        sub     d1,d0
        mov     (24,sp),d1
        mul     d1,d0
        mov     d0,d3                   # oF = (Fcur - LO) * step
        mov     (4,sp),a2               # out
        mov     (12,sp),a1              # p0
        mov     (8,sp),a3               # p1
        movbu   (6,a1),d0
        cmp     1,d0
        bne     ph_noflash
        jmp     ph_none                 # flash active: no plan
ph_noflash:
        movbu   (3,a1),d0               # AE mode
        cmp     6,d0
        bne     ph_auto
        # M: value = user Tv - offset, range [max(lo, -1536), min(hi, 3072)]
        movhu   (a3),d2
        add     d3,d2
        exth    d2                      # base = user Tv
        cmp     -32768,d2
        bne     ph_m_lim
        jmp     ph_none                 # bulb
ph_m_lim:
        movhu   (36,a2),d0
        exth    d0
        cmp     -1536,d0
        bge     ph_m_lo
        mov     -1536,d0
ph_m_lo:
        mov     d0,a0
        movhu   (34,a2),d0
        exth    d0
        cmp     3072,d0
        ble     ph_m_hi
        mov     3072,d0
ph_m_hi:
        mov     d0,a1
        jmp     ph_scan
ph_auto:
        movhu   (2,a3),d1
        cmp     0,d1
        bne     ph_iso
        jmp     ph_none                 # auto ISO: no plan
ph_iso:
        movhu   (22,a2),d2              # base = Ev of this prep + oF = err + Tv + Av + oF
        exth    d2
        movhu   (2,a2),d1
        exth    d1
        add     d1,d2
        movhu   (6,a2),d1
        exth    d1
        add     d1,d2
        add     d3,d2
        cmp     4,d0
        beq     ph_a
        cmp     5,d0
        beq     ph_s
        cmp     3,d0
        beq     ph_p
        cmp     7,d0
        beq     ph_p
        jmp     ph_none                 # scene modes: no plan
ph_a:                                   # A: [Av + lo, Av + hi]
        LIMITS  6, 36, 6, 34
ph_s:                                   # S: [Tv + Av_lo, Tv + Av_hi]
        LIMITS  2, 12, 2, 14
ph_p:                                   # P: [Av_lo + lo, Av_hi + hi]
        LIMITS  12, 36, 14, 34
ph_scan:                                # d2 = base; value_j = base - (j - LO) * step
        mov     (20,sp),d0
        mov     (24,sp),d1
        mul     d1,d0
        add     d0,d2                   # value_0
        mov     -1,d0
        mov     d0,(32,sp)              # F = none
        clr     d3                      # j
ph_loop:
        mov     a0,d0
        cmp     d0,d2
        blt     ph_next                 # value < mn
        mov     a1,d0
        cmp     d0,d2
        bgt     ph_next                 # value > mx
        mov     (32,sp),d0
        cmp     -1,d0
        bne     ph_last
        mov     d3,(32,sp)              # first reachable
ph_last:
        mov     d3,(36,sp)              # last reachable so far
ph_next:
        mov     (24,sp),d0
        sub     d0,d2
        inc     d3
        mov     (16,sp),d0
        cmp     d0,d3
        blt     ph_loop
        mov     (32,sp),d0
        cmp     -1,d0
        beq     ph_nothing
        mov     (36,sp),d1
        sub     d0,d1
        inc     d1                      # C = L - F + 1
        jmp     ph_write
ph_nothing:                             # no reachable frame: one frame, at the nearer end
        mov     (24,sp),d0
        add     d0,d2                   # value of frame n - 1
        mov     a1,d0
        clr     d1
        cmp     d0,d2
        ble     ph_dark
        mov     (16,sp),d1
        add     -1,d1                   # too bright for every frame: the last (brightest) one
ph_dark:
        mov     d1,d0                   # too dark for every frame: frame 0
        mov     1,d1
        jmp     ph_write
ph_none:                                # no plan: every frame, as stock
        clr     d0
        mov     (16,sp),d1
ph_write:                               # d0 = F, d1 = C
        mov     d0,d2
        asl     8,d1
        or      d0,d1
        movhu   d1,(WP)
        mov     (28,sp),d0
        cmp     d0,d2
        beq     ph_store
        mov     (8,sp),a0               # F changed: rebuild the exposure params and re-run AE once
        call    expo_build_addr,[d2,d3,a2,a3],24
        mov     (4,sp),a0
        add     -16,a0
        call    ae_calc_addr,[d2,d3,a2,a3],40
ph_store:
        mov     (4,sp),a0
        mov     (8,sp),d0
        mov     (12,sp),a1
        call    ae_store_addr,[d2,d3,a2,a3],76
        ret     [d2,d3,a2,a3],56
