import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order/order.js', import.meta.url), 'utf8');

function setup({ dirty = true, saving = false } = {}) {
  const warnings = [];
  const handlers = {};
  const closeHandlers = {};
  const close = { show() { return this; }, removeAttr() { return this; }, on(name, fn) { closeHandlers[name] = fn; return this; } };
  const main = { hides: 0, hide() { this.hides++; }, get_close_btn() { return close; },
    $wrapper: { on(name, fn) { handlers[name] = fn; } } };
  const protect = vm.runInNewContext(`${source}\nprotect_assignment_changes;`, {
    __: (message) => message,
    frappe: { ui: { form: { on() {} }, Dialog: class {
      constructor(options) { this.options = options; warnings.push(this); }
      show() { this.shown = true; }
      hide() { this.shown = false; this.options.on_hide?.(); }
    } } },
  });
  protect(main, () => dirty, () => saving);
  const background = () => { const target = {}; handlers['click.assignment']({ target, currentTarget: target }); };
  const event = { key: 'Escape', preventDefault() {}, stopPropagation() {} };
  return { main, warnings, background, close: () => closeHandlers['click.assignment'](event),
    escape: () => handlers['keydown.assignment'](event) };
}

test('untouched assignments close without a discard prompt', () => {
  const flow = setup({ dirty: false });
  flow.background();
  assert.equal(flow.main.hides, 1);
  assert.equal(flow.warnings.length, 0);
});

test('outside click preserves changes and Continue Editing leaves the modal open', () => {
  const flow = setup();
  flow.background();
  flow.background();
  assert.equal(flow.main.hides, 0);
  assert.equal(flow.warnings.length, 1);
  assert.equal(flow.warnings[0].options.primary_action_label, 'Continue Editing');
  flow.warnings[0].options.primary_action();
  assert.equal(flow.main.hides, 0);
  flow.background();
  assert.equal(flow.warnings.length, 2);
});

test('Discard Changes closes both dialogs explicitly', () => {
  const flow = setup();
  flow.background();
  assert.equal(flow.warnings[0].options.secondary_action_label, 'Discard Changes');
  flow.warnings[0].options.secondary_action();
  assert.equal(flow.warnings[0].shown, false);
  assert.equal(flow.main.hides, 1);
});

test('close button and Escape protect entered allocations', () => {
  for (const action of ['close', 'escape']) {
    const flow = setup();
    flow[action]();
    assert.equal(flow.main.hides, 0);
    assert.equal(flow.warnings.length, 1);
  }
});

test('assignment cannot be dismissed while saving', () => {
  const flow = setup({ saving: true });
  flow.background();
  flow.close();
  flow.escape();
  assert.equal(flow.main.hides, 0);
  assert.equal(flow.warnings.length, 0);
});

test('authorized allocators can reopen saved Placed assignments, but not Processing assignments', () => {
  const visible = vm.runInNewContext(`${source}\nshould_show_assign_godowns;`, {
    __: (message) => message,
    frappe: { session: { user: 'allocator@example.com' }, user_roles: ['Godown Allocator'], ui: { form: { on() {} } } },
  });
  const frm = { is_new: () => false, doc: { status: 'Placed', godown_assignment_pending: 0,
    godown_allocations: [{ godown: 'A', requested_quantity: 3 }] } };
  assert.equal(visible(frm), true);
  frm.doc.status = 'Processing';
  assert.equal(visible(frm), false);
});

test('branch users without allocation authority cannot open saved assignment editing', () => {
  const visible = vm.runInNewContext(`${source}\nshould_show_assign_godowns;`, {
    __: (message) => message,
    frappe: { session: { user: 'branch@example.com' }, user_roles: ['Branch Employee'], ui: { form: { on() {} } } },
  });
  assert.equal(visible({ is_new: () => false, doc: { status: 'Placed', godown_assignment_pending: 0 } }), false);
});
