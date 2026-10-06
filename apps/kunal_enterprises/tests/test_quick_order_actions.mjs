import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/quick_order_request/quick_order_request.js', import.meta.url), 'utf8');
function setup({ dirty = false, discard = true, saveFails = false } = {}) {
  const calls = [];
  const notices = [];
  const frm = { doc: { name: 'QOR-1' }, saves: 0, reloads: 0,
    is_dirty: () => dirty,
    async save() { this.saves++; if (saveFails) throw new Error('Invalid quantity'); dirty = false; },
    async reload_doc() { this.reloads++; dirty = false; } };
  const action = vm.runInNewContext(`${source}\nquick_order_action;`, {
    __: value => value,
    frappe: { ui: { form: { on() {} } },
      confirm(message, yes, no) { notices.push(message); discard ? yes() : no?.(); },
      msgprint(message) { notices.push(message); }, show_alert() {},
      async call(args) { calls.push(args); return { message: { success: true } }; } },
  });
  return { frm, calls, notices, action };
}

test('rejecting a request can discard incomplete unsaved review rows', async () => {
  const flow = setup({ dirty: true, saveFails: true });
  await flow.action(flow.frm, 'reject', { reason: 'Unable to fulfil' });
  assert.equal(flow.frm.saves, 0);
  assert.equal(flow.calls.length, 1);
  assert.equal(flow.calls[0].args.reason, 'Unable to fulfil');
  assert.equal(flow.frm.reloads, 1);
  assert.match(flow.notices[0], /discard/i);
});

test('cancelling discard preserves the draft and does not reject the request', async () => {
  const flow = setup({ dirty: true, discard: false });
  await flow.action(flow.frm, 'reject', { reason: 'Unable to fulfil' });
  assert.equal(flow.frm.saves, 0);
  assert.equal(flow.calls.length, 0);
  assert.equal(flow.frm.is_dirty(), true);
  assert.equal(flow.frm.__quick_order_busy, false);
});

test('conversion must not proceed when review rows fail to save', async () => {
  const flow = setup({ dirty: true, saveFails: true });
  await assert.rejects(flow.action(flow.frm, 'convert'), /Invalid quantity/);
  assert.equal(flow.calls.length, 0);
  assert.equal(flow.frm.__quick_order_busy, false);
});

test('conversion saves edited review rows before placing the order', async () => {
  const flow = setup({ dirty: true });
  await flow.action(flow.frm, 'convert');
  assert.equal(flow.frm.saves, 1);
  assert.equal(flow.calls[0].method, 'kunal_enterprises.api.quick_orders.convert');
  assert.equal(flow.frm.reloads, 1);
});
