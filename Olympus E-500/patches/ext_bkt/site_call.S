# One `call target,[d2,d3],12` to a helper, placed at a call site by build.py.
# target_addr comes from `ld --defsym`, and PAD (from `as --defsym`) is the number of trailing nops.

        .mn10300                        # base MN10300 only: AM33 extensions are an error
        .text
        call    target_addr,[d2,d3],12
        .rept   PAD
        nop
        .endr
