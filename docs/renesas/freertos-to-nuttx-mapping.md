# FreeRTOS/POSIX to NuttX API Mapping

**Date:** 2026-08-09
**Status:** Source-checked migration reference
**Purpose:** Cheat sheet for migrating FreeRTOS + POSIX FSP code to native NuttX equivalents

This table maps 15+ common FreeRTOS/POSIX APIs to their NuttX counterparts. Each row includes the header file, any caveats, and a reference PX4 code path demonstrating the pattern.

---

## Task / Thread Management

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xTaskCreate(fn, name, stack, param, pri, hdl)` | `task_create(name, pri, stack, main_fn, argv)` or `pthread_create()` | `sched.h`, `pthread.h` | `task_create()` returns a PID and requires a `main_t`: `int fn(int argc, char *argv[])`. Use a pthread when a single `void *` argument and POSIX cancellation semantics fit better. | `platforms/nuttx/src/px4/common/tasks.cpp` |
| `vTaskDelay(ticks)` | `nxsig_usleep((useconds_t)ticks * CONFIG_USEC_PER_TICK)` | `nuttx/signal.h`, `nuttx/clock.h` | Convert with the actual FreeRTOS tick period; never assume 1 ms or 10 ms. Guard multiplication overflow for untrusted/large values. | RZ/V2H drivers and apps |
| `vTaskDelete(hdl)` | `task_delete(pid)` or `pthread_cancel(tid)` | `sched.h`, `pthread.h` | `pthread_cancel()` follows configured cancellation semantics; do not assume it immediately terminates the thread. | Core NuttX |
| `uxTaskGetStackHighWaterMark(hdl)` | `nxsched_get_stackinfo(pid, &info)` with `CONFIG_STACK_COLORATION` | `nuttx/sched.h` | `ps`/`top` can expose stack use when stack coloration is enabled. Treat uncoloured values as unavailable. | Debug/status commands |

---

## Synchronization: Mutexes & Semaphores

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xSemaphoreCreateMutex()` | `nxmutex_init(lock)` | `nuttx/mutex.h` | Use mutexes for task-context mutual exclusion. They are not ISR primitives. | PX4/NuttX task code |
| `xSemaphoreTake(sem, timeout)` | `nxmutex_lock(lock)`, `nxmutex_trylock(lock)`, or `nxsem_tickwait(sem, ticks)` | `nuttx/mutex.h`, `nuttx/semaphore.h` | `nxmutex_lock()` blocks until acquired. `nxmutex_trylock()` is non-blocking. Select a timed semaphore/mutex API when the FreeRTOS timeout is part of the contract. | `platforms/nuttx/src/px4/common/*.cpp` |
| `xSemaphoreGive(sem)` | `nxmutex_unlock(lock)` or `nxsem_post(sem)` | `nuttx/mutex.h`, `nuttx/semaphore.h` | Unlock/post wakes highest-priority waiter. | — |
| `xSemaphoreCreateBinary()` | `nxsem_init(sem, 0, 0)` | `nuttx/semaphore.h` | Initialize to 0 (locked); call `nxsem_post()` to unlock. Used for event signaling. | ISR completion callbacks |
| `xSemaphoreCreateCounting(max, init)` | `nxsem_init(sem, 0, init)` | `nuttx/semaphore.h` | Initialize counting semaphore; no explicit max in NuttX (limited by int). | Resource pools |

---

## Event Groups & Queues

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xEventGroupSetBits(grp, bits)` | Atomic bit state plus `nxsem_post()` or a message queue | `nuttx/semaphore.h`, `mqueue.h` | This tree has no generic `nxevent_post()`/`nuttx/event.h` event-group API. Preserve wait-all/wait-any/clear-on-exit semantics explicitly. | Interrupt callback → deferred worker |
| `xQueueCreate(len, item_size)` | `mq_open(name, flags, mode, &attr)` | `mqueue.h` | Set `mq_maxmsg` and `mq_msgsize`; call `mq_unlink()` when named-queue lifetime should end. | NuttX applications |
| `xQueueSend(q, item, timeout)` | `mq_send()` or `mq_timedsend()` | `mqueue.h` | `mq_timedsend()` is the POSIX timeout form; kernel-internal code may use the `nxmq_*` equivalents. | NuttX applications |
| `xQueueReceive(q, buf, timeout)` | `mq_receive()` or `mq_timedreceive()` | `mqueue.h` | Blocking receive; use `mq_timedreceive()` when the FreeRTOS timeout is meaningful. | NuttX applications |

---

## Timers & Delays

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xTimerCreate(name, period, reload, id, callback)` | `wd_start(wd, ticks, callback, arg)` or delayed `work_queue()` | `nuttx/wdog.h`, `nuttx/wqueue.h` | A watchdog callback runs in timer-interrupt context and must not block. For task-context periodic work, have the worker requeue itself with a delay. | Sensor polling |
| `hrt_absolute_time()` (PX4 API) | `rzv_hrt_absolute_time()` under the RZ/V2H PX4 shim | `rzv_hrt.h` | The RZ/V2H PX4 implementation delegates to the GTM7 arch shim; this tree has no generic `up_hrt_time()` contract. | `platforms/nuttx/src/px4/renesas/rzv/hrt/hrt.c` |
| `usleep(us)` (POSIX) | `nxsig_usleep(us)` | `nuttx/signal.h` | POSIX-compatible sleep in microseconds. May be interrupted by signals. | Device drivers |
| `sleep(s)` (POSIX) | `sleep(s)` or `nxsig_sleep(s)` | `unistd.h`, `nuttx/signal.h` | POSIX sleep in seconds; same behavior. | — |

---

## ISR Context & Interrupt Handling

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xHigherPriorityTaskWoken` (ISR hint) | `work_queue(priority, &work_s, fn, arg, delay)` | `nuttx/wqueue.h` | Instead of waking a specific task, defer work to a work-queue (HPWORK for ISRs, LPWORK for background). NuttX scheduler handles priority. | Device drivers (ISR → deferred) |
| `portENTER_CRITICAL()` | `enter_critical_section()` | `nuttx/irq.h` | Save interrupt state and enter a critical section. Keep it bounded; do not sleep inside it. | `rzv_<driver>.c` |
| `portEXIT_CRITICAL()` | `leave_critical_section(flags)` | `nuttx/irq.h` | Restore the saved state from the matching `enter_critical_section()`. | — |
| `portISR_CONTEXT()` or `xPortInIsrContext()` | `up_interrupt_context()` | `nuttx/arch.h` | Test if currently in ISR. Used to choose blocking-safe calls (can't block in ISR). | ISR condition checks |
| `irq_attach(irq, fn, arg)` (NuttX) | Same | `nuttx/irq.h` | NuttX native; attach ISR to interrupt. Up to arch to define irq numbers. | All drivers |

---

## Memory Management

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `pvPortMalloc(size)` | `kmm_malloc(size)` (kernel heap) or `malloc(size)` (user heap) | `nuttx/mm/mm.h`, `stdlib.h` | NuttX separates kernel and user heaps. Neither allocation path is an ISR contract; allocate before enabling interrupts or defer allocation to task context. | Driver initialization |
| `vPortFree(ptr)` | `kmm_free(ptr)` or `free(ptr)` | `nuttx/mm/mm.h`, `stdlib.h` | Match the allocator and avoid freeing from ISR context. | — |
| `pvPortMallocAligned(size, align)` | `kmm_memalign(align, size)` | `nuttx/mm/mm.h` | Allocate an aligned block; DMA still requires cache, addressability, and lifetime proof. | DMA buffer setup |

---

## Logging & Debug

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `printf(fmt, ...)` | `syslog(priority, fmt, ...)` or PX4 logging in task context | `syslog.h` | Do not treat formatted logging or an arbitrary low-level putc as ISR-safe. Record counters/status in the ISR and format them later unless the selected backend explicitly documents interrupt safety. | Logging and diagnostics |
| `DEBUG_PRINT()` (app macro) | `DEBUGASSERT(cond)` or `syslog()` | `debug.h`, `syslog.h` | `DEBUGASSERT` follows the debug configuration; use it for invariants and use task-context logging for recoverable errors. | Validation checks |

---

## POSIX Shim → Native NuttX Call Sites

When porting drivers or middleware from FreeRTOS to NuttX, check these PX4 shim layers to see how cross-OS abstractions are implemented:

| Abstraction | Location | Purpose |
|---|---|---|
| HRT (high-resolution timer) | `platforms/nuttx/src/px4/renesas/rzv/hrt/hrt.c` | Binds the PX4 HRT queue to the RZ/V2H GTM7 arch shim |
| Task wrappers | `platforms/nuttx/src/px4/common/tasks.cpp` | Maps PX4 task APIs to NuttX task/pthread behavior |
| Work Queue | `platforms/common/px4_work_queue/` | PX4 scheduled work on the platform work-queue layer |
| uORB | `platforms/common/uORB/` | PX4 publish/subscribe transport; not a direct POSIX mqueue mapping |
| sleep / usleep | `unistd.h`, `nuttx/signal.h` | POSIX-compatible; prefer `nxsig_usleep()` where NuttX signal-aware sleep semantics are required |

---

## Thread/Task Creation Patterns

### FreeRTOS Pattern (FSP Reference)

```c
TaskHandle_t task_handle;
xTaskCreate(my_task_fn, "mytask", 2048, NULL, 2, &task_handle);

static void my_task_fn(void *arg) {
  for (;;) {
    /* Do work */
    vTaskDelay(pdMS_TO_TICKS(100));
  }
}
```

### NuttX Equivalent

```c
/* Option 1: NuttX native task */
static int my_task_main(int argc, char *argv[])
{
  for (;;)
    {
      nxsig_usleep(100000);
    }

  return 0;
}

pid_t pid = task_create("mytask", 2, 2048, my_task_main, NULL);

/* Option 2: POSIX pthread (recommended for portability) */
pthread_t tid;

static void *my_task_fn(void *arg) {
  for (;;) {
    /* Do work */
    nxsig_usleep(100000);  /* 100 ms in microseconds */
  }
  return NULL;  /* pthread requires return */
}

pthread_create(&tid, NULL, my_task_fn, NULL);
```

---

## ISR + Work-Queue Pattern

### FreeRTOS Pattern (FSP Reference)

```c
static void my_isr(void) {
  BaseType_t yield = pdFALSE;
  /* Read hardware status */
  uint32_t status = HW_STATUS_REG;
  /* Signal waiting task */
  xSemaphoreGiveFromISR(isr_sem, &yield);
  /* Scheduler decides if yield needed */
  portEND_SWITCHING_ISR(yield);
}
```

### NuttX Equivalent

```c
static int my_isr(int irq, void *context, void *arg) {
  struct dev_s *priv = (void *)arg;
  /* Read hardware status */
  uint32_t status = HW_STATUS_REG;
  /* Defer work (non-blocking) */
  work_queue(HPWORK, &priv->work, my_work_fn, priv, 0);
  /* Clear the peripheral/ICU source that raised this interrupt. */
  return OK;
}

static void my_work_fn(FAR void *arg) {
  struct dev_s *priv = (void *)arg;
  /* Now safe to call blocking NuttX APIs */
  nxmutex_lock(&priv->lock);
  /* Process data */
  nxmutex_unlock(&priv->lock);
}
```

---

## Related References

- [Reference Source Map](./reference-source-map.md) — select the matching EVK sample/core before comparing application or driver behavior
- [Design Guidelines](../design-guidelines.md) — detailed ISR/work-queue patterns
- [Porting Playbook](./porting-playbook.md) — step-by-step driver porting
- [Code Standards](../code-standards.md) — formatting and conventions
- NuttX Official Docs: `platforms/nuttx/NuttX/nuttx/Documentation/`

---

**Maintenance:** Revise when NuttX APIs change (e.g., semaphore refactor). Track new patterns discovered in driver ports (Phase 3+).
