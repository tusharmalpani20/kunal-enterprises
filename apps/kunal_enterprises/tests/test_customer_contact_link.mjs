import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order_intake_request/order_intake_request.js', import.meta.url), 'utf8');
function setup({roles = ['Order Coordinator'], user = 'reviewer@example.com', values = {}, dirty = false, writable = true} = {}) {
  const buttons = new Map(), calls = [], messages = [], dialogs = [];
  let reloaded = 0, hidden = 0;
  const context = {
    __: value => value,
    frappe: {
      session: {user}, user_roles: roles,
      ui: {form: {on() {}}, Dialog: class {
        constructor(options) {Object.assign(this, options); dialogs.push(this);}
        show() {}
        hide() {hidden++;}
      }},
      msgprint: text => messages.push(text),
      show_alert() {},
      call: async options => {calls.push(options); return {message: {customer: 'CUST-A'}};},
    },
  };
  vm.createContext(context); vm.runInContext(source, context);
  const frm = {
    doc: {name: 'INTAKE-A', modified: '2026-11-17 12:00:00', source: 'WhatsApp', status: 'Pending Review',
      whatsapp_account: 'TEST WA', sender_number: '919000000001', sender_name: 'Ramesh', customer: 'CUST-A', ...values},
    is_new: () => false, is_dirty: () => dirty, has_perm: () => writable,
    add_custom_button: (label, action) => buttons.set(label, action),
    async reload_doc() {reloaded++;},
  };
  return {context, frm, buttons, dialogs, calls, messages, get reloaded() {return reloaded;}, get hidden() {return hidden;}};
}

for (const role of ['Owner', 'Admin', 'Order Coordinator']) {
  test(`${role} receives the WhatsApp customer-link action`, () => {
    const flow = setup({roles: [role]});
    flow.context.intake_sender_link_controls(flow.frm);
    assert.equal(typeof flow.buttons.get('Link sender to Customer'), 'function');
  });
}

test('the special Administrator account receives the action without role assumptions', () => {
  const flow = setup({user: 'Administrator', roles: []});
  flow.context.intake_sender_link_controls(flow.frm);
  assert.equal(flow.buttons.size, 1);
});

test('System Manager requires a reviewer role, while mixed Owner/Admin accounts remain eligible', () => {
  for (const roles of [['System Manager'], ['System Manager', 'Owner'], ['System Manager', 'Admin']]) {
    const flow = setup({roles}); flow.context.intake_sender_link_controls(flow.frm);
    assert.equal(flow.buttons.size, roles.length === 1 ? 0 : 1);
  }
});

test('unwritable, finalized, unrelated-channel and unauthorized forms have no link action', () => {
  for (const options of [
    {roles: ['Branch Employee']}, {roles: ['Godown Allocator']}, {roles: ['System Manager']}, {writable: false},
    {values: {source: 'Manual'}}, {values: {status: 'Converted to Order'}},
    {values: {status: 'Resolved'}}, {values: {status: 'Dismissed'}},
    {values: {order: 'ORDER-A'}}, {values: {sender_number: ''}}, {values: {whatsapp_account: ''}},
  ]) {
    const flow = setup(options); flow.context.intake_sender_link_controls(flow.frm);
    assert.equal(flow.buttons.size, 0, JSON.stringify(options));
  }
  const flow = setup(); flow.frm.is_new = () => true;
  flow.context.intake_sender_link_controls(flow.frm); assert.equal(flow.buttons.size, 0);
});

test('dirty requests must be saved before opening the linking dialog', () => {
  const flow = setup({dirty: true}); flow.context.intake_sender_link_controls(flow.frm);
  flow.buttons.get('Link sender to Customer')();
  assert.equal(flow.dialogs.length, 0); assert.match(flow.messages[0], /Save/);
});

test('dialog uses scoped customer lookup and submits current saved request revision', async () => {
  const flow = setup(); flow.context.intake_sender_link_controls(flow.frm);
  flow.buttons.get('Link sender to Customer')();
  const dialog = flow.dialogs[0], fields = Object.fromEntries(dialog.fields.map(field => [field.fieldname, field]));
  assert.equal(fields.customer.default, 'CUST-A'); assert.equal(fields.contact_name.default, 'Ramesh');
  assert.equal(fields.sender_number.read_only, 1); assert.equal(fields.sender_number.default, '919000000001');
  assert.equal(fields.customer.get_query().query, 'kunal_enterprises.api.order_intake.intake_link_query');
  assert.equal(fields.customer.ignore_link_validation, true);
  await dialog.primary_action({customer: 'CUST-B', contact_name: 'Ramesh', designation: 'Purchase Manager'});
  assert.equal(flow.calls.length, 1);
  assert.equal(flow.calls[0].method, 'kunal_enterprises.api.customer_contacts.link_sender');
  assert.deepEqual(JSON.parse(JSON.stringify(flow.calls[0].args)), {
    request: 'INTAKE-A', expected_modified: '2026-11-17 12:00:00', customer: 'CUST-B',
    contact_name: 'Ramesh', designation: 'Purchase Manager',
  });
  assert.equal(flow.reloaded, 1); assert.equal(flow.hidden, 1);
});

test('an old dialog cannot submit after request identity or revision changes', async () => {
  for (const [key, value] of [['name', 'INTAKE-B'], ['modified', 'later'], ['sender_number', '919000000002']]) {
    const flow = setup(); flow.context.intake_sender_link_controls(flow.frm); flow.buttons.get('Link sender to Customer')();
    flow.frm.doc[key] = value;
    await flow.dialogs[0].primary_action({customer: 'CUST-A', contact_name: 'Ramesh'});
    assert.equal(flow.calls.length, 0); assert.match(flow.messages[0], /changed/i);
  }
});

test('failed linking stays open for correction and does not reload the request', async () => {
  const flow = setup(); flow.context.frappe.call = async () => {throw new Error('Number belongs to CUST-B');};
  flow.context.intake_sender_link_controls(flow.frm); flow.buttons.get('Link sender to Customer')();
  await assert.rejects(flow.dialogs[0].primary_action({customer: 'CUST-A', contact_name: 'Ramesh'}), /belongs to/);
  assert.equal(flow.hidden, 0); assert.equal(flow.reloaded, 0);
});
