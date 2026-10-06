import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order/order.js', import.meta.url), 'utf8');
function form(role, canProcess = true, pending = false, deferred = false, dirty = false) {
  let refresh;
  const buttons = new Map();
  const calls = [];
  const routes = [];
  const alerts = [];
  const frm = { doc: { name: 'ORDER-1', status: 'Placed', godown_assignment_pending: pending },
    is_new: () => false, is_dirty: () => dirty, reload_doc() {},
    add_custom_button(label, action) { buttons.set(label, action); return { addClass() {} }; } };
  vm.runInNewContext(source, { __: value => value, frappe: {
    session: { user: 'test@example.com' }, user_roles: [role],
    ui: { form: { on(_doctype, handlers) { refresh = handlers.refresh; } } },
    confirm(_message, yes) { yes(); },
    msgprint(message) { alerts.push(message); }, set_route(...args) { routes.push(args); }, show_alert(message) { alerts.push(message); },
    call(args) { calls.push(args); if (!deferred && args.method.endsWith('.processing_options')) args.callback({ message: { success: true, data: { can_process: canProcess } } }); },
  } });
  refresh(frm);
  return { buttons, calls, routes, alerts, frm, refresh };
}

test('all four global roles get the processing action and use the global endpoint', () => {
  for (const role of ['Owner', 'Admin', 'Godown Allocator', 'Order Coordinator']) {
    const flow = form(role);
    assert.ok(flow.buttons.has('Move to Processing'), role);
    flow.buttons.get('Move to Processing')();
    assert.equal(flow.calls.at(-1).method, 'kunal_enterprises.api.order_controls.mark_processing');
  }
});

test('branch processing action follows server eligibility and uses the branch endpoint', () => {
  for (const role of ['Branch Manager', 'Branch Employee']) {
    assert.equal(form(role, false).buttons.has('Move to Processing'), false);
    const flow = form(role);
    flow.buttons.get('Move to Processing')();
    assert.equal(flow.calls.at(-1).method, 'kunal_enterprises.api.branch_orders.mark_visible_order_processing');
  }
});

test('unassigned orders and unrelated roles have no processing action', () => {
  assert.equal(form('Owner', true, true).buttons.has('Move to Processing'), false);
  assert.equal(form('Sales Employee').buttons.has('Move to Processing'), false);
});


test('allocator action returns to the list when the processed order leaves its read scope', () => {
  const flow = form('Godown Allocator');
  flow.buttons.get('Move to Processing')();
  flow.calls.at(-1).callback({ message: { success: true, data: { can_read_order: false } } });
  assert.deepEqual(flow.routes[0], ['List', 'Order']);
  assert.equal(flow.alerts[0].message, 'Order moved to Processing');
});


test('an older eligibility response cannot restore the button after a newer refresh', () => {
  const flow = form('Branch Employee', true, false, true);
  const older = flow.calls[0];
  flow.refresh(flow.frm);
  flow.calls[1].callback({ message: { success: true, data: { can_process: false } } });
  older.callback({ message: { success: true, data: { can_process: true } } });
  assert.equal(flow.buttons.has('Move to Processing'), false);
});

test('repeated processing clicks send only one transition request', () => {
  const flow = form('Owner');
  const click = flow.buttons.get('Move to Processing');
  click(); click();
  assert.equal(flow.calls.filter(call => call.method.endsWith('.mark_processing')).length, 1);
});

test('unsaved edits must be saved or discarded before processing', () => {
  const flow = form('Owner', true, false, false, true);
  flow.buttons.get('Move to Processing')();
  assert.equal(flow.calls.filter(call => call.method.endsWith('.mark_processing')).length, 0);
  assert.match(flow.alerts.at(-1), /Save or discard/);
});


test('a failed request unlocks the action for retry', () => {
  const flow = form('Owner');
  const click = flow.buttons.get('Move to Processing');
  click();
  flow.calls.at(-1).always();
  click();
  assert.equal(flow.calls.filter(call => call.method.endsWith('.mark_processing')).length, 2);
});
