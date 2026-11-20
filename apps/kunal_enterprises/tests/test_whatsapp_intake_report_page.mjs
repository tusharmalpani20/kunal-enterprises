import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/kunal_enterprises/page/whatsapp_intake_report/whatsapp_intake_report.js', import.meta.url), 'utf8');
const escape = value => String(value).replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));

function loadReport(overrides = {}) {
  const context = {
    __: (value, params = []) => value.replace(/\{(\d+)\}/g, (placeholder, index) => params[index] ?? placeholder),
    frappe: {pages: {'whatsapp-intake-report': {}}, utils: {escape_html: escape}},
    location: {origin: 'http://localhost:8000'}, URL,
    ...overrides,
  };
  const expose = 'this.Rows = ReportRows; if (this.TestRows) ReportRows = this.TestRows; this.Report = WhatsAppIntakeReport; })();';
  vm.runInNewContext(source.replace(/\}\)\(\);\s*$/, expose), context);
  return context;
}

const report = overrides => Object.create(loadReport(overrides).Report.prototype);

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
  selected.attachment.file_name = 'a8cp008834.png';
  assert.match(instance.bubble(selected, 'WA-1'), /Open attachment/);
  assert.doesNotMatch(instance.bubble(selected, 'WA-1'), /a8cp008834\.png/);
  selected.content_type = 'document';
  selected.attachment.file_name = 'Drawing.pdf';
  assert.match(instance.bubble(selected, 'WA-1'), /Drawing\.pdf/);
});

test('a failed page-size switch preserves the current page and can be retried', async () => {
  const state = {};
  const instance = report({
    document: {activeElement: null},
    TestRows: class { set(rows) { state.rows = rows; } },
  });
  const control = () => ({setAttribute() {}, removeAttribute() {}});
  const nodes = {
    '.wir-scroll': {...control(), classList: {add() {}}}, '.wir-page-actions': {contains: () => false},
    '[data-previous]': control(), '[data-next]': control(), '.wir-page-number': control(),
    '.wir-page-size select': control(), '.wir-page-status': control(),
  };
  const previous = nodes['[data-previous]'], next = nodes['[data-next]'];
  const size = nodes['.wir-page-size select'], status = nodes['.wir-page-status'];
  let shouldFail = true;
  const allRows = Array.from({length: 51}, (_, i) => ({name: `row-${i + 1}`}));
  instance.call = async (_view, _filter, options) => {
    if (options.page_size === 100 && shouldFail) throw Error('Temporary request failure');
    if (options.page_size === 100) return {rows: allRows, next_cursor: null};
    return options.cursor ? {rows: allRows.slice(50)} : {rows: allRows.slice(0, 50), next_cursor: 'second-page'};
  };
  await instance.paged({querySelector: selector => nodes[selector]}, {view: 'messages', total: 51, current: () => true});
  assert.equal(status.textContent, 'Showing 1–50 of 51');
  await next.onclick();
  assert.equal(status.textContent, 'Showing 51 of 51');
  assert.equal(state.rows[0].name, 'row-51');
  size.value = '100';
  await size.onchange();
  assert.equal(size.value, '50');
  assert.equal(nodes['.wir-page-number'].textContent, '2');
  assert.equal(previous.disabled, false);
  assert.equal(state.rows[0].name, 'row-51');
  shouldFail = false;
  await next.onclick();
  assert.equal(size.value, '100');
  assert.equal(status.textContent, 'Showing 1–51 of 51');
  assert.equal(previous.disabled, true);
  assert.equal(next.disabled, true);
});

test('arrow keys navigate to read-only rows without action buttons', () => {
  const rows = Object.create(loadReport().Rows.prototype);
  let focused = false;
  Object.assign(rows, {
    items: [{}, {}], rowHeight: 44, paint() {},
    container: {scrollTop: 0, clientHeight: 100, querySelector: () => ({offsetHeight: 30})},
    nodes: new Map([[1, {querySelector: () => null, focus: () => { focused = true; }}]]),
  });
  rows.navigate({key: 'ArrowDown', preventDefault() {}, target: {closest: () => ({dataset: {index: '0'}})}});
  assert.equal(focused, true);
  assert.equal(rows.container.scrollTop, 18);
});

test('message rows show readable previews and keep internal IDs out of the list', () => {
  const instance = report();
  instance.data = {totals: {unaccounted: 61}};
  instance.paged = (_host, config) => {
    assert.deepEqual([...config.columns], ['Message', 'Status']);
    assert.equal(config.total, 61);
    const text = config.row({name: 'hidden-message-id', preview: 'Send <4> sheets', sender_name: 'Sender',
      received_at: '2026-11-19 00:15:09', coverage: 'waiting', status: 'Waiting to process', reason: 'Processing is pending.'}, 0);
    assert.match(text, /Send &lt;4&gt; sheets/);
    assert.match(text, /Sender · 2026-11-19 00:15/);
    assert.doesNotMatch(text, /hidden-message-id|Processing is pending/);
    assert.match(config.row({message_kind: 'image'}, 1), />Photo<\/button>/);
    assert.match(config.row({message_kind: 'restricted'}, 2), />Restricted message<\/button>/);
    assert.match(config.row({coverage: 'failed', reason: 'Attachment download failed.'}, 3), /Attachment download failed/);
  };
  instance.messageList(null, {metric: 'unaccounted'}, () => true, () => {});
});
