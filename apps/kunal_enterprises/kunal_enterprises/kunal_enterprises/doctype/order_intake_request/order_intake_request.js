frappe.ui.form.on("Order Intake Request", {
	setup(frm) {
		frm.fields_dict.items.grid.update_docfield_property("quantity", "formatter", intake_quantity_formatter);
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
		for (const field of ["item", "godown"]) {
			frm.set_query(field, "items", () => ({ query }));
			frm.fields_dict.items.grid.update_docfield_property(field, "ignore_link_validation", true);
		}
	},
	refresh(frm) {
		frm.set_intro("");
		if (globalThis.kunal_sales_portal_user?.()) {
			refresh_intake_messages(frm);
			update_intake_sections(frm);
			return;
		}
		intake_processing_controls(frm);
		intake_sender_link_controls(frm);
		refresh_intake_messages(frm);
		if (!frm.is_new() && intake_matching_editable(frm)) {
			frm.page.add_menu_item(__("Find matches"), () => find_intake_matches(frm));
			if (frm.doc.matching_json) {
				frm.page.add_menu_item(__("Review matches"), () => review_intake_matches(frm));
			}
		}
		const escape = value => frappe.utils.escape_html(value || "");
		const estimate = frm.doc.estimated_interpretation;
		frm.fields_dict.interpretation_display.$wrapper.html((estimate
			? `<div style="white-space: pre-wrap; overflow-wrap: anywhere">${escape(estimate)}</div>` : ""
		) + intake_proposals_html(frm.doc.proposed_updates, frm.doc));
		const pending = (intake_proposals(frm.doc.proposed_updates) || []).filter(({proposal}) => !proposal.reviewed_at);
		if (pending.length && !frm.is_new() && !intake_is_converted(frm)) {
			frm.set_intro(__("New messages need review. Check the suggested changes and attachments."), "orange");
			frm.add_custom_button(__("Review changes"), () => review_intake_update(frm, pending));
		}
		frm.set_df_property("status", "options", "Pending Review\nIn Review\nAwaiting Confirmation\nResolved\nDismissed" +
			(intake_is_converted(frm) ? "\nConverted to Order" : ""));
		update_intake_sections(frm);
		if (!intake_is_converted(frm)) for (const [section, label, field] of [
			["delivery_section", "Delivery Details", "delivery_address"],
			["references_section", "Attachment or Reference", "attachments"],
			["interpretation_section", "Message Details", "interpretation_notes"],
		]) {
			if (!intake_section_has_content(frm, section)) {
				frm.add_custom_button(__(label), () => {
					intake_open_sections(frm).add(section);
					update_intake_sections(frm);
					frm.fields_dict[section]?.collapse?.(false);
					frm.scroll_to_field(field);
				}, __("Add Details"));
			}
		}
	},
	after_save(frm) {
		intake_open_sections(frm).clear();
		update_intake_sections(frm);
	},
	whatsapp_account: invalidate_intake_messages,
	sender_number: invalidate_intake_messages,
	delivery_address: keep_delivery_open,
	delivery_contact_name: keep_delivery_open,
	delivery_contact_number: keep_delivery_open,
	interpretation_notes(frm) {
		intake_open_sections(frm).add("interpretation_section");
		update_intake_sections(frm);
	},
});

function intake_quantity_formatter(value, df, options, doc) {
	if (Number(doc?.quantity_unknown)) return __("Needs confirmation");
	return frappe.format ? frappe.format(value, {...df, formatter: null}, options, doc) : String(value ?? "");
}

frappe.ui.form.on("Order Intake Item", {
	quantity(frm, cdt, cdn) {
		const row = locals[cdt]?.[cdn];
		if (!row) return;
		return frappe.model.set_value(cdt, cdn, "quantity_unknown", row.quantity == null || row.quantity === "" ? 1 : 0);
	},
});

frappe.ui.form.on("Order Intake Attachment", {
	attachments_add: keep_references_open,
	attachments_remove: keep_references_open,
});

frappe.ui.form.on("Order Intake Source Message", {
	message: invalidate_intake_messages,
	source_messages_add: invalidate_intake_messages,
	source_messages_remove: invalidate_intake_messages,
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
	return has_text(["estimated_interpretation", "interpretation_notes"]) || Boolean(intake_proposals_html(frm.doc.proposed_updates));
}

function intake_proposals(value) {
	try {
		if (!value) return [];
		const proposals = typeof value === "string" ? JSON.parse(value) : value;
		if (!Array.isArray(proposals)) throw new Error("Invalid suggestions");
		if (proposals.some(proposal => !proposal || typeof proposal !== "object" || Array.isArray(proposal))) throw new Error("Invalid suggestion");
		return proposals.map((proposal, index) => ({proposal, index}));
	} catch (_) {
		return null;
	}
}

function intake_proposals_html(value, doc = {}) {
	if (!value) return "";
	const proposals = intake_proposals(value);
	if (proposals === null) {
		return `<p>${__("Proposed updates could not be displayed. Ask an administrator to review the stored suggestions; your selections are unchanged.")}</p>`;
	}
	return proposals.length ? `<hr><strong>${__("Message updates")}</strong>` + proposals.map(({proposal, index}) =>
		`<details><summary>${__("Update")} ${index + 1}${proposal.reviewed_at ? ` · ${__("Reviewed")}` : ""}</summary>${intake_update_html(proposal, doc)}</details>`).join("") : "";
}

function intake_update_html(proposal, doc) {
	const escape = text => frappe.utils.escape_html(String(text ?? ""));
	const wording = text => String(text || "").trim().toLowerCase();
	const quantity = item => `${item.quantity_unknown ? __("Needs confirmation") : item.quantity ?? __("Unclear")} ${item.unit || ""}`.trim();
	try {
		const items = (proposal.items || []).map(item => {
			const matches = (doc.items || []).filter(current => wording(current.original_text) === wording(item.original_text));
			const current = matches.length === 1 ? matches[0] : null;
			const change = current && quantity(current) !== quantity(item) ? `${quantity(current)} → ${quantity(item)}` : quantity(item);
			return `<tr><td>${escape(item.original_text)}</td><td>${escape(change)}</td><td>${escape(item.warehouse_text)}</td></tr>`;
		}).join("");
		const fields = [
			proposal.request_type && proposal.request_type !== doc.request_type && `${__("Request type")}: ${proposal.request_type}`,
			proposal.customer_text && `${__("Customer mentioned")}: ${proposal.customer_text}`,
			proposal.salesperson_text && `${__("Salesperson mentioned")}: ${proposal.salesperson_text}`,
			proposal.delivery_address && `${__("Delivery")}: ${proposal.delivery_address}`,
			[proposal.delivery_contact_name, proposal.delivery_contact_number].filter(Boolean).join(" · "),
		].filter(Boolean);
		const references = (proposal.new_references || []).map(row =>
			`<p>${escape(__("New attachment/reference"))}: ${escape(row.label || row.reference_type)} ${escape(row.contact_number || "")}</p>`).join("");
		const details = [proposal.summary, ...(proposal.unresolved_questions || []),
			...Object.values(proposal.media_warnings || {}).flat(), ...(proposal.items || []).map(item => item.notes)].filter(Boolean);
		return (proposal.review_warnings || []).map(warning => `<p class="alert alert-warning">${escape(warning)}</p>`).join("") + (items ? `<table class="table table-bordered"><thead><tr><th>${__("Item mentioned")}</th><th>${__("Quantity")}</th><th>${__("Warehouse mentioned")}</th></tr></thead><tbody>${items}</tbody></table>` : "") +
			fields.map(text => `<p>${escape(text)}</p>`).join("") + references +
			(details.length ? `<details><summary>${__("More details")}</summary><div style="white-space: pre-wrap; overflow-wrap: anywhere">${details.map(escape).join("\n")}</div></details>` : "");
	} catch (_) {
		return `<p>${__("This update could not be displayed. Ask an administrator to check it.")}</p>`;
	}
}

function review_intake_update(frm, pending) {
	const {proposal, index} = pending[0];
	frappe.msgprint({title: __("Message update"),
		message: `<p>${__("Check the changes, edit the request if needed, then mark reviewed.")}</p>` + intake_update_html(proposal, frm.doc),
		primary_action: {label: __("Mark reviewed"), action: async () => {
			if (frm.is_dirty() || frm.is_new()) {
				frappe.msgprint(__("Save your changes before marking this update reviewed."));
				return;
			}
			await frappe.call({method: "kunal_enterprises.api.order_intake.review_update", type: "POST", freeze: true,
				args: {request: frm.doc.name, proposal_index: index, expected_modified: frm.doc.modified}});
			frappe.hide_msgprint();
			await frm.reload_doc();
		}}});
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


function intake_matching_editable(frm) {
	return !frm.doc.order && !["Converted to Order", "Resolved", "Dismissed"].includes(frm.doc.status);
}

function intake_sender_link_controls(frm) {
	const reviewer = frappe.session?.user === "Administrator" || (frappe.user_roles || [])
		.some(role => ["Owner", "Admin", "Order Coordinator"].includes(role));
	if (!reviewer || frm.is_new() || !intake_matching_editable(frm) || (frm.has_perm && !frm.has_perm("write"))
		|| frm.doc.source !== "WhatsApp" || !frm.doc.sender_number || !frm.doc.whatsapp_account) return;
	frm.add_custom_button(__("Link sender to Customer"), () => link_intake_sender(frm));
}

function link_intake_sender(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save your changes before linking this sender."));
		return;
	}
	const request = frm.doc.name, expected_modified = frm.doc.modified, sender = frm.doc.sender_number;
	const dialog = new frappe.ui.Dialog({
		title: __("Link sender to Customer"),
		fields: [
			{fieldname: "sender_number", fieldtype: "Data", label: __("WhatsApp number"), read_only: 1, default: sender},
			{fieldname: "customer", fieldtype: "Link", options: "Customer", label: __("Customer"), reqd: 1,
				default: frm.doc.customer, ignore_link_validation: true,
				get_query: () => ({query: "kunal_enterprises.api.order_intake.intake_link_query"})},
			{fieldname: "contact_name", fieldtype: "Data", label: __("Person's name"), reqd: 1, default: frm.doc.sender_name},
			{fieldname: "designation", fieldtype: "Data", label: __("Designation")},
		],
		primary_action_label: __("Link sender"),
		async primary_action(values) {
			if (dialog.__linking) return;
			if (frm.is_dirty() || frm.doc.name !== request || frm.doc.modified !== expected_modified || frm.doc.sender_number !== sender) {
				frappe.msgprint(__("The request changed. Save and reopen the link dialog."));
				return;
			}
			dialog.__linking = true;
			try {
				await frappe.call({method: "kunal_enterprises.api.customer_contacts.link_sender", freeze: true,
					args: {request, expected_modified, customer: values.customer,
						contact_name: values.contact_name, designation: values.designation || ""}});
				dialog.hide();
				frm.__intake_chat = null;
				await frm.reload_doc();
				frappe.show_alert?.({message: __("Sender linked to Customer."), indicator: "green"});
			} finally {
				dialog.__linking = false;
			}
		},
	});
	dialog.show();
}

async function find_intake_matches(frm) {
	if (frm.is_new() || frm.is_dirty()) {
		frappe.msgprint(__("Save your changes before finding matches."));
		return;
	}
	if (!intake_matching_editable(frm)) return;
	const requestName = frm.doc.name;
	frappe.msgprint({title: __("Find matches"),
		message: __("Find customers, salespersons, items and warehouses from the message wording. The closest reasonable matches fill empty, uncorrected fields. Your existing selections stay unchanged. Other possibilities remain available under Review matches."),
		primary_action: {label: __("Find matches"), action: async () => {
			if (frm.doc.name !== requestName || frm.is_new() || frm.is_dirty() || !intake_matching_editable(frm)) {
				frappe.msgprint(__("Save your changes before finding matches."));
				return;
			}
			await frappe.call({method: "kunal_enterprises.api.order_intake_matching.match_request", type: "POST", freeze: true,
				args: {request: frm.doc.name, expected_modified: frm.doc.modified}});
			frappe.hide_msgprint();
			await frm.reload_doc();
			frappe.show_alert?.({message: __("Matches are ready for review."), indicator: "green"});
		}}});
}

function intake_match_context(value) {
	if (!value || typeof value !== "object" || !Array.isArray(value.items) ||
		value.items.some(row => !row || typeof row !== "object" || Array.isArray(row))) return null;
	const text = field => String(field || "");
	return JSON.stringify({
		customer: text(value.customer), whatsapp_account: text(value.whatsapp_account),
		sender_number: text(value.sender_number), customer_text: text(value.customer_text),
		salesperson_text: text(value.salesperson_text),
		items: value.items.map(row => ({row_key: text(row.row_key),
			original_text: text(row.original_text), warehouse_text: text(row.warehouse_text)}))
			.sort((a, b) => a.row_key.localeCompare(b.row_key)),
	});
}

function intake_match_review_state(doc) {
	// Capture master edits as well as source context. A dialog must not replace
	// a selection made elsewhere while that dialog was open.
	return JSON.stringify({context: intake_match_context(doc), modified: doc.modified,
		matching: doc.matching_json, sales_employee: doc.sales_employee || "",
		items: (doc.items || []).map(row => ({row_key: row.row_key || "", item: row.item || "", godown: row.godown || ""}))
			.sort((a, b) => a.row_key.localeCompare(b.row_key)),
	});
}

function review_intake_matches(frm) {
	if (!intake_matching_editable(frm)) return;
	let matching;
	try {
		matching = JSON.parse(frm.doc.matching_json || "{}");
		if (!matching || typeof matching !== "object" || Array.isArray(matching)) throw new Error("Invalid matches");
	} catch (_) {
		frappe.msgprint(__("Matches could not be displayed. Find matches again after saving your changes."));
		return;
	}
	if (!intake_match_context(matching.context) || intake_match_context(matching.context) !== intake_match_context(frm.doc)) {
		frappe.msgprint(__("The request details changed. Save your changes and Find matches again before reviewing choices."));
		return;
	}
	const reviewState = intake_match_review_state(frm.doc);
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	const fields = [{fieldname: "matching_help", fieldtype: "HTML", options:
		`<p>${__("Choose a match where needed. A blank choice keeps your current selection. You can also edit the request fields directly. Apply choices, then save the request.")}</p>`}];
	const choices = [];
	const add = (result, label, target, row = null) => {
		if (!result || typeof result !== "object" || !Array.isArray(result.candidates)) return;
		const candidates = result.candidates.filter(candidate => candidate && typeof candidate.name === "string" && candidate.name);
		if (!candidates.length && !result.text && !result.overflow) return;
		const current = row ? row[target] : frm.doc[target];
		const index = choices.length;
		const fieldname = `match_${index}`;
		const options = [{label: __("Keep current selection"), value: ""}, ...candidates.map(candidate => ({
			label: escape(String(candidate.label || candidate.name) + (candidate.label && candidate.label !== candidate.name ? ` (${candidate.name})` : "")),
			value: candidate.name,
		}))];
		fields.push({fieldname: `match_help_${index}`, fieldtype: "HTML", options:
			`<div class="mb-2"><strong>${escape(label)}</strong><br>${escape(result.text || "")}<br><small>${__("Current")}: ${escape(current || __("Not selected"))}</small>` +
			(candidates.length ? `<details><summary>${__("Why these matches?")}</summary>${candidates.map(candidate => `<p>${escape(candidate.label || candidate.name)} · ${escape(candidate.score ?? "")} %<br><small>${escape(candidate.reason || "")}</small></p>`).join("")}</details>` : `<p>${__("No match found. Select a record directly on the request if needed.")}</p>`) +
			(result.overflow ? `<p>${__("More possible matches exist. Use the request field to search further.")}</p>` : "") + "</div>"});
		if (candidates.length) fields.push({fieldname, fieldtype: "Select", label: escape(label), options, default: ""});
		choices.push({fieldname, target, row_key: row?.row_key, candidates});
	};
	add(matching.customer, __("Customer"), "customer");
	add(matching.sales_employee, __("Salesperson"), "sales_employee");
	for (const match of Array.isArray(matching.items) ? matching.items : []) {
		const row = (frm.doc.items || []).find(item => item.row_key && item.row_key === match?.row_key);
		if (!row) continue;
		const label = row.original_text || row.item || __("Item");
		add(match.item, __("Item") + ": " + label, "item", row);
		add(match.godown, __("Warehouse") + ": " + label, "godown", row);
	}
	if (!choices.length) {
		frappe.msgprint(__("No matches to review. Use Find matches or select records directly on the request."));
		return;
	}
	const requestName = frm.doc.name;
	const dialog = new frappe.ui.Dialog({title: __("Review matches"), fields, primary_action_label: __("Apply choices"),
		primary_action: async values => {
			if (frm.doc.name !== requestName || !intake_matching_editable(frm)) return;
			if (intake_match_review_state(frm.doc) !== reviewState) {
				frappe.msgprint(__("The available matches changed. Save your changes and Find matches again before reviewing choices."));
				return;
			}
			const selected = choices.filter(choice => values[choice.fieldname]);
			// Validate every choice before changing fields, including stable row IDs.
			if (selected.some(choice => !choice.candidates.some(candidate => candidate.name === values[choice.fieldname]) ||
				(choice.row_key && !(frm.doc.items || []).some(row => row.row_key === choice.row_key)))) {
				frappe.msgprint(__("The available matches changed. Reopen Review matches."));
				return;
			}
			const customerChoice = selected.find(choice => !choice.row_key && choice.target === "customer");
			if (customerChoice && values[customerChoice.fieldname] !== frm.doc.customer && selected.some(choice => choice.row_key)) {
				frappe.msgprint(__("Choose the customer first, save the request and Find matches again before selecting items or warehouses."));
				return;
			}
			for (const choice of selected) {
				const value = values[choice.fieldname];
				if (choice.row_key) {
					const row = frm.doc.items.find(item => item.row_key === choice.row_key);
					await frappe.model.set_value(row.doctype || "Order Intake Item", row.name, choice.target, value);
				} else {
					await frm.set_value(choice.target, value);
				}
			}
			dialog.hide();
			if (selected.length) frappe.show_alert?.({message: __("Choices applied. Save the request to keep them."), indicator: "blue"});
		}});
	dialog.show();
}


function intake_inline_context(frm) {
	return JSON.stringify({name: frm.doc.name, modified: frm.doc.modified, account: frm.doc.whatsapp_account || "",
		sender: frm.doc.sender_number || "", sources: frm.doc.source_messages || []});
}

function invalidate_intake_messages(frm) {
	const chat = frm.__intake_chat;
	if (chat && chat.context !== intake_inline_context(frm)) {
		chat.data = null;
		chat.error = __("Save your message changes to show the current conversation.");
		chat.stale = true;
		render_intake_messages(frm, chat);
	}
}

function intake_sender_html(data) {
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	const number = String(data.sender_number || "").trim();
	const profile = String(data.sender_profile_name || "").trim();
	// The editable request title is not a verified sender/profile name.
	const display = profile;
	const identity = data.sender_identity || {};
	const matches = Array.isArray(identity.matches) ? identity.matches.filter(row => row && typeof row === "object") : [];
	const matched = identity.status === "Matched" && matches.length === 1 ? matches[0] : null;
	const role = row => row.doctype === "Customer" ? __("Customer") : row.doctype === "Sales Employee" ? __("Salesperson") : __("Matched record");
	const label = matched ? String(matched.label || matched.name || "") : display || number || __("No sender number linked");
	const status = !number ? __("No sender number linked") : matched ? role(matched) :
		identity.status === "Ambiguous" ? __("Multiple matching records") : __("Not found in our records");
	const initials = (matched || display) ? label.split(/\s+/).filter(Boolean).slice(0, 2).map(word => Array.from(word)[0]).join("").toUpperCase() : "?";
	const otherNames = identity.status === "Ambiguous" ? matches.map(row => `${role(row)}: ${String(row.label || row.name || "")}`).join(" · ") : "";
	return `<div class="intake-chat-sender-summary" style="display:flex;gap:12px;align-items:center;min-height:74px;padding:12px 20px;border-radius:8px 8px 0 0;background:#075e54;color:#fff">` +
		`<span aria-hidden="true" style="display:flex;align-items:center;justify-content:center;flex-shrink:0;width:42px;height:42px;border-radius:50%;background:#ffffff26;color:#fff;font-size:13px;font-weight:600">${escape(initials)}</span>` +
		`<div style="min-width:0;overflow-wrap:anywhere"><strong style="display:block;font-size:14px;font-weight:600;line-height:1.4">${escape(label)}</strong>` +
		`<div style="font-size:11px;opacity:.85;line-height:1.5">${escape([number, status].filter(Boolean).join(" · "))}</div>` +
		(matched && profile && profile.toLocaleLowerCase() !== label.toLocaleLowerCase() ? `<div style="font-size:11px;opacity:.85">${__("WhatsApp name")}: ${escape(profile)}</div>` : "") +
		(otherNames ? `<div style="font-size:11px;opacity:.85">${escape(otherNames)}</div>` : "") + `</div><span style="margin-left:auto;flex-shrink:0;font-size:10px;opacity:.75">${__("Read-only")}</span></div>`;
}

function intake_review_html(data) {
	// Source AI labels can belong to an earlier run or another request sharing
	// the message. Review only the current request; keep real capture/media issues.
	const values = [...(Array.isArray(data.review_questions) ? data.review_questions : []),
		...(Array.isArray(data.review_warnings) ? data.review_warnings : []),
		...(data.messages || []).flatMap(message => (message.warnings || []).filter(value => !/^AI:/i.test(String(value).trim())))];
	const seen = new Set();
	const questions = values.filter(value => typeof value === "string").map(value => value.trim().replace(/\s+/g, " "))
		.filter(value => value && !seen.has(value.toLocaleLowerCase()) && seen.add(value.toLocaleLowerCase()));
	if (!questions.length) return "";
	const escape = value => frappe.utils.escape_html(value);
	return `<section class="intake-review-section" aria-label="${__("Please review")}" style="border:1px solid var(--border-color);border-radius:8px;padding:12px 16px;margin-bottom:16px;background:var(--subtle-fg)">` +
		`<strong>${__("Please review")}</strong><ul style="margin:8px 0 0;padding-left:20px">` +
		questions.map(question => `<li style="margin:4px 0;overflow-wrap:anywhere">${escape(question)}</li>`).join("") + "</ul></section>";
}

function render_intake_messages(frm, chat, latest = false) {
	if (frm.__intake_chat !== chat || frm.doc.name !== chat.request) return;
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	const button = (action, label) => `<button type="button" class="btn btn-sm btn-default" data-intake-chat="${action}"${chat.loading ? " disabled" : ""}>${escape(label)}</button>`;
	const controls = [];
	if (chat.data?.has_more) controls.push(button("older", __("Load older messages")));
	if (chat.data?.references?.length) controls.push(button("attachments", __("Review attachments")));
	if (!chat.stale && !frm.is_new()) controls.push(button("refresh", chat.error ? __("Retry") : __("Refresh messages")));
	const content = chat.error ? `<p class="text-muted" role="status">${escape(chat.error)}</p>` : chat.data
		? intake_review_html(chat.data) + intake_sender_html(chat.data) + intake_conversation_html(chat.data, true) : `<p class="text-muted" role="status">${escape(frm.is_new() ? __("Messages will appear here after this request is saved and source messages are linked.") : __("Loading messages…"))}</p>`;
	const wrapper = frm.fields_dict.conversation_display?.$wrapper;
	for (const cleanup of frm.__intake_map_cleanups || []) cleanup();
	frm.__intake_map_cleanups = [];
	const previous = wrapper?.find?.(".intake-chat-history")?.get?.(0);
	const position = previous && {top: previous.scrollTop, height: previous.scrollHeight};
	wrapper?.html(`<div class="intake-inline-chat" aria-label="${escape(__("Messages for this request"))}">${controls.length ? `<div class="mb-3" style="display:flex;gap:8px;flex-wrap:wrap">${controls.join("")}</div>` : ""}${content}</div>`);
	const history = wrapper?.find?.(".intake-chat-history")?.get?.(0);
	if (history) history.scrollTop = !position || latest ? history.scrollHeight : position.top + history.scrollHeight - position.height;
	void mount_intake_previews(frm, chat, history);
	void mount_intake_maps(frm, chat, history);
	wrapper?.off?.("click.intakeChat").on?.("click.intakeChat", "button[data-intake-chat]", event => {
		if (frm.__intake_chat !== chat || chat.loading) return;
		if (chat.context !== intake_inline_context(frm)) {invalidate_intake_messages(frm); return;}
		if (event.currentTarget.dataset.intakeChat === "attachments") return view_intake_messages(frm, "attachments");
		return load_intake_messages(frm, chat, event.currentTarget.dataset.intakeChat === "older");
	});
}

async function refresh_intake_messages(frm) {
	const context = intake_inline_context(frm);
	if (!frm.is_dirty()) frm.__intake_saved_chat_context = context;
	const chat = {request: frm.doc.name, context, data: null, loading: false};
	frm.__intake_chat = chat;
	if (frm.is_new()) {render_intake_messages(frm, chat); return;}
	if (frm.is_dirty() && context !== frm.__intake_saved_chat_context) {
		chat.stale = true;
		chat.error = __("Save your message changes to show the current conversation.");
		render_intake_messages(frm, chat);
		return;
	}
	await load_intake_messages(frm, chat);
}

async function load_intake_messages(frm, chat, older = false) {
	if (frm.__intake_chat !== chat || chat.loading || chat.stale) return;
	if (chat.context !== intake_inline_context(frm)) {invalidate_intake_messages(frm); return;}
	chat.loading = true;
	chat.error = null;
	render_intake_messages(frm, chat);
	try {
		const previous = older ? chat.data : null;
		const {message: data} = await frappe.call({method: "kunal_enterprises.api.order_intake_conversation.messages", type: "GET", silent: true,
			args: {request: chat.request, expected_modified: frm.doc.modified,
				...(previous ? {cursor: previous.next_cursor, revision: previous.revision} : {})}});
		if (frm.__intake_chat !== chat) return;
		if (chat.context !== intake_inline_context(frm)) {invalidate_intake_messages(frm); return;}
		if (data?.request !== chat.request || data.modified !== frm.doc.modified || typeof data.revision !== "string" ||
			!data.revision || !Array.isArray(data.messages) || (previous && data.revision !== previous.revision)) throw new Error("Stale messages");
		chat.data = {...data, messages: previous ? [...data.messages, ...previous.messages] : data.messages};
	} catch (_) {
		if (frm.__intake_chat !== chat) return;
		if (chat.context !== intake_inline_context(frm)) {invalidate_intake_messages(frm); return;}
		// Do not leave old evidence visible after a rejected revision/permission
		// check. A deliberate retry starts a fresh, request-scoped page.
		chat.data = null;
		chat.error = __("Messages could not be loaded or have changed. Retry, or reload the request if needed.");
	} finally {
		chat.loading = false;
		if (frm.__intake_chat === chat) render_intake_messages(frm, chat, !older);
	}
}

function intake_location_html(location, name) {
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	const latitude = Number(location.latitude), longitude = Number(location.longitude);
	const numeric = value => typeof value === "number" || (typeof value === "string" && value.trim() !== "");
	const valid = numeric(location.latitude) && numeric(location.longitude) &&
		Number.isFinite(latitude) && Number.isFinite(longitude) && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180;
	const url = valid ? `https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=16/${latitude}/${longitude}` : "";
	const map = valid ? `<div class="intake-chat-map" data-intake-map="${escape(name)}" aria-label="${__("Shared location")}"><a href="${escape(url)}" target="_blank" rel="noopener noreferrer">${__("Open map")}</a></div>` : "";
	return `<div class="intake-chat-location">${map}<strong>${escape(location.name || __("Shared location"))}</strong>` +
		(location.address ? `<div>${escape(location.address)}</div>` : "") +
		(!valid ? `<div>${__("Location preview unavailable")}</div>` : "") + "</div>";
}

async function mount_intake_maps(frm, chat, history) {
	if (!history?.querySelectorAll || !chat.data || chat.error || chat.stale) return;
	const hosts = Array.from(history.querySelectorAll("[data-intake-map]"));
	if (!hosts.length) return;
	const context = chat.context, revision = chat.data.revision;
	const valid = host => frm.__intake_chat === chat && frm.doc.name === chat.request &&
		chat.context === context && intake_inline_context(frm) === context &&
		chat.data?.revision === revision && !chat.error && !chat.stale && host.isConnected;
	try {
		if (!window.KunalWhatsAppMap?.mount) await frappe.require("/assets/kunal_enterprises/js/whatsapp_inbox_maps.js");
	} catch (_) {return;} // The ordinary Open map link remains usable.
	const messages = new Map(chat.data?.messages?.map(message => [message.name, message]) || []);
	const mount = host => {
		if (!valid(host) || !window.KunalWhatsAppMap?.mount) return;
		const location = messages.get(host.dataset.intakeMap)?.location;
		if (location) frm.__intake_map_cleanups.push(window.KunalWhatsAppMap.mount(host, location));
	};
	// As in Inbox, load tiles only when their message is visible, and destroy
	// old map instances whenever the transcript is refreshed or replaced.
	if (typeof IntersectionObserver === "function" && hosts.some(valid)) {
		const observer = new IntersectionObserver(entries => {
			for (const entry of entries) if (entry.isIntersecting) {observer.unobserve(entry.target); mount(entry.target);}
		}, {root: history});
		frm.__intake_map_cleanups.push(() => observer.disconnect());
		for (const host of hosts) if (valid(host)) observer.observe(host);
	} else for (const host of hosts) mount(host);
}

async function mount_intake_previews(frm, chat, history) {
	if (!history?.querySelectorAll || !chat.data || chat.error || chat.stale) return;
	const revision = chat.data.revision, context = chat.context;
	const valid = host => frm.__intake_chat === chat && frm.doc.name === chat.request &&
		chat.context === context && intake_inline_context(frm) === context &&
		chat.data?.revision === revision && !chat.error && !chat.stale && host.isConnected;
	const messages = new Map(chat.data.messages.map(row => [row.name, row]));
	chat.previews ||= new Map();
	await Promise.all(Array.from(history.querySelectorAll("[data-intake-preview]")).map(async host => {
		const message = messages.get(host.dataset.intakePreview);
		if (!message?.attachment?.available || !valid(host)) return;
		const key = JSON.stringify([revision, message.name, message.attachment.url]);
		if (!chat.previews.has(key)) {
			chat.previews.set(key, frappe.call({method: "kunal_enterprises.api.order_intake_conversation.preview", type: "GET", silent: true,
				args: {request: chat.request, name: message.name, revision, expected_modified: frm.doc.modified}})
				.then(result => result.message).catch(() => null));
		}
		const preview = await chat.previews.get(key);
		if (!valid(host)) return;
		if (!preview?.available || typeof preview.url !== "string" || !preview.url.startsWith("/private/files/")) {
			chat.previews.delete(key); // Refresh can retry transient permission/render failures.
			host.textContent = __("Preview unavailable. Open the attachment below.");
			return;
		}
		const escape = value => frappe.utils.escape_html(String(value ?? ""));
		const width = Math.min(480, Math.max(1, Number(preview.width) || 300));
		const height = Math.min(480, Math.max(1, Number(preview.height) || 200));
		const pinned = history.scrollHeight - history.scrollTop - history.clientHeight < 48;
		host.innerHTML = `<a href="${escape(message.attachment.url)}" target="_blank" rel="noopener noreferrer"><img src="${escape(preview.url)}" alt="${__("Attachment preview")}" width="${width}" height="${height}" style="aspect-ratio:${width}/${height}" loading="lazy"></a>`;
		host.querySelector?.("img")?.addEventListener("error", () => {
			if (valid(host)) host.textContent = __("Preview unavailable. Open the attachment below.");
		}, {once: true});
		if (pinned) history.scrollTop = history.scrollHeight;
	}));
}

function intake_conversation_file(file, messageName = null, contentType = "") {
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	if (!file?.available || typeof file.url !== "string" || !file.url.startsWith("/private/files/")) {
		return `<p class="text-muted">${escape(file?.note || __("Attachment unavailable. Review the original message."))}</p>`;
	}
	const name = file.file_name || __("Attachment");
	const type = String(file.file_type || name.split(".").pop() || "DOC").split("/").pop().toUpperCase();
	const badge = contentType === "image" ? "IMG" : type === "PDF" ? "PDF" : /^(PNG|JPE?G|GIF|WEBP|HEIC|BMP)$/.test(type) ? "IMG" :
		/^(MP3|OGG|WAV|M4A|AAC|OPUS)$/.test(type) ? "AUDIO" : /^(MP4|MOV|WEBM|AVI)$/.test(type) ? "VIDEO" : "DOC";
	const bytes = Number(file.size_bytes);
	const size = file.size_bytes != null && Number.isFinite(bytes) && bytes >= 0 ?
		(bytes < 1024 ? bytes + " B" : bytes < 1024 * 1024 ? (bytes / 1024).toFixed(1) + " KB" : (bytes / (1024 * 1024)).toFixed(1) + " MB") : "";
	const pages = Number(file.page_count);
	const metadata = [Number.isInteger(pages) && pages > 0 ? pages + " " + __("pages") : "", size, badge].filter(Boolean).join(" · ");
	const preview = messageName && ["IMG", "PDF"].includes(badge) ? `<div class="intake-chat-preview" data-intake-preview="${escape(messageName)}" aria-label="${__("Attachment preview")}"></div>` : "";
	return preview + `<div class="intake-chat-file" style="display:flex;gap:10px;align-items:center;border-radius:6px;padding:9px;margin-top:5px">` +
		`<span class="intake-chat-file-icon" aria-hidden="true" style="flex-shrink:0;white-space:nowrap;font-size:10px;font-weight:700;border:1px solid currentColor;border-radius:4px;padding:10px 5px">${badge}</span>` +
		`<div style="min-width:0"><a href="${escape(file.url)}" target="_blank" rel="noopener noreferrer" title="${__("Open file")}" style="display:block;font-size:12px;font-weight:500;overflow-wrap:anywhere">${escape(name)}</a>` +
		`<small class="text-muted">${escape(metadata)}</small></div>` +
		`<a href="${escape(file.url)}" download="${escape(name)}" title="${__("Download")}" aria-label="${escape(__("Download") + " " + name)}" style="margin-left:auto;flex-shrink:0;padding:5px;border:1px solid var(--border-color);border-radius:50%;font-size:16px;line-height:1">↓</a></div>`;
}

function intake_conversation_html(data, previews = false) {
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	const byName = new Map((data.messages || []).map(message => [message.name, message]));
	let previousDay;
	const blocks = (data.messages || []).map(message => {
		const stamp = String(message.received_at || "");
		const parsed = stamp.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
		const day = parsed?.[1];
		let date = "";
		if (day && day !== previousDay) {
			const value = new Date(day + "T12:00:00Z");
			const label = Number.isNaN(value.getTime()) ? day : value.toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"});
			date = `<div class="intake-chat-date"><span>${escape(label)}</span></div>`;
		}
		previousDay = day;
		const location = message.location;
		const quoted = byName.get(message.reply_to);
		const quote = String(quoted?.text || quoted?.attachment?.file_name || message.reply_context?.text || message.reply_context?.file_name || "");
		const reference = (data.references || []).find(row => row.reference_type === "File" &&
			row.source_message === message.name && row.attachment?.url === message.attachment?.url);
		const attachment = message.attachment && {...message.attachment, page_count: reference?.page_count};
		return date + `<div class="intake-chat-bubble">` +
			(message.reply_to ? `<div class="intake-chat-reply">${quote ? escape(quote.slice(0, 160)) + (quote.length > 160 ? "…" : "") : __("Reply to an earlier message")}</div>` : "") +
			(message.text ? `<div class="intake-chat-text">${escape(message.text)}</div>` : "") +
			(attachment ? intake_conversation_file(attachment, previews ? message.name : null, message.content_type) : "") +
			(location ? intake_location_html(location, message.name) : "") +
			`<div class="intake-chat-meta">` + (message.can_open_original === false ? "" : `<a href="/app/whatsapp-message/${escape(encodeURIComponent(message.name))}" target="_blank" rel="noopener noreferrer" title="${__("Open original message")}">${__("Original")}</a>`) +
			`<time datetime="${escape(stamp)}">${escape(parsed?.[2] || stamp.replace(/\.\d+$/, ""))}</time></div></div>`;
	}).join("");
	return `<style>
		.intake-chat-history{background-color:#efeae2;background-image:radial-gradient(rgba(110,100,85,.10) .8px,transparent .8px),radial-gradient(rgba(110,100,85,.06) .8px,transparent .8px);background-size:24px 24px;background-position:0 0,12px 12px;padding:20px 34px;border-radius:8px;color:#202c33;scrollbar-gutter:stable}
		.intake-inline-chat .intake-chat-history{border-radius:0 0 8px 8px}
		.intake-chat-history .intake-chat-date{text-align:center;margin:2px 0 16px;font-size:11px;color:#54656f}
		.intake-chat-history .intake-chat-date span{display:inline-block;background:#fffdf8;padding:5px 10px;border-radius:7px;box-shadow:0 1px 2px #00000012}
		.intake-chat-history .intake-chat-bubble{position:relative;width:fit-content;min-width:110px;max-width:78%;padding:8px 10px 5px;margin:0 0 10px 7px;border-radius:0 8px 8px 8px;background:#fff;box-shadow:0 1px 1px #0000001c;overflow-wrap:anywhere;font-size:13px;line-height:1.45}
		.intake-chat-history .intake-chat-bubble:before{content:"";position:absolute;left:-7px;top:0;border-top:8px solid #fff;border-left:8px solid transparent}
		.intake-chat-history .intake-chat-preview:empty::after{content:"…";display:block;padding:24px;text-align:center;color:#667781}
		.intake-chat-history .intake-chat-text{white-space:pre-wrap}
		.intake-chat-history:focus-visible{outline:2px solid #008069;outline-offset:-2px}
		.intake-chat-history .intake-chat-preview{width:320px;max-width:100%;margin-top:5px;border-radius:6px;overflow:hidden;background:#f4f5f5}
		.intake-chat-history .intake-chat-preview:empty{min-height:90px}
		.intake-chat-history .intake-chat-location{width:245px;max-width:100%}
		:is(.intake-chat-history,.intake-review-location) .intake-chat-map{width:225px;max-width:100%;min-height:160px;border-radius:5px;overflow:hidden;background:#e3ebe2;margin-bottom:6px}
		:is(.intake-chat-history,.intake-review-location) .intake-chat-map>a{display:block;padding:6px 8px;color:inherit;background:#e3ebe2}
		.intake-chat-history .intake-chat-preview a{display:block}
		.intake-chat-history .intake-chat-preview img{display:block;width:100%;height:auto;max-height:360px;object-fit:contain}
		.intake-chat-history .intake-chat-preview small{display:block;padding:10px;color:#667781}
		.intake-chat-history .intake-chat-meta{display:flex;gap:12px;justify-content:flex-end;align-items:center;margin-top:4px;font-size:10px;color:#86939a;line-height:1.3}
		.intake-chat-history .intake-chat-meta a{font-size:10px;color:inherit;text-decoration:none}
		.intake-chat-history .intake-chat-meta a:hover{text-decoration:underline}
		.intake-chat-history .intake-chat-file{display:flex;gap:10px;align-items:center;background:#f4f5f5;border-radius:6px;padding:9px;margin-top:5px;font-size:12px}
		.intake-chat-history .intake-chat-file-icon{line-height:1;color:#d06c66;background:#fff7f6}
		.intake-chat-history .intake-chat-file a{color:#405863}
		.intake-chat-history .intake-chat-file a[download]{font-size:11px}
		.intake-chat-history .intake-chat-file p{margin:0}
		.intake-chat-history .intake-chat-location,.intake-chat-history .intake-chat-reply{padding:7px 9px;margin-top:5px;background:#f4f5f5;border-radius:5px;font-size:12px}
		.intake-chat-history .intake-chat-reply{border-left:3px solid #56a899;color:#667781;font-size:11px}
		.intake-chat-history .intake-chat-empty{color:#667781;text-align:center;margin:20px 0;font-size:12px}
		[data-theme="dark"] .intake-chat-history{background-color:#0b141a;color:#e9edef}
		[data-theme="dark"] .intake-chat-history .intake-chat-bubble,[data-theme="dark"] .intake-chat-history .intake-chat-date span{background:#202c33;color:#e9edef}
		[data-theme="dark"] .intake-chat-history .intake-chat-bubble:before{border-top-color:#202c33}
		[data-theme="dark"] .intake-chat-history .intake-chat-file,[data-theme="dark"] .intake-chat-history .intake-chat-location,[data-theme="dark"] .intake-chat-history .intake-chat-reply{background:#182229}
		[data-theme="dark"] .intake-chat-history .intake-chat-file a{color:#b5cbd4}
		[data-theme="dark"] .intake-chat-history .intake-chat-preview{background:#182229}
		[data-theme="dark"] .intake-chat-history .intake-chat-preview small{color:#b5cbd4}
		[data-theme="dark"] :is(.intake-chat-history,.intake-review-location) .intake-chat-map,[data-theme="dark"] :is(.intake-chat-history,.intake-review-location) .intake-chat-map>a{background:#233b31;color:#e9edef}
		@media(max-width:640px){.intake-chat-history{padding:14px 14px}.intake-chat-history .intake-chat-bubble{max-width:92%}}
	</style><div class="intake-chat-history" tabindex="0" role="region" aria-label="${escape(__("Linked WhatsApp messages"))}" style="max-height:480px;overflow-y:auto">` +
		(blocks || `<p class="intake-chat-empty">${__("No source messages are linked. You can review the attachments below.")}</p>`) + "</div>";
}

function intake_reference_html(references, pageLimit) {
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	return references.length ? references.map(reference => {
		let detail = "";
		if (reference.reference_type === "File") {
			detail = intake_conversation_file({...reference.attachment, page_count: reference.page_count});
			const pdf = Boolean(reference.page_count) || /\.pdf$/i.test(reference.attachment?.file_name || "") || reference.attachment?.file_type?.toLowerCase() === "pdf";
			if (pdf) detail += `<p class="text-muted">${reference.page_count ? __("PDF pages") + ": " + escape(reference.page_count) : __("PDF page count not available.")}` +
				(reference.page_count > pageLimit ? ` · ${__("Above automatic page limit; review manually.")}` : "") + "</p>";
		} else if (reference.reference_type === "External Link") {
			detail = `<div style="white-space:pre-wrap;overflow-wrap:anywhere">${escape(reference.external_url)}</div><small class="text-muted">${__("Stored link — not opened or fetched.")}</small>`;
		} else if (reference.reference_type === "Contact") {
			detail = `<p>${escape(reference.contact_name)}<br>${escape(reference.contact_number)}</p>`;
		} else if (reference.reference_type === "Location") {
			detail = `<div class="intake-review-location" style="max-width:245px">${intake_location_html({latitude: reference.latitude,
				longitude: reference.longitude, address: reference.location_address}, reference.name)}</div>`;
		}
		return `<div style="border-top:1px solid var(--border-color);padding:10px 0"><strong>${escape(reference.label || reference.reference_type)}</strong>` +
			`<span class="text-muted"> · ${escape(reference.review_status)}</span><div class="my-1">${detail}</div></div>`;
	}).join("") : "";
}

function intake_conversation_state(frm) {
	return JSON.stringify({name: frm.doc.name, modified: frm.doc.modified, attachments: frm.doc.attachments || [], sources: frm.doc.source_messages || []});
}

async function view_intake_messages(frm, initialTab = "messages") {
	if (frm.is_new() || frm.is_dirty()) {
		frappe.msgprint(__("Save your changes before reviewing attachments."));
		return;
	}
	const request = frm.doc.name;
	const state = intake_conversation_state(frm);
	const unchanged = () => !frm.is_new() && !frm.is_dirty() && intake_conversation_state(frm) === state;
	const {message: data} = await frappe.call({method: "kunal_enterprises.api.order_intake_conversation.messages", type: "GET",
		args: {request, expected_modified: frm.doc.modified}, freeze: true});
	if (!unchanged()) {
		frappe.msgprint(__("The request changed. Open Review attachments again after saving your changes."));
		return;
	}
	const references = data.references || [];
	const canReview = !intake_is_converted(frm) && !globalThis.kunal_sales_portal_user?.();
	const safe_cell = value => frappe.utils.escape_html(String(value ?? ""));
	// Dialogs do not have a Form instance; native Form Tab Break controls
	// require one. These scoped switches keep the review in a single dialog.
	const fields = [
		...(references.length ? [{fieldname: "review_navigation", fieldtype: "HTML", options:
			`<div class="btn-group mb-3" role="tablist" aria-label="${__("Request review")}">` +
			`<button type="button" class="btn btn-sm btn-default" role="tab" data-intake-tab="messages">${__("Messages")}</button>` +
			`<button type="button" class="btn btn-sm btn-default" role="tab" data-intake-tab="attachments">${__("Attachments")}</button></div>`}] : []),
		{fieldname: "conversation", fieldtype: "HTML", options: intake_conversation_html(data)},
		...(references.length ? [
			{fieldname: "references_display", fieldtype: "HTML", options: intake_reference_html(references, data.pdf_page_limit)},
			{fieldname: "review_help", fieldtype: "HTML", options: `<p class="text-muted">${canReview ? __("Update the review status or notes below, then choose Done. Save the request to keep your changes.") : __("Review details are read-only for this request or user.")}</p>`},
		] : []),
	];
	if (references.length) fields.push({fieldname: "reviews", fieldtype: "Table", label: __("Attachment review"), in_place_edit: true,
		cannot_add_rows: true, cannot_delete_rows: true, data: references.map(row => ({row_name: row.name, label: row.label || row.reference_type, review_status: row.review_status, notes: row.notes})),
		fields: [{fieldname: "row_name", fieldtype: "Data", hidden: 1, read_only: 1},
			{fieldname: "label", fieldtype: "Data", label: __("Attachment"), read_only: 1, in_list_view: 1, columns: 4, formatter: safe_cell},
			{fieldname: "review_status", fieldtype: "Select", label: __("Review"), read_only: !canReview, options: "Not Reviewed\nNeeds Manual Review\nReviewed", in_list_view: 1, columns: 3, formatter: safe_cell},
			{fieldname: "notes", fieldtype: "Small Text", label: __("Notes"), read_only: !canReview, in_list_view: 1, columns: 3, formatter: safe_cell}]});
	let loading = false;
	const dialog = new frappe.ui.Dialog({title: initialTab === "attachments" ? __("Review attachments") : __("Messages for this request"), size: "large", fields,
		primary_action_label: references.length && canReview ? __("Done") : __("Close"), primary_action: async values => {
			if (!canReview) {dialog.hide(); return;}
			if (!unchanged()) {
				frappe.msgprint(__("The request changed. Close this view and reopen it after saving."));
				return;
			}
			const rows = references.length ? (values.reviews || []) : [];
			const allowed = new Set(references.map(row => row.name));
			const seen = new Set();
			if (rows.some(row => !allowed.has(row.row_name) || seen.has(row.row_name) ||
				!['Not Reviewed', 'Needs Manual Review', 'Reviewed'].includes(row.review_status) || !seen.add(row.row_name))) {
				frappe.msgprint(__("The attachment review changed. Close this view and try again."));
				return;
			}
			const updates = rows.filter(choice => {
				const original = references.find(row => row.name === choice.row_name);
				return choice.review_status !== original.review_status || (choice.notes || "") !== (original.notes || "");
			});
			if (updates.length) {
				// The source can change without changing the request timestamp
				// (for example, a private media download completing in the background).
				let validation;
				try {
					validation = await frappe.call({method: "kunal_enterprises.api.order_intake_conversation.messages", type: "GET",
						args: {request, revision: data.revision, expected_modified: data.modified}, freeze: true});
				} catch (_) {
					// Frappe displays the server/network error; retain the open review.
					return;
				}
				if (!unchanged() || validation.message?.request !== request || validation.message?.revision !== data.revision) {
					frappe.msgprint(__("The request or messages changed. Reopen this view before applying review notes."));
					return;
				}
			}
			for (const choice of updates) {
				const row = (frm.doc.attachments || []).find(row => row.name === choice.row_name);
				if (!row) return;
				await frappe.model.set_value(row.doctype || "Order Intake Attachment", row.name, {review_status: choice.review_status, notes: choice.notes || ""});
			}
			dialog.hide();
			if (updates.length) frappe.show_alert?.({message: __("Review notes applied. Save the request to keep them."), indicator: "blue"});
		}});
	if (data.has_more) {
		dialog.set_secondary_action_label(__("Load older messages"));
		dialog.set_secondary_action(async () => {
			if (loading) return;
			if (!unchanged()) {frappe.msgprint(__("The request changed. Reopen Review attachments after saving.")); return;}
			loading = true;
			try {
				const {message: page} = await frappe.call({method: "kunal_enterprises.api.order_intake_conversation.messages", type: "GET",
					args: {request, cursor: data.next_cursor, revision: data.revision, expected_modified: data.modified}, freeze: true});
				if (!unchanged()) return;
				data.messages = [...page.messages, ...data.messages];
				data.next_cursor = page.next_cursor;
				dialog.fields_dict.conversation.$wrapper.html(intake_conversation_html(data));
				if (!page.has_more) dialog.get_secondary_btn().hide();
			} finally {loading = false;}
		});
	}
	dialog.__intake_mount_review_maps = () => mount_intake_review_maps(dialog, data, unchanged);
	dialog.$wrapper?.on?.("shown.bs.modal", dialog.__intake_mount_review_maps);
	dialog.show();
	if (references.length) {
		dialog.fields_dict.review_navigation?.$wrapper?.on?.("click", "button[data-intake-tab]", event => {
			set_intake_review_tab(dialog, event.currentTarget.dataset.intakeTab);
		});
		set_intake_review_tab(dialog, initialTab);
	}
}

async function mount_intake_review_maps(dialog, data, unchanged) {
	const root = dialog.fields_dict.references_display?.$wrapper?.get?.(0);
	if (!root?.querySelectorAll) return;
	if (!root.querySelectorAll("[data-intake-map]").length) return;
	if (!dialog.__intake_review_maps) {
		const state = dialog.__intake_review_maps = {closed: false, cleanups: [], mounted: new WeakSet()};
		const previous = dialog.onhide;
		dialog.onhide = () => {
			state.closed = true;
			for (const cleanup of state.cleanups.splice(0)) cleanup();
			previous?.call(dialog);
		};
	}
	const state = dialog.__intake_review_maps;
	try {
		if (!window.KunalWhatsAppMap?.mount) await frappe.require("/assets/kunal_enterprises/js/whatsapp_inbox_maps.js");
	} catch (_) {return;} // The Open map link remains available without tiles.
	// HTML controls may refresh while the optional map asset is loading.
	const hosts = Array.from(root.querySelectorAll("[data-intake-map]"));
	for (const host of hosts) {
		if (state.closed || !unchanged() || !host.isConnected || state.mounted.has(host)) continue;
		if (host.getClientRects && !host.getClientRects().length) continue;
		const reference = data.references.find(row => row.name === host.dataset.intakeMap && row.reference_type === "Location");
		if (reference && window.KunalWhatsAppMap?.mount) {
			state.mounted.add(host);
			state.cleanups.push(window.KunalWhatsAppMap.mount(host, reference));
		}
	}
}

function set_intake_review_tab(dialog, selected) {
	if (!["messages", "attachments"].includes(selected)) return;
	dialog.fields_dict.conversation?.$wrapper?.toggle?.(selected === "messages");
	for (const field of ["references_display", "review_help", "reviews"]) {
		dialog.fields_dict[field]?.$wrapper?.toggle?.(selected === "attachments");
	}
	dialog.fields_dict.review_navigation?.$wrapper?.find?.("button[data-intake-tab]").each((_, button) => {
		const active = button.dataset.intakeTab === selected;
		button.setAttribute("aria-selected", String(active));
		button.classList.toggle("btn-primary", active);
		button.classList.toggle("btn-default", !active);
	});
	// Modal/tab lifecycle reliably exposes the map; viewport observers may be throttled.
	if (selected === "attachments") void dialog.__intake_mount_review_maps?.();
}


function intake_is_converted(frm) {
	return Boolean(frm.doc.order) || frm.doc.status === "Converted to Order";
}

function intake_processing_method(frm) {
	if (frm.has_perm && !frm.has_perm("write")) return null;
	if (frm.is_new() || intake_is_converted(frm) || !["Pending Review", "In Review", "Awaiting Confirmation"].includes(frm.doc.status)) return null;
	if (frm.doc.request_type === "Order") return "convert";
	if (["Stock Inquiry", "Price Inquiry"].includes(frm.doc.request_type)) return "handle_inquiry";
	return null;
}

function intake_processing_controls(frm) {
	const converted = intake_is_converted(frm);
	if (converted) {
		if (!frm.__intake_processing_readonly) {
			frm.__intake_processing_readonly = (frm.fields || []).map(field => [field.df.fieldname, field.df.read_only || 0]);
		}
		for (const [field] of frm.__intake_processing_readonly) frm.set_df_property(field, "read_only", 1);
		frm.disable_save?.();
		if (frm.doc.order) frm.add_custom_button(__("View Order"), () => frappe.set_route("Form", "Order", frm.doc.order));
	} else if (frm.__intake_processing_readonly) {
		for (const [field, readOnly] of frm.__intake_processing_readonly) frm.set_df_property(field, "read_only", readOnly);
		frm.__intake_processing_readonly = null;
		frm.enable_save?.();
	}
	const method = intake_processing_method(frm);
	if (method) frm.add_custom_button(method === "convert" ? __("Create Order") : __("Mark handled"), () => process_intake_request(frm, method));
}

function intake_processing_summary(doc, method) {
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	if (method === "handle_inquiry") return `<p>${__("Mark this inquiry handled. No Order is created. Your confirmed request-type corrections and reasons can help classify future messages.")}</p>` +
		`<p>${escape(doc.name)} · ${escape(doc.request_type)}</p>`;
	const rows = (doc.items || []).map(row => `<tr><td>${escape(row.item_name || row.item || __("Not selected"))}</td>` +
		`<td>${escape(row.quantity_unknown ? __("Needs confirmation") : row.quantity)} ${escape(row.unit || "")}</td><td>${escape(row.godown || __("Awaiting assignment"))}</td></tr>`).join("");
	return `<p>${__("Create the actual Order from these saved selections. Your confirmed choices and correction reasons can help match future messages.")}</p>` +
		`<p>${__("Request")}: ${escape(doc.name)}<br>${__("Customer")}: ${escape(doc.customer_name || doc.customer || __("Not selected"))}` +
		(doc.sales_employee ? `<br>${__("Salesperson")}: ${escape(doc.sales_employee_name || doc.sales_employee)}` : "") + "</p>" +
		`<table class="table table-bordered"><thead><tr><th>${__("Item")}</th><th>${__("Quantity")}</th><th>${__("Dispatch warehouse")}</th></tr></thead><tbody>${rows}</tbody></table>` +
		((doc.items || []).some(row => !row.godown) ? `<p class="text-muted">${__("Quantities without a warehouse will wait for warehouse assignment.")}</p>` : "") +
		(String(doc.unresolved_questions || "").trim() || (doc.attachments || []).some(row => row.review_status !== "Reviewed")
			? `<p class="text-muted">${__("Some message details or attachments still need review. Check the Messages section before creating the Order.")}</p>` : "");
}

async function process_intake_request(frm, method) {
	if (frm.__intake_processing_busy) return;
	if (frm.is_new() || frm.is_dirty()) {
		frappe.msgprint(__("Save your changes before processing this request."));
		return;
	}
	if (method !== intake_processing_method(frm)) return;
	const state = JSON.stringify(frm.doc);
	const request = frm.doc.name;
	const modified = frm.doc.modified;
	const unchanged = () => !frm.is_new() && !frm.is_dirty() && JSON.stringify(frm.doc) === state && method === intake_processing_method(frm);
	frm.__intake_processing_busy = true;
	try {
		const {message: evidence} = await frappe.call({method: "kunal_enterprises.api.order_intake_conversation.messages", type: "GET", freeze: true,
			args: {request, expected_modified: modified}});
		if (!unchanged()) {frappe.msgprint(__("The request changed. Save and review it again before processing.")); return;}
		if (evidence?.request !== request || evidence.modified !== modified || typeof evidence.revision !== "string" || !evidence.revision) {
			frappe.msgprint(__("Current message evidence is unavailable. Reload the request and try again.")); return;
		}
		const label = method === "convert" ? __("Create Order") : __("Mark handled");
		// Keep confirmation separate from the shared server-message dialog;
		// reusing msgprint can hide validation errors when its modal is replaced.
		const confirmation = new frappe.ui.Dialog({title: label,
			fields: [{fieldname: "summary", fieldtype: "HTML", options: intake_processing_summary(frm.doc, method)}],
			primary_action_label: label, primary_action: async () => {
				if (frm.__intake_processing_busy) return;
				if (!unchanged()) {frappe.msgprint(__("The request changed. Save and review it again before processing.")); return;}
				frm.__intake_processing_busy = true;
				try {
					await frappe.call({method: "kunal_enterprises.api.order_intake_processing." + method, type: "POST", freeze: true,
						args: {request, expected_modified: modified, revision: evidence.revision}});
					confirmation.hide();
					if (unchanged()) await frm.reload_doc();
					else frappe.show_alert?.({message: __("Request processed. Reopen it to see the result."), indicator: "blue"});
				} finally {frm.__intake_processing_busy = false;}
			}});
		confirmation.show();
	} finally {frm.__intake_processing_busy = false;}
}
