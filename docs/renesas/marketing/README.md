# RZ/V2H Autonomous Drone Solution and Design Guide

Start here to evaluate an RZ/V2H autonomous-drone solution and begin customer
board design and software development. This document set connects the product
opportunity, reusable development ecosystem, aircraft interfaces and software
architecture for one central compute SoC.

## Document map

| Document | Read it to | Main audience |
|---|---|---|
| [Single-SoC autonomous drone solution](./rzv2h-autonomous-drone-solution.md) | Understand customer value, use cases, hardware delivery options and measurable evaluation demonstrations | Customers, product leads, sales engineers and partners |
| [Development ecosystem](./rzv2h-development-ecosystem.md) | Select a Linux/ROS 2/AI profile, find repositories, evaluate YOLO compatibility and reproduce a pinned demo | Solution architects, BSP, AI and integration teams |
| [System specification](./rzv2h-system-specification.md) | Allocate hardware resources, design power and external interfaces, define device contracts and prepare board reviews | Systems, hardware, payload and validation teams |
| [Software specification](./rzv2h-software-specification.md) | Locate build inputs and source owners, design inter-core communication, integrate devices and plan software bring-up | Flight, RTOS, Linux, autonomy and validation teams |
| [Dual-CR8 demo architecture](./rzv2h-dualcr8-demo-architecture.md) | Review complete subsystem ownership, lifecycle, battery/persistence and output-inhibit flows | Demo and product integration teams |
| [Dual-CR8 engineering design](./rzv2h-dualcr8-demo-design.md) | Review proposed exact-BOM resources, IPC wire contracts, state/sequence diagrams and qualification gaps | Firmware, board and validation teams |

## Demo module contracts

The [shared requirements registry](./rzv2h-demo-requirements.md) owns new module IDs and links seven specifications: sensors/navigation, flight control, battery/power, calibration/storage, IPC, actuator safety and diagnostics/release. CR8-0 performs standard mixing; CR8-1 validates and owns physical outputs. Initial qualification is props-off with full battery/persistence requirements. Key production decisions are frozen: DShot is selected as the primary ESC protocol (with 400Hz PWM backup), and the production hardware layout targets a fully custom discrete RZ/V2H board derived directly from the working RDK-RZ/V2H multicore demo.

## Recommended reading paths

- **Customer evaluation:** read the solution brief, review its
  [customer demonstrations](./rzv2h-autonomous-drone-solution.md#42-customer-evaluation-three-demonstrations),
  then use the ecosystem guide to choose reusable assets and an evaluation baseline.
- **Board design:** read the system specification's
  [board-design start package](./rzv2h-system-specification.md#55-board-design-start-package),
  complete the resource and device records, then check driver and BSP work in
  the software specification and ecosystem guide.
- **Software development:** select a profile in the ecosystem guide, follow
  the software specification's
  [developer start path](./rzv2h-software-specification.md#34-developer-start-path),
  then progress through the CR8 peer, A55 gateway and joint-workload gates.

## Target architecture and platform scope

The [system specification](./rzv2h-system-specification.md#2-system-context-and-boundaries)
owns the target domain allocation, customer-board boundary and CM33 exclusion;
the [software specification](./rzv2h-software-specification.md#1-scope-and-design-rules)
owns the software partition and contracts. The RDK and repository images are
pre-development references, not customer pinouts or production evidence.

## Engineering entry points

| Task or question | Start here |
|---|---|
| Select reusable software, repositories and an AI model | Ecosystem [starting profiles](./rzv2h-development-ecosystem.md#1-choose-a-starting-profile), [repository map](./rzv2h-development-ecosystem.md#3-official-repository-map) and [AI/YOLO guidance](./rzv2h-development-ecosystem.md#4-ai-and-yolo-guidance) |
| Assign pins, peripherals, DMA, clocks and memory owners | System [resource ownership ledger](./rzv2h-system-specification.md#33-peripheral-and-shared-resource-ownership-ledger) |
| Define battery, camera, gimbal, sensor and actuator connections | System [device inventory](./rzv2h-system-specification.md#42-external-device-inventory) and [interface-control record](./rzv2h-system-specification.md#48-device-interface-control-record) |
| Understand how RZ/V2H receives battery information | System [digital BMS transactions and wiring](./rzv2h-system-specification.md#433-how-rzv2h-actually-receives-battery-data) and software [BMS service and driver reuse](./rzv2h-software-specification.md#52-bms-and-power-software) |
| Choose cameras and size their links, buffers and timing | System [camera architecture](./rzv2h-system-specification.md#44-camera-architecture) |
| Start board bring-up and CR8 development | System [first-board sequence](./rzv2h-system-specification.md#554-first-board-bring-up-order) and software [build/source entry points](./rzv2h-software-specification.md#34-developer-start-path) |
| Integrate Linux autonomy with PX4 and CR8-1 | Software [inter-domain communication and PX4 topic boundary](./rzv2h-software-specification.md#4-inter-domain-communication) |
| Plan integration evidence and a reproducible release | Software [bring-up gates](./rzv2h-software-specification.md#343-bring-up-gates-and-evidence-to-save) and [release manifest](./rzv2h-software-specification.md#104-minimum-release-manifest) |

## Requirements, evidence and maintenance

The dual-CR8 evaluation covers sensors/navigation, flight control, battery/power, calibration/storage, IPC, actuator safety and diagnostics/release. Full acceptance requires real battery health and persistent calibration. Props-off bring-up, configured disarmed pulses and electrically inactive outputs are separately identified; the engineering design does not promote an incomplete bench milestone to product compliance.

The system and software specifications define target requirements. Current
implementation status and named hardware evidence are maintained in the
[NuttX port status](../port-status-nuttx.md) and
[PX4 HAL status](../port-status-px4-hal.md). Use those records when assessing
what the repository currently demonstrates. Product performance and aircraft
qualification require results from the selected hardware and released workload.

The ecosystem guide owns the researched version snapshot and upstream links.
Record exact releases, commits, model identities and build artifacts for each
customer evaluation. Keep detailed requirements in their owning specification
and update this README when document responsibilities or section links change.

For contributor workflows, hardware references and validation guides, continue
to the [RZ/V2H documentation index](../README.md).
