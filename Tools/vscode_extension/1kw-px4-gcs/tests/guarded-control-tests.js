// Arm, disarm, mode and reboot against the real sidecar and vehicle peer:
// each precondition refuses without a dialog, declining sends nothing, the
// acknowledgement is named, a state change during the dialog is caught, and
// every outcome is journaled once. Plus the confirmation texts themselves.
const assert = require('assert');
const path = require('path');
const { Peer, PYTHON, PYTHON_DIR, freeUdpPort, sleep, tempDir, waitFor } = require('./bridge-test-harness');

function buildInternals(extDir) {
  const out = path.join(tempDir('px4-gcs-control-'), 'control.js');
  require('esbuild').buildSync({
    stdin: {
      contents: [
        "export * from './src/connection/connection-controller';", "export * from './src/vehicle/vehicle-state-store';",
        "export * from './src/session/session-journal';", "export * from './src/control/guarded-command-service';",
        "export * from './src/control/command-preconditions';", "export * from './src/control/confirmation-text';",
      ].join('\n'),
      resolveDir: extDir, loader: 'ts',
    },
    bundle: true, platform: 'node', format: 'cjs', target: 'node18', outfile: out, logLevel: 'silent',
  });
  return require(out);
}

const CMD = { arm: 400, mode: 176, reboot: 246 };

async function setup(I, peerConfig = {}) {
  const port = await freeUdpPort();
  const peer = new Peer({ udpTarget: `127.0.0.1:${port}`, config: peerConfig });
  await peer.ready;
  const store = new I.VehicleStateStore();
  const controller = new I.ConnectionController({ pythonDir: PYTHON_DIR, store, log: () => {} });
  const journal = new I.SessionJournal();
  const ctx = { peer, store, controller, journal, answers: [], shown: [], control: true, shift: 0, during: undefined };
  ctx.service = new I.GuardedCommandService({
    controller, store, journal,
    controlEnabled: () => ctx.control,
    now: () => Date.now() + ctx.shift,
    confirm: async (confirmation) => {
      ctx.shown.push(confirmation);
      if (ctx.during) await ctx.during();
      return ctx.answers.shift() === true;
    },
  });
  ctx.commands = (id) => peer.received('COMMAND_LONG').filter((e) => id === undefined || e.command === id);
  ctx.beat = () => store.get('heartbeat');
  ctx.stop = async () => {
    await controller.dispose();
    store.dispose();
    await peer.stop();
  };
  await controller.connect(PYTHON, async () => ({ transport: 'udp', host: '127.0.0.1', port, controlEnabled: true,
    sessionId: 't' }));
  await waitFor(() => ctx.beat() !== undefined, 5000, 'first heartbeat');
  return ctx;
}

async function preconditionsRefuseWithoutDialog(I) {
  const ctx = await setup(I);
  const { service, journal } = ctx;
  ctx.control = false;
  let outcome = await service.run('arm');
  assert.equal(outcome.result, 'refused');
  assert.match(outcome.message, /control is off/i);
  ctx.control = true;
  ctx.shift = 5000;
  outcome = await service.run('arm');
  assert.equal(outcome.result, 'refused');
  assert.match(outcome.message, /heartbeat/i);
  ctx.shift = 0;
  outcome = await service.run('set_mode', 'NO_SUCH_MODE');
  assert.equal(outcome.result, 'refused');
  assert.equal(ctx.shown.length, 0, 'a refusal shows no dialog');
  await ctx.controller.disconnect();
  outcome = await service.run('disarm');
  assert.equal(outcome.result, 'refused');
  assert.match(outcome.message, /not connected|connect/i);
  assert.equal(ctx.shown.length, 0);
  assert.equal(ctx.commands().filter((e) => [400, 176, 246].includes(e.command)).length, 0, 'nothing was sent');
  const entries = journal.entries('command');
  assert.equal(entries.length, 4, 'one journal entry per refusal');
  assert.ok(entries.every((e) => e.data.decision === 'refused'));
  await ctx.stop();
  console.log('  ok control off, stale heartbeat, unknown mode and no link refuse without a dialog');
}

async function declineArmDisarm(I) {
  const ctx = await setup(I, { armed: false });
  const { service, journal } = ctx;
  ctx.answers.push(false);
  let outcome = await service.run('arm');
  assert.equal(outcome.result, 'declined');
  assert.equal(ctx.shown[0].button, 'Arm');
  assert.match(ctx.shown[0].detail, /Propellers may spin/);
  await sleep(300);
  assert.equal(ctx.commands(CMD.arm).length, 0, 'declining sends nothing');

  ctx.answers.push(true);
  outcome = await service.run('arm');
  assert.equal(outcome.result, 'accepted', outcome.message);
  const arms = ctx.commands(CMD.arm);
  assert.equal(arms.length, 1, 'sent once');
  assert.equal(arms[0].param1, 1);
  assert.notEqual(arms[0].param2, 21196, 'never a forced arm');
  await waitFor(() => ctx.beat()?.armed === true, 5000, 'armed heartbeat');

  ctx.answers.push(true);
  outcome = await service.run('disarm');
  assert.equal(outcome.result, 'accepted', outcome.message);
  assert.equal(ctx.commands(CMD.arm)[1].param1, 0);
  assert.ok(ctx.commands(CMD.arm).every((e) => e.param2 !== 21196));
  await waitFor(() => ctx.beat()?.armed === false, 5000, 'disarmed heartbeat');
  const decisions = journal.entries('command').map((e) => `${e.data.action}:${e.data.decision}:${e.data.result}`);
  assert.deepEqual(decisions, ['arm:declined:declined', 'arm:confirmed:accepted', 'disarm:confirmed:accepted']);
  await ctx.stop();
  console.log('  ok declined arm sends nothing; arm and disarm accepted once each, never forced');
}

async function armDenied(I) {
  const ctx = await setup(I, { ackResults: { 400: 1 } });
  ctx.answers.push(true);
  let outcome = await ctx.service.run('arm');
  assert.equal(outcome.result, 'temporarily rejected');
  assert.match(outcome.message, /Arm: temporarily rejected/);
  await ctx.stop();
  const denied = await setup(I, { ackResults: { 400: 4 } });
  denied.answers.push(true);
  outcome = await denied.service.run('arm');
  assert.equal(outcome.result, 'failed');
  assert.match(outcome.message, /Arm: failed/);
  assert.equal(denied.commands(CMD.arm).length, 1, 'no retry after a rejection');
  await denied.stop();
  console.log('  ok a rejected arm is named and not retried');
}

async function modeChange(I) {
  const ctx = await setup(I, { availableModes: true });
  const { service } = ctx;
  await waitFor(() => ctx.store.get('modes')?.reported === true, 5000, 'available modes');
  let outcome = await service.run('set_mode', 'ALTCTL');
  assert.equal(outcome.result, 'refused');
  assert.match(outcome.message, /not available on this vehicle/);
  assert.equal(ctx.shown.length, 0);

  ctx.answers.push(true);
  outcome = await service.run('set_mode', 'AUTO_LOITER');
  assert.equal(outcome.result, 'accepted', outcome.message);
  assert.match(ctx.shown[0].message + ctx.shown[0].detail, /Position → Hold|Position.*Hold/);
  await waitFor(() => ctx.beat()?.modeKey === 'AUTO_LOITER', 5000, 'mode in the heartbeat');
  const sent = ctx.commands(CMD.mode);
  assert.equal(sent.length, 1);
  await ctx.stop();
  console.log('  ok an unavailable mode is refused; Hold is accepted and shows in the heartbeat');
}

async function rebootCases(I) {
  const ctx = await setup(I, { armed: false });
  ctx.answers.push(true);
  let outcome = await ctx.service.run('reboot');
  assert.equal(outcome.result, 'accepted', outcome.message);
  assert.match(ctx.shown[0].detail, /RAM-loaded image is lost/);
  assert.equal(ctx.commands(CMD.reboot).length, 1);

  // The vehicle arms while the dialog is open: the late check refuses.
  ctx.during = async () => {
    ctx.peer.selfArm();
    await waitFor(() => ctx.beat()?.armed === true, 5000, 'self-armed heartbeat');
  };
  ctx.answers.push(true);
  outcome = await ctx.service.run('reboot');
  assert.equal(outcome.result, 'refused');
  assert.match(outcome.message, /^Not sent: .*armed/);
  assert.equal(ctx.commands(CMD.reboot).length, 1, 'the second reboot was not sent');
  ctx.during = undefined;
  outcome = await ctx.service.run('reboot');
  assert.equal(outcome.result, 'refused', 'armed: refused before any dialog');
  assert.equal(ctx.shown.length, 2);
  const last = ctx.journal.entries('command').slice(-2).map((e) => e.data.decision);
  assert.deepEqual(last, ['confirmed', 'refused']);
  await ctx.stop();

  const denied = await setup(I, { armed: false, ackResults: { 246: 4 } });
  denied.answers.push(true);
  outcome = await denied.service.run('reboot');
  assert.equal(outcome.result, 'failed');
  assert.match(outcome.message, /Reboot: failed/);
  await denied.stop();
  console.log('  ok reboot accepted; arming during the dialog refuses it; a denied reboot is named');
}

function confirmationTexts(I) {
  const state = {
    controlEnabled: true, connection: 'connected', heartbeatAgeMs: 100, armed: false, modeKey: 'POSCTL',
    modeName: 'Position', systemId: 1, componentId: 1, transport: '/dev/ttyUSB0 @ 57600', availableModes: null,
  };
  let c = I.commandConfirmation('arm', state);
  assert.equal(c.button, 'Arm');
  assert.match(c.detail, /Position/);
  assert.match(c.detail, /\/dev\/ttyUSB0 @ 57600/);
  assert.ok(!c.detail.includes(I.NO_RC_SENTENCE), 'Position is not automatic');
  c = I.commandConfirmation('arm', { ...state, modeKey: 'AUTO_TAKEOFF', modeName: 'Takeoff' });
  assert.match(c.detail, /Takeoff is an automatic mode/);
  assert.ok(c.detail.includes(I.NO_RC_SENTENCE), 'automatic mode: the no-RC sentence');
  c = I.commandConfirmation('set_mode', { ...state, modeKey: 'AUTO_LOITER', modeName: 'Hold' },
    { key: 'POSCTL', name: 'Position', main: 3, sub: 0, needsSticks: true });
  assert.match(c.detail, /Position needs stick input\. This extension sends no stick input/);
  c = I.commandConfirmation('set_mode', { ...state, armed: true }, { key: 'AUTO_RTL', name: 'Return', main: 4, sub: 5,
    needsSticks: false });
  assert.match(c.detail, /changes its behaviour immediately/);
  assert.equal(I.commandRefusal('reboot', { ...state, armed: null }) !== undefined, true, 'unknown armed: no reboot');
  assert.equal(I.resultText('MAV_RESULT_TEMPORARILY_REJECTED'), 'temporarily rejected');
  console.log('  ok confirmation texts name the mode, link, no-RC and stick consequences');
}

async function run({ EXT_DIR }) {
  const I = buildInternals(EXT_DIR);
  confirmationTexts(I);
  await preconditionsRefuseWithoutDialog(I);
  await declineArmDisarm(I);
  await armDenied(I);
  await modeChange(I);
  await rebootCases(I);
}

module.exports = { run };
