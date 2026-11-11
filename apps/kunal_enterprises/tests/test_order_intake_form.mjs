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
  const makeField = name => ({ df: {}, grid: { update_docfield_property() {} },
    $wrapper: { html(value) { html.set(name, value); return this; } } });
  const frm = {
    doc: { name: 'OIR-A', items: [], attachments: [], source_messages: [], ...values },
    fields_dict: new Proxy({}, { get(_, name) {
      if (!fields.has(name)) fields.set(name, makeField(name));
      return fields.get(name);
    } }),
    set_intro() {},
    set_query() {},
    set_df_property(name, property, value) {
      this.fields_dict[name].df[property] = value;
      if (property === 'hidden') hidden.set(name, Boolean(value));
    },
    toggle_display(names, show) {
      for (const name of Array.isArray(names) ? names : [names]) hidden.set(name, !show);
    },
    add_custom_button(label, action, group) {
      buttons.set(`${group || ''}/${label}`, action);
      return { addClass() { return this; } };
    },
    remove_custom_button(label, group) { buttons.delete(`${group || ''}/${label}`); },
    refresh_field() {},
    scroll_to_field() {},
    dirty() {},
    is_new() { return this.doc.name.startsWith('new-'); },
    set_value(name, value) { this.doc[name] = value; return Promise.resolve(); },
  };
  vm.runInNewContext(source, {
    __: value => value,
    frappe: {
      ui: { form: { on(doctype, registered) {
        if (doctype === 'Order Intake Request') handlers = registered;
      } } },
      utils: { escape_html: value => String(value).replace(/[&<>"']/g,
        char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]) },
    },
  });
  return { frm, hidden, buttons, html, handlers };
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
    ['Interpretation', 'interpretation_section'],
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
