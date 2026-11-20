# m_tv_ref: reference shutter value for the M-mode shutter dial (E-500 fw 1.3).
#
# The #5 (user Tv) dial handlers step from #3000 (the AE output Tv) and revert the change
# unless #3000 afterwards equals the new value. In M mode the AE input is #5 - bkt_offset,
# so with the extended bracket (frame 0 = -3 EV, not 0 like stock) #3000 never equals #5
# and the dial is stuck. This helper replaces those #3000 reads:
#     M mode (#40 == 6), AE BKT on (#88 == 1), #6 a preset  ->  #5     (the value the user set)
#     otherwise                                             ->  #3000  (stock, unchanged)
# Assembled twice by build.py:
#     SHADOW=0: getter = setting_get        (handlers 0x40071FE6 / 0x4007203D)
#     SHADOW=1: getter = shadow_get 0x4007458F (handlers 0x4006E572 / 0x4006E5DB)
# SHADOW comes from `as --defsym`, getter_addr and ext_lo_addr (skip.S: preset n -> LO, else -1)
# from `ld --defsym`.
# Called as `call m_tv_ref,[d2,d3],12`, so it returns with `ret [d2,d3],12`. The getter's
# own call frame saves what it uses, so only d0, d1, a0 and a1 change, as with a plain getter call.

        .macro  GET id
        mov     \id,d0
        .if     SHADOW
        call    getter_addr,[d2],4
        .else
        call    getter_addr,[d2,d3],12
        .endif
        .endm

        .mn10300                        # base MN10300 only: AM33 extensions are an error
        .text
m_tv_ref:
        GET     40
        exthu   d0
        cmp     6,d0
        bne     stock           # not M mode
        GET     88
        exthu   d0
        cmp     1,d0
        bne     stock           # AE bracketing off
        GET     6
        call    ext_lo_addr,[],4        # changes d0, d1, a0 only
        cmp     -1,d0
        beq     stock           # a stock bracket choice
        GET     5               # the user's set shutter value, exactly as the getter returns it
        ret     [d2,d3],12
stock:
        GET     3000
        ret     [d2,d3],12
