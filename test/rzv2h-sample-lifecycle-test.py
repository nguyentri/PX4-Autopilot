#!/usr/bin/env python3
"""Execute sample descriptor cleanup under host-injected transfer failures."""
from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('boundary', ROOT/'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)
APPS = ROOT/'platforms/nuttx/NuttX/apps/testing/rzv_hwtest'
PRELUDE = B.PRELUDE + r'''
#include <sys/types.h>
#include <fcntl.h>
#include <termios.h>
#include <time.h>
#define open test_open
#define close test_close
#define read test_read
#define write test_write
#define tcgetattr test_tcgetattr
#define tcsetattr test_tcsetattr
#define clock_gettime test_clock_gettime
#define CLOCK_MONOTONIC 1
#define HWTEST_PASS 0
#define HWTEST_FAIL 1
#define HWTEST_ASSERT_TRUE(x) do { if (!(x)) return HWTEST_FAIL; } while (0)
#define HWTEST_ASSERT_EQ_INT(a,b) HWTEST_ASSERT_TRUE((a)==(b))
#define HWTEST_FAIL_REASON(...) return HWTEST_FAIL
#define syslog(...) ((void)0)
static int failure, opened, closed, clock_calls;
static unsigned char transmitted[128];
static ssize_t write(int fd, const void *data, size_t size)
{ (void)fd; if (failure==3) {errno=EIO;return -1;} memcpy(transmitted,data,size);return size; }
static ssize_t read(int fd, void *data, size_t size)
{ (void)fd; if (failure==4) {errno=EIO;return -1;} memcpy(data,transmitted,size);return size; }
static int open(const char *path,int flags)
{ (void)path;(void)flags;opened++;return 3; }
static int close(int fd)
{ (void)fd;opened--;closed++;if(failure==6){errno=EIO;return -1;}return 0; }
static int clock_gettime(int clock,struct timespec *now)
{ (void)clock;clock_calls++;now->tv_sec=0;now->tv_nsec=0;if(failure==5){errno=EIO;return -1;}return 0; }
static int usleep(unsigned int usec) { (void)usec;return 0; }
'''


class SampleLifecycles(unittest.TestCase):
    def test_scif_closes_and_disables_loop_on_exchange_errors(self):
        source = (APPS/'scif/scif_internal_loopback_test.c').read_text()
        code = PRELUDE + r'''
#define RZV2H_SCIF_LOOP 1
struct rzv2h_scif_sample_state_s {unsigned rxi,txi,attached_irqs;bool loop;};
static unsigned g_rxi,g_txi;
static bool loop;
static int disable_calls;
static int rzv2h_scif_sample_state(struct rzv2h_scif_sample_state_s *out)
{ static unsigned count;out->rxi=out->txi=++count;out->attached_irqs=opened;out->loop=loop;return 0; }
static int ioctl(int fd,int command,int value)
{ (void)fd;(void)command;if(!value){disable_calls++;loop=false;return 0;}if(failure==2){errno=EIO;return -1;}loop=true;return 0; }
static int tcgetattr(int fd,struct termios *s) {(void)fd;memset(s,0,sizeof(*s));return 0;}
static int tcsetattr(int fd,int action,const struct termios *s)
{ (void)fd;(void)action;(void)s;if(failure==1){errno=EIO;return -1;}return 0; }
''' + B.EXTRACT.definition(source, 'static int exchange(int fd)') + B.EXTRACT.definition(source, 'static int transfer(void)') + r'''
int main(void)
{
 for(failure=0;failure<=6;failure++) {
  opened=closed=clock_calls=disable_calls=0;loop=false;
  assert(transfer()==(failure==0 ? HWTEST_PASS : HWTEST_FAIL));
  assert(opened==0 && closed==1 && disable_calls==1 && !loop);
 }
 return 0;
}
'''
        B.compile_run(code)

    def test_ipc_closes_each_owned_descriptor_on_exchange_errors(self):
        source = (APPS/'ipc/ipc_local_loopback_test.c').read_text()
        code = PRELUDE + r'''
struct rzv2h_ipc_sample_state_s {unsigned open_count,queued,irq_entries;};
static int rzv2h_ipc_sample_state(struct rzv2h_ipc_sample_state_s *out)
{ static unsigned count;out->open_count=opened;out->queued=0;out->irq_entries=++count;return 0; }
''' + B.EXTRACT.definition(source, 'static int exchange_messages(') + B.EXTRACT.definition(source, 'static int echo(void)') + r'''
int main(void)
{
 for(failure=0;failure<=6;failure++) {
  if(failure==1 || failure==2) continue;
  opened=closed=clock_calls=0;
  assert(echo()==(failure==0 ? HWTEST_PASS : HWTEST_FAIL));
  assert(opened==0 && closed==(failure==0 ? 2 : 1));
 }
 return 0;
}
'''
        B.compile_run(code)


if __name__ == '__main__':
    unittest.main()
