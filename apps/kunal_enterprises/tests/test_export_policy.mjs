import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../kunal_enterprises/public/js/export_policy.js', import.meta.url), 'utf8');

function setup({roles = ['Branch Employee'], user = 'staff@example.com', route = ['List', 'Order', 'List'], maxPageLength = 200} = {}) {
  const added = [];
  class Page {
    constructor() { this.actions = {}; this.menu = {}; }
    add_dropdown_item(options) { added.push(options); return {visible: true}; }
    add_inner_button(label) { added.push({label}); return {visible: true}; }
  }
  const frappe = {
    session: {user}, user_roles: roles,
    boot: {kunal_max_list_rows: maxPageLength},
    views: {},
    get_route: () => route,
    model: {can_export: (doctype) => doctype === 'Exportable'},
    ui: {Page},
  };
  vm.runInNewContext(source, {
    frappe,
    __: (label, args, context) => context ? `translated:${context}:${label}` : `translated:${label}`,
    $: (value) => Array.isArray(value) ? {visible: false} : {
      data: (key) => value[key],
    },
  });
  return {frappe, page: new Page(), added};
}

function installLazyBaseList(frappe) {
  frappe.views.BaseList = class {
    constructor() { this.page_length = 500; this.selected_page_count = 500; }
    setup_paging_area() {
      this.buttons = [20, 100, 500, 2500].map(value => ({value}));
      this.$paging_area = {
        find: () => ({
          filter: (callback) => ({
            remove: () => { this.buttons = this.buttons.filter(button => !callback.call(button)); },
          }),
        }),
      };
    }
  };
}

for (const role of ['Branch Manager', 'Branch Employee', 'Order Coordinator', 'Godown Allocator']) {
  test(`${role} cannot use export menus even on a DocType granting export`, () => {
    const {frappe, page, added} = setup({roles: [role, 'Desk User', 'All']});
    assert.equal(frappe.model.can_export('Exportable'), false);
    for (const label of ['Export', 'Export as zip', 'Download Report', 'Download as CSV']) {
      assert.equal(page.add_dropdown_item({label: `translated:${label}`, parent: page.actions}).visible, false);
      assert.equal(page.add_inner_button(`translated:${label}`).visible, false);
    }
    assert.equal(added.length, 0);
  });
}

test('context-translated list actions are hidden while ordinary actions remain', () => {
  const {page, added} = setup();
  page.add_dropdown_item({label: 'translated:Button in list view actions menu:Export', parent: page.actions});
  page.add_dropdown_item({label: 'translated:Button in list view actions menu:Print', parent: page.actions});
  page.add_dropdown_item({label: 'translated:Assign To', parent: page.actions});
  assert.deepEqual(added.map(x => x.label), ['translated:Assign To']);
});

test('individual document printing remains available', () => {
  const {page, added} = setup({route: ['Form', 'Order', 'KE-ORD-1']});
  page.add_dropdown_item({label: 'translated:Print', parent: page.menu});
  page.add_dropdown_item({label: 'translated:PDF', parent: page.menu});
  page.add_inner_button('translated:Print');
  assert.equal(added.length, 3);
});

for (const route of [['query-report', 'ToDo'], ['List', 'Order', 'Report']]) {
  test(`bulk report Print/PDF is omitted on ${route.join('/')}`, () => {
    const {page, added} = setup({route});
    page.add_dropdown_item({label: 'translated:Print', parent: page.menu});
    page.add_dropdown_item({label: 'translated:PDF', parent: page.menu});
    page.add_dropdown_item({label: 'translated:Refresh', parent: page.menu});
    assert.deepEqual(added.map(x => x.label), ['translated:Refresh']);
  });
}

for (const actor of [
  {roles: ['Owner']}, {roles: ['Admin']}, {roles: ['System Manager']},
  {roles: ['Branch Employee', 'Owner']}, {roles: [], user: 'Administrator'},
]) {
  test(`${actor.user || actor.roles.join('+')} retains original export and print access`, () => {
    const {frappe, page, added} = setup(actor);
    assert.equal(frappe.model.can_export('Exportable'), true);
    assert.equal(frappe.model.can_export('NotExportable'), false);
    page.add_dropdown_item({label: 'translated:Export', parent: page.actions});
    page.add_dropdown_item({label: 'translated:Print', parent: page.actions});
    page.add_inner_button('translated:Download Report');
    assert.equal(added.length, 3);
  });
}

test('Administrator role name alone does not grant special user bypass', () => {
  const {frappe} = setup({roles: ['Administrator']});
  assert.equal(frappe.model.can_export('Exportable'), false);
});

test('Report Manager cannot create a scheduled report export from the report menu', () => {
  const {page, added} = setup({roles: ['Report Manager'], route: ['query-report', 'Note']});
  assert.equal(page.add_dropdown_item({label: 'translated:Setup Auto Email', parent: page.menu}).visible, false);
  assert.equal(added.length, 0);
});

test('lazy list pager removes oversized options and limits stale page selections', () => {
  const {frappe, page} = setup();
  installLazyBaseList(frappe);
  page.add_dropdown_item({label: 'translated:Refresh', parent: page.menu});
  const list = new frappe.views.BaseList();
  list.setup_paging_area();
  assert.deepEqual(list.buttons.map(button => button.value), [20, 100]);
  assert.equal(list.page_length, 100);
  assert.equal(list.selected_page_count, 100);
});

test('pager uses the server-provided maximum without hiding ordinary page choices', () => {
  const {frappe, page} = setup({maxPageLength: 50});
  installLazyBaseList(frappe);
  page.add_dropdown_item({label: 'translated:Refresh', parent: page.menu});
  const list = new frappe.views.BaseList();
  list.setup_paging_area();
  assert.deepEqual(list.buttons.map(button => button.value), [20]);
  assert.equal(list.page_length, 20);
});

test('privileged pager retains all original choices and page sizes', () => {
  const {frappe, page} = setup({roles: ['Admin']});
  installLazyBaseList(frappe);
  page.add_dropdown_item({label: 'translated:Refresh', parent: page.menu});
  const list = new frappe.views.BaseList();
  list.setup_paging_area();
  assert.deepEqual(list.buttons.map(button => button.value), [20, 100, 500, 2500]);
  assert.equal(list.page_length, 500);
  assert.equal(list.selected_page_count, 500);
});
