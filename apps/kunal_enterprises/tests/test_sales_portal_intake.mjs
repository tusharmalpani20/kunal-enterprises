import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/public/js/sales_portal_intake.js', import.meta.url), 'utf8');
const plain = value => JSON.parse(JSON.stringify(value));

function setup({roles = ['Sales Portal User'], user = 'sales@example.com', values = {}, fresh = false, fail = false} = {}) {
  const buttons = new Map(), calls = [], dialogs = [], confirmations = [];
  let refresh, disabled = 0, reloaded = 0;
  const frm = {
    doc: {name: 'QA-INTAKE', modified: '2026-11-17 12:34:56.000001', status: 'Pending Review',
      customer: 'ASSIGNED-CUSTOMER', items: [{row_key: 'stable-line', original_text: '2200 SF',
        item: 'ITEM-A', quantity: 20, unit: 'sheets', godown: 'GODOWN-A', notes: 'Keep source note'}], ...values},
    is_new: () => fresh,
    disable_save() {disabled++;},
    add_custom_button(label, action) {buttons.set(label, action);},
    async reload_doc() {reloaded++;},
  };
  const before = plain(frm.doc);
  vm.runInNewContext(source, {
    __: value => value,
    frappe: {
      session: {user}, user_roles: roles,
      ui: {form: {on(_doctype, handlers) {refresh = handlers.refresh;}},
        Dialog: class {
          constructor(options) {this.options = options; this.visible = false; dialogs.push(this);}
          show() {this.visible = true;}
          hide() {this.visible = false;}
        },
      },
      confirm(message, action) {confirmations.push({message, action});},
      async call(args) {calls.push(plain(args)); if (fail) throw new Error('Request was refused'); return {message: {state: 'Saved'}};},
    },
  });
  return {frm, before, buttons, calls, dialogs, confirmations, refresh: () => refresh(frm),
    get disabled() {return disabled;}, get reloaded() {return reloaded;}};
}

test('sales users get only narrow correction and approval actions without enabling generic Save', () => {
  const ui = setup();
  ui.refresh();
  assert.equal(ui.disabled, 1);
  assert.deepEqual([...ui.buttons.keys()], ['Correct intake', 'Approve intake']);
  assert.deepEqual(plain(ui.frm.doc), ui.before);
  assert.equal(ui.calls.length, 0);
});

test('privileged and unrelated users retain their existing form controls', () => {
  for (const config of [
    {user: 'Administrator'},
    ...['Owner', 'Admin', 'System Manager'].map(role => ({roles: ['Sales Portal User', role]})),
    {roles: ['Order Coordinator']},
    {roles: []},
  ]) {
    const ui = setup(config);
    ui.refresh();
    assert.equal(ui.disabled, 0);
    assert.equal(ui.buttons.size, 0);
    assert.equal(ui.calls.length, 0);
  }
});

test('new, closed and converted intake records offer no correction or approval actions', () => {
  for (const config of [
    {fresh: true},
    ...['Resolved', 'Dismissed', 'Converted to Order'].map(status => ({values: {status}})),
    {values: {status: 'Pending Review', order: 'EXISTING-ORDER'}},
  ]) {
    const ui = setup(config);
    ui.refresh();
    assert.equal(ui.disabled, 1);
    assert.equal(ui.buttons.size, 0);
  }
});

test('existing approval is displayed without offering another approval while corrections stay available', () => {
  const ui = setup({values: {sales_approval_status: 'Approved'}});
  ui.refresh();
  assert.deepEqual([...ui.buttons.keys()], ['Correct intake']);
});

test('approval requires confirmation and submits the saved request revision then reloads', async () => {
  const ui = setup();
  ui.refresh();
  ui.buttons.get('Approve intake')();
  assert.equal(ui.confirmations.length, 1);
  assert.equal(ui.calls.length, 0, 'opening confirmation does not approve');
  await ui.confirmations[0].action();
  assert.equal(ui.calls.length, 1);
  assert.equal(ui.calls[0].method, 'kunal_enterprises.api.sales_portal_intake.approve');
  assert.deepEqual(ui.calls[0].args, {request: 'QA-INTAKE', expected_modified: ui.before.modified});
  assert.equal(ui.reloaded, 1);
  assert.deepEqual(plain(ui.frm.doc), ui.before, 'approval attribution comes from the server');
});

test('correction dialog limits editable data, preserves original evidence and scopes link searches', () => {
  const ui = setup();
  ui.refresh();
  ui.buttons.get('Correct intake')();
  const dialog = ui.dialogs[0], fields = dialog.options.fields;
  assert.equal(dialog.visible, true);
  assert.deepEqual(plain(fields.map(field => field.fieldname)), ['customer', 'items']);
  const customer = fields[0], table = fields[1];
  assert.equal(customer.get_query().query, 'kunal_enterprises.api.sales_portal_intake.customer_query');
  assert.equal(table.cannot_add_rows, true);
  assert.equal(table.cannot_delete_rows, true);
  assert.equal(table.fields.find(field => field.fieldname === 'original_text').read_only, true);
  assert.equal(table.fields.find(field => field.fieldname === 'row_key').hidden, true);
  for (const name of ['item', 'godown']) {
    assert.equal(table.fields.find(field => field.fieldname === name).get_query().query,
      'kunal_enterprises.api.sales_portal_intake.master_query');
  }
  table.data[0].quantity = 5;
  assert.equal(ui.frm.doc.items[0].quantity, 20, 'editing dialog does not mutate unsaved evidence in the main form');
  assert.equal(ui.calls.length, 0);
});

test('corrections send only approved fields and revision, dropping injected evidence and approval fields', async () => {
  const ui = setup();
  ui.refresh();
  ui.buttons.get('Correct intake')();
  const dialog = ui.dialogs[0];
  await dialog.options.primary_action({customer: 'OTHER-ASSIGNED-CUSTOMER',
    status: 'Converted to Order', sales_approved_by: 'Administrator',
    delivery_address: 'Injected destination', items: [{row_key: 'stable-line', original_text: 'Injected text',
      item: 'ITEM-B', quantity: 5, godown: 'GODOWN-B', notes: 'Injected note', unit: 'kg', source_message: 'FOREIGN'}]});
  assert.deepEqual(ui.calls[0].args, {request: 'QA-INTAKE', expected_modified: ui.before.modified,
    customer: 'OTHER-ASSIGNED-CUSTOMER', items: [{row_key: 'stable-line', item: 'ITEM-B', quantity: 5, godown: 'GODOWN-B'}]});
  assert.equal(ui.calls[0].method, 'kunal_enterprises.api.sales_portal_intake.correct');
  assert.equal(dialog.visible, false);
  assert.equal(ui.reloaded, 1);
  assert.deepEqual(plain(ui.frm.doc), ui.before);
});

test('unknown quantities remain blank in correction dialog rather than appearing as confirmed zero', () => {
  const ui = setup({values: {items: [{row_key: 'unknown', original_text: '2200 SF', quantity: 0, quantity_unknown: 1}]}});
  ui.refresh();
  ui.buttons.get('Correct intake')();
  assert.equal(ui.dialogs[0].options.fields[1].data[0].quantity, null);
});

test('failed correction keeps the dialog open for review and does not reload as if saved', async () => {
  const ui = setup({fail: true});
  ui.refresh();
  ui.buttons.get('Correct intake')();
  const dialog = ui.dialogs[0];
  await assert.rejects(dialog.options.primary_action({customer: ui.frm.doc.customer, items: []}), /refused/);
  assert.equal(dialog.visible, true);
  assert.equal(ui.reloaded, 0);
});
