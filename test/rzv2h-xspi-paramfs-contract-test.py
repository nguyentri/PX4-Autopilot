#!/usr/bin/env python3
"""Execute production xSPI MTD callbacks; replace only platform boundaries."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NUTTX = ROOT / "platforms/nuttx/NuttX/nuttx"
BOARD = NUTTX / "boards/arm/rzv/rdk-rzv2h/src"


class ParameterBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-xspi-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        for name in ("nuttx/config.h", "nuttx/fs/ioctl.h", "nuttx/mtd/mtd.h", "hardware/rzv_xspi.h"):
            dest = directory / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if name == "nuttx/config.h":
                dest.write_text("")
            else:
                source = NUTTX / ("arch/arm/src/rzv/" + name if name.startswith("hardware/") else "include/" + name)
                content = source.read_text()
                if name == "nuttx/fs/ioctl.h":
                    # MTD ioctl constants are real; unrelated ioctl-family
                    # includes are outside this callback interface.
                    content = re.sub(r"^#include[^\n]*$", "", content, flags=re.M)
                dest.write_text(content)
        source = (BOARD / "rzv2h_xspi_paramfs.c").read_text()
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
static unsigned mmio, registrations, mounts, mode, erases;
static uint32_t last_address, first_erase, last_erase;
static int registration_result, mount_result, validation_result;
static uint32_t getreg32(uintptr_t address) {
    ++mmio;
    if (address == RZV_XSPI_INTS) {
        if (mode == 1) return XSPI_INTS_BUSERR;
        if (mode == 2) return 0;
        return XSPI_INTS_CMDCMP;
    }
    return 0;
}
static void putreg32(uint32_t value, uintptr_t address) {
    ++mmio;
    if (address == RZV_XSPI_CDA) last_address = value;
    if (address == RZV_XSPI_CDT && (value >> XSPI_CDT_CMD_SHIFT) == 0x20) {
        if (erases++ == 0) first_erase = last_address;
        last_erase = last_address;
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
    struct mtd_dev_s *dev = &g_xspi_param_mtd.mtd;
    if (!strcmp(argv[1], "config-invalid")) {
        assert(rzv2h_xspi_paramfs_initialize() == -EINVAL);
        assert(!mmio && !registrations && !mounts);
        return 0;
    }
    if (!strcmp(argv[1], "disabled")) {
        assert(rzv2h_xspi_paramfs_initialize() == -ENOTSUP);
        assert(!mmio && !registrations && !mounts);
        assert(rzv2h_xspi_bread(dev, 0, 1, buffer) == -EACCES);
        assert(rzv2h_xspi_bwrite(dev, 0, 1, buffer) == -EACCES);
        assert(rzv2h_xspi_erase(dev, 0, 1) == -EACCES);
        assert(rzv2h_xspi_read(dev, 0, 1, buffer) == -EACCES);
        assert(!mmio);
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
        assert(!mmio && !erases && mounts == 1);
        mount_result = 0;
        assert(rzv2h_xspi_paramfs_initialize() == 0);
        assert(registrations == 1 && mounts == 2);
        assert(rzv2h_xspi_paramfs_initialize() == 0);
        assert(registrations == 1 && mounts == 2);
        return 0;
    }
    if (!strcmp(argv[1], "foreign-registration")) {
        registration_result = -EEXIST;
        assert(rzv2h_xspi_paramfs_initialize() == -EEXIST);
        assert(!mmio && !mounts);
        return 0;
    }
    if (!strcmp(argv[1], "foreign-mount")) {
        mount_result = -EBUSY;
        assert(rzv2h_xspi_paramfs_initialize() == -EBUSY);
        assert(!mmio && !erases);
        return 0;
    }
    assert(rzv2h_xspi_paramfs_initialize() == 0);
    if (!strcmp(argv[1], "invalid-ranges")) {
        const off_t bad[] = {-1, INT64_MAX};
        for (unsigned i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i) {
            assert(rzv2h_xspi_bread(dev, bad[i], 1, buffer) == -EINVAL);
            assert(rzv2h_xspi_bwrite(dev, bad[i], 1, buffer) == -EINVAL);
            assert(rzv2h_xspi_read(dev, bad[i], 1, buffer) == -EINVAL);
            assert(rzv2h_xspi_erase(dev, bad[i], 1) == -EINVAL);
        }
        assert(rzv2h_xspi_bread(dev, 0, SIZE_MAX, buffer) == -EINVAL);
        assert(rzv2h_xspi_bwrite(dev, 0, SIZE_MAX, buffer) == -EINVAL);
        assert(rzv2h_xspi_read(dev, 0, SIZE_MAX, buffer) == -EINVAL);
        assert(rzv2h_xspi_erase(dev, 0, SIZE_MAX) == -EINVAL);
        assert(rzv2h_xspi_bread(dev, 32, 1, buffer) == -EINVAL);
        assert(rzv2h_xspi_bwrite(dev, 32, 1, buffer) == -EINVAL);
        assert(rzv2h_xspi_read(dev, 8192, 1, buffer) == -EINVAL);
        assert(rzv2h_xspi_erase(dev, 2, 1) == -EINVAL);
        assert(rzv2h_xspi_bread(dev, 0, 1, NULL) == -EINVAL);
        assert(rzv2h_xspi_bwrite(dev, 0, 1, NULL) == -EINVAL);
        assert(rzv2h_xspi_read(dev, 0, 1, NULL) == -EINVAL);
        assert(!mmio);
        return 0;
    }
    if (!strcmp(argv[1], "zero-at-end")) {
        assert(rzv2h_xspi_bread(dev, 32, 0, NULL) == 0);
        assert(rzv2h_xspi_bwrite(dev, 32, 0, NULL) == 0);
        assert(rzv2h_xspi_read(dev, 8192, 0, NULL) == 0);
        assert(rzv2h_xspi_erase(dev, 2, 0) == 0);
        assert(!mmio);
        return 0;
    }
    if (!strcmp(argv[1], "geometry-bulk-erase")) {
        struct mtd_geometry_s geo;
        assert(rzv2h_xspi_ioctl(dev, MTDIOC_GEOMETRY, (unsigned long)&geo) == 0);
        assert(geo.blocksize == 256 && geo.erasesize == 4096 && geo.neraseblocks == 2);
        assert(rzv2h_xspi_ioctl(dev, MTDIOC_GEOMETRY, 0) == -EINVAL);
        assert(rzv2h_xspi_ioctl(dev, 0x1234, 0) == -ENOTTY);
        assert(rzv2h_xspi_ioctl(dev, MTDIOC_BULKERASE, 0) == 2);
        assert(erases == 2 && first_erase == 0x4000 && last_erase == 0x5000);
        return 0;
    }
    if (!strcmp(argv[1], "timeout") || !strcmp(argv[1], "command-error")) {
        mode = !strcmp(argv[1], "timeout") ? 2 : 1;
        assert(rzv2h_xspi_erase(dev, 0, 1) == (mode == 2 ? -ETIMEDOUT : -EIO));
        assert(!erases); /* Failed WREN must not issue an erase command. */
        return 0;
    }
    if (!strcmp(argv[1], "command-shape")) {
        assert(rzv2h_xspi_command(0, 0, 0, buffer, NULL, 5) == -E2BIG);
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
    assert(rzv2h_xspi_bread(dev, 31, 1, buffer) == 1);
    for (unsigned i=0; i<256; ++i) assert(buffer[i] == 0x5a);
    memset(buffer, 0xa5, sizeof(buffer));
    assert(rzv2h_xspi_bwrite(dev, 31, 1, buffer) == 1);
    assert(!memcmp((uint8_t *)mapped + 7936, buffer, 256));
    assert(rzv2h_xspi_read(dev, 8191, 1, buffer) == 1 && buffer[0] == 0xa5);
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


if __name__ == "__main__":
    unittest.main()
