// Test runner for the 1KW-Px4-GCS extension. Each suite file exports
// `async function run(ctx)`; the runner executes them in order and stops on the
// first failure with a non-zero exit code.
const path = require('path');

const EXT_DIR = path.resolve(__dirname, '..');
const REPO_ROOT = path.resolve(EXT_DIR, '../../..');

const SUITES = [
  'manifest-tests.js',
  'bridge-protocol-tests.js',
  'bridge-trust-lifecycle-tests.js',
  'serial-lease-tests.js',
  'connection-tests.js',
  'dashboard-logic-tests.js',
  'console-session-tests.js',
  'guarded-control-tests.js',
  'parameter-tests.js', 'plots-and-track-tests.js', 'log-and-session-tests.js',
];

async function main() {
  console.log('== 1KW-Px4-GCS tests ==');
  const ctx = { EXT_DIR, REPO_ROOT };
  for (const suite of SUITES) {
    console.log(`-- ${suite}`);
    await require(path.join(__dirname, suite)).run(ctx);
  }
  console.log('== all suites passed ==');
}

// A failed suite must not leave a peer or sidecar running: kill every tracked child first.
main().then(() => process.exit(0), async (err) => {
  console.error(err && err.stack ? err.stack : err);
  await require('./bridge-test-harness').killAll();
  process.exit(1);
});
