import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
import * as flow from '../src/domain/quickOrderFlow.mjs';
import * as state from '../src/domain/sharedStateFlow.mjs';

const source = readFileSync(new URL('../src/flow/useQuickOrders.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;

// Exercise the real hook's async boundaries without launching the phone.
function setup(api, initial = {}) {
  let index = 0;
  const slots = [];
  let effects = [];
  const errors = [];
  const options = { api, customer: 'CUST-A', salesEmployee: 'SE-1', contextKey: 'SE-1:CUST-A', enabled: true, active: false,
    onError: error => errors.push(error), ...initial };
  const memo = (callback, deps) => {
    const slot = index++;
    if (!slots[slot] || deps.some((dep, i) => !Object.is(dep, slots[slot].deps[i]))) slots[slot] = { deps, value: callback() };
    return slots[slot].value;
  };
  const react = {
    useState(value) { const slot = index++; if (!(slot in slots)) slots[slot] = value;
      return [slots[slot], next => { slots[slot] = typeof next === 'function' ? next(slots[slot]) : next; }]; },
    useRef(value) { const slot = index++; return slots[slot] ??= { current: value }; },
    useMemo: memo,
    useCallback(callback, deps) { return memo(() => callback, deps); },
    useEffect(callback, deps) { memo(() => { effects.push(callback); }, deps); },
  };
  const exports = {};
  vm.runInNewContext(compiled, { exports, require(name) {
    if (name === 'react') return react;
    if (name.includes('quickOrderFlow')) return flow;
    if (name.includes('sharedStateFlow')) return state;
    throw new Error(name);
  } });
  function render(patch = {}) {
    Object.assign(options, patch); index = 0;
    const result = exports.useQuickOrders(options);
    const queued = effects; effects = []; queued.forEach(effect => effect());
    return result;
  }
  render();
  return { render, errors };
}

test('switching customers resets draft and ignores the previous customer submission even after returning', async () => {
  let resolve;
  const calls = [];
  const api = { quickOrderSubmit(...args) { calls.push(args); return new Promise(done => { resolve = done; }); },
    async quickOrderHistory() { return { requests: [], has_more: false }; } };
  const view = setup(api);
  view.render().setText('Customer A text');
  const pending = view.render().submit();
  assert.deepEqual(calls[0], ['Customer A text', 'CUST-A', 'SE-1']);
  view.render({ customer: 'CUST-B', contextKey: 'SE-1:CUST-B' });
  assert.equal(view.render().text, '');
  view.render({ customer: 'CUST-A', contextKey: 'SE-1:CUST-A' });
  view.render().setText('New draft');
  resolve({ name: 'QOR-OLD' });
  assert.equal(await pending, undefined);
  assert.equal(view.render().text, 'New draft');
  assert.equal(view.render().requests.length, 0);
  assert.equal(view.errors.length, 0);
});

test('employee history and detail use token employee scope rather than the currently selected customer', async () => {
  const calls = [];
  const view = setup({
    async quickOrderHistory(...args) { calls.push(args); return { requests: [], has_more: false }; },
    async quickOrderDetail(...args) { calls.push(args); return { name: 'QOR-B', customer: 'CUST-B' }; },
  });
  await view.render().loadHistory();
  await view.render().loadDetail('QOR-B');
  assert.equal(calls[0][0], undefined);
  assert.equal(calls[0][2], 'SE-1');
  assert.deepEqual(calls[1], ['QOR-B', undefined, 'SE-1']);
  assert.equal(view.render().detail.customer, 'CUST-B');
});

test('employee submission cannot run before selecting a customer', async () => {
  let calls = 0;
  const view = setup({ async quickOrderSubmit() { calls++; } }, { customer: '', contextKey: 'SE-1:' });
  view.render().setText('3 sheets');
  assert.equal(await view.render().submit(), undefined);
  assert.equal(calls, 0);
});
