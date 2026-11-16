import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order_intake_request/order_intake_request.js', import.meta.url), 'utf8');
const candidate = (name, changes = {}) => ({name, label: name, score: 90, reason: 'Matching wording', ...changes});
const result = (text, names) => ({text, candidates: names.map(name => candidate(name))});
function setup(values = {}) {
  let handlers;
  const buttons = new Map(), dialogs = [], messages = [], calls = [], changed = [], queries = [], properties = [];
  let reloads = 0;
  const frm = {
    doc: {name: 'OIR-MATCH', modified: '2026-11-12 10:00:00', status: 'Pending Review', customer: 'KEEP', items: [], ...values},
    fields_dict: new Proxy({}, {get: () => ({df: {}, grid: {update_docfield_property(...args) {properties.push(args);}}, $wrapper: {html() {}}})}),
    set_query(...args) {queries.push(args);}, set_intro() {}, set_df_property() {}, toggle_display() {},
    page: {add_menu_item(label, action) {buttons.set('Menu/' + label, action);}},
    add_custom_button(label, action, group) {buttons.set(`${group || ''}/${label}`, action);},
    is_new() {return this.doc.name.startsWith('new-');}, is_dirty() {return Boolean(this.doc.__unsaved);},
    async reload_doc() {reloads++;}, async set_value(field, value) {this.doc[field] = value; changed.push([field, value]);},
  };
  if (frm.doc.matching_json) {
    try {
      const matching = JSON.parse(frm.doc.matching_json);
      if (!Object.hasOwn(matching, 'context')) matching.context = {
        customer: frm.doc.customer || '', whatsapp_account: frm.doc.whatsapp_account || '',
        sender_number: frm.doc.sender_number || '', customer_text: frm.doc.customer_text || '',
        salesperson_text: frm.doc.salesperson_text || '',
        items: frm.doc.items.map(row => ({row_key: row.row_key || '', original_text: row.original_text || '', warehouse_text: row.warehouse_text || ''})),
      };
      frm.doc.matching_json = JSON.stringify(matching);
    } catch (_) {}
  }
  const escape = value => String(value).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  vm.runInNewContext(source, {
    __: text => text,
    frappe: {
      utils: {escape_html: escape},
      ui: {form: {on(doctype, value) {if (doctype === 'Order Intake Request') handlers = value;}},
        Dialog: class {constructor(options) {Object.assign(this, options); dialogs.push(this);} show() {} hide() {} }},
      msgprint(value) {messages.push(value);}, hide_msgprint() {}, show_alert() {},
      async call(value) {if (!value.silent) calls.push(value); return {message: {state: 'Matched'}};},
      model: {async set_value(doctype, name, field, value) {changed.push([name, field, value]); const row = frm.doc.items.find(item => item.name === name); row[field] = value;}},
    },
  });
  return {frm, handlers, buttons, dialogs, messages, calls, changed, queries, properties, get reloads() {return reloads;}};
}

test('matching is on demand and does not run on refresh or overwrite selected values', () => {
  const flow = setup({matching_json: JSON.stringify({customer: result('Customer wording', ['CANDIDATE'])})});
  const before = JSON.stringify(flow.frm.doc);
  flow.handlers.refresh(flow.frm);
  assert.equal(flow.calls.length, 0);
  assert.equal(JSON.stringify(flow.frm.doc), before);
  assert.equal(typeof flow.buttons.get('Menu/Find matches'), 'function');
  assert.equal(typeof flow.buttons.get('Menu/Review matches'), 'function');
  assert.equal(flow.buttons.has('/Find matches'), false);
  assert.equal(flow.buttons.has('/Review matches'), false);
});

test('finding matches explains the action, posts the saved revision, and reloads', async () => {
  const flow = setup(); flow.handlers.refresh(flow.frm);
  await flow.buttons.get('Menu/Find matches')();
  assert.match(flow.messages[0].message, /existing selections stay unchanged/);
  await flow.messages[0].primary_action.action();
  assert.equal(flow.calls[0].method, 'kunal_enterprises.api.order_intake_matching.match_request');
  assert.equal(flow.calls[0].type, 'POST');
  assert.equal(flow.calls[0].args.request, 'OIR-MATCH');
  assert.equal(flow.calls[0].args.expected_modified, '2026-11-12 10:00:00');
  assert.equal(flow.reloads, 1);
});

test('unsaved changes or switching requests prevent the matching request', async () => {
  const flow = setup(); flow.handlers.refresh(flow.frm);
  flow.frm.doc.__unsaved = true;
  await flow.buttons.get('Menu/Find matches')();
  assert.match(flow.messages[0], /Save your changes/);
  flow.frm.doc.__unsaved = false;
  await flow.buttons.get('Menu/Find matches')();
  flow.frm.doc.name = 'OIR-OTHER';
  await flow.messages[1].primary_action.action();
  assert.equal(flow.calls.length, 0);
});

test('terminal and converted requests do not offer matching actions', () => {
  for (const values of [{status: 'Resolved'}, {status: 'Dismissed'}, {status: 'Converted to Order'}, {order: 'ORDER-1'}, {name: 'new-order-intake-request'}]) {
    const flow = setup(values); flow.handlers.refresh(flow.frm);
    assert.equal(flow.buttons.has('Menu/Find matches'), false);
    assert.equal(flow.buttons.has('Menu/Review matches'), false);
  }
});

test('review applies explicit candidate choices to stable rows without saving or altering quantity', async () => {
  const flow = setup({items: [{name: 'ROW-1', row_key: 'KEY-1', original_text: '21317 MR', quantity: 4, item: 'OLD', godown: 'OLD-WH'}],
    matching_json: JSON.stringify({customer: result('Customer wording', ['C-1']), items: [{row_key: 'KEY-1', item: result('21317 MR', ['SKU-1']), godown: result('Main', ['WH-1'])}]})});
  flow.handlers.refresh(flow.frm); await flow.buttons.get('Menu/Review matches')();
  const dialog = flow.dialogs[0];
  assert.match(dialog.fields.map(f => f.options).join(''), /KEEP/);
  assert.equal(flow.changed.length, 0);
  await dialog.primary_action({match_0: '', match_1: 'SKU-1', match_2: 'WH-1'});
  assert.equal(flow.frm.doc.customer, 'KEEP');
  assert.equal(flow.frm.doc.items[0].item, 'SKU-1');
  assert.equal(flow.frm.doc.items[0].godown, 'WH-1');
  assert.equal(flow.frm.doc.items[0].quantity, 4);
  assert.equal(flow.calls.length, 0);
});

test('forged choices and rows deleted while reviewing are rejected before any change', async () => {
  for (const removeRow of [false, true]) {
    const flow = setup({items: [{name: 'ROW-1', row_key: 'KEY-1'}], matching_json: JSON.stringify({customer: result('Customer', ['C-1']), items: [{row_key: 'KEY-1', item: result('item', ['SKU-1'])}]})});
    flow.handlers.refresh(flow.frm); await flow.buttons.get('Menu/Review matches')();
    if (removeRow) flow.frm.doc.items = [];
    await flow.dialogs[0].primary_action({match_0: 'C-1', match_1: removeRow ? 'SKU-1' : 'FORGED'});
    assert.equal(flow.changed.length, 0);
    assert.match(flow.messages[0], /available matches changed/);
  }
});

test('candidate labels, original wording, reasons and field labels are escaped', async () => {
  const malicious = '<img src=x onerror=bad()>';
  const flow = setup({items: [{name: 'ROW-1', row_key: 'KEY-1', original_text: malicious}], matching_json: JSON.stringify({items: [{row_key: 'KEY-1', item: {text: malicious, candidates: [candidate('SKU', {label: malicious, reason: malicious})], overflow: true}}]})});
  flow.handlers.refresh(flow.frm); await flow.buttons.get('Menu/Review matches')();
  const fields = flow.dialogs[0].fields;
  const rendered = fields.filter(f => f.fieldtype === 'HTML').map(f => f.options).join('');
  assert.match(rendered, /&lt;img/); assert.doesNotMatch(rendered, /<img/);
  assert.match(rendered, /More possible matches/);
  const select = fields.find(f => f.fieldtype === 'Select');
  assert.doesNotMatch(select.label, /<img/);
  assert.doesNotMatch(select.options[1].label, /<img/);
});

test('malformed stored matching data is visible as a warning rather than breaking the form', async () => {
  const flow = setup({matching_json: '{invalid'}); flow.handlers.refresh(flow.frm);
  await flow.buttons.get('Menu/Review matches')();
  assert.equal(flow.dialogs.length, 0);
  assert.match(flow.messages[0], /could not be displayed/);
});

test('item and warehouse links use scoped intake searches without mobile status gates', () => {
  const flow = setup(); flow.handlers.setup(flow.frm);
  for (const field of ['item', 'godown']) {
    const query = flow.queries.find(args => args[0] === field && args[1] === 'items');
    assert.equal(query[2]().query, 'kunal_enterprises.api.order_intake.intake_link_query');
    assert.equal(query[2]().filters, undefined);
    assert.ok(flow.properties.some(args => args[0] === field && args[1] === 'ignore_link_validation' && args[2] === true));
  }
});


test('missing or outdated context cannot offer saved choices after customer or wording changes', async () => {
  for (const change of ['missing', 'customer', 'wording', 'sender']) {
    const flow = setup({items: [{name: 'ROW', row_key: 'KEY', original_text: 'old text'}],
      matching_json: JSON.stringify({context: change === 'missing' ? null : undefined, customer: result('Customer', ['C-1'])})});
    // setup supplies the server context for ordinary fixtures.
    if (change !== 'missing') {
      const matching = JSON.parse(flow.frm.doc.matching_json);
      matching.context = {customer: 'KEEP', whatsapp_account: '', sender_number: '', customer_text: '', salesperson_text: '',
        items: [{row_key: 'KEY', original_text: 'old text', warehouse_text: ''}]};
      flow.frm.doc.matching_json = JSON.stringify(matching);
      if (change === 'customer') flow.frm.doc.customer = 'DIFFERENT';
      if (change === 'wording') flow.frm.doc.items[0].original_text = 'new text';
      if (change === 'sender') flow.frm.doc.sender_number = 'different-sender';
    }
    flow.handlers.refresh(flow.frm); await flow.buttons.get('Menu/Review matches')();
    assert.equal(flow.dialogs.length, 0);
    assert.match(flow.messages[0], /Find matches again/);
  }
});

test('intervening manual master selections cannot be overwritten by an already-open dialog', async () => {
  for (const change of ['customer', 'item', 'warehouse']) {
    const flow = setup({items: [{name: 'ROW', row_key: 'KEY', original_text: 'item', item: 'OLD', godown: 'WH'}],
      matching_json: JSON.stringify({customer: result('Customer', ['C-1']), items: [{row_key: 'KEY', item: result('item', ['SKU-1'])}]})});
    flow.handlers.refresh(flow.frm); await flow.buttons.get('Menu/Review matches')();
    if (change === 'customer') flow.frm.doc.customer = 'MANUAL';
    if (change === 'item') flow.frm.doc.items[0].item = 'MANUAL';
    if (change === 'warehouse') flow.frm.doc.items[0].godown = 'MANUAL';
    await flow.dialogs[0].primary_action({match_1: 'SKU-1'});
    assert.equal(flow.changed.length, 0);
    assert.match(flow.messages[0], /available matches changed/);
  }
});

test('changing customer cannot apply customer-scoped item choices in the same operation', async () => {
  const flow = setup({items: [{name: 'ROW', row_key: 'KEY', original_text: 'item'}],
    matching_json: JSON.stringify({customer: result('Customer', ['C-1']), items: [{row_key: 'KEY', item: result('item', ['SKU-1'])}]})});
  flow.handlers.refresh(flow.frm); await flow.buttons.get('Menu/Review matches')();
  await flow.dialogs[0].primary_action({match_0: 'C-1', match_1: 'SKU-1'});
  assert.equal(flow.changed.length, 0);
  assert.match(flow.messages[0], /customer first/);
  await flow.dialogs[0].primary_action({match_0: 'C-1'});
  assert.equal(flow.frm.doc.customer, 'C-1');
  assert.equal(flow.frm.doc.items[0].item, undefined);
});


test('reordering rows does not invalidate stable matching identities', async () => {
  const flow = setup({items: [{name: 'ROW-A', row_key: 'A', original_text: 'first'}, {name: 'ROW-B', row_key: 'B', original_text: 'second'}],
    matching_json: JSON.stringify({items: [{row_key: 'A', item: result('first', ['SKU-A'])}]})});
  flow.frm.doc.items.reverse();
  flow.handlers.refresh(flow.frm); await flow.buttons.get('Menu/Review matches')();
  flow.frm.doc.items.reverse();
  await flow.dialogs[0].primary_action({match_0: 'SKU-A'});
  assert.equal(flow.frm.doc.items.find(row => row.row_key === 'A').item, 'SKU-A');
  assert.equal(flow.frm.doc.items.find(row => row.row_key === 'B').item, undefined);
});

test('malformed matching context is reported without opening a broken dialog', async () => {
  const flow = setup({matching_json: JSON.stringify({context: {items: [null]}, customer: result('Customer', ['C-1'])})});
  flow.handlers.refresh(flow.frm); await flow.buttons.get('Menu/Review matches')();
  assert.equal(flow.dialogs.length, 0);
  assert.match(flow.messages[0], /Find matches again/);
});
