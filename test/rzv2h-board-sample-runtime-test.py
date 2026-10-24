#!/usr/bin/env python3
"""Exercise retained board owners and negative sample paths with real C."""
from pathlib import Path
import importlib.util
import re
import unittest
ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'platforms/nuttx/NuttX/nuttx/boards/arm/rzv/rdk-rzv2h'
SPEC = importlib.util.spec_from_file_location('boundary', ROOT / 'test/rzv2h-driver-boundary-runtime-test.py')
B = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B)

ARCH = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'


def without_includes(source):
    return re.sub(r'^\s*#\s*include[^\n]*$', '', source, flags=re.M)


def bus_sample_state_type():
    header = (BOARD / 'include/rzv2h-sample-test.h').read_text()
    return re.search(r'struct rzv2h_bus_sample_state_s\s*\{.*?\n\};',
                     header, re.S).group() + '\n'


def sci_sample_fixture(mode):
    """Use production private types and getters; only host OS types differ."""
    source = (ARCH / f'rzv_sci_{mode}.c').read_text()
    code = B.PRELUDE + r'''
typedef int sem_t;
typedef int mutex_t;
struct spi_dev_s {int unused;};
struct i2c_master_s {int unused;};
enum spi_mode_e {SPIDEV_MODE0, SPIDEV_MODE1, SPIDEV_MODE2, SPIDEV_MODE3};
'''
    code += bus_sample_state_type()
    code += without_includes((ARCH / f'rzv_sci_{mode}_internal.h').read_text())
    if mode == 'i2c':
        code += re.search(r'^#define SCI_I2C_CHANNEL_COUNT[^\n]*',
                          source, re.M).group() + '\n'
    code += re.search(
        rf'static struct rzv_sci_{mode}_priv_s\s+g_sci_{mode}_priv\[[^;]*;',
        source, re.S).group() + '\n'
    code += re.search(r'^static uint32_t g_sample_transfers\[[^;]*;',
                      source, re.M).group() + '\n'
    for signature in (f'int rzv_sci_{mode}_sample_instance(',
                      f'uint32_t rzv2h_sci_{mode}_sample_transfers_at(',
                      f'uint32_t rzv2h_sci_{mode}_sample_transfers('):
        code += B.EXTRACT.definition(source, signature)
    return code


def board_observation_assertions(mode):
    """Observe actual stored coordinates, including errors from the lower."""
    return r'''
 struct rzv2h_bus_sample_state_s state;
 assert(STATE_AT(-1,&state)==-EINVAL && STATE_AT(10,&state)==-EINVAL);
 assert(STATE_AT(0,NULL)==-EINVAL && STATE_AT(1,&state)==-ENODEV);
 assert(STATE_AT(0,&state)==0 && state.identity==(uintptr_t)&device);
 assert(state.registrations==1 && state.transfers==0);
 assert(state.channel==0 && state.base==0x12800c00u);
 assert(STATE_WRAPPER(NULL)==-EINVAL);
 assert(STATE_WRAPPER(&state)==0 && state.identity==(uintptr_t)&device);
 assert(state.channel==0 && state.base==0x12800c00u);

 /* Distinct stored coordinates expose an observer that echoes the index. */
 DRIVER_STATE[0].channel=7;
 DRIVER_STATE[0].base=0x12802800u;
 g_sample_transfers[0]=3; g_sample_transfers[7]=11;
 assert(STATE_AT(0,&state)==0);
 assert(state.channel==7 && state.base==0x12802800u && state.transfers==11);
 assert(rzv2h_sci_MODE_sample_transfers()==14);

 /* A foreign retained pointer must fail without being dereferenced. */
 BOARD_STATE[0]=(void *)(uintptr_t)1;
 assert(STATE_AT(0,&state)==-ENODEV);
 BOARD_STATE[0]=&device;
 DRIVER_STATE[0].initialized=false;
 assert(STATE_AT(0,&state)==-ENODEV);
 DRIVER_STATE[0].initialized=true;
 assert(initializations==1 && registrations==2);
'''.replace('STATE_AT', f'rzv2h_sci_{mode}_sample_state_at').replace(
        'STATE_WRAPPER', f'rzv2h_sci_{mode}_sample_state').replace(
        'DRIVER_STATE', f'g_sci_{mode}_priv').replace(
        'BOARD_STATE', f'g_sci_{mode}').replace('sci_MODE', f'sci_{mode}')


class BoardSamples(unittest.TestCase):
    def test_internal_spi_demo_does_not_claim_external_routes(self):
        source = (BOARD / 'src/rzv2h_bringup.c').read_text()
        for loopback in (False, True):
            with self.subTest(loopback=loopback):
                code = B.PRELUDE + r'''
#define CONFIG_RZV_SPI 1
#define CONFIG_RZV2H_EXAMPLE_SUPPORT 1
#define UNUSED(x) ((void)(x))
#define LOG_INFO 0
#define LOG_ERR 1
#define syslog(...) ((void)0)
static int external_calls, example_calls;
int board_spi_initialize(void) { external_calls++; return -ENOTSUP; }
int rzv2h_app_examples(void) { example_calls++; return 0; }
'''
                if loopback:
                    code += '#define CONFIG_RZV2H_SPI_LOOPBACK_EXAMPLE 1\n'
                code += B.EXTRACT.definition(source, 'int board_bringup(void)')
                code += f'''
int main(void) {{
 assert(board_bringup()=={0 if loopback else '-ENOTSUP'});
 assert(external_calls=={0 if loopback else 1} && example_calls==1);
 return 0;
}}
'''
                B.compile_run(code)

    def test_sci_i2c_registration_retry_retains_one_lower(self):
        source = (BOARD / 'src/rzv2h_sci_i2c.c').read_text()
        start = source.index('static struct i2c_master_s *g_sci_i2c')
        end = source.index('/****************************************************************************', start)
        code = sci_sample_fixture('i2c') + r'''
#define CONFIG_RZV_SCI0_I2C 1
#define CONFIG_I2C_DRIVER 1
#define CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT 1
#define BOARD_SCI_I2C_BUS_BASE 10
#define device g_sci_i2c_priv[0].dev
static int initializations, registrations, failed;
static struct i2c_master_s *rzv_sci_i2c_initialize(int channel)
{
 assert(channel==0); initializations++;
 g_sci_i2c_priv[0].initialized=true;
 g_sci_i2c_priv[0].channel=0;
 g_sci_i2c_priv[0].base=0x12800c00u;
 return &device;
}
static int i2c_register(struct i2c_master_s *dev, int bus)
{ assert(dev==&device && bus==10); registrations++; return failed ? -EACCES : 0; }
''' + source[start:end] + B.EXTRACT.definition(source, 'int rzv2h_sci_i2c_setup(void)')
        for signature in ('int rzv2h_sci_i2c_sample_state_at(',
                          'int rzv2h_sci_i2c_sample_state('):
            code += B.EXTRACT.definition(source, signature)
        code += r'''
int main(void)
{
 failed=1; assert(rzv2h_sci_i2c_setup()==-EACCES);
 assert(initializations==1 && registrations==1 && !g_registered[0]);
 failed=0; assert(rzv2h_sci_i2c_setup()==0);
 assert(initializations==1 && registrations==2 && g_registered[0]);
 assert(rzv2h_sci_i2c_setup()==0 && initializations==1 && registrations==2);
''' + board_observation_assertions('i2c') + r'''
 return 0;
}
'''
        B.compile_run(code)

    def test_sci_spi_registration_retry_and_singleton(self):
        source = (BOARD / 'src/rzv2h_sci_spi.c').read_text()
        start = source.index('static struct spi_dev_s *g_sci_spi')
        end = source.index('\n#ifndef CONFIG_RZV2H_SAMPLE_CONTROLLED_INIT', start)
        code = sci_sample_fixture('spi') + r'''
#define CONFIG_RZV_SCI0_SPI 1
#define CONFIG_SPI_DRIVER 1
#define spierr(...) ((void)0)
#define spiinfo(...) ((void)0)
#define UNUSED(value) ((void)(value))
#define device g_sci_spi_priv[0].dev
static int initializations, registrations, failed;
static int rzv2h_sci0_spi_setup(void) {return 0;}
static struct spi_dev_s *rzv_sci_spi_initialize(int channel)
{
 assert(channel==0); initializations++;
 g_sci_spi_priv[0].initialized=true;
 g_sci_spi_priv[0].channel=0;
 g_sci_spi_priv[0].base=0x12800c00u;
 return &device;
}
static int spi_register(struct spi_dev_s *dev, int bus)
{ assert(dev==&device && bus==0); registrations++; return failed ? -EACCES : 0; }
''' + source[start:end]
        for signature in ('static bool rzv2h_sci_spi_enabled(',
                          'int board_sci_spi_initialize(void)',
                          'int rzv2h_sci_spi_sample_state_at(',
                          'int rzv2h_sci_spi_sample_state('):
            code += B.EXTRACT.definition(source, signature)
        code += r'''
int main(void)
{
 failed=1; assert(board_sci_spi_initialize()==-EACCES);
 assert(initializations==1 && registrations==1 && !g_registered[0]);
 assert(!g_initialized[0] && g_sci_spi[0]==&device);
 failed=0; assert(board_sci_spi_initialize()==0);
 assert(initializations==1 && registrations==2 && g_registered[0]);
 assert(g_initialized[0] && g_cs_ready);
 assert(board_sci_spi_initialize()==0 && initializations==1 && registrations==2);
''' + board_observation_assertions('spi') + r'''
 return 0;
}
'''
        B.compile_run(code)

    def test_sci_sample_getters_reject_invalid_lowers_and_report_stored_state(self):
        for mode in ('i2c', 'spi'):
            with self.subTest(mode=mode):
                code = sci_sample_fixture(mode) + r'''
int main(void)
{
 unsigned int channel=UINT_MAX;
 uintptr_t base=UINTPTR_MAX;
 assert(GET_INSTANCE(NULL,&channel,&base)==-EINVAL);
 assert(GET_INSTANCE(&PRIVATE[0].dev,NULL,&base)==-EINVAL);
 assert(GET_INSTANCE(&PRIVATE[0].dev,&channel,NULL)==-EINVAL);
 assert(GET_INSTANCE((void *)(uintptr_t)1,&channel,&base)==-ENODEV);
 assert(channel==UINT_MAX && base==UINTPTR_MAX);
 for(unsigned int index=0;index<10;index++) {
   assert(GET_INSTANCE(&PRIVATE[index].dev,&channel,&base)==-ENODEV);
   assert(channel==UINT_MAX && base==UINTPTR_MAX);
   PRIVATE[index].initialized=true;
   PRIVATE[index].channel=(index+3)%10;
   PRIVATE[index].base=0x12800c00u+PRIVATE[index].channel*0x400u;
   assert(GET_INSTANCE(&PRIVATE[index].dev,&channel,&base)==0);
   assert(channel==PRIVATE[index].channel && base==PRIVATE[index].base);
   PRIVATE[index].initialized=false;
   channel=UINT_MAX; base=UINTPTR_MAX;
   assert(GET_INSTANCE(&PRIVATE[index].dev,&channel,&base)==-ENODEV);
   assert(channel==UINT_MAX && base==UINTPTR_MAX);
 }
 assert(rzv2h_sci_MODE_sample_transfers_at(10)==0);
 assert(rzv2h_sci_MODE_sample_transfers()==0);
 return 0;
}
'''
                code = code.replace('GET_INSTANCE', f'rzv_sci_{mode}_sample_instance').replace(
                    'PRIVATE', f'g_sci_{mode}_priv').replace('sci_MODE', f'sci_{mode}')
                B.compile_run(code)

    def test_riic_sample_counters_are_indexed_and_aggregate_remains_available(self):
        source = (ARCH / 'rzv_i2c.c').read_text()
        board = (BOARD / 'src/rzv2h_i2c.c').read_text()
        code = '#define _POSIX_C_SOURCE 200809L\n' + B.PRELUDE + r'''
#include <sys/types.h>
#include <time.h>
#define FAR
#define CODE
#define CONFIG_RZV2H_SAMPLE_TEST_API 1
#define NXMUTEX_INITIALIZER 0
#define container_of(ptr,type,member) ((type *)((char *)(ptr)-offsetof(type,member)))
#define i2cerr(...) ((void)0)
typedef int sem_t;
typedef int mutex_t;
typedef unsigned irqstate_t;
'''
        code += without_includes((ARCH.parents[3] / 'include/nuttx/i2c/i2c_master.h').read_text())
        code += without_includes((ARCH / 'hardware/rzv_i2c.h').read_text())
        code += bus_sample_state_type()
        for pattern in (
            r'enum rzv_i2c_state_e\s*\{.*?\n\};',
            r'struct rzv_i2c_priv_s\s*\{.*?\n\};',
            r'static struct rzv_i2c_priv_s g_riic_priv\[[^;]*;',
            r'static mutex_t g_riic_lock[^;]*;',
            r'static uint32_t g_sample_transfers\[[^;]*;',
            r'^#define RIIC_TIMEOUT_MS[^\n]*',
        ):
            code += re.search(pattern, source, re.S | re.M).group() + '\n'
        code += re.search(r'static struct i2c_master_s \*g_i2c\[[^;]*;', board).group() + '\n'
        code += r'''
static struct rzv_i2c_priv_s *active;
static bool locked;
static unsigned int touches, starts, completions;
static int nxmutex_lock(mutex_t *lock) {
  assert(lock==&g_riic_lock && !locked); locked=true; return 0;
}
static int nxmutex_unlock(mutex_t *lock) {
  assert(lock==&g_riic_lock && locked); locked=false; return 0;
}
static int nxsem_wait_uninterruptible(sem_t *sem) {
  assert(locked && active==NULL);
  for(unsigned int index=0;index<RZV_RIIC_MAX_CHANNELS;index++) {
    if(sem==&g_riic_priv[index].sem_excl) {
      assert(g_riic_priv[index].refs>0);
      active=&g_riic_priv[index]; return 0;
    }
  }
  assert(false); return -EINVAL;
}
static int nxsem_reset(sem_t *sem,int value) {
  assert(active && sem==&active->sem_isr && value==0); return 0;
}
static int nxsem_post(sem_t *sem) {
  assert(active && sem==&active->sem_excl && !locked);
  active=NULL; return 0;
}
static void rzv_i2c_set_nack(struct rzv_i2c_priv_s *priv,bool nack) {
  assert(priv==active && !nack); ++touches;
}
static uint8_t rzv_i2c_getreg(struct rzv_i2c_priv_s *priv,unsigned int offset) {
  assert(priv==active && offset==RZV_RIIC_ICSR2_OFFSET); ++touches; return 0;
}
static void rzv_i2c_putreg(struct rzv_i2c_priv_s *priv,unsigned int offset,uint8_t value) {
  assert(priv==active && (offset==RZV_RIIC_ICSR2_OFFSET || offset==RZV_RIIC_ICIER_OFFSET));
  (void)value; ++touches;
}
static void rzv_i2c_sendstart(struct rzv_i2c_priv_s *priv) {
  assert(priv==active && priv->state==RIIC_STATE_START && !locked); ++starts;
}
static int nxsem_timedwait_uninterruptible(sem_t *sem,const struct timespec *deadline) {
  assert(active && sem==&active->sem_isr && deadline->tv_sec>0);
  assert(starts==completions+1); ++completions; return 0;
}
static irqstate_t enter_critical_section(void) { assert(false); return 0; }
static void leave_critical_section(irqstate_t flags) { (void)flags; assert(false); }
static void rzv_i2c_abort(struct rzv_i2c_priv_s *priv) { (void)priv; assert(false); }
'''
        for signature in ('static int rzv_i2c_acquire(',
                          'static int rzv_i2c_transfer(',
                          'int rzv_i2c_sample_channel(',
                          'uintptr_t rzv_i2c_sample_base(',
                          'uint32_t rzv2h_riic_sample_transfers(',
                          'uint32_t rzv2h_riic_sample_transfers_at('):
            code += B.EXTRACT.definition(source, signature)
        for signature in ('int rzv2h_riic_sample_state_at(',
                          'int rzv2h_riic_sample_state('):
            code += B.EXTRACT.definition(board, signature)
        code += r'''
int main(void)
{
 uint8_t payload=0x55;
 struct i2c_msg_s message={.frequency=100000,.addr=0x42,.buffer=&payload,.length=1};
 struct rzv2h_bus_sample_state_s state;
 assert(rzv2h_riic_sample_transfers_at(0)==0 && rzv2h_riic_sample_transfers_at(8)==0);
 assert(rzv2h_riic_sample_transfers_at(9)==0 && rzv2h_riic_sample_transfers_at(UINT_MAX)==0);
 assert(rzv2h_riic_sample_transfers()==0);
 assert(rzv2h_riic_sample_state_at(-1,&state)==-EINVAL);
 assert(rzv2h_riic_sample_state_at(9,&state)==-EINVAL);
 assert(rzv2h_riic_sample_state_at(INT_MAX,&state)==-EINVAL);
 assert(rzv2h_riic_sample_state_at(0,NULL)==-EINVAL && rzv2h_riic_sample_state(NULL)==-EINVAL);
 assert(rzv_i2c_sample_channel(NULL)==-EINVAL && rzv_i2c_sample_base(NULL)==0);
 assert(rzv_i2c_sample_channel((void *)(uintptr_t)1)==-EINVAL);
 assert(rzv_i2c_sample_base((void *)(uintptr_t)1)==0);
 assert(rzv_i2c_transfer(NULL,&message,1)==-EINVAL);
 assert(rzv_i2c_transfer(&g_riic_priv[0].dev,NULL,1)==-EINVAL);
 assert(rzv_i2c_transfer(&g_riic_priv[0].dev,&message,0)==-EINVAL);
 assert(rzv_i2c_transfer((void *)(uintptr_t)1,&message,1)==-EINVAL);
 assert(rzv_i2c_transfer(&g_riic_priv[8].dev,&message,1)==-ENODEV);
 assert(!touches && !starts && !locked && active==NULL && rzv2h_riic_sample_transfers()==0);

 g_riic_priv[0].refs=1; g_riic_priv[0].port=0; g_riic_priv[0].base=RZV_RIIC0_BASE;
 g_riic_priv[8].refs=1; g_riic_priv[8].port=8; g_riic_priv[8].base=RZV_RIIC8_BASE;
 g_i2c[0]=&g_riic_priv[0].dev; g_i2c[8]=&g_riic_priv[8].dev;
 assert(rzv_i2c_transfer(g_i2c[8],&message,1)==0);
 assert(rzv2h_riic_sample_transfers_at(8)==1 && rzv2h_riic_sample_transfers_at(0)==0);
 assert(rzv2h_riic_sample_transfers()==1);
 assert(rzv_i2c_transfer(g_i2c[0],&message,1)==0 && rzv_i2c_transfer(g_i2c[0],&message,1)==0);
 assert(rzv2h_riic_sample_transfers_at(0)==2 && rzv2h_riic_sample_transfers_at(8)==1);
 assert(rzv2h_riic_sample_transfers()==3);
 for(unsigned int channel=1;channel<8;channel++) assert(rzv2h_riic_sample_transfers_at(channel)==0);
 assert(rzv2h_riic_sample_state_at(0,&state)==0);
 assert(state.identity==(uintptr_t)g_i2c[0] && state.channel==0 && state.base==RZV_RIIC0_BASE);
 assert(state.transfers==2);
#ifdef CONFIG_I2C_DRIVER
 assert(state.registrations==1);
#else
 assert(state.registrations==0);
#endif
 assert(rzv2h_riic_sample_state_at(8,&state)==0);
 assert(state.identity==(uintptr_t)g_i2c[8] && state.channel==8 && state.base==RZV_RIIC8_BASE);
 assert(state.transfers==1);
#ifdef CONFIG_I2C_DRIVER
 assert(state.registrations==1);
#else
 assert(state.registrations==0);
#endif
 assert(rzv2h_riic_sample_state(&state)==0 && state.transfers==2 && state.channel==0);
 assert(rzv2h_riic_sample_state_at(1,&state)==0);
 assert(!state.identity && state.channel==(unsigned int)-EINVAL && !state.base && !state.transfers && !state.registrations);
 g_riic_priv[8].refs=0;
 unsigned int saved=touches;
 assert(rzv_i2c_transfer(g_i2c[8],&message,1)==-ENODEV);
 assert(touches==saved && rzv2h_riic_sample_transfers_at(8)==1 && rzv2h_riic_sample_transfers()==3);
 assert(starts==3 && completions==3 && !locked && active==NULL);
 return 0;
}
'''
        for register in (False, True):
            with self.subTest(i2c_driver=register):
                B.compile_run(('#define CONFIG_I2C_DRIVER 1\n' if register else '') + code)

    def test_dmac_partial_failure_retry_preserves_initialized_unit(self):
        source = (BOARD / 'src/rzv2h_dmac.c').read_text()
        header = (BOARD / 'include/rzv2h-sample-test.h').read_text()
        enum = header[header.index('typedef enum'):header.index('} rzv2h_dmac_periph_t;')+len('} rzv2h_dmac_periph_t;')]
        code = B.PRELUDE + enum + r'''
#define RZV_DMAC_NUM_UNITS 2
#define RZV_DMAC_CHANNELS_PER_UNIT 16
#define RZV_DMAC_MAX_CHANNELS 32
#define dmainfo(...) ((void)0)
#define dmaerr(...) ((void)0)
static uint32_t g_initialized_units;
static int g_dmac_channel_map[DMAC_PERIPH_COUNT];
static int calls[2], failed;
static void rzv2h_dmac_check_collisions(void) {}
static int rzv_dmac_channel_initialize(int channel)
{int unit=channel/16; calls[unit]++; return unit==failed ? -ETIMEDOUT : 0;}
''' + B.EXTRACT.definition(source, 'int rzv2h_dmac_setup(void)') + r'''
int main(void)
{
 for(int i=0;i<DMAC_PERIPH_COUNT;i++) g_dmac_channel_map[i]=-1;
 g_dmac_channel_map[DMAC_PERIPH_UART0_RX]=0;
 g_dmac_channel_map[DMAC_PERIPH_UART0_TX]=16;
 failed=1; assert(rzv2h_dmac_setup()==-ETIMEDOUT && g_initialized_units==1);
 failed=-1; assert(rzv2h_dmac_setup()==0 && g_initialized_units==3);
 assert(calls[0]==1 && calls[1]==2);
 assert(rzv2h_dmac_setup()==0 && calls[0]==1 && calls[1]==2);
 return 0;
}
'''
        B.compile_run(code)

    def test_paramfs_rejects_foreign_busy_mount(self):
        source = (BOARD / 'src/rzv2h_volatile_paramfs.c').read_text()
        code = B.PRELUDE + r'''
#define RZV2H_PARAM_MOUNTPOINT "/fs"
#define TMPFS_MAGIC 0x01021994u
#define syslog(...) ((void)0)
struct statfs {unsigned int f_type;};
static int mount_result; static unsigned int type;
static int mkdir(const char *path, unsigned int mode) {(void)path;(void)mode;return 0;}
static int nx_mount(const char *src,const char *path,const char *fs,unsigned int flags,const void *data)
{(void)src;(void)path;(void)fs;(void)flags;(void)data;return mount_result;}
static int statfs(const char *path,struct statfs *out) {(void)path;out->f_type=type;return 0;}
''' + B.EXTRACT.definition(source, 'int rzv2h_volatile_paramfs_initialize(void)') + r'''
int main(void)
{
 mount_result=-EBUSY; type=0xdead;
 assert(rzv2h_volatile_paramfs_initialize()==-EBUSY);
 type=TMPFS_MAGIC; assert(rzv2h_volatile_paramfs_initialize()==0);
 mount_result=-ENOTDIR; assert(rzv2h_volatile_paramfs_initialize()==0);
 mount_result=-EACCES; assert(rzv2h_volatile_paramfs_initialize()==-EACCES);
 return 0;
}
'''
        B.compile_run(code)

    def test_paramfs_directory_wrapper_pins_actual_mount_inode(self):
        source = (BOARD / 'src/rzv2h_volatile_paramfs.c').read_text()
        code = B.PRELUDE + r"""
#define RZV2H_PARAM_MOUNTPOINT "/fs"
#define TMPFS_MAGIC 0x01021994u
#define O_RDONLY 0
#define O_DIRECTORY 1
#define INODE_IS_MOUNTPT(n) ((n)->mount)
struct statfs { unsigned f_type, f_files; };
struct inode;
struct ops { int (*statfs)(struct inode *, struct statfs *); };
struct inode { bool mount; union { struct ops *i_mops; } u; void *i_private; };
struct fs_dirent_s { struct inode *fd_root; };
struct file { struct inode *f_inode; void *f_priv; };
struct rzv2h_paramfs_sample_state_s { uintptr_t identity; unsigned filesystem_type, files; };
static int stat_result, closes, open_result;
static int fsstat(struct inode *inode, struct statfs *out)
{ (void)inode; out->f_type=TMPFS_MAGIC; out->f_files=0; return stat_result; }
static struct ops ops={fsstat};
static struct inode actual={.mount=true,.u.i_mops=&ops,.i_private=(void *)0x1234};
static struct inode wrapper;
static struct fs_dirent_s dir={.fd_root=&actual};
static int file_open(struct file *out,const char *path,int flags)
{ (void)path; (void)flags; out->f_inode=&wrapper; out->f_priv=&dir; return open_result; }
static int file_close(struct file *f) { (void)f; closes++; return 0; }
""" + B.EXTRACT.definition(source, 'int rzv2h_paramfs_sample_state(') + r"""
int main(void)
{
 struct rzv2h_paramfs_sample_state_s out;
 assert(rzv2h_paramfs_sample_state(NULL)==-EINVAL && closes==0);
 assert(rzv2h_paramfs_sample_state(&out)==0 && closes==1);
 assert(out.identity==0x1234 && out.filesystem_type==TMPFS_MAGIC && out.files==0);
 stat_result=-EIO; assert(rzv2h_paramfs_sample_state(&out)==-EIO && closes==2);
 stat_result=0; actual.mount=false;
 assert(rzv2h_paramfs_sample_state(&out)==-ENOSYS && closes==3);
 open_result=-ENOENT; assert(rzv2h_paramfs_sample_state(&out)==-ENOENT && closes==3);
 return 0;
}
"""
        B.compile_run(code)

    def test_local_ipc_requires_interrupt_before_read(self):
        source = (BOARD / 'src/rzv2h_ipc_local.c').read_text()
        start = source.index('static struct\n{')
        end = source.index('static int local_interrupt', start)
        code = B.PRELUDE + r'''
#define LOCAL_BYTES 64
#define LOCAL_SGI 15
typedef int irqstate_t;
struct file {int unused;};
static unsigned int interrupts; static int sgi_failed;
static int depth;
static int enter_critical_section(void) {depth++;return 0;}
static void leave_critical_section(int f) {(void)f;depth--;}
static int arm_cpu_sgi(int sgi,unsigned int cpuset)
{assert(sgi==15&&cpuset==0&&depth==1);interrupts++;return sgi_failed?-EIO:0;}
''' + source[start:end]
        for signature in ('static int local_interrupt(', 'static int local_open(', 'static int local_close(', 'static ssize_t local_write(', 'static ssize_t local_read('):
            code += B.EXTRACT.definition(source, signature)
        code = code.replace('__asm__ volatile ("dsb sy" ::: "memory");', '(void)0;')
        # Only the ARM barrier is substituted; the SGI recorder deliberately
        # does not dispatch the ISR. This is host lifecycle evidence.
        code = '#include <sys/types.h>\n' + code
        code += r'''
int main(void)
{
 struct file f={0};char tx[64],rx[64];memset(tx,0xa5,sizeof(tx));
 assert(local_open(&f)==0 && local_open(&f)==-EBUSY);
 assert(local_read(&f,rx,sizeof(rx))==-EAGAIN);
 assert(local_write(&f,tx,63)==-EMSGSIZE && !interrupts);
 assert(local_write(&f,tx,64)==64 && interrupts==1);
 assert(local_read(&f,rx,64)==-EAGAIN);
 assert(local_write(&f,tx,64)==-EAGAIN);
 local_interrupt(15,NULL,NULL);
 assert(local_read(&f,rx,64)==64 && memcmp(tx,rx,64)==0 && g_local.interrupts==1);
 assert(local_read(&f,rx,64)==-EAGAIN);
 assert(local_close(&f)==0 && !g_local.opens && !g_local.readable && !g_local.pending);
 assert(local_open(&f)==0 && local_read(&f,rx,64)==-EAGAIN);
 sgi_failed=1;assert(local_write(&f,tx,64)==-EIO && !g_local.pending);
 assert(local_close(&f)==0 && depth==0);
 return 0;
}
'''
        # The real VFS callback signatures carry unused context arguments.
        # Keep all other warning classes fatal in the extracted host harness.
        with B.tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / 'test.c').write_text(code)
            B.subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',
                              '-Wno-unused-parameter',str(path/'test.c'),'-o',str(path/'test')],check=True)
            B.subprocess.run([str(path/'test')],check=True)

    def test_architecture_self_sgi_uses_physical_register(self):
        arch = ROOT / 'platforms/nuttx/NuttX/nuttx/arch/arm/src/rzv'
        source = (arch/'rzv_irq.c').read_text()
        header = re.sub(r'^\s*#\s*include[^\n]*$', '', (arch/'hardware/rzv_intc_gic.h').read_text(), flags=re.M)
        code = B.PRELUDE + header + r'''
static int writes;
static void putreg32(uint32_t value,uintptr_t address)
{assert(value==0x0200000f&&address==0x12c11f00);writes++;}
''' + B.EXTRACT.definition(source, 'int arm_cpu_sgi(') + r'''
int main(void)
{
 assert(arm_cpu_sgi(-1,0)==-EINVAL&&arm_cpu_sgi(16,0)==-EINVAL&&!writes);
 assert(arm_cpu_sgi(15,0)==0&&writes==1);
 return 0;
}
'''
        B.compile_run(code)
        self.assertNotIn('putreg', (BOARD/'src/rzv2h_ipc_local.c').read_text())

if __name__ == '__main__': unittest.main()
