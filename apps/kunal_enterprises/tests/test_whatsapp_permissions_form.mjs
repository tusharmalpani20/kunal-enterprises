import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const sources = Object.fromEntries(['order_intake_message', 'whatsapp_account_permissions'].map(name => [
  name, readFileSync(new URL(`../kunal_enterprises/public/js/${name}.js`, import.meta.url), 'utf8'),
]));

function setup({doctype = 'WhatsApp Message', write = false, autoRead = 0, canCreate = true, isNew = false, doc = {}} = {}) {
  const handlers = new Map();
  const buttons = new Map();
  const calls = [];
  const lookups = [];
  const newDocs = [];
  const confirmations = [];
  const routes = [];
  // A regression that appends handlers without removing the unsafe upstream
  // actions must fail, rather than silently passing a stub-only test.
  const unsafeUpstream = () => { throw new Error('Unsafe upstream handler was not replaced'); };
  handlers.set(`${doctype}:onload`, [unsafeUpstream]);
  handlers.set(`${doctype}:refresh`, [unsafeUpstream]);
  const frm = {
    doc: {name: 'WA-TEST', type: 'Incoming', from: '919000000039', whatsapp_account: 'Receiving Account',
      message_id: 'synthetic-id', status: 'Received', business_id: 'synthetic-business', ...doc},
    perm: [{write: Number(write)}],
    is_new: () => isNew,
    add_custom_button(label, callback) { buttons.set(label, callback); },
    async call(value) { calls.push(value); return {message: {success: true}}; },
    async reload_doc() {},
  };
  vm.runInNewContext(sources[doctype === 'WhatsApp Message' ? 'order_intake_message' : 'whatsapp_account_permissions'], {
    __: text => text,
    frappe: {
      session: {user: write ? 'admin@example.com' : 'coordinator@example.com'},
      user_roles: [write ? 'Admin' : 'Order Coordinator'],
      ui: {form: {
        off(type, event) { handlers.set(`${type}:${event}`, []); },
        on(type, registered) {
          for (const [event, callback] of Object.entries(registered)) {
            const key = `${type}:${event}`;
            handlers.set(key, [...(handlers.get(key) || []), callback]);
          }
        },
      }},
      db: {async get_value(...args) { lookups.push(args); return {message: {allow_auto_read_receipt: autoRead}}; }},
      model: {can_create: () => canCreate},
      new_doc(...args) { newDocs.push(JSON.parse(JSON.stringify(args))); },
      set_route(...args) { routes.push(JSON.parse(JSON.stringify(args))); },
      async call() { throw new Error('Intake API action was not requested'); },
      confirm(message, callback) { confirmations.push(message); callback(); },
    },
  });
  return {frm, buttons, calls, lookups, newDocs, confirmations, routes,
    async run(event) { for (const callback of handlers.get(`${doctype}:${event}`) || []) await callback(frm); }};
}

test('read-only reviewers never auto-read, reply or mark messages read', async () => {
  const flow = setup({autoRead: 1});
  await flow.run('onload');
  await flow.run('refresh');
  assert.equal(flow.lookups.length, 0);
  assert.equal(flow.calls.length, 0);
  assert.equal(flow.buttons.has('Reply'), false);
  assert.equal(flow.buttons.has('Mark as read'), false);
  assert.equal(flow.buttons.has('View Sender Messages'), true);
});

test('writer with auto-read disabled does not call Meta automatically', async () => {
  const flow = setup({write: true, autoRead: 0});
  await flow.run('onload');
  await flow.run('refresh');
  assert.deepEqual(flow.calls, []);
  assert.equal(flow.buttons.has('Mark as read'), true);
  await flow.buttons.get('Mark as read')();
  assert.deepEqual(flow.calls, ['send_read_receipt']);
});

test('writer with auto-read enabled sends exactly one automatic read receipt', async () => {
  const flow = setup({write: true, autoRead: 1});
  await flow.run('onload');
  await flow.run('refresh');
  assert.deepEqual(flow.calls, ['send_read_receipt']);
  assert.equal(flow.buttons.has('Mark as read'), false);
  assert.deepEqual(flow.lookups[0], ['WhatsApp Account', 'Receiving Account', 'allow_auto_read_receipt']);
});

test('Reply preserves both sender and receiving WhatsApp account', async () => {
  const flow = setup({write: true});
  await flow.run('refresh');
  assert.equal(flow.newDocs.length, 0);
  flow.buttons.get('Reply')();
  assert.deepEqual(flow.newDocs, [['WhatsApp Message', {to: '919000000039', whatsapp_account: 'Receiving Account'}]]);
});

test('writer without create permission has no Reply action', async () => {
  const flow = setup({write: true, canCreate: false});
  await flow.run('refresh');
  assert.equal(flow.buttons.has('Reply'), false);
  assert.equal(flow.buttons.has('Mark as read'), true);
});

test('new, outgoing and already-read messages do not send automatic read receipts', async () => {
  for (const options of [{isNew: true}, {doc: {type: 'Outgoing'}}, {doc: {status: 'marked as read'}}, {doc: {message_id: ''}}]) {
    const flow = setup({write: true, autoRead: 1, ...options});
    await flow.run('onload');
    await flow.run('refresh');
    assert.equal(flow.calls.length, 0);
    assert.equal(flow.buttons.has('Mark as read'), false);
  }
});

test('read-only account reviewers cannot subscribe the app', async () => {
  const flow = setup({doctype: 'WhatsApp Account'});
  await flow.run('refresh');
  assert.equal(flow.buttons.has('Subscribe App to Webhooks'), false);
  assert.equal(flow.calls.length, 0);
});

test('account writers subscribe only through the explicit confirmed action', async () => {
  const flow = setup({doctype: 'WhatsApp Account', write: true});
  await flow.run('refresh');
  assert.equal(flow.calls.length, 0);
  assert.equal(flow.buttons.has('Subscribe App to Webhooks'), true);
  flow.buttons.get('Subscribe App to Webhooks')();
  assert.equal(flow.confirmations.length, 1);
  assert.equal(flow.calls.length, 1);
  assert.equal(flow.calls[0].method, 'subscribe_app');
  assert.equal(flow.calls[0].doc, flow.frm.doc);
});

test('unsaved accounts cannot invoke subscription', async () => {
  const flow = setup({doctype: 'WhatsApp Account', write: true, isNew: true});
  await flow.run('refresh');
  assert.equal(flow.buttons.has('Subscribe App to Webhooks'), false);
});

test('sender history groups equivalent formatted numbers using the normalized identity', async () => {
  const flow = setup({doc: {from: '+91 (900) 000-0039', intake_sender_key: '919000000039'}});
  await flow.run('refresh');
  flow.buttons.get('View Sender Messages')();
  assert.deepEqual(flow.routes, [['List', 'WhatsApp Message', {
    type: 'Incoming', whatsapp_account: 'Receiving Account', intake_sender_key: '919000000039',
  }]]);
});

test('attachment retry is available only to writers with missing incoming media', async () => {
  const failed = {intake_media_id: 'synthetic-media', intake_media_state: 'Failed'};
  const reader = setup({doc: failed});
  await reader.run('refresh');
  assert.equal(reader.buttons.has('Retry Attachment Download'), false);
  const writer = setup({write: true, doc: failed});
  await writer.run('refresh');
  assert.equal(writer.buttons.has('Retry Attachment Download'), true);
  const downloaded = setup({write: true, doc: {...failed, intake_media_state: 'Downloaded', attach: '/private/files/example.pdf'}});
  await downloaded.run('refresh');
  assert.equal(downloaded.buttons.has('Retry Attachment Download'), false);
});
