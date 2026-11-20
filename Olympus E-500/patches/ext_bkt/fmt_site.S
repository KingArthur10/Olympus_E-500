# The 5-case of ui_fmt_bkt_count (0x4006233F, 9 bytes), placed by build.py. Stock:
#     mov 32,d0 / movbu d0,(12,sp) / mov 53,d0 / bra 0x4006234F      (" 5")
# fmt_n6 (menu.S) has already left the two characters in d1 and a1 (" 5" for a real 5).
# The bra goes to 0x4006234F (movbu d0,(13,sp)): 11 bytes on from the bra at 0x40062344.
# (A bra to an absolute symbol would be widened into a 5-byte jmp, so it is written relative.)

        .mn10300                        # base MN10300 only: AM33 extensions are an error
        .text
        movbu   d1,(12,sp)
        mov     a1,d0
        bra     .+11
        nop
        nop
