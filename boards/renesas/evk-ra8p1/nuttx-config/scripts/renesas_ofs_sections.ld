/****************************************************************************
 * boards/arm/ra8/evk-ra8p1/scripts/common/renesas_ofs_sections.ld
 *
 * Renesas Option Setting Bytes
 * Hardware configuration registers programmed during reset
 *
 ****************************************************************************/

SECTIONS
{
    /* Option Setting Memory (OFS) */
    .ofs0 :
    {
        KEEP(*(.ofs0))
    }> OPTION_SETTING_OFS0

    .ofs1 :
    {
        KEEP(*(.ofs1))
    }> OPTION_SETTING_OFS1

    .ofs2 :
    {
        KEEP(*(.ofs2))
    }> OPTION_SETTING_OFS2

    .ofs3 :
    {
        KEEP(*(.ofs3))
    }> OPTION_SETTING_OFS3

    /* Secure OFS */
    .ofs0_sec :
    {
        KEEP(*(.ofs0_sec))
    }> OPTION_SETTING_OFS0_SEC

    .ofs1_sec :
    {
        KEEP(*(.ofs1_sec))
    }> OPTION_SETTING_OFS1_SEC

    .ofs2_sec :
    {
        KEEP(*(.ofs2_sec))
    }> OPTION_SETTING_OFS2_SEC

    .ofs3_sec :
    {
        KEEP(*(.ofs3_sec))
    }> OPTION_SETTING_OFS3_SEC

    .ofs3_sel :
    {
        KEEP(*(.ofs3_sel))
    }> OPTION_SETTING_OFS3_SEL

    /* Block Protection Settings */
    .bps :
    {
        KEEP(*(.bps))
    }> OPTION_SETTING_BPS

    .bps_sec :
    {
        KEEP(*(.bps_sec))
    }> OPTION_SETTING_BPS_SEC

    /* OTP (One-Time Programmable) Settings */
    .otp_fsblctrl0 :
    {
        KEEP(*(.otp_fsblctrl0))
    }> OPTION_SETTING_OTP_FSBLCTRL0

    .otp_fsblctrl1 :
    {
        KEEP(*(.otp_fsblctrl1))
    }> OPTION_SETTING_OTP_FSBLCTRL1

    .otp_fsblctrl2 :
    {
        KEEP(*(.otp_fsblctrl2))
    }> OPTION_SETTING_OTP_FSBLCTRL2

    .otp_samr :
    {
        KEEP(*(.otp_samr))
    }> OPTION_SETTING_OTP_SAMR

    /* Security Access Control registers */
    .otp_sacc00 :
    {
        KEEP(*(.otp_sacc00))
    }> OPTION_SETTING_OTP_SACC00

    .otp_sacc10 :
    {
        KEEP(*(.otp_sacc10))
    }> OPTION_SETTING_OTP_SACC10

    .otp_sacc01 :
    {
        KEEP(*(.otp_sacc01))
    }> OPTION_SETTING_OTP_SACC01

    .otp_sacc11 :
    {
        KEEP(*(.otp_sacc11))
    }> OPTION_SETTING_OTP_SACC11

    .otp_sacc02 :
    {
        KEEP(*(.otp_sacc02))
    }> OPTION_SETTING_OTP_SACC02

    .otp_sacc12 :
    {
        KEEP(*(.otp_sacc12))
    }> OPTION_SETTING_OTP_SACC12

    .otp_sacc03 :
    {
        KEEP(*(.otp_sacc03))
    }> OPTION_SETTING_OTP_SACC03

    .otp_sacc13 :
    {
        KEEP(*(.otp_sacc13))
    }> OPTION_SETTING_OTP_SACC13

    /* Protected Block Protection Settings */
    .otp_pbps_sec :
    {
        KEEP(*(.otp_pbps_sec))
    }> OPTION_SETTING_OTP_PBPS_SEC

    .otp_pbps :
    {
        KEEP(*(.otp_pbps))
    }> OPTION_SETTING_OTP_PBPS

    .otp_zhuk :
    {
        KEEP(*(.otp_zhuk))
    }> OPTION_SETTING_OTP_ZHUK
}
