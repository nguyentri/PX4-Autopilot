#!/usr/bin/env python3
"""Execute the v3 producer callback and supervisor loop at host I/O boundaries."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
BOUNDARY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOUNDARY)

COMMON = r'''
#include <apps/output-producer.hpp>
#include <apps/output-status.hpp>
#include <cassert>
#include <cstdio>
using namespace rzv2h::demo;
using hrt_abstime = uint64_t;
constexpr uint16_t OutputRateHz = 400, HardwareContract = 1;
const OutputProfile *output_profiles(size_t &count) {
    static const OutputProfile profiles[] = {[] {
        OutputProfile p{}; p.identity=4;
        p.configuration.airframe_id=4014; p.configuration.rate_hz=400;
        for (unsigned i=0; i<4; ++i) {
            auto &c=p.configuration.channels[i]; c.function=101+i;
            c.minimum=1000; c.maximum=2000; c.disarmed=c.failsafe=1000;
        }
        return p;
    }()};
    count=1; return profiles;
}
Hello hardware_identity() {
    Hello h{}; h.board=1; h.resources=2; h.profile=3; h.output_config=4; return h;
}
'''

PRODUCER = r'''
constexpr unsigned MAX_ACTUATORS=4;
uint64_t hrt_absolute_time() { return 1000; }
// Publication B is visible to independent subscribers; the mixer consumed A.
struct actuator_motors_s { uint64_t timestamp{950}; };
struct vehicle_status_s { bool safety_off{true}; };
struct Subscription { template<class T> void copy(T *value) { *value=T{}; } };
struct Parameter { int get() { return 4014; } };
struct ArmedState {
    bool armed{true}, force_failsafe{false}, lockdown{false}, manual_lockdown{false};
};
struct Mixing {
    hrt_abstime consumed[4]{800,800,800,800};
    ArmedState state{};
    uint32_t rangeReverseOutputs() { return 0; }
    uint32_t reversibleOutputs() { return 0; }
    uint16_t outputFunction(unsigned i) { return 101+i; }
    uint16_t minValue(unsigned) { return 1000; }
    uint16_t maxValue(unsigned) { return 2000; }
    uint16_t disarmedValue(unsigned) { return 1000; }
    uint16_t actualFailsafeValue(unsigned) { return 1000; }
    bool isFunctionSet(unsigned) { return true; }
    ArmedState armed() { return state; }
    bool getOutputPublicationTimestamp(unsigned i, hrt_abstime &t) {
        t=consumed[i]; return t!=0;
    }
};
class RemoteOutputs {
public:
    bool updateOutputs(bool, uint16_t [MAX_ACTUATORS], unsigned, unsigned);
    Mixing _mixing;
    Parameter _param_sys_autostart;
    Subscription _motors, _vehicle;
    AtomicRecord<6> _peer;
    px4::atomic<uint32_t> _configuration_id{0};
    px4::atomic<bool> _exhausted{false};
    OutputProducer _producer;
    SnapshotStore _snapshot;
};
'''

PRODUCER_MAIN = r'''
int main() {
    uint16_t values[4]{1200,1200,1200,1200};
    const uint32_t new_token[6]{7,2,900,0,ArmReady,1};
    RemoteOutputs stale;
    stale._peer.publish(new_token);
    assert(!stale.updateOutputs(false,values,4,1)); // A predates token; B cannot grant freshness.
    RemoteOutputs matching;
    const uint32_t earlier_token[6]{7,1,700,0,ArmReady,1};
    matching._peer.publish(earlier_token);
    assert(matching.updateOutputs(false,values,4,1));
    OutputSnapshot snapshot{};
    assert(matching._snapshot.read(snapshot) && snapshot.control_us==800);
    assert(!matching.updateOutputs(false,values,4,1)); // Cached A cannot renew authority.
    RemoteOutputs fresh;
    fresh._peer.publish(new_token);
    for (auto &t:fresh._mixing.consumed) { t=950; }
    assert(fresh.updateOutputs(false,values,4,1));
    RemoteOutputs incoherent;
    incoherent._peer.publish(earlier_token);
    incoherent._mixing.consumed[2]=750;
    assert(!incoherent.updateOutputs(false,values,4,1));
    RemoteOutputs missing;
    missing._peer.publish(earlier_token);
    missing._mixing.consumed[0]=0;
    assert(!missing.updateOutputs(false,values,4,1));
    missing._mixing.state.armed=false;
    assert(missing.updateOutputs(true,values,4,0)); // Missing progress never blocks disarm.
    puts("consumed motor progress, token causality, caching and disarm passed");
}
'''

SUPERVISOR = r'''
struct rzv_ipc_raw_stats_s { bool ready{false}, degraded{true}; uint32_t epoch{0}; };
struct LinkState {
    bool ready{false}, degraded{true}, hello_pending{false};
    uint32_t epoch{0}, pending_epoch{7}, reads{0}, recoveries{0};
} transport;
class RawLink {
public:
    bool open_link() { return true; }
    bool state(rzv_ipc_raw_stats_s &s) {
        s.ready=transport.ready; s.degraded=transport.degraded; s.epoch=transport.epoch; return true;
    }
    bool receive(Frame &frame) {
        ++transport.reads;
        // Match the driver's responder read contract: stats alone never adopts.
        if (transport.pending_epoch!=transport.epoch) {
            transport.epoch=transport.pending_epoch; transport.ready=true;
            transport.degraded=false; transport.hello_pending=true;
        }
        if (!transport.hello_pending) { return false; }
        transport.hello_pending=false;
        Context c{}; c.epoch=transport.epoch; c.sequence=1;
        frame=encode(hardware_identity(),c); return true;
    }
    bool recover() { ++transport.recoveries; return false; }
};
constexpr int SCHED_DEFAULT=0, SCHED_PRIORITY_ACTUATOR_OUTPUTS=1, SCHED_PRIORITY_DEFAULT=0;
int px4_task_spawn_cmd(const char *,int,int,int,int (*)(int,char **),char **) { return 1; }
#define PX4_ERR(...) ((void)0)
unsigned iterations=0, scenario=0;
struct EndLoop {};
uint64_t hrt_absolute_time() { return 1000+iterations*2500; }
void px4_usleep(unsigned) {}
class IoSupervisor {
public:
    void run();
    static int worker(int,char **) { return 0; }
    static int reporter(int,char **) { return 0; }
    bool should_exit() {
        if (++iterations>6) { throw EndLoop{}; }
        if (iterations==3 && scenario) {
            transport.pending_epoch=8;
            if (scenario==1) { transport.ready=false; transport.degraded=true; }
        }
        return false;
    }
    px4::atomic<bool> _worker_stop{false}, _worker_done{true}, _reporter_done{true}, _rotate{false};
    OutputPlanStore _plan;
    OutputWorkerReportStore _worker_status;
    OutputStatusStore _control_status;
};
'''

SUPERVISOR_MAIN = r'''
int main(int argc,char **) {
    scenario=unsigned(argc-1);
    if (scenario) {
        transport.epoch=7; transport.ready=true; transport.degraded=false; transport.hello_pending=true;
    }
    IoSupervisor supervisor;
    try { supervisor.run(); } catch (const EndLoop &) {}
    Status status{}; uint32_t epoch=0; uint64_t updated=0;
    assert(supervisor._control_status.read(status,epoch,updated));
    assert(epoch==(scenario ? 8u : 7u) && status.token!=0);
    assert(transport.reads>0 && transport.reads<=6*8 && transport.recoveries==0);
    puts("responder boot, quarantine/live epoch adoption and current-epoch hello passed");
}
'''


class RuntimeBoundaries(unittest.TestCase):
    def compile_run(self, prelude, definition, main, arguments=()):
        with tempfile.TemporaryDirectory(prefix='rzv2h-runtime-boundary-') as tmp:
            source=Path(tmp)/'boundary.cpp'; binary=Path(tmp)/'boundary'
            source.write_text(COMMON+prelude+definition+main)
            subprocess.run(['g++','-std=c++14','-O1','-g','-Wall','-Wextra','-Werror',
                            '-fsanitize=undefined','-fno-sanitize-recover=all',
                            '-I',str(ROOT/'src'),'-I',str(ROOT/'platforms/common/include'),
                            str(source),str(ROOT/'src/apps/protocol.cpp'),
                            str(ROOT/'src/apps/actuator-lease.cpp'),'-o',str(binary)],check=True)
            for args in arguments or ((),):
                subprocess.run([str(binary),*args],check=True)

    def test_motor_progress_belongs_to_the_values_consumed_by_the_mixer(self):
        source=(ROOT/'boards/renesas/rdk-rzv2h/rzv2h_outputs/remote-outputs.cpp').read_text()
        self.compile_run(PRODUCER,BOUNDARY.EXTRACT.definition(source,'bool RemoteOutputs::updateOutputs('),PRODUCER_MAIN)

    def test_responder_read_adopts_offline_and_live_epochs_before_dispatch(self):
        source=(ROOT/'boards/renesas/rdk-rzv2h-io-cr8_1/rzv2h_io/io-supervisor.cpp').read_text()
        self.compile_run(SUPERVISOR,BOUNDARY.EXTRACT.definition(source,'void IoSupervisor::run('),
                         SUPERVISOR_MAIN,((),('quarantine',),('live', 'epoch')))


if __name__=='__main__':
    unittest.main()
