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

class BoardSamples(unittest.TestCase):
    def test_sci_i2c_registration_retry_retains_one_lower(self):
        source = (BOARD / 'src/rzv2h_sci_i2c.c').read_text()
        start = source.index('static struct i2c_master_s *g_sci_i2c')
        end = source.index('/****************************************************************************', start)
        code = B.PRELUDE + r'''
#define CONFIG_RZV_SCI0_I2C 1
#define BOARD_SCI_I2C_BUS_BASE 10
struct i2c_master_s {int unused;};
static struct i2c_master_s device;
static int initializations, registrations, failed;
static struct i2c_master_s *rzv_sci_i2c_initialize(int channel)
{ assert(channel==0); initializations++; return &device; }
static int i2c_register(struct i2c_master_s *dev, int bus)
{ assert(dev==&device && bus==10); registrations++; return failed ? -EACCES : 0; }
''' + source[start:end] + B.EXTRACT.definition(source, 'int rzv2h_sci_i2c_setup(void)') + r'''
int main(void)
{
 failed=1; assert(rzv2h_sci_i2c_setup()==-EACCES);
 assert(initializations==1 && registrations==1 && !g_registered[0]);
 failed=0; assert(rzv2h_sci_i2c_setup()==0);
 assert(initializations==1 && registrations==2 && g_registered[0]);
 assert(rzv2h_sci_i2c_setup()==0 && initializations==1 && registrations==2);
 return 0;
}
'''
        B.compile_run(code)

    def test_sci_spi_registration_retry_and_singleton(self):
        source = (BOARD / 'src/rzv2h_sci_spi.c').read_text()
        code = B.PRELUDE + r'''
#define CONFIG_RZV_SCI0_SPI 1
#define CONFIG_SPI_DRIVER 1
#define spierr(...) ((void)0)
#define spiinfo(...) ((void)0)
struct spi_dev_s {int unused;};
static struct spi_dev_s device, *g_sci_spi;
static bool g_registered;
static int initializations, registrations, failed;
static int rzv2h_sci0_spi_setup(void) {return 0;}
static struct spi_dev_s *rzv_sci_spi_initialize(int channel)
{ assert(channel==0); initializations++; return &device; }
static int spi_register(struct spi_dev_s *dev, int bus)
{ assert(dev==&device && bus==0); registrations++; return failed ? -EACCES : 0; }
''' + B.EXTRACT.definition(source, 'int board_sci_spi_initialize(void)') + r'''
int main(void)
{
 failed=1; assert(board_sci_spi_initialize()==-EACCES);
 assert(initializations==1 && registrations==1 && !g_registered);
 failed=0; assert(board_sci_spi_initialize()==0);
 assert(initializations==1 && registrations==2 && g_registered);
 assert(board_sci_spi_initialize()==0 && initializations==1 && registrations==2);
 return 0;
}
'''
        B.compile_run(code)

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
 mount_result=-EACCES; assert(rzv2h_volatile_paramfs_initialize()==-EACCES);
 return 0;
}
'''
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
