import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/public/js/sales_portal.js', import.meta.url), 'utf8');

function setup({roles = ['Sales Portal User'], user = 'sales@example.com'} = {}) {
  const styles = [], events = new Map(), delivered = [];
  const document = {createElement(tag) {return {tag, textContent: ''};}, head: {appendChild(node) {styles.push(node);}}};
  const realtime = {identity: 'original-realtime', emit(...args) {delivered.push({receiver: this, args}); return 'delivered';}};
  const originalEmit = realtime.emit;
  const frappe = {user_roles: roles, session: {user}, realtime};
  vm.runInNewContext(source, {frappe, document, $(target) {
    assert.equal(target, document);
    return {on(event, callback) {events.set(event, callback);}};
  }});
  return {frappe, styles, delivered, originalEmit, ready() {events.get('app_ready')();}};
}

test('sales boot installs read-only action styling and suppresses only broad realtime subscriptions', () => {
  const ui = setup();
  assert.equal(ui.styles.length, 1);
  for (const args of [
    ['doctype_subscribe', 'Order'],
    ['doctype_subscribe', 'Customer'],
    ['doc_subscribe', 'WhatsApp Account', 'TEST-WA'],
  ]) {
    ui.frappe.realtime.emit(...args);
  }
  assert.equal(ui.delivered.length, 0, 'broad rooms never reach socket emitter');
  const args = ['doc_subscribe', 'Order Intake Request', 'ALLOWED-INTAKE'];
  assert.equal(ui.frappe.realtime.emit(...args), 'delivered');
  assert.deepEqual(ui.delivered[0].args, args);
  assert.equal(ui.delivered[0].receiver, ui.frappe.realtime, 'original emitter receives its original context');
  ui.frappe.realtime.emit('doc_subscribe', 'WhatsApp Message', 'ALLOWED-MESSAGE');
  ui.frappe.realtime.emit('doc_unsubscribe', 'Order', 'ALLOWED-ORDER');
  ui.frappe.realtime.emit('other-event', {payload: 'preserved'});
  assert.equal(ui.delivered.length, 4, 'ordinary document events keep working');
});

test('app_ready installs protections when user roles are populated after the script loads', () => {
  const ui = setup({roles: []});
  assert.equal(ui.styles.length, 0);
  assert.equal(ui.frappe.realtime.emit, ui.originalEmit);
  ui.frappe.user_roles = ['Sales Portal User'];
  ui.ready();
  assert.equal(ui.styles.length, 1);
  ui.frappe.realtime.emit('doc_subscribe', 'WhatsApp Account', 'TEST-WA');
  assert.equal(ui.delivered.length, 0);
  const wrappedEmit = ui.frappe.realtime.emit;
  ui.ready();
  ui.ready();
  assert.equal(ui.styles.length, 1, 'repeated ready events do not append duplicate styling');
  assert.equal(ui.frappe.realtime.emit, wrappedEmit, 'repeated ready events do not wrap emitter again');
});

test('Administrator and privileged or unrelated roles keep their original styles and realtime behavior', () => {
  for (const config of [
    {user: 'Administrator'},
    ...['Owner', 'Admin', 'System Manager'].map(role => ({roles: ['Sales Portal User', role]})),
    {roles: ['Order Coordinator']},
    {roles: ['Branch Employee']},
  ]) {
    const ui = setup(config);
    ui.ready();
    assert.equal(ui.styles.length, 0);
    assert.equal(ui.frappe.realtime.emit, ui.originalEmit);
    ui.frappe.realtime.emit('doctype_subscribe', 'Order');
    assert.deepEqual(ui.delivered[0].args, ['doctype_subscribe', 'Order']);
  }
});
