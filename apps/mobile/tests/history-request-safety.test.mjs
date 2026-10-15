import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import ts from 'typescript';
import { readFileSync } from 'node:fs';
import { classifyApiFailure } from '../src/domain/sharedStateFlow.mjs';

// Exercise the provider's real history actions and their asynchronous callbacks.
const provider = readFileSync(new URL('../src/flow/OrderFlowProvider.tsx', import.meta.url), 'utf8');
const start = provider.includes('  function historyRequestGuard(') ? provider.indexOf('  function historyRequestGuard(') : provider.indexOf('  async function showHistory()');
const historyActions = provider.slice(start, provider.indexOf('  function fetchHistoryPage', start));
const detailSource = provider.slice(provider.indexOf('  async function showOrderDetail('), provider.indexOf('  async function revokeAndLogout('));
const actions = ts.transpileModule(historyActions + detailSource, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
function setup() {
  const pending = [];
  const steps = [];
  const errors = [];
  let logouts = 0;
  const context = {
    hasActiveModeSession: true, historyLoading: false, historyHasMore: true, historyRows: [], HISTORY_PAGE_SIZE: 20,
    linkedOrderRequestId: { current: 0 }, mode: 'Sales Employee', activeSalesEmployeeIdentity: () => 'SE-1', activeCustomerIdentity: () => 'CUST-1',
    setOrderDetail(value) { context.detail = value; }, api: { orderDetail() { return new Promise((resolve, reject) => { pending.push({ resolve, reject }); }); } },
    historyRequestId: { current: 0 }, historyInFlight: { current: false },
    navigationChangeRevision: { current: 0 }, linkedNavigation: { current: { revision: 0 } },
    classifyApiFailure,
    setHistoryLoading() {}, setHistoryHasMore() {},
    setHistoryRows(value) { context.historyRows = typeof value === 'function' ? value(context.historyRows) : value; },
    setSystemState(value) { errors.push(value); },
    setStep(value) { steps.push(value); context.navigationChangeRevision.current++; },
    async logout() { logouts++; },
    fetchHistoryPage() { return new Promise((resolve, reject) => { pending.push({ resolve, reject }); }); },
  };
  vm.runInNewContext(`${actions}\nthis.open = showHistory; this.more = loadMoreHistory; this.detailAction = showOrderDetail;`, context);
  return { context, pending, steps, errors, logouts: () => logouts,
    leave() { context.navigationChangeRevision.current++; context.linkedNavigation.current.revision++; } };
}

test('history results cannot navigate or populate rows after leaving the screen/account', async () => {
  const flow = setup();
  const request = flow.context.open();
  flow.leave();
  flow.pending[0].resolve([{ name: 'OLD-PRIVATE-REQUEST' }]);
  await request;
  assert.equal(flow.context.historyRows.length, 0);
  assert.equal(flow.steps.length, 0);
});

test('late history errors cannot log out the next account', async () => {
  const flow = setup();
  const request = flow.context.open();
  flow.leave();
  flow.pending[0].reject(new Error('Invalid or inactive token'));
  await request;
  assert.equal(flow.logouts(), 0);
  assert.equal(flow.errors.length, 0);
});

test('rapid Load more taps request one page', async () => {
  const flow = setup();
  const first = flow.context.more();
  const second = flow.context.more();
  assert.equal(flow.pending.length, 1);
  flow.pending[0].resolve([{ name: 'QOR-1' }]);
  await Promise.all([first, second]);
  assert.equal(flow.context.historyRows.length, 1);
});

test('a newer history refresh wins over an older request', async () => {
  const flow = setup();
  const first = flow.context.open();
  const second = flow.context.open();
  flow.pending[1].resolve([{ name: 'CURRENT' }]);
  await second;
  flow.pending[0].resolve([{ name: 'OLD' }]);
  await first;
  assert.equal(flow.context.historyRows[0].name, 'CURRENT');
  assert.equal(flow.steps.length, 1);
});


test('late converted Order details cannot reopen a screen or expire a different session', async () => {
  for (const fail of [false, true]) {
    const flow = setup();
    const request = flow.context.detailAction({ name: 'CONVERTED-ORDER' });
    flow.leave();
    if (fail) flow.pending[0].reject(new Error('Invalid or inactive token'));
    else flow.pending[0].resolve({ name: 'CONVERTED-ORDER' });
    await request;
    assert.equal(flow.context.detail, undefined);
    assert.equal(flow.steps.length, 0);
    assert.equal(flow.errors.length, 0);
    assert.equal(flow.logouts(), 0);
  }
});
