"""Run Cortex-Debug's J-Link server as an exact owned lease child."""
import os
import sys

from .doctor import check_tool
from .probe import ProbeLease, probe_directory
from .process import ManagedProcess
from .target_state import TargetState
from .verification import OperationError


def cmd_jlink_server(argv):
    options, forwarded = {}, []
    for argument in argv:
        if argument.startswith('--firmware-') and '=' in argument:
            key, value = argument.split('=', 1)
            if key not in ('--firmware-lease', '--firmware-serial', '--firmware-server', '--firmware-core') or key in options:
                print('Invalid managed server parameter', file=sys.stderr)
                return 2
            options[key] = value
        else:
            forwarded.append(argument)
    try:
        token, serial, requested = (options[key] for key in ('--firmware-lease', '--firmware-serial', '--firmware-server'))
        core = options.get('--firmware-core')
        if core not in ('cr8_0', 'cr8_1', 'cm85', 'cm33'):
            raise OperationError('Managed server requires an exact core')
        server = check_tool(requested)
        if not server:
            raise OperationError('J-Link GDB server executable is unavailable', 'SERVER_UNAVAILABLE', True)
        os.environ.update(FIRMWARE_PROBE_LEASE=token, FIRMWARE_PROBE_SERIAL=serial,
                          FIRMWARE_PROBE_CORE=core)
        with ProbeLease(serial):
            code, _, _ = ManagedProcess([server, *forwarded]).run(preserve_streams=True)
            if code:
                TargetState(probe_directory(serial) / 'target-state.json').record(
                    ['cr8_0', 'cr8_1', 'cm33'] if core.startswith('cr8_') else [core],
                    'indeterminate/recovery-required', 'debug-server-failed')
            return code
    except (OperationError, OSError, KeyError) as error:
        print(f'Managed J-Link server refused: {error}', file=sys.stderr)
        return 3
