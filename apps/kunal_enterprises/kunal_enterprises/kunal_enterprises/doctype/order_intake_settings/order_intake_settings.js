frappe.ui.form.on("Order Intake Settings", {
	refresh(frm) { frm.set_intro(""); },
	provider(frm) {
		// Only adjust the known default; never silently replace a custom model.
		for (const field of ["grouping_model", "extraction_model"]) {
			if (frm.doc.provider === "OpenRouter" && frm.doc[field] === "gpt-6-luna") {
				frm.set_value(field, "openai/gpt-6-luna");
			} else if (frm.doc.provider === "OpenAI" && frm.doc[field] === "openai/gpt-6-luna") {
				frm.set_value(field, "gpt-6-luna");
			}
		}
	},
});
