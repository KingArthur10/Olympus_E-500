# Replacement for 20 bytes at 0x400A30F7 inside trig_can_resume (E-500 fw 1.3):
#   stock:  movbu (0xb00f6725),d0 / cmp 1,d0 / bne fail
#           movbu (0xb00f6736),d0 / cmp 1,d0 / bne fail
# Both checks move into cont_resume_ok. fail (0x400A316F) is `clr d0` then `ret [],4`.
# helper_addr and fail_addr are supplied by build.py via `ld --defsym`.

        .mn10300                        # base MN10300 only: AM33 extensions are an error
        .text
site:
        call    helper_addr,[],4
        cmp     0,d0
        beq     fail_addr
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
        nop
