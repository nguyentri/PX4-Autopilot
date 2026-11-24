// Parameters against the real sidecar and vehicle peer: build metadata and the
// "differs from build default" mark, the edit policy and its families, typed
// writes with read-back, and QGC `.params` export, import, snapshot and restore.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { Peer, PYTHON, PYTHON_DIR, freeUdpPort, tempDir, waitFor } = require('./bridge-test-harness');

const FIXTURES = path.join(__dirname, 'fixtures');
const METADATA = path.join(FIXTURES, 'metadata', 'sim_vehicle', 'parameters.json');

function buildInternals(extDir) {
  const out = path.join(tempDir('px4-gcs-params-'), 'params.js');
  require('esbuild').buildSync({
    stdin: {
      contents: [
        "export * from './src/connection/connection-controller';", "export * from './src/vehicle/vehicle-state-store';",
        "export * from './src/session/session-journal';", "export * from './src/parameters/parameter-store';",
        "export * from './src/parameters/parameter-edit-service';", "export * from './src/parameters/parameter-edit-policy';",
        "export * from './src/parameters/parameter-import-service';", "export * from './src/parameters/parameter-metadata';",
        "export * from './src/parameters/parameter-metadata-loader';", "export * from './src/parameters/qgc-params-file';",
        "export * from './src/parameters/parameter-diff';",
      ].join('\n'),
      resolveDir: extDir, loader: 'ts',
    },
    bundle: true, platform: 'node', format: 'cjs', target: 'node18', outfile: out, logLevel: 'silent',
  });
  return require(out);
}

async function setup(I, peerConfig = {}, { metadata = true } = {}) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}`, config: { armed: false, ...peerConfig } });
  await peer.ready;
  const store = new I.VehicleStateStore();
  const controller = new I.ConnectionController({ pythonDir: PYTHON_DIR, store, log: () => {} });
  const journal = new I.SessionJournal();
  const ctx = { peer, store, controller, journal, answers: [], shown: [], previews: [], snapshots: [], values: [] };
  const confirm = async (confirmation) => {
    ctx.shown.push(confirmation);
    return ctx.answers.shift() === true;
  };
  const base = { controller, store, journal, controlEnabled: () => true, confirm };
  ctx.params = new I.ParameterStore(controller, { onState: () => {}, onValue: (e) => ctx.values.push(e) });
  ctx.editor = new I.ParameterEditService({ ...base, params: ctx.params });
  ctx.snapshotDir = tempDir('px4-gcs-snap-');
  ctx.restore = false;
  ctx.importer = new I.ParameterImportService({
    ...base, params: ctx.params, editor: ctx.editor,
    showPreview: async (text) => { ctx.previews.push(text); },
    saveSnapshot: async (text) => {
      const file = path.join(ctx.snapshotDir, `snapshot-${ctx.snapshots.length}.params`);
      fs.writeFileSync(file, text);
      ctx.snapshots.push(file);
      return file;
    },
    offerRestore: async () => ctx.restore,
    readFile: async (file) => fs.readFileSync(file, 'utf8'),
  });
  ctx.writes = () => peer.log().filter((e) => e.kind === 'param_set');
  ctx.stop = async () => {
    ctx.params.dispose();
    await controller.dispose();
    store.dispose();
    await peer.stop();
  };
  await controller.connect(PYTHON, async () => ({ transport: 'udp', host: '127.0.0.1', port, controlEnabled: true,
    sessionId: 't' }));
  await waitFor(() => store.get('heartbeat') !== undefined, 5000, 'first heartbeat');
  if (metadata) ctx.params.setMetadata(I.loadMetadataFile(METADATA));
  await ctx.params.load(false);
  assert.equal(ctx.params.state.state, 'done');
  return ctx;
}

function policyAndFamilies(I) {
  const cls = (name) => I.safetyClass(name)?.cls;
  assert.equal(cls('CAL_ACC0_PRIO'), 'sensors and estimator');
  assert.equal(cls('CA_ROTOR0_PX'), 'actuators');
  assert.equal(cls('BAT1_N_CELLS'), 'protections');
  assert.equal(cls('RC_MAP_KILL_SW'), 'radio');
  assert.equal(cls('RC1_MIN'), 'radio');
  assert.equal(cls('MAV_0_RATE'), 'link and system');
  assert.equal(cls('EKF2_GPS_CTRL'), 'sensors and estimator');
  for (const name of ['MPC_XY_VEL_MAX', 'MC_ROLLRATE_P', 'SIH_LOC_LAT0', 'MIS_TAKEOFF_ALT', 'COMX_TEST', 'RCX']) {
    assert.equal(cls(name), undefined, `${name} is not a safety family`);
  }
  assert.deepEqual(I.parseParamValue('12.5', 'REAL32'), { value: 12.5 });
  assert.ok('error' in I.parseParamValue('1.5', 'INT32'));
  assert.ok('error' in I.parseParamValue('2147483648', 'INT32'));
  assert.ok('error' in I.parseParamValue('abc', 'REAL32'));
  const meta = { name: 'X', type: 'REAL32', min: 0, max: 20, rebootRequired: true };
  const reasons = I.editReasons({ name: 'MPC_X', type: 'REAL32', value: 25, armed: true, metadataLoaded: true, meta });
  assert.equal(reasons.length, 3, reasons.join(' | '));
  assert.deepEqual(I.editReasons({ name: 'MPC_X', type: 'REAL32', value: 5, armed: false, metadataLoaded: true,
    meta: { ...meta, rebootRequired: false } }), []);
  assert.match(I.editReasons({ name: 'MPC_X', type: 'REAL32', value: 5, armed: false, metadataLoaded: false })[0],
    /no parameter metadata/);
  assert.match(I.editReasons({ name: 'MPC_X', type: 'INT32', value: 5, armed: false, metadataLoaded: true, meta })[0],
    /type REAL32 differs/);
  const dp = { name: 'X', type: 'REAL32', default: 12, decimalPlaces: 1 };
  assert.equal(I.differsFromDefault(12.0000001, 'REAL32', dp), false);
  assert.equal(I.differsFromDefault(12.2, 'REAL32', dp), true);
  assert.equal(I.differsFromDefault(5, 'INT32', { name: 'X', type: 'INT32', default: 5, volatile: true }), undefined);
  console.log('  ok edit policy: families, typed parsing, reasons, default comparison');
}

function paramsFileFormat(I) {
  const parsed = I.parseParamsFile(fs.readFileSync(path.join(FIXTURES, 'qgc-sample.params'), 'utf8'));
  assert.equal(parsed.rows.length, 9);
  assert.equal(parsed.errors.length, 1, 'the broken line is reported');
  const text = I.formatParamsFile([{ name: 'B', value: 0.1, type: 'REAL32' }, { name: 'A', value: -3, type: 'INT32' }], 1, 1,
    ['test']);
  assert.match(text, /# Vehicle-Id Component-Id Name Value Type/);
  const again = I.parseParamsFile(text);
  assert.deepEqual(again.rows.map((r) => [r.name, r.type]), [['A', 'INT32'], ['B', 'REAL32']], 'sorted, typed');
  assert.ok(I.sameParamValue(again.rows[1].value, 0.1, 'REAL32'));
  console.log('  ok QGC .params format: header, sorted rows, typed round-trip, malformed line reported');
}

async function metadataDiscovery(I) {
  const root = tempDir('px4-gcs-meta-');
  for (const build of ['board_a', 'board_b']) {
    fs.mkdirSync(path.join(root, 'build', build), { recursive: true });
    fs.copyFileSync(METADATA, path.join(root, 'build', build, 'parameters.json'));
  }
  assert.equal(I.discoverMetadataFiles([root]).length, 2);
  const memory = new Map();
  let picks = 0;
  const loader = new I.ParameterMetadataLoader({
    settingPath: () => '', workspaceFolders: () => [root], log: () => {},
    pick: async (files) => { picks += 1; return files[1]; },
    memory: { get: (k) => memory.get(k), update: async (k, v) => { memory.set(k, v); } },
  });
  let set = await loader.resolve();
  assert.equal(set.target, 'board_b');
  set = await loader.resolve();
  assert.equal(picks, 1, 'the choice is remembered');
  await loader.resolve(true);
  assert.equal(picks, 2, 'Refresh asks again');
  const meta = set.byName.get('MPC_XY_VEL_MAX');
  assert.equal(meta.type, 'REAL32');
  assert.equal(meta.max, 20);
  assert.equal(I.metadataSourceText(set), `${set.path} (board_b)`);
  console.log('  ok metadata discovery: build/*/parameters.json, pick remembered, Refresh re-asks');
}

async function editsAndDiff(I) {
  const ctx = await setup(I, { silentWrite: { TEST_F01: 'reject' } });
  const { params, editor, journal } = ctx;
  assert.equal(params.entry('MAV_0_RATE').differs, true, 'vehicle 4000, build default 1200');
  assert.equal(params.entry('MPC_XY_VEL_MAX').differs, false);
  assert.equal(params.entry('TEST_I14').differs, undefined, 'volatile: no mark');
  assert.equal(params.entry('MPC_XY_VEL_MAX').meta.units, 'm/s');
  assert.equal(params.entry('TEST_I13').meta.typeMismatch, 'REAL32');
  assert.equal(params.state.metadata, I.metadataSourceText(params.metadata));

  let outcome = await editor.edit('MPC_XY_VEL_MAX', '10.5');
  assert.equal(outcome.result, 'applied', outcome.message);
  assert.equal(ctx.shown.length, 0, 'an in-range edit with metadata applies without a dialog');
  assert.equal(params.entry('MPC_XY_VEL_MAX').value, 10.5);
  assert.equal(params.entry('MPC_XY_VEL_MAX').differs, true);
  assert.ok(ctx.values.some((e) => e.name === 'MPC_XY_VEL_MAX'), 'the row update is emitted');

  const before = ctx.writes().length;
  ctx.answers.push(false);
  outcome = await editor.edit('MPC_XY_VEL_MAX', '25');
  assert.equal(outcome.result, 'declined');
  assert.match(ctx.shown[0].detail, /above the maximum 20/);
  assert.equal(ctx.writes().length, before, 'declining writes nothing');

  ctx.answers.push(true);
  outcome = await editor.edit('TEST_I05', '-77');
  assert.equal(outcome.result, 'applied', outcome.message);
  assert.match(ctx.shown[1].detail, /not in the loaded metadata/);
  assert.equal(params.entry('TEST_I05').value, -77, 'int32 round-trip');

  ctx.answers.push(true);
  outcome = await editor.edit('MAV_0_RATE', '1200');
  assert.equal(outcome.result, 'applied', outcome.message);
  assert.match(ctx.shown[2].detail, /link and system/);
  assert.match(ctx.shown[2].detail, /reboot/);
  assert.equal(params.entry('MAV_0_RATE').differs, false);

  ctx.answers.push(true);
  outcome = await editor.edit('TEST_F01', '9.25');
  assert.equal(outcome.result, 'not applied');
  assert.match(outcome.message, /vehicle holds 0.5/);

  for (const [name, text] of [['_INTERNAL_X', '1'], ['NO_SUCH', '1'], ['TEST_I01', '1.5']]) {
    outcome = await editor.edit(name, text);
    assert.equal(outcome.result, 'refused', name);
  }
  const results = journal.entries('param_write').map((e) => e.data.result);
  assert.deepEqual(results, ['applied', 'declined', 'applied', 'applied', 'not applied', 'refused', 'refused', 'refused'],
    'one journal entry per edit');
  assert.equal(journal.entries('param_write')[0].data.old, 12);
  await ctx.stop();
  console.log('  ok edits: direct, confirmed, declined, rejected read-back, refused; differs mark follows the write');
}

async function noMetadataAlwaysConfirms(I) {
  const ctx = await setup(I, {}, { metadata: false });
  assert.equal(ctx.params.state.metadata, 'no metadata');
  ctx.answers.push(false);
  const outcome = await ctx.editor.edit('MPC_XY_VEL_MAX', '10');
  assert.equal(outcome.result, 'declined');
  assert.match(ctx.shown[0].detail, /no parameter metadata is loaded/);
  await ctx.stop();
  console.log('  ok without metadata every edit asks first');
}

async function exportImportRestore(I) {
  const ctx = await setup(I);
  const { importer, params, journal } = ctx;
  const exported = importer.exportText();
  assert.ok(!/\b_HASH_CHECK\b|\b_INTERNAL_X\b/.test(exported), 'internal parameters are not exported');
  assert.ok(!/\bTEST_I14\b/.test(exported), 'volatile parameters are not exported');
  let summary = await importer.importText(exported, 'export');
  assert.equal(summary.result, 'nothing to change', 'export then import is an empty change set');

  const sample = path.join(FIXTURES, 'qgc-sample.params');
  const plan = I.planImport(I.parseParamsFile(fs.readFileSync(sample, 'utf8')), (n) => params.entry(n), 1, 1);
  assert.deepEqual(plan.changes.map((c) => c.name).sort(), ['BAT1_N_CELLS', 'MPC_XY_VEL_MAX']);
  assert.equal(plan.changes.find((c) => c.name === 'BAT1_N_CELLS').safety, 'protections');
  assert.equal(plan.unchanged, 1, 'MPC_LAND_SPEED 0.699999988 equals 0.7 as float32');
  assert.equal(plan.ignored, 2, 'rows for vehicle 2 and component 2');
  assert.deepEqual(plan.skipped.map((s) => s.name).sort(), ['NOT_ON_VEHICLE', 'TEST_I12', 'TEST_I14', '_INTERNAL_X']);

  const before = ctx.writes().length;
  ctx.answers.push(false);
  summary = await importer.importFile(sample);
  assert.equal(summary.result, 'declined');
  assert.equal(ctx.previews.length, 1, 'the preview came first');
  assert.match(ctx.previews[0], /MPC_XY_VEL_MAX\t12 -> 10.5/);
  assert.equal(ctx.snapshots.length, 0, 'a declined import leaves no snapshot');
  assert.equal(ctx.writes().length, before);

  ctx.answers.push(true, true);
  ctx.restore = true;
  summary = await importer.importFile(sample);
  assert.equal(summary.result, 'completed', summary.message);
  assert.deepEqual(summary.applied.sort(), ['BAT1_N_CELLS', 'MPC_XY_VEL_MAX']);
  assert.equal(ctx.snapshots.length, 2, 'a snapshot before the import and one before its restore');
  assert.match(fs.readFileSync(ctx.snapshots[0], 'utf8'), /MPC_XY_VEL_MAX\t12\t9/);
  assert.equal(params.entry('MPC_XY_VEL_MAX').value, 12, 'restore returned the starting value');
  assert.equal(params.entry('BAT1_N_CELLS').value, 3);
  const imports = journal.entries('param_import').map((e) => e.data.result);
  assert.deepEqual(imports, ['nothing to change', 'declined', 'completed', 'completed'], 'one entry per run (restore included)');
  await ctx.stop();

  const armed = await setup(I, { armed: true });
  summary = await armed.importer.importFile(sample);
  assert.equal(summary.result, 'refused');
  assert.match(summary.message, /armed/);
  assert.equal(armed.previews.length + armed.shown.length, 0, 'refused before preview or dialog');
  await armed.stop();
  console.log('  ok export/import: empty round-trip, preview, decline, snapshot, restore, armed refusal');
}

async function run({ EXT_DIR }) {
  const I = buildInternals(EXT_DIR);
  policyAndFamilies(I);
  paramsFileFormat(I);
  await metadataDiscovery(I);
  await editsAndDiff(I);
  await noMetadataAlwaysConfirms(I);
  await exportImportRestore(I);
}

module.exports = { run };
