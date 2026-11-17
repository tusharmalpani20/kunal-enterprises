/* Sales corrections use narrow actions; generic document writes stay denied. */
globalThis.kunal_sales_portal_user = () => frappe.session.user !== "Administrator" &&
 (frappe.user_roles || []).includes("Sales Portal User") &&
 !(frappe.user_roles || []).some(role => ["Owner", "Admin", "System Manager"].includes(role));

frappe.ui.form.on("Order Intake Request", {
 refresh(frm) {
  if (!globalThis.kunal_sales_portal_user()) return;
  frm.disable_save();
  if (frm.is_new() || !["Pending Review", "In Review", "Awaiting Confirmation"].includes(frm.doc.status) || frm.doc.order) return;
  frm.add_custom_button(__("Correct intake"), () => sales_correct_intake(frm));
  if (frm.doc.sales_approval_status !== "Approved") {
   frm.add_custom_button(__("Approve intake"), () => frappe.confirm(
    __("Record that you have checked and approved the current customer, items, quantities and godowns?"),
    async () => {
     await frappe.call({method: "kunal_enterprises.api.sales_portal_intake.approve", args: {
      request: frm.doc.name, expected_modified: frm.doc.modified
     }, freeze: true});
     await frm.reload_doc();
    }
   ));
  }
 }
});

function sales_correct_intake(frm) {
 const query = "kunal_enterprises.api.sales_portal_intake.master_query";
 const dialog = new frappe.ui.Dialog({title: __("Correct intake"), size: "extra-large", fields: [
  {fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Customer"),
   default: frm.doc.customer, get_query: () => ({query: "kunal_enterprises.api.sales_portal_intake.customer_query"}),
   ignore_link_validation: true},
  {fieldname: "items", fieldtype: "Table", label: __("Items"), cannot_add_rows: true, cannot_delete_rows: true,
   in_place_edit: true, data: (frm.doc.items || []).map(row => ({row_key: row.row_key,
    original_text: row.original_text, item: row.item, quantity: row.quantity_unknown ? null : row.quantity, godown: row.godown})),
   fields: [
    {fieldname: "row_key", fieldtype: "Data", hidden: true},
    {fieldname: "original_text", fieldtype: "Data", label: __("Original Text"), read_only: true, in_list_view: true, columns: 3},
    {fieldname: "item", fieldtype: "Link", options: "Tally Item", label: __("Item"), in_list_view: true, columns: 3,
     get_query: () => ({query}), ignore_link_validation: true},
    {fieldname: "quantity", fieldtype: "Float", label: __("Quantity"), in_list_view: true, columns: 1},
    {fieldname: "godown", fieldtype: "Link", options: "Tally Godown", label: __("Godown"), in_list_view: true, columns: 3,
     get_query: () => ({query}), ignore_link_validation: true}
   ]}
 ], primary_action_label: __("Save corrections"), async primary_action(values) {
  await frappe.call({method: "kunal_enterprises.api.sales_portal_intake.correct", args: {
   request: frm.doc.name, expected_modified: frm.doc.modified, customer: values.customer || "",
   items: (values.items || []).map(row => ({row_key: row.row_key, item: row.item || "", quantity: row.quantity, godown: row.godown || ""}))
  }, freeze: true});
  dialog.hide();
  await frm.reload_doc();
 }});
 dialog.show();
}
