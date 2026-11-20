# A jump to a helper, placed by build.py. target_addr comes from `ld --defsym`, and PAD (from
# `as --defsym`) is the number of trailing nops (never executed).

        .mn10300                        # base MN10300 only: AM33 extensions are an error
        .text
        jmp     target_addr
        .rept   PAD
        nop
        .endr
