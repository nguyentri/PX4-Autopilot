# FreeRTOS/POSIX to NuttX API Mapping

**Status:** Source-checked migration reference; target qualification is separate

Use this page while reading an FSP or FreeRTOS reference implementation. It
maps concepts and highlights semantic decisions that must be made in the
actual NuttX subsystem. It does not prescribe a one-to-one replacement or
prove that a migrated driver works on hardware. Read the selected source and
upper-half contract first, then use the [porting playbook](./porting-playbook.md)
for the implementation sequence.

The [reference source map](./reference-source-map.md) owns RDK/EVK provenance
and core selection. Native raw IPC ABI-v2 remains separate from the CA55
RPMsg/RPC/uXRCE path. Existing GY-912 and simple profiles retain P93 CS/P94
DRDY; any extension profile is explicit and default-off.

## Tasks and threads

| FreeRTOS/POSIX concept | NuttX surface | Semantic decision to record |
|---|---|---|
| `xTaskCreate()` | `task_create()` or `pthread_create()` | `task_create()` uses a NuttX `main_t` and returns a PID; a pthread preserves a `void *` argument and pthread lifecycle semantics. Choose from the owner interface, not from the function name alone. |
| `vTaskDelay(ticks)` | `nxsig_usleep()` or a NuttX timer/work queue | Convert using the actual FreeRTOS tick period. A delay inside a work callback must be represented by requeueing or another task-context design. |
| `vTaskDelete()` | `task_delete()` or `pthread_cancel()` | Cancellation and cleanup behavior differ. Prove who owns the task, buffers, handles, and shutdown ordering. |
| `uxTaskGetStackHighWaterMark()` | `nxsched_get_stackinfo()` or `ps`/`top` with stack coloration | Treat stack data as unavailable unless the selected configuration enables the required accounting. Record the configured task/POSIX stack owner. |
| FreeRTOS priority | NuttX task or work-queue priority | Numeric ranges and scheduling policy differ. Preserve the deadline and blocking assumptions, then choose the profile's priority; do not rescale by a fixed formula. |

PX4 task wrappers are in
`platforms/nuttx/src/px4/common/tasks.cpp`. Inspect them before introducing a
new task boundary in a PX4 module.

## Mutexes, semaphores, events, and queues

| FreeRTOS/POSIX concept | NuttX surface | Semantic difference |
|---|---|---|
| `xSemaphoreCreateMutex()` | `nxmutex_init()` | A mutex is task-context ownership and mutual exclusion. It is not an ISR signal. |
| `xSemaphoreTake()` / `xSemaphoreGive()` | `nxmutex_lock()`/`nxmutex_unlock()`, or `nxsem_*()` | Choose a mutex for ownership or a semaphore for counting/signaling. Preserve timeout, interruption, and priority behavior instead of mapping every semaphore to a mutex. |
| Binary semaphore from an ISR | `nxsem_init()` plus `nxsem_post()` from the supported completion path | Initialize the count and prove whether multiple completions may coalesce. Use the subsystem's ISR-safe primitive. |
| Counting semaphore | `nxsem_*()` | NuttX's count and timeout behavior are the contract. Record overflow and cancellation expectations when they matter. |
| Event group | Explicit atomic flags plus semaphore, or a message queue | NuttX has no generic FreeRTOS wait-all/wait-any/clear-on-exit equivalent in this port. Preserve each event bit's ownership and clear semantics explicitly. |
| `xQueueCreate()` / send / receive | POSIX `mq_*()` or the internal `nxmq_*()` API | Set message size/count and lifetime intentionally. Use the internal form only where the owner is kernel-side; named queues require explicit unlink/cleanup. |

Do not use a mutex, semaphore, queue, or event group from interrupt context
unless the selected NuttX interface documents that operation as safe. The
usual RZ/V2H driver pattern records the event in the ISR and wakes/delegates
work to task context.

## Timers and time

| FreeRTOS/POSIX concept | NuttX surface | Semantic difference |
|---|---|---|
| `xTimerCreate()` callback | `wd_start()` or delayed `work_queue()` | A watchdog callback has timer/interrupt-context restrictions. Use delayed work or a task when the callback can block or take a mutex. |
| `vTaskDelayUntil()` | Requeued work, a task wait, or the subsystem timer API | Preserve absolute-period and overrun behavior; repeated relative sleeps can drift. |
| `usleep()` | `nxsig_usleep()` where signal-aware behavior is required | Record whether interruption is expected and how `EINTR` is handled. |
| `sleep()` | POSIX `sleep()` or `nxsig_sleep()` | Keep the existing seconds-level contract; do not use it for a driver deadline without checking tick and signal behavior. |
| PX4 `hrt_absolute_time()` | The PX4 RZ/V2H HRT shim | The implementation is in `platforms/nuttx/src/px4/renesas/rzv/hrt/hrt.c` and delegates to the profile-selected RZ/V2H GTM path. It is not a generic NuttX `up_hrt_time()` substitution. |

## Interrupts and deferred work

| FreeRTOS/POSIX concept | NuttX surface | Semantic difference |
|---|---|---|
| `xHigherPriorityTaskWoken` / `portEND_SWITCHING_ISR()` | The driver ISR plus `work_queue()` or a documented semaphore path | NuttX does not require the FreeRTOS yield hint. The ISR must clear the source it owns and defer blocking/heavy work using the selected queue or task contract. |
| `portENTER_CRITICAL()` / `portEXIT_CRITICAL()` | `enter_critical_section()` / `leave_critical_section()` | Save and restore the returned `irqstate_t`. Keep the region bounded and never sleep within it. |
| ISR-context test | `up_interrupt_context()` | Use only when the call path genuinely has task and ISR variants; it does not make a blocking operation ISR-safe. |
| FreeRTOS interrupt registration | `irq_attach()` plus the RZ/V2H ICU/GIC owner API | IRQ numbering, edge/level setup, routing, enablement, and source clear are core/IP-specific. There is no generic manual GIC acknowledgement recipe. |

The RZ/V2H architecture and drivers show the relevant route in
`rzv_icu.h`, `rzv_icu_*.c`, `rzv_serial.c`, `rzv_gpt.c`, and the corresponding
hardware header. Compare the selected core and peripheral before porting an
interrupt sequence.

## Memory and DMA

| FreeRTOS/POSIX concept | NuttX/RZ/V2H surface | Semantic decision to record |
|---|---|---|
| `pvPortMalloc()` / `vPortFree()` | `kmm_malloc()`/`kmm_free()` or the selected C allocator | Match the execution domain and ownership contract. Allocate before enabling interrupts and never allocate/free from an ISR. |
| Aligned allocation | `kmm_memalign()` or a static aligned buffer | Alignment alone does not prove DMA addressability, cache state, transfer width, or lifetime. |
| DMA TX buffer | `up_clean_dcache()` through the current DMAC/peripheral path | Clean the exact range after CPU writes and before the DMA reads it, where the owner requires it. |
| DMA RX buffer | `up_invalidate_dcache()` before CPU consumption | Invalidate the exact range after DMA writes and before the CPU consumes it, where the owner requires it. |
| FreeRTOS DMA channel/event setup | `rzv_dmac_channel_initialize()`, `rzv_dmac_channel_configure()`, and the matching stop/disable path | Prove channel ownership, width, count, address aliases, trigger routing, one-shot/reload mode, completion/error handling, and cleanup. |

The RZ/V2H DMAC API and cache behavior are owned by
`platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv/rzv_dmac.h` and
`rzv_dmac.c`. Do not copy cache helper names or bus-address assumptions from an
unrelated FreeRTOS BSP. A DMAC memory-copy result does not qualify a peripheral
consumer.

## Logging and error handling

| FreeRTOS/POSIX concept | NuttX/PX4 surface | Semantic decision to record |
|---|---|---|
| `printf()` or a debug macro | `syslog()`/NuttX subsystem logging or PX4 logging | Keep formatted output in task context unless the selected backend documents interrupt safety. Record bounded ISR state and format it later. |
| Fatal assertion | `DEBUGASSERT()` for programmer invariants | Assertions are not recovery. Return or log recoverable hardware/configuration failures. |
| FreeRTOS status code | NuttX `0`/negative `errno` or the selected upper-half result | Preserve the actual interface's return type and unwind partial initialization. Do not treat a pointer/`NULL` factory as an integer status API. |

## PX4 boundaries to inspect

| Boundary | Owner |
|---|---|
| HRT | `platforms/nuttx/src/px4/renesas/rzv/hrt/hrt.c` |
| PX4 task wrappers | `platforms/nuttx/src/px4/common/tasks.cpp` |
| PX4 scheduled work | `platforms/common/px4_work_queue/` |
| uORB transport | `platforms/common/uORB/`; this is not a direct POSIX mqueue mapping |
| Board SPI/I2C/UART/GPIO adapters | The existing adapter under `boards/renesas/rdk-rzv2h/src/` and its selected NuttX lower half |

Before coding, list every FreeRTOS call in the reference and classify it as
task lifecycle, ownership, signaling, timing, interrupt, memory/cache, or
logging. For each call, record the NuttX owner, timeout/cancellation meaning,
ISR legality, and cleanup path. Then run the focused source/build checks and
use the [validation checklist](./validation/validation-checklist.md) to separate host
evidence from named board qualification.

## Related owners

- [Porting playbook](./porting-playbook.md) — comparison, implementation, and review sequence.
- [Reference source map](./reference-source-map.md) — FSP/core provenance and gaps.
- [Code standards](../code-standards.md) — formatting and contribution rules.
- [Deployment guide](../deployment-guide.md) — build, artifact, console, and debug procedures.
- [Validation checklist](./validation/validation-checklist.md) — evidence and recovery gates.
