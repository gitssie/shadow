"""Execute the exact WKUserScript with DOM doubles; never access a real clipboard."""
import json
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
source = (root / "src/ShadowCore.dylib/policy/WebClipboardPolicy.m").read_text()
script = "".join(json.loads(literal) for literal in re.findall(r'@("(?:\\.|[^"\\])*")', source))
assert script and "SHDWFingerprintWebClipboardScript(void)" in source
runner = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const script = SCRIPT;
const navigatorRecords = new WeakMap();
const fixture = `
  globalThis.reads = 0;
  globalThis.writes = [];
  globalThis.listeners = new Map();
  class EventTarget {}
  const eventTypes = new WeakMap();
  class Event {
    constructor(type) { eventTypes.set(this, type); this.defaultPrevented = false; }
    get type() {
      if (!eventTypes.has(this)) throw new TypeError('Illegal invocation');
      return eventTypes.get(this);
    }
    preventDefault() { this.defaultPrevented = true; }
  }
  class DataTransfer {
    constructor() { this.values = {}; this.items = []; this.files = []; }
    get types() { return Object.keys(this.values); }
    getData(type) { return this.values[type] || ''; }
    setData(type, value) { this.values[type] = value; }
  }
  const clipboardTransfers = new WeakMap();
  class ClipboardEvent extends Event {
    constructor(type, transfer) { super(type); clipboardTransfers.set(this, transfer); }
    get clipboardData() {
      if (!clipboardTransfers.has(this)) throw new TypeError('Illegal invocation');
      return clipboardTransfers.get(this);
    }
  }
  const inputRecords = new WeakMap();
  class InputEvent extends Event {
    constructor(type, inputType, data, transfer) {
      super(type); inputRecords.set(this, {inputType, data, transfer});
    }
    get inputType() { return inputRecords.get(this).inputType; }
    get data() { return inputRecords.get(this).data; }
    get dataTransfer() { return inputRecords.get(this).transfer; }
  }
  class Clipboard {
    readText() { reads++; return Promise.resolve('private text'); }
    read() { reads++; return Promise.resolve(['private item']); }
    writeText(text) { writes.push(text); return Promise.resolve(); }
    write(items) { writes.push(items); return Promise.resolve(); }
  }
  class Navigator {
    constructor() { navigatorRecords.set(this, new Clipboard()); }
    get clipboard() {
      if (!navigatorRecords.has(this)) throw new TypeError('Illegal invocation');
      return navigatorRecords.get(this);
    }
  }
  globalThis.navigator = new Navigator();
  globalThis.parent = globalThis;
  globalThis.frames = [];
  globalThis.opener = null;
  globalThis.originalClipboard = navigator.clipboard;
  globalThis.originalWrite = navigator.clipboard.write;
  globalThis.originalWriteText = navigator.clipboard.writeText;
  globalThis.addEventListener = (type, callback, capture) => {
    const list = listeners.get(type) || [];
    list.push({callback, capture}); listeners.set(type, list);
  };
  globalThis.dispatch = event => {
    const type = Object.getOwnPropertyDescriptor(Event.prototype, 'type').get.call(event);
    const list = listeners.get(type) || [];
    for (const listener of list.filter(l => l.capture)) listener.callback(event);
    for (const listener of list.filter(l => !l.capture)) listener.callback(event);
    if (!event.defaultPrevented && type === 'paste') globalThis.inserted = 'private text';
    return event;
  };
  globalThis.privateTransfer = new DataTransfer();
  privateTransfer.setData('text/plain', 'private text');
  privateTransfer.setData('text/html', '<b>private text</b>');
  privateTransfer.items.push('private item'); privateTransfer.files.push('private file');
`;
function realm(options = {}) {
  const context = vm.createContext({navigatorRecords});
  vm.runInContext(fixture, context);
  if (options.ownReads) vm.runInContext(`navigator.clipboard.readText = function () { reads++; return Promise.resolve('private own text'); }; navigator.clipboard.read = function () { reads++; return Promise.resolve(['private own item']); }`, context);
  if (options.noClipboard) vm.runInContext('delete Navigator.prototype.clipboard', context);
  if (options.noRead) vm.runInContext('delete Clipboard.prototype.read', context);
  if (options.noDataTransfer) vm.runInContext('DataTransfer = undefined', context);
  if (options.throwDataTransfer) vm.runInContext('DataTransfer = class { constructor() { throw Error(); } }', context);
  if (options.noEvents) vm.runInContext('ClipboardEvent = undefined; InputEvent = undefined; addEventListener = undefined', context);
  if (options.noTypeGetters) vm.runInContext(`
    Object.defineProperty(Event.prototype, 'type', {configurable: true, value: 'paste'});
    Object.defineProperty(InputEvent.prototype, 'inputType', {configurable: true, value: 'insertFromPaste'});
  `, context);
  if (!options.noScript) vm.runInContext(script, context);
  return context;
}
function checkEmpty(context, expression) {
  assert.equal(vm.runInContext(`(${expression}).getData('text/plain')`, context), '');
  assert.equal(vm.runInContext(`(${expression}).getData('text/html')`, context), '');
  for (const field of ['types', 'items', 'files'])
    assert.equal(vm.runInContext(`(${expression}).${field}.length`, context), 0);
}
(async () => {
  const context = realm();
  assert.equal(vm.runInContext('navigator.clipboard === originalClipboard', context), true);
  assert.equal(await vm.runInContext('navigator.clipboard.readText()', context), '');
  assert.equal((await vm.runInContext('navigator.clipboard.read()', context)).length, 0);
  assert.equal(await vm.runInContext('Clipboard.prototype.readText.call(navigator.clipboard)', context), '');
  assert.equal((await vm.runInContext('Clipboard.prototype.read.call(navigator.clipboard)', context)).length, 0);
  assert.equal(vm.runInContext('reads', context), 0);
  assert.throws(() => vm.runInContext('navigator.clipboard.readText.call({})', context), /Illegal invocation/);
  assert.equal(vm.runInContext('navigator.clipboard.write === originalWrite && navigator.clipboard.writeText === originalWriteText', context), true);
  await vm.runInContext("navigator.clipboard.writeText('allowed write'); navigator.clipboard.write(['allowed item'])", context);
  assert.equal(vm.runInContext('writes.length', context), 2);
  vm.runInContext(`
    globalThis.bubbled = 0;
    addEventListener('paste', event => { bubbled++; globalThis.pageTransfer = event.clipboardData; }, false);
    globalThis.paste = new ClipboardEvent('paste', privateTransfer);
    dispatch(paste);
  `, context);
  assert.equal(vm.runInContext('bubbled === 1 && paste.defaultPrevented && globalThis.inserted === undefined', context), true);
  checkEmpty(context, 'pageTransfer');
  checkEmpty(context, "Object.getOwnPropertyDescriptor(ClipboardEvent.prototype, 'clipboardData').get.call(paste)");
  vm.runInContext(`
    globalThis.spoofed = new ClipboardEvent('paste', privateTransfer);
    Object.defineProperty(spoofed, 'type', {value: 'copy'});
    dispatch(spoofed);
  `, context);
  assert.equal(vm.runInContext('bubbled === 2 && spoofed.defaultPrevented', context), true);
  checkEmpty(context, "Object.getOwnPropertyDescriptor(ClipboardEvent.prototype, 'clipboardData').get.call(spoofed)");
  for (const type of ['copy', 'cut']) {
    vm.runInContext(`globalThis.other = new ClipboardEvent('${type}', privateTransfer); dispatch(other)`, context);
    assert.equal(vm.runInContext('!other.defaultPrevented && other.clipboardData === privateTransfer', context), true);
  }
  for (const type of ['insertFromPaste', 'insertFromPasteAsQuotation']) {
    vm.runInContext(`
      globalThis.input = new InputEvent('beforeinput', '${type}', 'private text', privateTransfer);
      Object.defineProperty(input, 'inputType', {value: 'insertText'});
      dispatch(input);
    `, context);
    assert.equal(vm.runInContext('input.defaultPrevented && input.data === null', context), true);
    checkEmpty(context, 'input.dataTransfer');
    assert.equal(vm.runInContext("Object.getOwnPropertyDescriptor(InputEvent.prototype, 'data').get.call(input)", context), null);
    checkEmpty(context, "Object.getOwnPropertyDescriptor(InputEvent.prototype, 'dataTransfer').get.call(input)");
  }
  vm.runInContext(`globalThis.input = new InputEvent('beforeinput', 'insertText', 'typed', privateTransfer); dispatch(input)`, context);
  assert.equal(vm.runInContext("!input.defaultPrevented && input.data === 'typed' && input.dataTransfer === privateTransfer", context), true);
  for (const type of ['paste', 'copy', 'cut']) {
    assert.throws(() => vm.runInContext(`Object.getOwnPropertyDescriptor(ClipboardEvent.prototype, 'clipboardData').get.call(new Event('${type}'))`, context), /Illegal invocation/);
  }
  for (const property of ['data', 'dataTransfer']) {
    for (const receiver of ["new Event('beforeinput')", "{}", "Object.create(InputEvent.prototype)"]) {
      assert.throws(() => vm.runInContext(`Object.getOwnPropertyDescriptor(InputEvent.prototype, '${property}').get.call(${receiver})`, context), /TypeError/);
    }
  }
  const getter = vm.runInContext("Object.getOwnPropertyDescriptor(ClipboardEvent.prototype, 'clipboardData').get", context);
  const reader = vm.runInContext('navigator.clipboard.readText', context);
  vm.runInContext(script, context);
  assert.equal(vm.runInContext("Object.getOwnPropertyDescriptor(ClipboardEvent.prototype, 'clipboardData').get", context), getter);
  assert.equal(vm.runInContext('navigator.clipboard.readText', context), reader);
  assert.equal(vm.runInContext("listeners.get('paste').filter(l => l.capture).length", context), 1);
  assert.equal(vm.runInContext('reads', context), 0);
  for (const options of [{noDataTransfer: true}, {throwDataTransfer: true}]) {
    const fallback = realm(options);
    vm.runInContext("globalThis.paste = new ClipboardEvent('paste', privateTransfer); dispatch(paste)", fallback);
    checkEmpty(fallback, 'paste.clipboardData');
  }
  const own = realm({ownReads: true});
  assert.equal(await vm.runInContext('navigator.clipboard.readText()', own), '');
  assert.equal((await vm.runInContext('navigator.clipboard.read()', own)).length, 0);
  assert.equal(await vm.runInContext('Clipboard.prototype.readText.call(navigator.clipboard)', own), '');
  assert.equal((await vm.runInContext('Clipboard.prototype.read.call(navigator.clipboard)', own)).length, 0);
  assert.equal(vm.runInContext('reads', own), 0);
  for (const type of ['insertFromPaste', 'insertFromPasteAsQuotation']) {
    vm.runInContext(`globalThis.input = new InputEvent('input', '${type}', 'private text', privateTransfer); dispatch(input)`, context);
    assert.equal(vm.runInContext('!input.defaultPrevented && input.data === null', context), true);
    checkEmpty(context, 'input.dataTransfer');
  }
  const absent = realm({noClipboard: true, noEvents: true});
  assert.equal(vm.runInContext("'clipboard' in navigator", absent), false);
  const missingRead = realm({noRead: true});
  assert.equal(vm.runInContext("'read' in navigator.clipboard", missingRead), false);
  const frame = realm();
  assert.equal(await vm.runInContext('navigator.clipboard.readText()', frame), '');
  assert.equal(vm.runInContext('reads', frame), 0);
  const parent = realm();
  const child = realm();
  parent.frames.push(child);
  child.parent = parent;
  parent.child = child;
  child.parentRealm = parent;
  for (const [local, remoteName] of [[parent, 'child'], [child, 'parentRealm']]) {
    for (const method of ['readText', 'read']) {
      for (const expression of [
        `Clipboard.prototype.${method}.call(${remoteName}.navigator.clipboard)`,
        `Reflect.apply(Clipboard.prototype.${method}, ${remoteName}.navigator.clipboard, [])`,
        `navigator.clipboard.${method}.call(${remoteName}.navigator.clipboard)`
      ]) {
        const value = await vm.runInContext(expression, local);
        assert.equal(method === 'readText' ? value : value.length, method === 'readText' ? '' : 0);
      }
      for (const invalid of ['{}', 'Object.create(Clipboard.prototype)', 'new Proxy(navigator.clipboard, {})']) {
        assert.throws(() => vm.runInContext(`Reflect.apply(Clipboard.prototype.${method}, ${invalid}, [])`, local), /Illegal invocation/);
      }
    }
    assert.equal(vm.runInContext('reads', local), 0);
  }
  const initialFrame = realm({noScript: true});
  parent.frames.push(initialFrame);
  parent.initialFrame = initialFrame;
  assert.equal(await vm.runInContext('Reflect.apply(Clipboard.prototype.readText, initialFrame.navigator.clipboard, [])', parent), '');
  assert.equal(vm.runInContext('reads', initialFrame), 0);
  // A window inaccessible to this realm must not prevent searching accessible siblings.
  parent.frames.unshift(new Proxy({}, { get() { throw new Error('SecurityError'); } }));
  assert.equal(await vm.runInContext('Clipboard.prototype.readText.call(child.navigator.clipboard)', parent), '');
  assert.equal(vm.runInContext('reads', parent) + vm.runInContext('reads', child), 0);
  console.log('web clipboard: exact production script, empty reads/events, propagation, writes, scopes and idempotence passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
subprocess.run(["node"], input=runner.replace("SCRIPT", json.dumps(script), 1), text=True, check=True)
