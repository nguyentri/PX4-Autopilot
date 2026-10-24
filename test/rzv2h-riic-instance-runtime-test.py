#!/usr/bin/env python3
"""Execute the RIIC public lifecycle with observable host resource boundaries."""

import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ARCH = ROOT / "platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv"
SPEC = importlib.util.spec_from_file_location(
    "riic_runtime", ROOT / "test/rzv2h-audit-remediation-runtime-test.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def lifecycle(enabled, body):
    source = (ARCH / "rzv_i2c.c").read_text()
    code = RUNTIME.PRE + r'''
#define FAR
#define container_of(p,t,m) ((t *)((char *)(p) - offsetof(t,m)))
#define i2cerr(...) ((void)0)
#define SEM_PRIO_NONE 0
#define NXMUTEX_INITIALIZER 0
typedef int sem_t;
typedef int mutex_t;
struct i2c_msg_s { int unused; };
struct i2c_ops_s;
struct i2c_master_s { const struct i2c_ops_s *ops; };
struct i2c_ops_s { int (*transfer)(struct i2c_master_s *, struct i2c_msg_s *, int); };
static int rzv_i2c_transfer(struct i2c_master_s *d, struct i2c_msg_s *m, int n)
{ (void)d; (void)m; (void)n; return 0; }
static int sem_count, sem_calls, sem_fail, initialized, deinitialized, locks;
static int init_fail;
static int nxmutex_lock(mutex_t *m) { (void)m; ++locks; return 0; }
static int nxmutex_unlock(mutex_t *m) { (void)m; --locks; return 0; }
static int nxsem_init(sem_t *s, int shared, int value)
{ (void)shared; ++sem_calls; if (sem_calls == sem_fail) return -ENOMEM;
  *s = value; ++sem_count; return 0; }
static int nxsem_destroy(sem_t *s) { (void)s; --sem_count; return 0; }
static int nxsem_set_protocol(sem_t *s, int p) { (void)s; (void)p; return 0; }
static int nxsem_wait_uninterruptible(sem_t *s) { (void)s; return 0; }
static int nxsem_post(sem_t *s) { (void)s; return 0; }
'''
    code += "\n".join(f"#define CONFIG_RZV_I2C{i} 1" for i in enabled)
    code += "\n" + RUNTIME.header(ARCH / "hardware/rzv_i2c.h") + "\n"
    clock = (ARCH / "rzv_clock.h").read_text()
    code += "\n".join(line for line in clock.splitlines()
                      if re.match(r"#define RZV_CPG_CLK_I2C\d\s", line)) + "\n"
    for name in ("enum rzv_i2c_state_e", "struct rzv_i2c_config_s",
                 "struct rzv_i2c_priv_s"):
        match = re.search(re.escape(name) + r"\n\{.*?\n\};", source, re.S)
        if match:
            code += match[0] + "\n"
    start = source.index("static const struct i2c_ops_s rzv_i2c_ops =")
    end = source.index(" * Private Functions", start)
    code += source[start:source.rfind("/****", start, end)] + "\n"
    if "static bool rzv_i2c_port_enabled(" in source:
        code += RUNTIME.extract(source, "static bool rzv_i2c_port_enabled(")
    code += r'''
static const uintptr_t expected_base[9] = {
  0x14400400,0x14400800,0x14400c00,0x14401000,0x14401400,
  0x14401800,0x14401c00,0x14402000,0x11c01000 };
static int rzv_i2c_init(struct rzv_i2c_priv_s *p)
{
  ++initialized;
  assert(p->port >= 0 && p->port < 9);
  assert(p->base == expected_base[p->port] && p->dev.ops != NULL);
  return init_fail ? -ETIMEDOUT : 0;
}
static int rzv_i2c_deinit(struct rzv_i2c_priv_s *p)
{ (void)p; ++deinitialized; return 0; }
'''
    code += RUNTIME.extract(source, "struct i2c_master_s *rzv_i2c_initialize(")
    code += RUNTIME.extract(source, "int rzv_i2c_uninitialize(")
    # Some existing source-execution tests deliberately compile unused helpers.
    code += "\nint main(void) {\n" + body + r'''
  (void)nxsem_post; (void)nxsem_wait_uninterruptible;
  (void)nxmutex_lock; (void)nxmutex_unlock;
  assert(sem_count == 0 && locks == 0);
  return 0;
}
'''
    RUNTIME.run(code)


class RiicInstances(unittest.TestCase):
    def test_invalid_and_disabled_indices_have_no_resource_activity(self):
        lifecycle([0, 8], r'''
  int invalid[] = {-1,1,2,3,4,5,6,7,9,80,INT_MAX};
  for (unsigned i=0; i<sizeof(invalid)/sizeof(invalid[0]); ++i)
    assert(rzv_i2c_initialize(invalid[i]) == NULL);
  assert(initialized == 0 && sem_calls == 0 && deinitialized == 0);
  assert(rzv_i2c_uninitialize(NULL) == -EINVAL);
  struct i2c_master_s foreign = {0};
  assert(rzv_i2c_uninitialize(&foreign) == -EINVAL);
''')

    def test_all_nine_instances_have_distinct_identity_and_balanced_references(self):
        lifecycle(range(9), r'''
  struct i2c_master_s *dev[9];
  for (int i=0; i<9; ++i) {
    dev[i] = rzv_i2c_initialize(i); assert(dev[i]);
    for (int j=0; j<i; ++j) assert(dev[j] != dev[i]);
    assert(rzv_i2c_initialize(i) == dev[i]);
  }
  assert(initialized == 9 && sem_count == 18);
  for (int i=0; i<9; ++i) {
    assert(rzv_i2c_uninitialize(dev[i]) == 0);
    assert(rzv_i2c_uninitialize(dev[i]) == 0);
    assert(rzv_i2c_uninitialize(dev[i]) == -EINVAL);
  }
  assert(deinitialized == 9);
''')

    def test_semaphore_and_hardware_failure_can_retry_without_leaks(self):
        for fail in (1, 2, 0):
            with self.subTest(failure=fail):
                lifecycle([8], f'''
  sem_fail = {fail}; init_fail = {int(fail == 0)};
  assert(rzv_i2c_initialize(8) == NULL);
  assert(sem_count == 0 && locks == 0);
  sem_fail = 0; init_fail = 0;
  struct i2c_master_s *d = rzv_i2c_initialize(8); assert(d);
  assert(rzv_i2c_uninitialize(d) == 0);
''')


def concurrent_lifecycle_source():
    """Compile unchanged admission/lifecycle functions with real pthread/sem OS calls."""
    source = (ARCH / "rzv_i2c.c").read_text()
    code = "#define _POSIX_C_SOURCE 200809L\n" + RUNTIME.PRE + r'''
#include <pthread.h>
#include <semaphore.h>
#include <time.h>
#include <stdlib.h>
#include <stdio.h>
#define FAR
#define container_of(p,t,m) ((t *)((char *)(p) - offsetof(t,m)))
#define i2cerr(...) ((void)0)
#define SEM_PRIO_NONE 0
#define NXMUTEX_INITIALIZER PTHREAD_MUTEX_INITIALIZER
#define CONFIG_RZV_I2C0 1
#define CONFIG_RZV_I2C8 1
typedef pthread_mutex_t mutex_t;
struct i2c_msg_s { int unused; };
struct i2c_ops_s;
struct i2c_master_s { const struct i2c_ops_s *ops; };
struct i2c_ops_s { int (*transfer)(struct i2c_master_s *, struct i2c_msg_s *, int); };
static int rzv_i2c_transfer(struct i2c_master_s *d, struct i2c_msg_s *m, int n)
{ (void)d; (void)m; (void)n; return 0; }
'''
    code += RUNTIME.header(ARCH / "hardware/rzv_i2c.h") + "\n"
    code += "\n".join(line for line in (ARCH / "rzv_clock.h").read_text().splitlines()
                      if re.match(r"#define RZV_CPG_CLK_I2C\d\s", line)) + "\n"
    for name in ("enum rzv_i2c_state_e", "struct rzv_i2c_config_s",
                 "struct rzv_i2c_priv_s"):
        match = re.search(re.escape(name) + r"\n\{.*?\n\};", source, re.S)
        if match is None:
            raise AssertionError(f"missing production type: {name}")
        code += match[0] + "\n"
    start = source.index("static const struct i2c_ops_s rzv_i2c_ops =")
    end = source.index(" * Private Functions", start)
    code += source[start:source.rfind("/****", start, end)] + "\n"
    code += RUNTIME.extract(source, "static bool rzv_i2c_port_enabled(")
    code += r'''
enum { MAIN, ACTIVE, CLOSE, LATE, PROBE, ROLE_COUNT };
static _Thread_local int role;
static _Thread_local bool owns_lifecycle;
static pthread_mutex_t trace = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static int owner = -1;
static unsigned mutex_attempts[ROLE_COUNT], sem_waits[ROLE_COUNT];
static unsigned live_sems, init_calls, deinit_calls;
static int sem_wait_error;
static bool active_admitted, allow_active_release, active_done;
static bool close_waiting, close_done, late_at_mutex, late_done, probe_done;
static int close_result, late_result, probe_acquire_result, probe_close_result;
static struct rzv_i2c_priv_s *target;
struct tracked_sem {
  sem_t *sem;
  bool live;
  unsigned waiters, generations, destroys;
};
static struct tracked_sem tracked[18];

static struct timespec deadline(long milliseconds) {
  struct timespec value;
  assert(clock_gettime(CLOCK_REALTIME, &value) == 0);
  value.tv_sec += milliseconds / 1000;
  value.tv_nsec += (milliseconds % 1000) * 1000000L;
  if (value.tv_nsec >= 1000000000L) { ++value.tv_sec; value.tv_nsec -= 1000000000L; }
  return value;
}
static void lock_trace(void) { assert(pthread_mutex_lock(&trace) == 0); }
static void unlock_trace(void) { assert(pthread_mutex_unlock(&trace) == 0); }
static void notify(void) { assert(pthread_cond_broadcast(&changed) == 0); }
/* Every barrier is bounded; timeouts diagnose a deadlock, never establish order. */
static void await_event(const bool *event) {
  struct timespec until = deadline(5000);
  while (!*event) assert(pthread_cond_timedwait(&changed, &trace, &until) == 0);
}
static struct tracked_sem *lookup(sem_t *sem, bool create) {
  for (unsigned i = 0; i < 18; ++i) {
    if (tracked[i].sem == sem) return &tracked[i];
    if (!tracked[i].sem && create) { tracked[i].sem = sem; return &tracked[i]; }
  }
  assert(!"semaphore accessed before initialization"); return NULL;
}
static int nxmutex_lock(mutex_t *mutex) {
  lock_trace();
  ++mutex_attempts[role];
  if (role == LATE) {
    assert(close_waiting && owner == CLOSE && !close_done);
    assert(pthread_mutex_trylock(mutex) == EBUSY);
    late_at_mutex = true; notify();
  }
  unlock_trace();
  struct timespec until = deadline(role == PROBE ? 100 : 5000);
  int result = pthread_mutex_timedlock(mutex, &until);
  if (result) return -result;
  lock_trace();
  assert(owner == -1 && !owns_lifecycle);
  owner = role; owns_lifecycle = true;
  unlock_trace();
  return 0;
}
static int nxmutex_unlock(mutex_t *mutex) {
  lock_trace();
  assert(owner == role && owns_lifecycle);
  owner = -1; owns_lifecycle = false;
  assert(pthread_mutex_unlock(mutex) == 0);
  notify(); unlock_trace(); return 0;
}
static int nxsem_init(sem_t *sem, int shared, int count) {
  assert(owns_lifecycle);
  lock_trace();
  struct tracked_sem *entry = lookup(sem, true);
  assert(!entry->live && !entry->waiters);
  assert(sem_init(sem, shared, (unsigned)count) == 0);
  entry->live = true; ++entry->generations; ++live_sems;
  unlock_trace(); return 0;
}
static int nxsem_set_protocol(sem_t *sem, int protocol) {
  assert(protocol == SEM_PRIO_NONE);
  lock_trace(); assert(lookup(sem, false)->live); unlock_trace(); return 0;
}
static int nxsem_wait_uninterruptible(sem_t *sem) {
  assert(owns_lifecycle);
  lock_trace();
  assert(owner == role && role != LATE && role != PROBE);
  struct tracked_sem *entry = lookup(sem, false);
  assert(entry->live);
  ++sem_waits[role];
  if (sem_wait_error) { int result = sem_wait_error; unlock_trace(); return result; }
  ++entry->waiters;
  if (role == CLOSE) {
    assert(target && sem == &target->sem_excl && active_admitted && !allow_active_release);
    close_waiting = true; notify();
  }
  unlock_trace();
  struct timespec until = deadline(5000);
  int result;
  do { result = sem_timedwait(sem, &until); } while (result && errno == EINTR);
  int saved_errno = errno;
  lock_trace();
  assert(entry->live && entry->waiters > 0);
  --entry->waiters;
  unlock_trace();
  return result ? -saved_errno : 0;
}
static int nxsem_post(sem_t *sem) {
  lock_trace();
  assert(lookup(sem, false)->live);
  assert(sem_post(sem) == 0);
  /* Keep trace held until sem_post returns, so close cannot destroy it mid-call. */
  notify(); unlock_trace(); return 0;
}
static int nxsem_destroy(sem_t *sem) {
  assert(owns_lifecycle);
  lock_trace();
  struct tracked_sem *entry = lookup(sem, false);
  assert(entry->live && !entry->waiters && live_sems > 0);
  assert(sem_destroy(sem) == 0);
  entry->live = false; ++entry->destroys; --live_sems;
  unlock_trace(); return 0;
}
static int rzv_i2c_init(struct rzv_i2c_priv_s *priv) {
  assert(owns_lifecycle && (priv->port == 0 || priv->port == 8));
  assert(priv->base == (priv->port == 8 ? 0x11c01000u : 0x14400400u));
  ++init_calls; return 0;
}
static int rzv_i2c_deinit(struct rzv_i2c_priv_s *priv) {
  assert(owns_lifecycle && priv->refs == 1);
  lock_trace();
  assert(lookup(&priv->sem_excl, false)->live && !lookup(&priv->sem_excl, false)->waiters);
  unlock_trace(); ++deinit_calls; return 0;
}
'''
    for signature in ("static int rzv_i2c_acquire(",
                      "struct i2c_master_s *rzv_i2c_initialize(",
                      "int rzv_i2c_uninitialize("):
        code += RUNTIME.extract(source, signature)
    code += r'''
static void *active_client(void *unused) {
  (void)unused; role = ACTIVE;
  assert(rzv_i2c_acquire(target) == 0);
  lock_trace();
  assert(!owns_lifecycle && owner == -1);
  active_admitted = true; notify(); await_event(&allow_active_release);
  unlock_trace();
  assert(nxsem_post(&target->sem_excl) == 0);
  lock_trace(); active_done = true; notify(); unlock_trace(); return NULL;
}
static void *final_close(void *unused) {
  (void)unused; role = CLOSE;
  int result = rzv_i2c_uninitialize(&target->dev);
  lock_trace(); close_result = result; close_done = true; notify(); unlock_trace(); return NULL;
}
static void *late_client(void *unused) {
  (void)unused; role = LATE;
  int result = rzv_i2c_acquire(target);
  lock_trace(); late_result = result; late_done = true; notify(); unlock_trace(); return NULL;
}
static void *owned_mutex_probe(void *unused) {
  (void)unused; role = PROBE;
  int acquire_result = rzv_i2c_acquire(target);
  int release_result = rzv_i2c_uninitialize(&target->dev);
  lock_trace();
  probe_acquire_result = acquire_result; probe_close_result = release_result;
  probe_done = true; notify(); unlock_trace(); return NULL;
}
static unsigned total_sem_waits(void) {
  unsigned total = 0;
  for (unsigned i = 0; i < ROLE_COUNT; ++i) total += sem_waits[i];
  return total;
}
static void rejection_checks(void) {
  struct rzv_i2c_priv_s foreign = {0};
  unsigned before = total_sem_waits();
  assert(rzv_i2c_acquire(NULL) == -EINVAL);
  assert(rzv_i2c_acquire(&foreign) == -EINVAL);
  assert(rzv_i2c_acquire((struct rzv_i2c_priv_s *)(uintptr_t)1) == -EINVAL);
  assert(rzv_i2c_acquire(&g_riic_priv[0]) == -ENODEV);
  assert(rzv_i2c_acquire(&g_riic_priv[8]) == -ENODEV);
  assert(rzv_i2c_uninitialize(NULL) == -EINVAL);
  assert(rzv_i2c_uninitialize(&foreign.dev) == -EINVAL);
  assert(rzv_i2c_uninitialize(&g_riic_priv[0].dev) == -EINVAL);
  assert(total_sem_waits() == before && !live_sems && owner == -1 && !owns_lifecycle);
}
static void race_and_reopen(int port) {
  struct i2c_master_s *dev = rzv_i2c_initialize(port);
  assert(dev && live_sems == 2);
  target = &g_riic_priv[port];
  assert(dev == &target->dev && target->refs == 1);
  lock_trace();
  active_admitted = allow_active_release = active_done = false;
  close_waiting = close_done = late_at_mutex = late_done = false;
  unlock_trace();
  pthread_t active, closer, late;
  assert(pthread_create(&active, NULL, active_client, NULL) == 0);
  lock_trace(); await_event(&active_admitted); unlock_trace();
  assert(pthread_create(&closer, NULL, final_close, NULL) == 0);
  lock_trace(); await_event(&close_waiting);
  assert(owner == CLOSE && live_sems == 2 && !close_done);
  unlock_trace();
  assert(pthread_create(&late, NULL, late_client, NULL) == 0);
  lock_trace(); await_event(&late_at_mutex);
  assert(owner == CLOSE && !late_done && !close_done);
  assert(sem_waits[LATE] == 0 && lookup(&target->sem_excl, false)->waiters == 1);
  allow_active_release = true; notify();
  await_event(&active_done); await_event(&close_done); await_event(&late_done);
  assert(close_result == 0 && late_result == -ENODEV && sem_waits[LATE] == 0);
  assert(!lookup(&target->sem_excl, false)->live && !lookup(&target->sem_isr, false)->live);
  unlock_trace();
  assert(pthread_join(active, NULL) == 0);
  assert(pthread_join(closer, NULL) == 0);
  assert(pthread_join(late, NULL) == 0);
  assert(target->refs == 0 && !live_sems && owner == -1);
  unsigned before = total_sem_waits();
  assert(rzv_i2c_acquire(target) == -ENODEV && total_sem_waits() == before);
  assert(rzv_i2c_uninitialize(dev) == -EINVAL);
  unsigned generation = lookup(&target->sem_excl, false)->generations;
  assert(rzv_i2c_initialize(port) == dev && target->refs == 1);
  assert(lookup(&target->sem_excl, false)->generations == generation + 1);
  assert(rzv_i2c_acquire(target) == 0);
  assert(nxsem_post(&target->sem_excl) == 0);
  assert(rzv_i2c_uninitialize(dev) == 0 && !live_sems);
}
static void owned_mutex_wait(void) {
  struct i2c_master_s *dev = rzv_i2c_initialize(8);
  assert(dev); target = &g_riic_priv[8];
  unsigned before = total_sem_waits();
  assert(nxmutex_lock(&g_riic_lock) == 0);
  pthread_t probe;
  assert(pthread_create(&probe, NULL, owned_mutex_probe, NULL) == 0);
  lock_trace(); await_event(&probe_done);
  assert(owner == MAIN && probe_acquire_result == -ETIMEDOUT && probe_close_result == -ETIMEDOUT);
  assert(mutex_attempts[PROBE] == 2 && total_sem_waits() == before);
  assert(target->refs == 1 && live_sems == 2);
  unlock_trace();
  assert(pthread_join(probe, NULL) == 0);
  assert(nxmutex_unlock(&g_riic_lock) == 0);
  sem_wait_error = -EINTR;
  assert(rzv_i2c_acquire(target) == -EINTR && owner == -1 && !owns_lifecycle);
  assert(rzv_i2c_uninitialize(dev) == -EINTR && target->refs == 1 && live_sems == 2);
  sem_wait_error = 0;
  assert(rzv_i2c_acquire(target) == 0);
  assert(nxsem_post(&target->sem_excl) == 0);
  assert(rzv_i2c_uninitialize(dev) == 0 && !live_sems);
}
int main(int argc, char **argv) {
  assert(argc == 2);
  if (!strcmp(argv[1], "reject")) rejection_checks();
  else if (!strcmp(argv[1], "race")) {
    for (unsigned repeat = 0; repeat < 12; ++repeat) race_and_reopen(repeat % 2 ? 8 : 0);
    assert(init_calls == 24 && deinit_calls == 24);
    rejection_checks();
  } else { assert(!strcmp(argv[1], "owned-mutex")); owned_mutex_wait(); }
  assert(!live_sems && owner == -1 && !owns_lifecycle);
  for (unsigned i = 0; i < 18; ++i)
    assert(!tracked[i].live && !tracked[i].waiters && tracked[i].generations == tracked[i].destroys);
  return 0;
}
'''
    return code


class RiicTransferAdmission(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="rzv2h-riic-admission-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = directory / "test.c"
        source.write_text(concurrent_lifecycle_source())
        cls.binary = directory / "test"
        result = subprocess.run(
            ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
             "-Wno-unused-parameter", "-pthread", str(source), "-o", str(cls.binary)],
            capture_output=True, text=True, check=False, timeout=30,
        )
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True, check=False, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_foreign_null_and_zero_reference_admission_never_touches_semaphores(self):
        self.run_case("reject")

    def test_active_transfer_final_close_and_late_transfer_are_serialized(self):
        self.run_case("race")

    def test_owned_mutex_wait_is_bounded_and_wait_errors_preserve_live_instance(self):
        self.run_case("owned-mutex")


if __name__ == "__main__":
    unittest.main()
