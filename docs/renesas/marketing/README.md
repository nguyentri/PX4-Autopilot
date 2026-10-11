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

The target assigns Linux, ROS 2, perception, autonomy and payload services to
the Cortex-A55 cluster with DRP-AI3/DRP acceleration. CR8-0 runs PX4 on NuttX
and owns flight decisions. CR8-1 runs NuttX for aircraft I/O and supervised
actuator output. The Cortex-M33 core is excluded from boot and runtime roles.

The design applies to customer RZ/V2H platforms, including a SOM with a custom
carrier or a discrete SoC board. External memory, power electronics, sensors,
cameras, BMS, radios, gimbal controllers, ESCs and motors form part of the
aircraft. The customer selects their parts, wiring, protocols and board support.

The RDK-RZ/V2H provides a pre-development example. Its pins, images and PX4/
NuttX or FreeRTOS samples are reference implementations. The stock RDK has no
usable analog battery input; customer hardware defines a digital BMS/power
monitor connection or a protected analog sensing path where required.

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
