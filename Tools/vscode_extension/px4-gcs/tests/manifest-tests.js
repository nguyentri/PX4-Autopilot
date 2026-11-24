// Manifest, packaging and activation checks.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const { createVscodeStub, loadExtension } = require('./vscode-stub');

const RESTRICTED = ['px4Gcs.pythonPath', 'px4Gcs.udp.host', 'px4Gcs.parameters.metadataPath', 'px4Gcs.recording.directory'];
const EXACT = /^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/;

async function run({ EXT_DIR }) {
  const pkg = JSON.parse(fs.readFileSync(path.join(EXT_DIR, 'package.json'), 'utf8'));
  assert.equal(pkg.name, 'px4-gcs');
  assert.equal(pkg.displayName, 'Px4-GCS');
  assert.equal(pkg.publisher, 'px4-nuttx');
  assert.equal(pkg.license, 'BSD-3-Clause');
  assert.deepEqual(pkg.extensionKind, ['workspace']);
  assert.equal(pkg.engines.vscode, '^1.85.0');

  const trust = pkg.capabilities.untrustedWorkspaces;
  assert.equal(trust.supported, 'limited');
  assert.deepEqual([...trust.restrictedConfigurations].sort(), [...RESTRICTED].sort());
  const props = pkg.contributes.configuration.properties;
  for (const key of RESTRICTED) {
    assert.equal(props[key].scope, 'machine', `${key} must be machine-scoped`);
  }
  for (const [key, def] of Object.entries(props)) {
    assert.ok(key.startsWith('px4Gcs.'), key);
    assert.ok(['machine', 'window'].includes(def.scope), `${key} needs an explicit scope`);
  }
  console.log('  ok manifest identity, trust and setting scopes');

  for (const [name, version] of Object.entries({ ...pkg.dependencies, ...pkg.devDependencies })) {
    assert.match(version, EXACT, `${name} must be pinned exactly (got ${version})`);
  }
  assert.equal(Object.keys(pkg.dependencies || {}).length, 0, 'everything shipped is bundled');
  console.log('  ok every dependency version is exact');

  const icon = pkg.contributes.viewsContainers.activitybar[0].icon;
  assert.ok(fs.existsSync(path.join(EXT_DIR, icon)), 'activity bar icon exists');
  assert.ok(fs.existsSync(path.join(EXT_DIR, pkg.icon)), 'extension icon exists');
  // The dashboard panel loads these (dist files exist after the build step that precedes the tests).
  const panel = fs.readFileSync(path.join(EXT_DIR, 'src', 'dashboard', 'dashboard-panel.ts'), 'utf8');
  const assets = [...panel.matchAll(/(?:asset\(|joinPath\()(dist|media), '([\w.-]+)'\)/g)];
  assert.ok(assets.length >= 4, 'script, two style sheets and the icon are referenced');
  for (const [, base, name] of assets) {
    assert.ok(fs.existsSync(path.join(EXT_DIR, base, name)), `dashboard asset ${base}/${name} exists`);
  }
  for (const welcome of pkg.contributes.viewsWelcome) {
    for (const [, id] of welcome.contents.matchAll(/command:([\w.]+)/g)) {
      assert.ok(pkg.contributes.commands.some((c) => c.command === id), `welcome link ${id} is declared`);
    }
  }

  const bundle = path.join(EXT_DIR, 'dist', 'extension.js');
  assert.ok(fs.existsSync(bundle) && fs.statSync(bundle).size > 500, 'extension bundle exists');
  assert.ok(fs.existsSync(path.join(EXT_DIR, 'dist', 'dashboard.js')), 'dashboard bundle exists');

  const stub = createVscodeStub({ extensionPath: EXT_DIR });
  const ext = loadExtension(EXT_DIR, stub);
  ext.activate(stub.context);
  const declared = pkg.contributes.commands.map((c) => c.command).sort();
  assert.deepEqual([...stub.commands.keys()].sort(), declared, 'declared commands equal registered commands');
  await ext.deactivate();
  for (const d of stub.context.subscriptions) d.dispose();
  console.log('  ok every declared command is registered and nothing else');
}

module.exports = { run };
