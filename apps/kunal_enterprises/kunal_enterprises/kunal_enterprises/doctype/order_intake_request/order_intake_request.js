frappe.ui.form.on("Order Intake Request", {
	setup(frm) {
		const query = "kunal_enterprises.api.order_intake.intake_link_query";
		for (const field of ["customer", "sales_employee", "whatsapp_account"]) {
			frm.set_query(field, () => ({ query }));
			// The scoped lookup is reviewer-authorized. Server save still validates
			// link existence; skip the generic client call requiring upstream ACLs.
			frm.fields_dict[field].df.ignore_link_validation = true;
		}
		const source_query = () => ({ query, filters: {
			whatsapp_account: frm.doc.whatsapp_account || "",
			from: frm.doc.sender_number || "",
		} });
		frm.set_query("message", "source_messages", source_query);
		frm.fields_dict.source_messages.grid.update_docfield_property("message", "ignore_link_validation", true);
		for (const table of ["items", "attachments"]) {
			frm.set_query("source_message", table, source_query);
			frm.fields_dict[table].grid.update_docfield_property("source_message", "ignore_link_validation", true);
		}
		frm.set_query("warehouse_source_message", "items", source_query);
		frm.fields_dict.items.grid.update_docfield_property("warehouse_source_message", "ignore_link_validation", true);
		frm.set_query("godown", "items", () => ({ filters: { is_active: 1 } }));
	},
	refresh(frm) {
		frm.set_intro("");
		const escape = value => frappe.utils.escape_html(value || "");
		const estimate = frm.doc.estimated_interpretation;
		const questions = frm.doc.unresolved_questions;
		frm.fields_dict.interpretation_display.$wrapper.html(
			estimate || questions
				? `<div style="white-space: pre-wrap; overflow-wrap: anywhere">${escape(estimate)}${questions ? `<hr><strong>${__("Unresolved Questions")}</strong><br>${escape(questions)}` : ""}</div>`
				: ""
		);
		frm.set_df_property("status", "options", "Pending Review\nIn Review\nAwaiting Confirmation\nResolved\nDismissed");
		update_intake_sections(frm);
		for (const [section, label, field] of [
			["delivery_section", "Delivery Details", "delivery_address"],
			["references_section", "Attachment or Reference", "attachments"],
			["interpretation_section", "Interpretation", "interpretation_notes"],
		]) {
			if (!intake_section_has_content(frm, section)) {
				frm.add_custom_button(__(label), () => {
					intake_open_sections(frm).add(section);
					update_intake_sections(frm);
					frm.scroll_to_field(field);
				}, __("Add Details"));
			}
		}
	},
	after_save(frm) {
		intake_open_sections(frm).clear();
		update_intake_sections(frm);
	},
	delivery_address: keep_delivery_open,
	delivery_contact_name: keep_delivery_open,
	delivery_contact_number: keep_delivery_open,
	interpretation_notes(frm) {
		intake_open_sections(frm).add("interpretation_section");
		update_intake_sections(frm);
	},
});

frappe.ui.form.on("Order Intake Attachment", {
	attachments_add: keep_references_open,
	attachments_remove: keep_references_open,
});

function intake_open_sections(frm) {
	// A reused Desk form must not carry another request's temporary open state.
	if (frm.__intake_optional_doc !== frm.doc.name) {
		frm.__intake_optional_doc = frm.doc.name;
		frm.__intake_open_sections = new Set();
	}
	return frm.__intake_open_sections;
}

function intake_section_has_content(frm, section) {
	const has_text = fields => fields.some(field => String(frm.doc[field] || "").trim());
	if (section === "delivery_section") {
		return has_text(["delivery_address", "delivery_contact_name", "delivery_contact_number"]);
	}
	if (section === "references_section") return Boolean(frm.doc.attachments?.length);
	return has_text(["estimated_interpretation", "unresolved_questions", "interpretation_notes"]);
}

function update_intake_sections(frm) {
	const opened = intake_open_sections(frm);
	for (const section of ["delivery_section", "references_section", "interpretation_section"]) {
		frm.toggle_display(section, intake_section_has_content(frm, section) || opened.has(section));
	}
}

function keep_delivery_open(frm) {
	intake_open_sections(frm).add("delivery_section");
	update_intake_sections(frm);
}

function keep_references_open(frm) {
	intake_open_sections(frm).add("references_section");
	update_intake_sections(frm);
}
