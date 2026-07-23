# FreeRTOS/POSIX to NuttX API Mapping

**Date:** 2026-07-11  
**Status:** Phase 2 (Workflow Enablement)  
**Purpose:** Cheat sheet for migrating FreeRTOS + POSIX FSP code to native NuttX equivalents

This table maps 15+ common FreeRTOS/POSIX APIs to their NuttX counterparts. Each row includes the header file, any caveats, and a reference PX4 code path demonstrating the pattern.

---

## Task / Thread Management

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xTaskCreate(fn, name, stack, param, pri, hdl)` | `task_create(name, pri, stack, fn, param)` or `pthread_create()` | `nuttx/task.h`, `pthread.h` | NuttX task_create returns PID; FreeRTOS xTaskCreate returns task handle. For compatibility, use pthread_create (POSIX). | `platforms/nuttx/src/px4/drivers/*.c` |
| `vTaskDelay(ticks)` | `nxsig_usleep(ticks * 1000 / freq)` | `nuttx/signal.h` | FreeRTOS ticks are typically 10 ms; NuttX uses microseconds. Convert: `ticks_to_us = (ticks * 1000000) / CONFIG_USEC_PER_TICK`. | `platforms/nuttx/px4/hrt.c` |
| `vTaskDelete(hdl)` | `task_delete(pid)` or `pthread_cancel(tid)` | `nuttx/task.h`, `pthread.h` | task_delete is synchronous; pthread_cancel may be deferred. | Core NuttX |
| `uxTaskGetStackHighWaterMark(hdl)` | Not directly available | — | NuttX lacks runtime stack watermark. Use STACK_COLOR at build time or monitor syslog for stack overflow warnings. | Debug only |

---

## Synchronization: Mutexes & Semaphores

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xSemaphoreCreateMutex()` | `nxmutex_init(lock)` | `nuttx/mutex.h` | NuttX mutex is more efficient than binary semaphore for mutual exclusion. Handles priority inheritance. | `platforms/nuttx/px4/lock.c` |
| `xSemaphoreTake(sem, timeout)` | `nxmutex_lock(lock)` or `nxsem_wait(sem)` | `nuttx/mutex.h`, `nuttx/semaphore.h` | nxmutex_lock is non-blocking (returns immediately if locked by same task). nxsem_wait blocks. | `platforms/nuttx/src/px4/*.c` |
| `xSemaphoreGive(sem)` | `nxmutex_unlock(lock)` or `nxsem_post(sem)` | `nuttx/mutex.h`, `nuttx/semaphore.h` | Unlock/post wakes highest-priority waiter. | — |
| `xSemaphoreCreateBinary()` | `nxsem_init(sem, 0, 0)` | `nuttx/semaphore.h` | Initialize to 0 (locked); call `nxsem_post()` to unlock. Used for event signaling. | ISR completion callbacks |
| `xSemaphoreCreateCounting(max, init)` | `nxsem_init(sem, 0, init)` | `nuttx/semaphore.h` | Initialize counting semaphore; no explicit max in NuttX (limited by int). | Resource pools |

---

## Event Groups & Queues

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xEventGroupSetBits(grp, bits)` | `nxevent_post(bits)` or `nxsem_post(sem)` chain | `nuttx/event.h`, `nuttx/semaphore.h` | NuttX lacks direct event-group API; use work-queue or semaphore chain for multi-event. | Interrupt callbacks |
| `xQueueCreate(len, item_size)` | `mq_open(name, flags, mode, mq_attr)` or `nxmq_create()` | `nuttx/mqueue.h` | NuttX message queue; specify max messages and item size in attributes. Persistent across process death (unlike FreeRTOS queue). | `platforms/nuttx/px4/mq_*.c` |
| `xQueueSend(q, item, timeout)` | `mq_send(mqd, buf, len, prio)` | `nuttx/mqueue.h` | Message queue is POSIX; supports priority levels. No timeout variant in mq_send (use nxmq_timedreceive). | — |
| `xQueueReceive(q, buf, timeout)` | `mq_receive(mqd, buf, len, prio)` or `mq_timedreceive()` | `nuttx/mqueue.h` | Blocking receive; use mq_timedreceive for timeout. | PX4 module startup |

---

## Timers & Delays

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xTimerCreate(name, period, reload, id, callback)` | `wd_start(wd, ticks, callback, arg)` (one-shot) or work-queue loop | `nuttx/wdog.h` | NuttX watchdog timer is simpler; reload requires manual restart. For periodic, use work-queue with `work_queue_timer()`. | Sensor polling |
| `hrt_absolute_time()` (PX4 shim) | `up_hrt_time()` or `rzv_hrt_time()` (RZ/V2H-specific) | `nuttx/hrt.h`, `arch/board.h` | PX4 shim abstracts OS-specific HRT. NuttX exposes raw `up_hrt_time()` in microseconds. | `platforms/nuttx/px4/hrt.c` |
| `usleep(us)` (POSIX) | `nxsig_usleep(us)` | `nuttx/signal.h` | POSIX-compatible sleep in microseconds. May be interrupted by signals. | Device drivers |
| `sleep(s)` (POSIX) | `sleep(s)` or `nxsig_sleep(s)` | `nuttx/unistd.h`, `nuttx/signal.h` | POSIX sleep in seconds; same behavior. | — |

---

## ISR Context & Interrupt Handling

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `xHigherPriorityTaskWoken` (ISR hint) | `work_queue(priority, &work_s, fn, arg, delay)` | `nuttx/wqueue.h` | Instead of waking a specific task, defer work to a work-queue (HPWORK for ISRs, LPWORK for background). NuttX scheduler handles priority. | Device drivers (ISR → deferred) |
| `portENTER_CRITICAL()` | `up_irq_save()` | `nuttx/arch.h` (up_arch.h) | Disable interrupts; return saved state. Critical sections protect R-M-W register access. | `rzv_<driver>.c` |
| `portEXIT_CRITICAL()` | `up_irq_restore(state)` | `nuttx/arch.h` | Re-enable interrupts to prior state. Always pair with up_irq_save(). | — |
| `portISR_CONTEXT()` or `xPortInIsrContext()` | `up_interrupt_context()` | `nuttx/arch.h` | Test if currently in ISR. Used to choose blocking-safe calls (can't block in ISR). | ISR condition checks |
| `irq_attach(irq, fn, arg)` (NuttX) | Same | `nuttx/irq.h` | NuttX native; attach ISR to interrupt. Up to arch to define irq numbers. | All drivers |

---

## Memory Management

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `pvPortMalloc(size)` | `kmm_malloc(size)` (kernel heap) or `malloc(size)` (user heap) | `nuttx/kmm.h`, `stdlib.h` | NuttX separates kernel and user heaps. Kernel heap (kmm_*) is interrupt-safe; user heap may sleep. | Driver init (use kmm_) |
| `vPortFree(ptr)` | `kmm_free(ptr)` or `free(ptr)` | `nuttx/kmm.h`, `stdlib.h` | Must match allocation (kmm_free with kmm_malloc). | — |
| `pvPortMallocAligned(size, align)` | `kmm_memalign(align, size)` | `nuttx/kmm.h` | Allocate aligned block (for DMA buffers). | DMA buffer setup |

---

## Logging & Debug

| FreeRTOS / POSIX | NuttX Equivalent | Header | Notes | PX4 Reference |
|---|---|---|---|---|
| `printf(fmt, ...)` (POSIX; use carefully in ISR) | `syslog(priority, fmt, ...)` (blocking) or `lib_lowputc(ch)` (ISR-safe) | `nuttx/syslog.h`, `nuttx/lib_internal.h` | syslog is task-safe; never call in ISR. For ISR debug, use lib_lowputc (character-at-a-time). | Logging everywhere |
| `DEBUG_PRINT()` (app macro) | `DEBUGASSERT(cond)` or `syslog()` | `nuttx/assert.h`, `nuttx/syslog.h` | DEBUGASSERT strips in release builds; syslog remains. Use DEBUGASSERT for invariant checks, syslog for recoverable errors. | Validation checks |

---

## POSIX Shim → Native NuttX Call Sites

When porting drivers or middleware from FreeRTOS to NuttX, check these PX4 shim layers to see how cross-OS abstractions are implemented:

| Abstraction | Location | Purpose |
|---|---|---|
| HRT (high-resolution timer) | `platforms/nuttx/src/px4/hrt.c` | Abstracts OS-specific timer; NuttX uses up_hrt_time() |
| Mutex / Lock | `platforms/nuttx/src/px4/lock.c` | nxmutex wrappers and task-safe initialization |
| Message Queue | `platforms/nuttx/src/px4/mq_*.c` | PX4 topic abstraction on top of NuttX mqueue |
| Work Queue | `platforms/nuttx/src/px4/work_*.c` | Maps PX4 deferred-work API to NuttX work_queue |
| Signal Handling | `platforms/nuttx/src/px4/signal_*.c` | Cross-OS signal dispatch (PX4 custom) |
| sleep / usleep | `nuttx/unistd.h`, `nuttx/signal.h` | POSIX-compliant; prefer nxsig_usleep for signal safety |

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
pid_t pid = task_create("mytask", 2, 2048, my_task_fn, NULL);

/* Option 2: POSIX pthread (recommended for portability) */
pthread_t tid;
pthread_create(&tid, NULL, my_task_fn, NULL);

static void *my_task_fn(void *arg) {
  for (;;) {
    /* Do work */
    nxsig_usleep(100000);  /* 100 ms in microseconds */
  }
  return NULL;  /* pthread requires return */
}
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
  /* Clear interrupt in ICU */
  ICU_ICLR = 0x01;
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

- [Design Guidelines](./design-guidelines.md) — detailed ISR/work-queue patterns
- [Porting Playbook](./porting-playbook.md) — step-by-step driver porting
- [Code Standards](../code-standards.md) — formatting and conventions
- NuttX Official Docs: `platforms/nuttx/NuttX/nuttx/Documentation/`

---

**Maintenance:** Revise when NuttX APIs change (e.g., semaphore refactor). Track new patterns discovered in driver ports (Phase 3+).
