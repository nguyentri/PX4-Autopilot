"""The only PX4 flight-mode table: decode, encode, display names, stick flag.

PX4 packs the mode into HEARTBEAT.custom_mode: main mode in bits 16..23, sub
mode in bits 24..31 (`px4_custom_mode.h`). `needsSticks` marks the modes that
need manual stick input; without RC they are not useful (no RC in this GCS).
"""
from __future__ import annotations

# (key, display name, main, sub, needs sticks)
MODES = (
    ("MANUAL", "Manual", 1, 0, True),
    ("ALTCTL", "Altitude", 2, 0, True),
    ("POSCTL", "Position", 3, 0, True),
    ("POSCTL_ORBIT", "Orbit", 3, 1, False),
    ("POSCTL_SLOW", "Position Slow", 3, 2, True),
    ("AUTO_READY", "Ready", 4, 1, False),
    ("AUTO_TAKEOFF", "Takeoff", 4, 2, False),
    ("AUTO_LOITER", "Hold", 4, 3, False),
    ("AUTO_MISSION", "Mission", 4, 4, False),
    ("AUTO_RTL", "Return", 4, 5, False),
    ("AUTO_LAND", "Land", 4, 6, False),
    ("AUTO_FOLLOW_TARGET", "Follow Me", 4, 8, False),
    ("AUTO_PRECLAND", "Precision Land", 4, 9, False),
    ("AUTO_VTOL_TAKEOFF", "VTOL Takeoff", 4, 10, False),
    ("ACRO", "Acro", 5, 0, True),
    ("OFFBOARD", "Offboard", 6, 0, False),
    ("STABILIZED", "Stabilized", 7, 0, True),
    ("TERMINATION", "Termination", 10, 0, False),
) + tuple((f"AUTO_EXTERNAL{n}", f"External {n}", 4, 10 + n, False) for n in range(1, 9))

_BY_KEY = {m[0]: m for m in MODES}
_BY_PAIR = {(m[2], m[3]): m for m in MODES}
MAIN_NAMES = {1: "Manual", 2: "Altitude", 3: "Position", 4: "Auto", 5: "Acro", 6: "Offboard",
              7: "Stabilized", 8: "Rattitude", 9: "Simple", 10: "Termination"}


def table() -> list:
    return [{"key": k, "name": n, "main": main, "sub": sub, "needsSticks": sticks}
            for k, n, main, sub, sticks in MODES]


def split(custom_mode: int):
    return (custom_mode >> 16) & 0xFF, (custom_mode >> 24) & 0xFF


def decode(custom_mode: int) -> dict:
    main, sub = split(custom_mode)
    entry = _BY_PAIR.get((main, sub)) or (_BY_PAIR.get((main, 0)) if main != 4 else None)
    if entry:
        return {"key": entry[0], "name": entry[1], "main": main, "sub": sub}
    base = MAIN_NAMES.get(main)
    name = f"{base} ({sub})" if base else f"Unknown {main}/{sub}"
    return {"key": None, "name": name, "main": main, "sub": sub}


def encode(key: str):
    """(main, sub) for a table key; None when unknown."""
    entry = _BY_KEY.get(key)
    return (entry[2], entry[3]) if entry else None


def availability(custom_modes) -> list:
    """Keys whose PX4 custom_mode the vehicle reported in AVAILABLE_MODES."""
    pairs = {split(cm) for cm in custom_modes}
    return [m[0] for m in MODES if (m[2], m[3]) in pairs]
