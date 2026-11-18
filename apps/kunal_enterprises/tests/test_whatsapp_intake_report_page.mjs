import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/kunal_enterprises/page/whatsapp_intake_report/whatsapp_intake_report.js', import.meta.url), 'utf8');
const escape = value => String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));

function report() {
  const context = {
    __: value => value,
    frappe: {pages: {'whatsapp-intake-report': {}}, utils: {escape_html: escape}},
    location: {origin: 'http://localhost:8000'}, URL,
  };
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, 'this.Report = WhatsAppIntakeReport; })();'), context);
  return Object.create(context.Report.prototype);
}

test('an older report request cannot replace a newer filter result', async () => {
  const instance = report();
  const pending = [];
  const rendered = [];
  const selectable = {};
  Object.assign(instance, {
    root: {querySelector: () => selectable}, status: {}, summary: {replaceChildren() {}},
    generation: 0, breakdownGeneration: 0, pickerGeneration: 0, mode: 'overview',
    dialog: {open: false}, detailGeneration: 0,
    filters: {from_date: '2026-11-01', to_date: '2026-11-18'},
    call: () => new Promise(resolve => pending.push(resolve)),
    drawTabs() {}, renderMode() {rendered.push(this.data.totals.received);},
  });
  const oldRequest = instance.refresh();
  instance.filters.to_date = '2026-11-19';
  const newRequest = instance.refresh();
  pending[1]({scope: 'sales', totals: {received: 4}});
  await newRequest;
  pending[0]({scope: 'overall', totals: {received: 50}});
  await oldRequest;
  assert.deepEqual(rendered, [4]);
  assert.equal(selectable.hidden, true);
});

test('the conversion total opens actual orders for the current received date range', () => {
  const instance = report();
  const button = {dataset: {metric: 'orders'}, textContent: 'Orders created12'};
  instance.drill = (view, filter, title, opener) => {
    assert.equal(view, 'intakes');
    assert.equal(filter.metric, 'orders');
    assert.equal(title, 'Orders created');
    assert.equal(opener, button);
  };
  instance.click({target: {closest: selector => selector === 'button' ? button : null}});
});

test('only the selected message is labeled and only site file paths are opened', () => {
  const instance = report();
  const selected = {name: 'WA-1', text: '<script>example</script>', content_type: 'image',
    received_at: '2026-11-19T00:15:09', attachment: {available: true, url: '/private/files/attachment.png'}};
  const context = {name: 'WA-2', attachment: {available: true, url: '/files/../external'}};
  const selectedHtml = instance.bubble(selected, 'WA-1');
  const contextHtml = instance.bubble(context, 'WA-1');
  assert.match(selectedHtml, />Selected message<\/strong>/);
  assert.doesNotMatch(selectedHtml, /Selected message · WA-1/);
  assert.match(selectedHtml, /2026-11-19 00:15/);
  assert.match(selectedHtml, /&lt;script&gt;/);
  assert.match(selectedHtml, /href="\/private\/files\/attachment\.png"/);
  assert.doesNotMatch(contextHtml, /Selected message|href=/);
});

test('message rows show readable previews and keep internal IDs out of the list', () => {
  const instance = report();
  instance.paged = (_host, config) => {
    assert.deepEqual([...config.columns], ['Message', 'Status']);
    const text = config.row({name: 'hidden-message-id', preview: 'Send <4> sheets', sender_name: 'Sender',
      received_at: '2026-11-19 00:15:09', coverage: 'waiting', status: 'Waiting to process', reason: 'Processing is pending.'}, 0);
    assert.match(text, /Send &lt;4&gt; sheets/);
    assert.match(text, /Sender · 2026-11-19 00:15/);
    assert.doesNotMatch(text, /hidden-message-id|Processing is pending/);
    assert.match(config.row({message_kind: 'image'}, 1), />Photo<\/button>/);
    assert.match(config.row({message_kind: 'restricted'}, 2), />Restricted message<\/button>/);
    assert.match(config.row({coverage: 'failed', reason: 'Attachment download failed.'}, 3), /Attachment download failed/);
  };
  instance.messageList(null, {}, () => true, () => {});
});
