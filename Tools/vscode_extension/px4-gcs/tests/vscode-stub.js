// Minimal `vscode` module stand-in for loading the bundled extension in plain
// Node. Tests read what the extension registered and drive the recorded
// callbacks; `answers` scripts modal and pick results.
const Module = require('module');
const path = require('path');

class EventEmitter {
  constructor() { this.listeners = new Set(); this.event = (fn) => { this.listeners.add(fn); return { dispose: () => this.listeners.delete(fn) }; }; }
  fire(value) { for (const fn of [...this.listeners]) fn(value); }
  dispose() { this.listeners.clear(); }
}

function createVscodeStub(options = {}) {
  const config = { ...(options.config || {}) };
  const commands = new Map();
  const messages = [];
  const answers = options.answers || [];
  const stateStore = new Map();
  const output = [];
  const trust = { isTrusted: options.trusted !== false };
  const record = (kind) => (message, ...rest) => {
    const items = rest.filter((r) => typeof r === 'string');
    const modal = rest.some((r) => r && typeof r === 'object' && r.modal);
    messages.push({ kind, message, items, modal });
    const answer = answers.length > 0 ? answers.shift() : undefined;
    return Promise.resolve(typeof answer === 'function' ? answer(message, items) : answer);
  };
  const disposable = { dispose() {} };
  const vscode = {
    EventEmitter,
    Disposable: class { constructor(fn) { this.dispose = fn || (() => {}); } static from(...d) { return { dispose: () => d.forEach((x) => x.dispose()) }; } },
    TreeItem: class { constructor(label, state) { this.label = label; this.collapsibleState = state; } },
    TreeItemCollapsibleState: { None: 0, Collapsed: 1, Expanded: 2 },
    ThemeIcon: class { constructor(id, color) { this.id = id; this.color = color; } },
    ThemeColor: class { constructor(id) { this.id = id; } },
    MarkdownString: class { constructor(v) { this.value = v || ''; } },
    StatusBarAlignment: { Left: 1, Right: 2 },
    ViewColumn: { Active: -1, Beside: -2, One: 1 },
    ProgressLocation: { Notification: 15, Window: 10 },
    ConfigurationTarget: { Global: 1, Workspace: 2 },
    Uri: {
      file: (p) => ({ fsPath: p, path: p, scheme: 'file', toString: () => `file://${p}` }),
      joinPath: (base, ...parts) => { const p = path.join(base.fsPath, ...parts); return { fsPath: p, path: p, scheme: 'file', toString: () => `file://${p}` }; },
      parse: (s) => ({ fsPath: s, path: s, scheme: s.split(':')[0], toString: () => s }),
      from: (c) => ({ fsPath: c.path, path: c.path, scheme: c.scheme, toString: () => `${c.scheme}:${c.path}` }),
    },
    env: { clipboard: { writeText: async () => {} }, openExternal: async () => true },
    commands: {
      registerCommand: (id, fn) => { commands.set(id, fn); return { dispose: () => commands.delete(id) }; },
      executeCommand: async (id, ...args) => (commands.has(id) ? commands.get(id)(...args) : undefined),
    },
    workspace: {
      get isTrusted() { return trust.isTrusted; },
      workspaceFolders: options.workspaceFolders || [],
      getConfiguration: (section) => ({
        get: (key, fallback) => { const k = `${section}.${key}`; return k in config ? config[k] : fallback; },
        update: async (key, value) => { config[`${section}.${key}`] = value; },
      }),
      onDidChangeConfiguration: () => disposable,
      onDidGrantWorkspaceTrust: (fn) => { trust.grant = fn; return disposable; },
      fs: { writeFile: async () => {} },
      registerTextDocumentContentProvider: (scheme, provider) => { (vscode.__content ||= new Map()).set(scheme, provider); return disposable; },
      openTextDocument: async (uri) => ({ uri, getText: () => (vscode.__content?.get(uri.scheme)?.provideTextDocumentContent(uri) ?? '') }),
    },
    window: {
      showInformationMessage: record('info'),
      showWarningMessage: record('warning'),
      showErrorMessage: record('error'),
      showQuickPick: async (items) => { messages.push({ kind: 'pick', items }); const a = answers.shift(); return typeof a === 'function' ? a(items) : a; },
      showInputBox: async () => answers.shift(),
      showSaveDialog: async () => answers.shift(),
      showOpenDialog: async () => answers.shift(),
      showTextDocument: async (doc) => { messages.push({ kind: 'document', text: doc.getText() }); return {}; },
      withProgress: async (_opts, task) => task({ report() {} }, { isCancellationRequested: false, onCancellationRequested: () => disposable }),
      createOutputChannel: (name) => ({ name, appendLine: (l) => output.push(l), append: (l) => output.push(l), show() {}, dispose() {} }),
      createStatusBarItem: () => ({ text: '', tooltip: '', command: undefined, show() {}, hide() {}, dispose() {} }),
      registerTreeDataProvider: (id, provider) => { (vscode.__trees ||= new Map()).set(id, provider); return disposable; },
      createTreeView: (id, opts) => { (vscode.__trees ||= new Map()).set(id, opts.treeDataProvider); return { dispose() {}, badge: undefined, description: '' }; },
      createWebviewPanel: options.createWebviewPanel || (() => { throw new Error('webview not stubbed'); }),
    },
  };
  const context = {
    subscriptions: [],
    extensionPath: options.extensionPath,
    extensionUri: { fsPath: options.extensionPath, path: options.extensionPath, scheme: 'file' },
    extension: { packageJSON: options.extensionPath ? require(path.join(options.extensionPath, 'package.json')) : {} },
    globalStorageUri: { fsPath: options.globalStorage || '/tmp', path: options.globalStorage || '/tmp', scheme: 'file' },
    workspaceState: { get: (k, d) => (stateStore.has(k) ? stateStore.get(k) : d), update: async (k, v) => { stateStore.set(k, v); } },
    globalState: { get: (k, d) => (stateStore.has(`g:${k}`) ? stateStore.get(`g:${k}`) : d), update: async (k, v) => { stateStore.set(`g:${k}`, v); } },
  };
  return { vscode, context, commands, messages, answers, config, output, trust };
}

/** Load the bundled extension with `vscode` resolved to the stub; returns its exports. */
function loadExtension(extDir, stub) {
  const entry = path.join(extDir, 'dist', 'extension.js');
  delete require.cache[entry];
  const originalLoad = Module._load;
  Module._load = function load(request, parent, isMain) {
    if (request === 'vscode') return stub.vscode;
    return originalLoad.call(this, request, parent, isMain);
  };
  try {
    return require(entry);
  } finally {
    Module._load = originalLoad;
  }
}

module.exports = { createVscodeStub, loadExtension };
