#!/usr/bin/env python3
"""Exercise native param_save_default on real files with faulted I/O boundaries."""
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BODY = b"complete native parameter export boundary\0"
# The export writes its BSON size header last; a complete document's header equals its length.
EXPORT = struct.pack("<i", 4 + len(BODY)) + BODY


class ParameterSave(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="rzv2h-param-save-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        source = (ROOT / "src/lib/parameters/parameters.cpp").read_text()
        recover = source.index("#ifdef CONFIG_BOARD_PARAM_FILE_ATOMIC\nstatic int param_temporary_path")
        recover_end = source.index("\n#endif\n", recover) + len("\n#endif\n")
        start = source.index("#ifdef CONFIG_BOARD_PARAM_FILE_ATOMIC\nstatic int param_save_atomic")
        end = source.index("\n/**", start)
        prelude = r'''
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <pthread.h>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <climits>
#include <string>
#include <fstream>
#include <cassert>
#define PX4_OK 0
#define PX4_ERROR -1
#define PX4_O_MODE_666 0666
#define PX4_DEBUG(...) ((void)0)
#define PX4_ERR(...) ((void)0)
#define PX4_WARN(...) ((void)0)
static const char *filename, *param_backup_file;
static std::string scenario;
static pthread_mutex_t file_mutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned resets, unlocks, exports;
static int param_export_perf;
struct Unsaved { void reset() { ++resets; } } params_unsaved;
static const char *param_get_default_file() { return filename; }
static int px4_shutdown_lock() { return 0; }
static void px4_shutdown_unlock() { ++unlocks; }
static void px4_usleep(unsigned) {}
static void perf_begin(int) {}
static void perf_end(int) {}
static int flash_param_save(void *) { return -ENOTSUP; }
static constexpr char body[] = "complete native parameter export boundary";
static char data[sizeof(int32_t) + sizeof(body)];
static int param_export_internal(int fd, void *) {
    ++exports;
    const int32_t placeholder = 0;
    if (scenario == "partial-export") { ::write(fd, &placeholder, sizeof(placeholder)); return -EIO; }
    return ::write(fd, data, sizeof(data)) == sizeof(data) ? 0 : -errno;
}
static int param_verify(int fd) {
    char value[sizeof(data)] = {};
    if (scenario == "verify-data") return -EIO;
    return ::read(fd, value, sizeof(value)) == sizeof(value) && !memcmp(value, data, sizeof(data)) ? 0 : -EIO;
}
static int host_open(const char *path, int flags, mode_t mode = 0) {
    if ((scenario == "open-temp" && (flags & O_WRONLY)) ||
        (scenario == "verify-open" && flags == O_RDONLY) ||
        (scenario == "backup-error" && strstr(path, "backup"))) {
        errno = EACCES; return -1;
    }
    return ::open(path, flags, mode);
}
int host_fsync(int fd) {
    if (scenario == "sync-error") { errno = ENOSPC; return -1; }
    int result = ::fsync(fd);
    if (scenario == "exit-before-rename") _exit(75);
    return result;
}
static int host_close(int fd) {
    const int access = ::fcntl(fd, F_GETFL) & O_ACCMODE;
    int result = ::close(fd);
    if (scenario == "close-error" || (scenario == "verify-close" && access == O_RDONLY)) { errno = EIO; return -1; }
    return result;
}
int host_rename(const char *oldpath, const char *newpath) {
    if (scenario == "rename-error") { errno = EIO; return -1; }
    // NuttX removes an existing target before moving the source over it.
    if (scenario == "exit-in-target-unlink") { ::unlink(newpath); _exit(77); }
    int result = ::rename(oldpath, newpath);
    if (scenario == "exit-after-rename") _exit(76);
    return result;
}
#define open host_open
#define fsync host_fsync
#define close host_close
#define rename host_rename
'''
        main = r'''
#undef open
#undef fsync
#undef close
#undef rename
int main(int argc, char **argv) {
    assert(argc == 4);
    scenario = argv[1]; filename = argv[2];
    const int32_t size = sizeof(data);
    memcpy(data, &size, sizeof(size));
    memcpy(data + sizeof(size), body, sizeof(body));
    if (scenario == "backup-error") param_backup_file = argv[3];
#ifdef CONFIG_BOARD_PARAM_FILE_ATOMIC
    if (scenario == "recover") {
        param_recover_atomic(filename);
        assert(pthread_mutex_trylock(&file_mutex) == 0);
        pthread_mutex_unlock(&file_mutex);
        return 0;
    }
    if (scenario == "path-overflow") {
        std::string longpath(PATH_MAX, 'x');
        assert(param_save_atomic(longpath.c_str()) == -ENAMETOOLONG);
        assert(exports == 0 && resets == 0);
        return 0;
    }
#endif
    if (scenario == "lock-busy") {
        pthread_mutex_lock(&file_mutex);
        assert(param_save_default(false) == -EWOULDBLOCK);
        pthread_mutex_unlock(&file_mutex);
        assert(exports == 0 && resets == 0 && unlocks == 0);
        return 0;
    }
    int result = param_save_default(true);
    const bool success = scenario == "success" || scenario == "backup-error";
    assert(success ? result == 0 : result != 0);
    assert(resets == (success ? 1u : 0u));
    assert(unlocks == 1);
    assert(pthread_mutex_trylock(&file_mutex) == 0);
    pthread_mutex_unlock(&file_mutex);
    if (!success && scenario != "open-temp" && scenario != "verify-open") assert(exports == 3);
}
'''
        cls.binaries = {}
        for name, flags in (("atomic", ["-DCONFIG_BOARD_PARAM_FILE_ATOMIC"]), ("legacy", [])):
            path = directory / (name + ".cpp")
            path.write_text(prelude + source[recover:recover_end] + source[start:end] + main)
            binary = directory / name
            subprocess.run(["c++", "-std=c++14", "-Wall", "-Wextra", "-Werror", "-pthread", *flags, str(path), "-o", str(binary)], check=True)
            cls.binaries[name] = binary

    def run_save(self, scenario, mode="atomic", expected_exit=0):
        with tempfile.TemporaryDirectory(prefix="rzv2h-save-files-") as directory:
            active = Path(directory) / "params"
            backup = Path(directory) / "backup"
            active.write_bytes(b"old valid parameters")
            backup.write_bytes(b"old valid backup")
            result = subprocess.run([str(self.binaries[mode]), scenario, str(active), str(backup)], capture_output=True, text=True)
            self.assertEqual(result.returncode, expected_exit, result.stderr)
            return active.read_bytes(), backup.read_bytes(), (Path(str(active) + ".tmp").exists())

    def test_success_commits_complete_export(self):
        active, _, temp = self.run_save("success")
        self.assertEqual(active, EXPORT)
        self.assertFalse(temp)

    def test_all_precommit_errors_preserve_active_parameters(self):
        for scenario in ("open-temp", "partial-export", "sync-error", "close-error", "verify-open", "verify-data", "verify-close", "rename-error"):
            with self.subTest(scenario=scenario):
                active, _, temp = self.run_save(scenario)
                self.assertEqual(active, b"old valid parameters")
                self.assertFalse(temp)

    def test_interruption_before_rename_retains_old_file(self):
        active, _, temp = self.run_save("exit-before-rename", expected_exit=75)
        self.assertEqual(active, b"old valid parameters")
        self.assertTrue(temp)

    def test_interruption_after_rename_retains_complete_new_file(self):
        active, _, temp = self.run_save("exit-after-rename", expected_exit=76)
        self.assertEqual(active, EXPORT)
        self.assertFalse(temp)

    def run_recover(self, active=None, temporary=None):
        with tempfile.TemporaryDirectory(prefix="rzv2h-recover-files-") as directory:
            path = Path(directory) / "params"
            temp = Path(str(path) + ".tmp")
            if active is not None:
                path.write_bytes(active)
            if temporary is not None:
                temp.write_bytes(temporary)
            result = subprocess.run([str(self.binaries["atomic"]), "recover", str(path), "unused"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return (path.read_bytes() if path.exists() else None,
                    temp.read_bytes() if temp.exists() else None)

    def test_interruption_inside_target_unlink_is_recovered_on_selection(self):
        with tempfile.TemporaryDirectory(prefix="rzv2h-unlink-files-") as directory:
            active = Path(directory) / "params"
            active.write_bytes(b"old valid parameters")
            result = subprocess.run([str(self.binaries["atomic"]), "exit-in-target-unlink", str(active), "unused"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 77, result.stderr)
            self.assertFalse(active.exists())
            result = subprocess.run([str(self.binaries["atomic"]), "recover", str(active), "unused"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(active.read_bytes(), EXPORT)
            self.assertFalse(Path(str(active) + ".tmp").exists())

    def test_recovery_promotes_only_a_complete_temporary_over_a_missing_target(self):
        self.assertEqual(self.run_recover(temporary=EXPORT), (EXPORT, None))
        partial = struct.pack("<i", 0) + BODY[:8]
        self.assertEqual(self.run_recover(temporary=partial), (None, partial))
        short = EXPORT[:-1]
        self.assertEqual(self.run_recover(temporary=short), (None, short))
        self.assertEqual(self.run_recover(temporary=b"ab"), (None, b"ab"))
        self.assertEqual(self.run_recover(active=b"old valid parameters", temporary=EXPORT),
                         (b"old valid parameters", EXPORT))
        self.assertEqual(self.run_recover(), (None, None))

    def test_recovery_runs_where_parameter_files_are_selected_and_loaded(self):
        source = (ROOT / "src/lib/parameters/parameters.cpp").read_text()
        for function, argument in (("param_set_default_file", "param_default_file"),
                                   ("param_set_backup_file", "param_backup_file"),
                                   ("param_load_default", "filename")):
            with self.subTest(function=function):
                body = source[source.index(function + "(const char *filename)\n{")
                              if function != "param_load_default"
                              else source.index("param_load_default()\n{"):]
                body = body[:body.index("\n}\n")]
                self.assertIn(f"param_recover_atomic({argument});", body)

    def test_backup_failure_preserves_backup_and_primary_success(self):
        active, backup, _ = self.run_save("backup-error")
        self.assertEqual(active, EXPORT)
        self.assertEqual(backup, b"old valid backup")

    def test_nonblocking_lock_failure_has_no_side_effect(self):
        active, _, temp = self.run_save("lock-busy")
        self.assertEqual(active, b"old valid parameters")
        self.assertFalse(temp)

    def test_temporary_path_overflow_has_no_side_effect(self):
        active, _, temp = self.run_save("path-overflow")
        self.assertEqual(active, b"old valid parameters")
        self.assertFalse(temp)

    def test_unselected_legacy_save_and_lock_contract_remain(self):
        active, _, temp = self.run_save("success", "legacy")
        self.assertEqual(active, EXPORT)
        self.assertFalse(temp)
        active, _, _ = self.run_save("lock-busy", "legacy")
        self.assertEqual(active, b"old valid parameters")


if __name__ == "__main__":
    unittest.main()
