import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order_intake_request/order_intake_request.js', import.meta.url), 'utf8');
const optionalSections = ['delivery_section', 'references_section', 'interpretation_section'];

function setup(values = {}) {
  let handlers;
  const hidden = new Map();
  const buttons = new Map();
  const html = new Map();
  const fields = new Map();
  const messages = [], calls = [];
  let reloaded = 0;
  const makeField = name => ({ df: {}, grid: { update_docfield_property() {} },
    $wrapper: { html(value) { html.set(name, value); return this; } } });
  const frm = {
    doc: { name: 'OIR-A', modified: '2026-11-12 00:00:00', items: [], attachments: [], source_messages: [], ...values },
    fields_dict: new Proxy({}, { get(_, name) {
      if (!fields.has(name)) fields.set(name, makeField(name));
      return fields.get(name);
    } }),
    set_intro(text, color) { this.intro = {text, color}; },
    set_query() {},
    set_df_property(name, property, value) {
      this.fields_dict[name].df[property] = value;
      if (property === 'hidden') hidden.set(name, Boolean(value));
    },
    toggle_display(names, show) {
      for (const name of Array.isArray(names) ? names : [names]) hidden.set(name, !show);
    },
    page: {add_menu_item(label, action) {buttons.set('Menu/' + label, action);}},
    add_custom_button(label, action, group) {
      buttons.set(`${group || ''}/${label}`, action);
      return { addClass() { return this; } };
    },
    remove_custom_button(label, group) { buttons.delete(`${group || ''}/${label}`); },
    refresh_field() {},
    scroll_to_field() {},
    dirty() {},
    is_new() { return this.doc.name.startsWith('new-'); },
    is_dirty() { return Boolean(this.doc.__unsaved); },
    async reload_doc() { reloaded++; },
    set_value(name, value) { this.doc[name] = value; return Promise.resolve(); },
  };
  vm.runInNewContext(source, {
    __: value => value,
    frappe: {
      msgprint: args => messages.push(args),
      hide_msgprint() {},
      call: async args => { if (!args.silent) calls.push(args); return { message: { state: 'Reviewed' } }; },
      ui: { form: { on(doctype, registered) {
        if (doctype === 'Order Intake Request') handlers = registered;
      } } },
      utils: { escape_html: value => String(value).replace(/[&<>"']/g,
        char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]) },
    },
  });
  return { frm, hidden, buttons, html, handlers, messages, calls, get reloaded() { return reloaded; } };
}

function assertVisible(flow, section, visible) {
  assert.equal(flow.hidden.get(section), !visible, `${section} should be ${visible ? 'visible' : 'hidden'}`);
}

test('empty optional sections stay out of the initial request form', () => {
  const flow = setup();
  flow.handlers.refresh(flow.frm);
  for (const section of optionalSections) assertVisible(flow, section, false);
});

test('delivery details, attachments and a manual interpretation show their sections', () => {
  const flow = setup({ delivery_contact_number: '9000000000',
    attachments: [{ reference_type: 'External Link', external_url: 'https://example.com/order' }],
    interpretation_notes: 'Customer requested delivery tomorrow.' });
  flow.handlers.refresh(flow.frm);
  for (const section of optionalSections) assertVisible(flow, section, true);
});

test('unresolved questions are visible even without an estimated interpretation', () => {
  const flow = setup({ unresolved_questions: 'Which warehouse did the sender mean?' });
  flow.handlers.refresh(flow.frm);
  assertVisible(flow, 'interpretation_section', true);
  assertVisible(flow, 'delivery_section', false);
  assertVisible(flow, 'references_section', false);
  assert.match(flow.html.get('interpretation_display'), /Which warehouse/);
});

test('Add Details reveals the requested empty section without changing draft data', async () => {
  const flow = setup({ items: [{ original_text: '21317 mr', quantity: 2, notes: 'Keep this note' }],
    review_notes: 'General note' });
  flow.handlers.refresh(flow.frm);
  const before = JSON.stringify(flow.frm.doc);
  for (const [label, section] of [
    ['Delivery Details', 'delivery_section'],
    ['Attachment or Reference', 'references_section'],
    ['Message Details', 'interpretation_section'],
  ]) {
    const action = flow.buttons.get(`Add Details/${label}`);
    assert.equal(typeof action, 'function', `Add Details offers ${label}`);
    await action();
    assertVisible(flow, section, true);
    assert.equal(JSON.stringify(flow.frm.doc), before, 'opening a section preserves the draft');
  }
});

test('saving a request hides optional sections that were opened but left empty', async () => {
  const flow = setup();
  flow.handlers.refresh(flow.frm);
  const action = flow.buttons.get('Add Details/Delivery Details');
  assert.equal(typeof action, 'function');
  await action();
  assertVisible(flow, 'delivery_section', true);
  assert.equal(typeof flow.handlers.after_save, 'function');
  await flow.handlers.after_save(flow.frm);
  for (const section of optionalSections) assertVisible(flow, section, false);
});

test('switching documents does not carry an empty section opened on another request', async () => {
  const flow = setup();
  flow.handlers.refresh(flow.frm);
  const action = flow.buttons.get('Add Details/Attachment or Reference');
  assert.equal(typeof action, 'function');
  await action();
  assertVisible(flow, 'references_section', true);
  flow.frm.doc = { name: 'OIR-B', items: [], attachments: [], source_messages: [] };
  flow.handlers.refresh(flow.frm);
  for (const section of optionalSections) assertVisible(flow, section, false);
});

test('AI interpretation text is displayed literally rather than inserted as executable HTML', () => {
  const estimate = '<img src=x onerror="alert(1)">\nTwo sheets requested';
  const questions = '<script>bad()</script>';
  const flow = setup({ estimated_interpretation: estimate, unresolved_questions: questions });
  flow.handlers.refresh(flow.frm);
  assertVisible(flow, 'interpretation_section', true);
  const rendered = flow.html.get('interpretation_display');
  assert.match(rendered, /&lt;img/);
  assert.match(rendered, /&lt;script&gt;/);
  assert.doesNotMatch(rendered, /<img|<script>/);
  assert.equal(flow.frm.doc.estimated_interpretation, estimate);
  assert.equal(flow.frm.doc.unresolved_questions, questions);
});

test('saving populated optional sections preserves their content and visibility', async () => {
  const flow = setup({ delivery_address: 'Customer site',
    attachments: [{ reference_type: 'File', file: '/private/files/purchase-order.pdf' }],
    interpretation_notes: 'Manual interpretation remains editable' });
  flow.handlers.refresh(flow.frm);
  const before = JSON.stringify(flow.frm.doc);
  await flow.handlers.after_save(flow.frm);
  for (const section of optionalSections) assertVisible(flow, section, true);
  assert.equal(JSON.stringify(flow.frm.doc), before);
});

test('late-message suggestions are readable and escaped without replacing reviewer values', () => {
  const flow = setup({ customer: 'CUSTOMER-SELECTED', items: [{ item: 'SKU-SELECTED', quantity: 3 }],
    proposed_updates: JSON.stringify([{ request_type: 'Order', summary: '<script>Late update</script>',
      customer_text: 'Different wording', items: [{ original_text: '21317 MR', quantity: 4, unit: 'NOS', warehouse_text: 'Main' }],
      unresolved_questions: ['Confirm customer'], media_warnings: { 'MSG-1': ['Unread attachment'] } }]) });
  const before = JSON.stringify(flow.frm.doc);
  flow.handlers.refresh(flow.frm);
  assertVisible(flow, 'interpretation_section', true);
  const rendered = flow.html.get('interpretation_display');
  assert.match(rendered, /Message updates/);
  assert.match(rendered, /21317 MR/);
  assert.match(rendered, /Unread attachment/);
  assert.match(rendered, /&lt;script&gt;/);
  assert.doesNotMatch(rendered, /<script>/);
  assert.equal(JSON.stringify(flow.frm.doc), before);
});

test('malformed stored suggestions show a review warning without breaking the form', () => {
  const flow = setup({ proposed_updates: '{bad json' });
  flow.handlers.refresh(flow.frm);
  assertVisible(flow, 'interpretation_section', true);
  assert.match(flow.html.get('interpretation_display'), /could not be displayed/);
});


test('message details are collapsed after ordinary fields and update review stays on demand', () => {
  const schema = JSON.parse(readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order_intake_request/order_intake_request.json', import.meta.url), 'utf8'));
  const section = schema.fields.find(field => field.fieldname === 'interpretation_section');
  assert.equal(section.collapsible, 1);
  assert.equal(section.label, 'Message Details');
  assert.ok(schema.field_order.indexOf('interpretation_section') > schema.field_order.indexOf('attachments'));
  const flow = setup({ proposed_updates: JSON.stringify([{ items: [] }]) });
  flow.handlers.refresh(flow.frm);
  assert.equal(typeof flow.buttons.get('/Review changes'), 'function');
  assert.match(flow.frm.intro.text, /New messages need review/);
  assert.equal(flow.frm.intro.color, 'orange');
  assert.equal(flow.buttons.has('/Review updates'), false);
  assert.equal(flow.messages.length, 0);
  assert.doesNotMatch(flow.html.get('interpretation_display'), /<details open/);
});

test('review dialog shows a compact quantity change without changing the draft', async () => {
  const flow = setup({ items: [{ original_text: '21317 MR', quantity: 4, unit: 'NOS' }],
    proposed_updates: JSON.stringify([{ items: [{ original_text: '21317 MR', quantity: 5, unit: 'NOS', warehouse_text: '<Main>' }] }]) });
  flow.handlers.refresh(flow.frm);
  const before = JSON.stringify(flow.frm.doc);
  await flow.buttons.get('/Review changes')();
  assert.match(flow.messages[0].message, /4 NOS → 5 NOS/);
  assert.match(flow.messages[0].message, /&lt;Main&gt;/);
  assert.equal(JSON.stringify(flow.frm.doc), before);
  await flow.messages[0].primary_action.action();
  assert.equal(flow.calls[0].method, 'kunal_enterprises.api.order_intake.review_update');
  assert.equal(flow.calls[0].type, 'POST');
  assert.deepEqual({ ...flow.calls[0].args }, { request: 'OIR-A', proposal_index: 0, expected_modified: '2026-11-12 00:00:00' });
  assert.equal(flow.reloaded, 1);
});

test('reviewed updates do not stay pending but remain available in message details', () => {
  const flow = setup({ proposed_updates: JSON.stringify([{ items: [], reviewed_at: '2026-11-12 01:00:00', reviewed_by: 'staff@example.com' }]) });
  flow.handlers.refresh(flow.frm);
  assert.equal(flow.buttons.has('/Review changes'), false);
  assert.equal(flow.frm.intro.text, '');
  assert.match(flow.html.get('interpretation_display'), /Reviewed/);
});

test('mark reviewed refuses to discard unsaved edits and uses original proposal index', async () => {
  const flow = setup({ proposed_updates: JSON.stringify([{ reviewed_at: 'already reviewed' }, { items: [] }]) });
  flow.handlers.refresh(flow.frm);
  await flow.buttons.get('/Review changes')();
  flow.frm.doc.__unsaved = true;
  await flow.messages[0].primary_action.action();
  assert.equal(flow.calls.length, 0);
  assert.match(flow.messages[1], /Save your changes/);
  flow.frm.doc.__unsaved = false;
  await flow.messages[0].primary_action.action();
  assert.equal(flow.calls[0].args.proposal_index, 1);
});

test('retained-item warnings appear directly in update review and stay escaped',()=>{
  const flow=setup({request_type:'Order',status:'Pending Review',proposed_updates:JSON.stringify([{items:[],review_warnings:['Earlier items retained <script>bad()</script>']}])});
  flow.handlers.refresh(flow.frm);
  assert.match(flow.html.get('interpretation_display'),/alert alert-warning/);
  assert.match(flow.html.get('interpretation_display'),/Earlier items retained &lt;script&gt;/);
  assert.doesNotMatch(flow.html.get('interpretation_display'),/<script>/);
});

 test('ordinary drafts have no update notice or update button', () => {
  const flow = setup();
  flow.handlers.refresh(flow.frm);
  assert.equal(flow.frm.intro.text, '');
  assert.equal(flow.buttons.has('/Review changes'), false);
 });

test('new shared contact details appear safely in the change review', async () => {
  const flow = setup({ proposed_updates: JSON.stringify([{ items: [], new_references: [
    { reference_type: 'Contact', label: '<Amol>', contact_number: '+91 99854 45566' },
  ] }]) });
  flow.handlers.refresh(flow.frm);
  await flow.buttons.get('/Review changes')();
  assert.match(flow.messages[0].message, /New attachment\/reference/);
  assert.match(flow.messages[0].message, /&lt;Amol&gt;/);
  assert.match(flow.messages[0].message, /\+91 99854 45566/);
  assert.doesNotMatch(flow.messages[0].message, /<Amol>/);
});
