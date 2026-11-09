#!/usr/bin/env python3
"""Execute the production xSPI arch driver and board policy; replace only platform boundaries."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
BOARD = NUTTX / "boards/arm/rzv/rdk-rzv2h/src"
ARCH = NUTTX / "arch/arm/src/rzv"


class ParameterBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-xspi-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        for name in ("nuttx/config.h", "nuttx/fs/ioctl.h", "nuttx/mtd/mtd.h", "hardware/rzv_xspi.h", "rzv_xspi.h"):
            dest = directory / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if name == "nuttx/config.h":
                dest.write_text("")
            else:
                arch = name.startswith("hardware/") or name == "rzv_xspi.h"
                source = (ARCH if arch else NUTTX / "include") / name
                content = source.read_text()
                if name in ("nuttx/fs/ioctl.h", "rzv_xspi.h"):
                    # MTD ioctl constants are real; unrelated ioctl-family
                    # includes are outside this callback interface.
                    content = re.sub(r"^#include[^\n]*$", "", content, flags=re.M)
                dest.write_text(content)
        # The arch driver and the board policy form one translation unit so
        # the board's static state and the driver's callbacks stay reachable.
        source = (ARCH / "rzv_xspi.c").read_text() + (BOARD / "rzv2h_xspi_paramfs.c").read_text()
        source = re.sub(r"^\s*#\s*include[^\n]*$", "", source, flags=re.M)
        # The hardware authority hook is a platform boundary. In one build
        # retain its real fail-closed default; another controls its return.
        enabled = source.replace("int weak_function board_xspi_paramfs_validate(void)\n{\n  return -ENOTSUP;\n}", "")
        prelude = r'''
#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/mman.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <limits.h>
#include <errno.h>
#include <string.h>
#include <assert.h>
#define CONFIG_RZV_XSPI 1
#define CONFIG_RDK_RZV2H_XSPI_PARAMFS 1
#define CONFIG_RDK_RZV2H_XSPI_PARAM_BASE 0x20004000u
#define CONFIG_RDK_RZV2H_XSPI_PARAM_OFFSET 0x4000u
#define CONFIG_RDK_RZV2H_XSPI_PARAM_SIZE 8192u
#define CONFIG_RDK_RZV2H_XSPI_PARAM_ADDRLEN 3
#define CONFIG_RDK_RZV2H_XSPI_PARAM_MANIFEST "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
#define FAR
#define weak_function
#define OK 0
#define UNUSED(x) (void)(x)
#define LOG_ERR 0
#define LOG_INFO 0
#define syslog(...) ((void)0)
#include <nuttx/mtd/mtd.h>
#include <hardware/rzv_xspi.h>
#include <rzv_xspi.h>
typedef int mutex_t;
#define NXMUTEX_INITIALIZER 0
static unsigned locks, cleans, invalidates, pushes;
static int nxmutex_lock(mutex_t *lock) { (void)lock; ++locks; return 0; }
static void nxmutex_unlock(mutex_t *lock) { (void)lock; assert(locks > 0); --locks; }
static void up_clean_dcache(uintptr_t start, uintptr_t end) { assert(start < end); ++cleans; }
static void up_invalidate_dcache(uintptr_t start, uintptr_t end) { assert(start < end); ++invalidates; }
#define ARM_DSB() ((void)0)
#define OPCODE(cdt) ((cdt) >> 24)
static unsigned mmio, registrations, mounts, mode, erases, wrens, bad_cdt;
static uint32_t last_address, first_erase, last_erase, last_cdt, erase_cdt;
static int registration_result, mount_result, validation_result;
static uint32_t cmctl, cmcfg1, cmcfg2, bmctl0, bmcfg;
static uint32_t getreg32(uintptr_t address) {
    ++mmio;
    if (address == RZV_XSPI_CMCTL) return cmctl;
    if (address == RZV_XSPI_INTS) {
        if (mode == 1) return XSPI_INTS_BUSERR;
        if (mode == 2) return 0;
        return XSPI_INTS_CMDCMP;
    }
    return 0;
}
static void putreg32(uint32_t value, uintptr_t address) {
    ++mmio;
    if (address == RZV_XSPI_BMCTL1 && (value & XSPI_BMCTL1_MWRPUSH)) ++pushes;
    if (address == RZV_XSPI_CSA_0_CMCFG(1)) cmcfg1 = value;
    if (address == RZV_XSPI_CSA_0_CMCFG(2)) cmcfg2 = value;
    if (address == RZV_XSPI_BMCTL0) bmctl0 = value;
    if (address == RZV_XSPI_BMCFG) bmcfg = value;
    if (address == RZV_XSPI_CDT) {
        last_cdt = value;
        /* Every manual command is a 1-byte opcode in the upper CMD byte. */
        if (((value >> XSPI_CDT_CMDSIZE_SHIFT) & 3u) != 1u || (value & 0x00ff0000u)) ++bad_cdt;
        if (OPCODE(value) == 0x06) ++wrens;
    }
    if (address == RZV_XSPI_CDA) {
        last_address = value;
        if (OPCODE(last_cdt) == 0x20) {
            if (erases++ == 0) first_erase = value;
            last_erase = value;
            erase_cdt = last_cdt;
        }
    }
}
static int register_mtddriver(const char *path, struct mtd_dev_s *dev, int perms, void *priv) {
    (void)dev; (void)perms; (void)priv;
    assert(!strcmp(path, "/dev/xspi_params")); ++registrations;
    return registration_result;
}
static int host_mkdir(const char *path, int perms) { (void)path; (void)perms; return 0; }
#define mkdir host_mkdir
static int nx_mount(const char *source, const char *target, const char *type, unsigned long flags, const void *data) {
    (void)source; (void)target; (void)flags;
    assert(!strcmp(type, "littlefs")); assert(data == NULL); ++mounts;
    return mount_result;
}
'''
        main = r'''
int main(int argc, char **argv) {
    assert(argc == 2);
    uint8_t buffer[256];
    struct mtd_dev_s *dev = &g_rzv_xspi.mtd;
    if (!strcmp(argv[1], "config-invalid")) {
        assert(rzv2h_xspi_paramfs_initialize() == -EINVAL);
        assert(!mmio && !registrations && !mounts);
        return 0;
    }
    if (!strcmp(argv[1], "disabled")) {
        assert(rzv2h_xspi_paramfs_initialize() == -ENOTSUP);
        assert(!mmio && !registrations && !mounts);
        assert(rzv_xspi_bread(dev, 0, 1, buffer) == -EACCES);
        assert(rzv_xspi_bwrite(dev, 0, 1, buffer) == -EACCES);
        assert(rzv_xspi_erase(dev, 0, 1) == -EACCES);
        assert(rzv_xspi_read(dev, 0, 1, buffer) == -EACCES);
        assert(rzv_xspi_ioctl(dev, MTDIOC_BULKERASE, 0) == -EACCES);
        assert(!mmio && !locks);
        return 0;
    }
    if (!strcmp(argv[1], "authority-denied")) {
        validation_result = -EPERM;
        assert(rzv2h_xspi_paramfs_initialize() == -EPERM);
        assert(!mmio && !registrations && !mounts);
        return 0;
    }
    if (!strcmp(argv[1], "corrupt-mount")) {
        mount_result = -EIO;
        assert(rzv2h_xspi_paramfs_initialize() == -EIO);
        assert(!erases && !wrens && registrations == 1 && mounts == 1);
        mmio = 0;
        mount_result = 0;
        assert(rzv2h_xspi_paramfs_initialize() == 0);
        assert(registrations == 1 && mounts == 2);
        assert(!mmio); /* The retry reuses the configured controller. */
        assert(rzv2h_xspi_paramfs_initialize() == 0);
        assert(registrations == 1 && mounts == 2 && !mmio);
        return 0;
    }
    if (!strcmp(argv[1], "foreign-registration")) {
        registration_result = -EEXIST;
        assert(rzv2h_xspi_paramfs_initialize() == -EEXIST);
        assert(!mounts && !erases && !wrens);
        return 0;
    }
    if (!strcmp(argv[1], "foreign-mount")) {
        mount_result = -EBUSY;
        assert(rzv2h_xspi_paramfs_initialize() == -EBUSY);
        assert(!erases && !wrens);
        return 0;
    }
    if (!strcmp(argv[1], "xip-refused")) {
        cmctl = XSPI_CMCTL_XIPEN;
        assert(rzv2h_xspi_paramfs_initialize() == -ENODEV);
        assert(!registrations && !mounts && !g_rzv_xspi.initialized);
        assert(rzv_xspi_read(dev, 0, 1, buffer) == -EACCES);
        return 0;
    }
    assert(rzv2h_xspi_paramfs_initialize() == 0);
    assert(!locks && registrations == 1 && mounts == 1);
    /* Initialization programs the FSP Open sequence for CS0. */
    assert(cmcfg1 == ((0x0bu << 8) | (8u << 16)) && cmcfg2 == (0x02u << 8));
    assert((bmctl0 & XSPI_BMCTL0_CS0ACC_MASK) == (3u << XSPI_BMCTL0_CS0ACC_SHIFT));
    assert(bmcfg & XSPI_BMCFG_MWRCOMB);
    {
        struct rzv_xspi_config_s other = g_xspi_param_config;
        other.erase_cmd = 0xd8;
        assert(rzv_xspi_initialize(&g_xspi_param_config) == dev);
        assert(rzv_xspi_initialize(&other) == NULL);
    }
    mmio = 0;
    if (!strcmp(argv[1], "invalid-ranges")) {
        const off_t bad[] = {-1, INT64_MAX};
        for (unsigned i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i) {
            assert(rzv_xspi_bread(dev, bad[i], 1, buffer) == -EINVAL);
            assert(rzv_xspi_bwrite(dev, bad[i], 1, buffer) == -EINVAL);
            assert(rzv_xspi_read(dev, bad[i], 1, buffer) == -EINVAL);
            assert(rzv_xspi_erase(dev, bad[i], 1) == -EINVAL);
        }
        assert(rzv_xspi_bread(dev, 0, SIZE_MAX, buffer) == -EINVAL);
        assert(rzv_xspi_bwrite(dev, 0, SIZE_MAX, buffer) == -EINVAL);
        assert(rzv_xspi_read(dev, 0, SIZE_MAX, buffer) == -EINVAL);
        assert(rzv_xspi_erase(dev, 0, SIZE_MAX) == -EINVAL);
        assert(rzv_xspi_bread(dev, 32, 1, buffer) == -EINVAL);
        assert(rzv_xspi_bwrite(dev, 32, 1, buffer) == -EINVAL);
        assert(rzv_xspi_read(dev, 8192, 1, buffer) == -EINVAL);
        assert(rzv_xspi_erase(dev, 2, 1) == -EINVAL);
        assert(rzv_xspi_bread(dev, 0, 1, NULL) == -EINVAL);
        assert(rzv_xspi_bwrite(dev, 0, 1, NULL) == -EINVAL);
        assert(rzv_xspi_read(dev, 0, 1, NULL) == -EINVAL);
        assert(!mmio);
        return 0;
    }
    if (!strcmp(argv[1], "zero-at-end")) {
        assert(rzv_xspi_bread(dev, 32, 0, NULL) == 0);
        assert(rzv_xspi_bwrite(dev, 32, 0, NULL) == 0);
        assert(rzv_xspi_read(dev, 8192, 0, NULL) == 0);
        assert(rzv_xspi_erase(dev, 2, 0) == 0);
        assert(!mmio);
        return 0;
    }
    if (!strcmp(argv[1], "geometry-bulk-erase")) {
        struct mtd_geometry_s geo;
        assert(rzv_xspi_ioctl(dev, MTDIOC_GEOMETRY, (unsigned long)&geo) == 0);
        assert(geo.blocksize == 256 && geo.erasesize == 4096 && geo.neraseblocks == 2);
        assert(rzv_xspi_ioctl(dev, MTDIOC_GEOMETRY, 0) == -EINVAL);
        assert(rzv_xspi_ioctl(dev, 0x1234, 0) == -ENOTTY);
        assert(rzv_xspi_ioctl(dev, MTDIOC_BULKERASE, 0) == 0);
        assert(erases == 2 && first_erase == 0x4000 && last_erase == 0x5000);
        /* 3 address bytes, no data, write transaction, sector-erase opcode. */
        assert(erase_cdt == ((1u << XSPI_CDT_CMDSIZE_SHIFT) | (3u << XSPI_CDT_ADDSIZE_SHIFT) |
                             XSPI_CDT_TRTYPE | (0x20u << 24)));
        assert(wrens == 2 && invalidates == 2 && !bad_cdt && !locks);
        return 0;
    }
    if (!strcmp(argv[1], "timeout") || !strcmp(argv[1], "command-error")) {
        mode = !strcmp(argv[1], "timeout") ? 2 : 1;
        assert(rzv_xspi_erase(dev, 0, 1) == (mode == 2 ? -ETIMEDOUT : -EIO));
        assert(!erases); /* Failed WREN must not issue an erase command. */
        return 0;
    }
    if (!strcmp(argv[1], "command-shape")) {
        uint32_t word = 0;
        assert(rzv_xspi_command(0, 0, 0, true, &word, 5) == -E2BIG);
        assert(rzv_xspi_command(0, 0, 5, true, &word, 0) == -E2BIG);
        assert(rzv_xspi_command(0, 0, 0, false, NULL, 1) == -E2BIG);
        assert(!mmio);
        return 0;
    }
    assert(!strcmp(argv[1], "read-write-end"));
    void *mapped = mmap((void *)(uintptr_t)RZV2H_XSPI_PARAM_BASE, RZV2H_XSPI_PARAM_SIZE,
                        PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
    assert(mapped != MAP_FAILED);
    size_t mapped_size = RZV2H_XSPI_PARAM_SIZE;
    memset(mapped, 0x5a, mapped_size);
    memset(buffer, 0, sizeof(buffer));
    assert(rzv_xspi_bread(dev, 31, 1, buffer) == 1);
    for (unsigned i=0; i<256; ++i) assert(buffer[i] == 0x5a);
    memset(buffer, 0xa5, sizeof(buffer));
    assert(rzv_xspi_bwrite(dev, 31, 1, buffer) == 1);
    assert(!memcmp((uint8_t *)mapped + 7936, buffer, 256));
    /* One write enable and cache clean per 64-byte combined write. */
    assert(wrens == 4 && cleans == 4 && !pushes && !bad_cdt && !locks);
    assert(rzv_xspi_read(dev, 8191, 1, buffer) == 1 && buffer[0] == 0xa5);
    munmap(mapped, RZV2H_XSPI_PARAM_SIZE);
}
'''
        cls.binaries = {}
        for name, body, hook in (("default", source, ""), ("enabled", enabled, "int board_xspi_paramfs_validate(void) { return validation_result; }\n")):
            path = directory / (name + ".c")
            path.write_text(prelude + hook + body + main)
            binary = directory / name
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(directory), str(path), "-o", str(binary)], check=True)
            cls.binaries[name] = binary
        invalid = {
            "unaligned": ("0x20004000u", "0x20004001u"),
            "offset-overflow": ("0x4000u", "0xfffff000u"),
            "address-overflow": ("0x20004000u", "0xfffff000u"),
            "size-zero": ("8192u", "0u"),
            "base-below-offset": ("0x20004000u", "0x2000u"),
            "base-not-mapping-offset": ("0x20004000u", "0x20008000u"),
            "outside-cs0-window": [("0x20004000u", "0x27fff000u"), ("0x4000u", "0x07fff000u"),
                                   ("PARAM_ADDRLEN 3", "PARAM_ADDRLEN 4")],
            "missing-manifest": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", ""),
            "invalid-manifest": ("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", "z" * 64),
        }
        for name, replacements in invalid.items():
            variant = prelude
            for old, new in ([replacements] if isinstance(replacements, tuple) else replacements):
                assert old in variant, old
                variant = variant.replace(old, new)
            path = directory / (name + ".c")
            path.write_text(variant + source + main)
            binary = directory / name
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(directory), str(path), "-o", str(binary)], check=True)
            cls.binaries[name] = binary

    def test_invalid_geometry_and_manifest_have_no_side_effect(self):
        for name in ("unaligned", "offset-overflow", "address-overflow", "size-zero", "base-below-offset",
                     "base-not-mapping-offset", "outside-cs0-window",
                     "missing-manifest", "invalid-manifest"):
            with self.subTest(config=name):
                self.case("config-invalid", name)

    def case(self, name, binary="enabled"):
        result = subprocess.run([str(self.binaries[binary]), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_default_authority_hook_denies_all_access(self): self.case("disabled", "default")
    def test_authority_error_precedes_registration(self): self.case("authority-denied")
    def test_negative_overflow_and_null_ranges(self): self.case("invalid-ranges")
    def test_zero_length_exact_partition_end(self): self.case("zero-at-end")
    def test_geometry_and_flash_relative_bulk_erase(self): self.case("geometry-bulk-erase")
    def test_controller_timeout_stops_before_erase(self): self.case("timeout")
    def test_controller_error_stops_before_erase(self): self.case("command-error")
    def test_invalid_command_shape_has_no_mmio(self): self.case("command-shape")
    def test_actual_read_write_callbacks_at_partition_end(self): self.case("read-write-end")
    def test_corrupt_mount_does_not_format_and_retry_is_owned(self): self.case("corrupt-mount")
    def test_foreign_registration_is_not_claimed(self): self.case("foreign-registration")
    def test_foreign_mount_is_not_claimed(self): self.case("foreign-mount")
    def test_controller_in_xip_mode_is_refused(self): self.case("xip-refused")


if __name__ == "__main__":
    unittest.main()
