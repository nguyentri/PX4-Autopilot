"""MAVLink sidecar for the Px4-GCS VS Code extension.

The sidecar owns the serial port or UDP socket and speaks JSON lines on stdio:
commands arrive on stdin, replies and events leave on stdout, diagnostics go to
stderr. `pymavlink` is used only to parse and pack frames.
"""

BRIDGE_VERSION = "0.1.0"
