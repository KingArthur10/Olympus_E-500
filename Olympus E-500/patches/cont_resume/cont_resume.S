# cont_resume_ok: placed in free space (image tail, 0xFF) by build.py (E-500 fw 1.3).
#
# Called from trig_can_resume (0x400A30DC) in place of its two stock checks
#     6725 == 1  (fresh full press)   and   6736 == 1  (ready flag)
# Returns d0 = 1 when those pass, OR in the one new case:
#     6736 == 1, and 6725 == 2 (full press held since the burst started, any release clears it),
#     and continuous drive (6743 = #62 == 1), and not PC mode (6749 != 1),
#     and either no bracket (limit 6722 == -1) or an unfinished AE bracket
#     (#88 == 1, #7 != 0, #305 == 0, #307 == 0).
# Otherwise d0 = 0. Only d0 is changed, setting_get's own call saves d2/d3.
# Called as `call cont_resume_ok,[],4`, so it must return with `ret [],4`.
# setting_get_addr is supplied by build.py via `ld --defsym`.

        .mn10300                        # base MN10300 only: AM33 extensions are an error
        .text
cont_resume_ok:
        movbu   (0xb00f6736),d0
        cmp     1,d0
        bne     no              # stock: ready flag required
        movbu   (0xb00f6725),d0
        cmp     1,d0
        beq     yes             # stock: fresh full press
        cmp     2,d0
        bne     no
        movbu   (0xb00f6743),d0
        cmp     1,d0
        bne     no              # continuous drive only
        movbu   (0xb00f6749),d0
        cmp     1,d0
        beq     no              # PC/remote capture: stock
        movhu   (0xb00f6722),d0
        exth    d0
        cmp     -1,d0
        beq     yes             # unlimited burst: plain continuous
        mov     88,d0
        call    setting_get_addr,[d2,d3],12
        exthu   d0
        cmp     1,d0
        bne     no              # limit from another bracket type: stock
        mov     7,d0
        call    setting_get_addr,[d2,d3],12
        extbu   d0
        cmp     0,d0
        beq     no              # AE bracket finished: stock (no new bracket while held)
        mov     305,d0
        call    setting_get_addr,[d2,d3],12
        exthu   d0
        cmp     0,d0
        bne     no
        mov     307,d0
        call    setting_get_addr,[d2,d3],12
        exthu   d0
        cmp     0,d0
        bne     no
yes:
        mov     1,d0
        ret     [],4
no:
        clr     d0
        ret     [],4
