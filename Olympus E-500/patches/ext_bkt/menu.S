# menu: hooks for the bracket preset menu (E-500 fw 1.3). Placed in free space by build.py.
# Findings: notes/2026-11-18-menu-labels-and-layouts.md.
#
#   res_hook   resource lookup 0x400FBA83: ids EXT_RES .. EXT_RES+EXT_RES_N-1 -> the new label
#              bitmaps (stock: ids >= 1467 have no resource). Every other id as stock.
#   lay_hook   layout lookup 0x40076A4A: ids EXT_LAY .. EXT_LAY+EXT_LAY_N-1 -> the new layouts
#              (stock indexes its 4598-entry table without a bound). Every other id as stock.
#   val_n6     ae_bkt_validate's get(6): a preset n reads as 5, so the validator uses its stock
#              {5, 1/3 EV, 0.3 EV} row (exposure-scale arrows) instead of running off its table.
#   fmt_n6     ui_fmt_bkt_count's get(6): a preset n reads as 5 and returns its two digits in
#              d1 (tens) and a1 (ones) for the patched 5-case. A real 5 returns ' ' and '5'.
#
# EXT_RES, EXT_RES_N, EXT_LAY and EXT_LAY_N come from `as --defsym`. ext_res_table_addr,
# ext_lay_table_addr, setting_get_addr, ext_lo_addr and the stock re-entry points come from
# `ld --defsym`.
        .equ    LAYTAB_PTR, 0x4016bebc  # ROM pointer to the stock layout table (4598 entries)

        .mn10300                        # base MN10300 only: AM33 extensions are an error
        .text

# res_hook: replaces `cmp 1467,d1` + `bcc null` at 0x400FBA8D (reached by a jmp, inside the
# function's `call ...,[d2,d3,a2,a3],24` frame). d1 = id, a2 = 0 (the "no resource" result).
res_hook:
        cmp     1467,d1
        bcc     rh_high
        jmp     res_stock_addr          # 0x400FBA93: the stock table walk
rh_high:
        mov     d1,a1                   # keep the id
        add     -EXT_RES,d1
        cmp     EXT_RES_N,d1
        bcc     rh_none                 # not ours: no resource, as stock
        asl2    d1
        mov     ext_res_table_addr,a0
        mov     (d1,a0),a2              # header {w, h, data, 0}
rh_none:
        mov     a1,d1
        jmp     res_ret_addr            # 0x400FBADF: mov a2,a0, ret

# lay_hook: replaces `mov (LAYTAB_PTR),a2` at 0x40076A4A (in the function's own frame).
# d1 = layout id. Continues at 0x40076A50: exthu d1, asl2 d1, mov (d1,a2),d1.
lay_hook:
        exthu   d1
        cmp     EXT_LAY,d1
        bcs     lh_stock
        cmp     EXT_LAY+EXT_LAY_N,d1
        bcc     lh_stock
        add     -EXT_LAY,d1
        mov     ext_lay_table_addr,a2
        jmp     lay_back_addr
lh_stock:
        mov     (LAYTAB_PTR),a2
        jmp     lay_back_addr

# val_n6: replaces `mov 6,d0` + `call setting_get,[d2,d3],12`. -> d0 = #6, or 5 for a preset.
# call val_n6,[d2,d3],12. Changes d0, d1, a0, a1, like the getter it replaces.
val_n6:
        mov     6,d0
        call    setting_get_addr,[d2,d3],12
        mov     d0,d2
        call    ext_lo_addr,[],4
        cmp     -1,d0
        beq     vn_stock
        mov     5,d0
        ret     [d2,d3],12
vn_stock:
        mov     d2,d0
        ret     [d2,d3],12

# fmt_n6: like val_n6, and also d1 = first character, a1 = second character of the count
# for the 5-case: a preset n -> its tens and ones digits, a real 5 -> ' ' and '5'.
# call fmt_n6,[d2,d3],12
fmt_n6:
        mov     6,d0
        call    setting_get_addr,[d2,d3],12
        mov     d0,d2
        call    ext_lo_addr,[],4
        cmp     -1,d0
        beq     fn_stock
        mov     d2,d0
        extbu   d0
        mov     10,d1
        ext     d0
        div     d1,d0                   # d0 = tens, mdr = ones (n <= 99)
        add     0x30,d0
        mov     d0,d1
        mov     mdr,d0
        add     0x30,d0
        mov     d0,a1
        mov     5,d0
        ret     [d2,d3],12
fn_stock:
        mov     0x20,d1
        mov     0x35,d0
        mov     d0,a1
        mov     d2,d0
        ret     [d2,d3],12
