frappe.ui.form.on("Order Intake Settings", {
	refresh(frm) {
		frm.set_intro("");
		const explanations = {
			preview: __("See which messages and related requests would be included for this sender. Nothing is changed."),
			prepare_now: __("Prepare this sender's pending messages now, including recent unresolved messages. Automatic scheduling stays unchanged; this does not create an order."),
			retry_selected: __("Retry only the messages you select, including older messages or messages needing attention. Original received times are kept, and active jobs are not replaced."),
		};
		const prompt = (method, label, retry = false) => {
			let dialog;
			const fields = [
			{fieldname: "action_help", fieldtype: "HTML", options:
				'<div class="alert alert-info"><strong>' + frappe.utils.escape_html(__("What this does")) + '</strong><p class="mb-0">' +
				frappe.utils.escape_html(explanations[method]) + '</p></div>'},
			{fieldname: "whatsapp_account", fieldtype: "Link", options: "WhatsApp Account", label: __("Receiving WhatsApp Account"), reqd: 1},
			{fieldname: "sender", fieldtype: "Data", label: __("Sender Number / Identity"), reqd: 1},
		];
			if (retry) fields.push({fieldname: "messages", fieldtype: "Table", label: __("Messages to Retry"), reqd: 1,
				description: __("Select up to 100 messages from this sender, including older messages that need review. Original received times are preserved."),
				in_place_edit: true, fields: [{fieldname: "message", fieldtype: "Link", options: "WhatsApp Message", label: __("WhatsApp Message"), reqd: 1, in_list_view: 1,
					get_query: () => {
						const raw = String(dialog.get_value("sender") || "").trim();
						const sender = /^[\d+ ()-]+$/.test(raw) ? raw.replace(/[^\d]/g, "") : raw;
						return {filters: {type: "Incoming", whatsapp_account: dialog.get_value("whatsapp_account"), intake_sender_key: sender,
							intake_received_at: ["is", "set"], intake_status: ["!=", "Duplicate"]}};
					}}]});
			dialog = frappe.prompt(fields, async values => {
				const args = {...values};
				if (retry) args.messages = (values.messages || []).filter(row => row.message).map(row => row.message);
				const {message} = await frappe.call({method: "kunal_enterprises.api.order_intake_queue." + method,
					args, type: method === "preview" ? "GET" : "POST", freeze: true});
				const escape = value => frappe.utils.escape_html(String(value || ""));
				const context = message.context;
				const details = context ? [
					__("Messages: {0}", [context.message_ids.length]),
					__("Reply references: {0}", [context.reply_message_ids.length]),
					__("Earlier messages needing review: {0}", [context.manual_review_message_ids.length]),
					__("Related open requests: {0}", [context.open_requests.length]),
				] : message.ready !== undefined ? [
					__("Chats ready: {0}", [message.ready]),
					__("Chats waiting for retry: {0}", [message.retrying]),
					__("Chats needing another attempt: {0}", [message.failed_chats + message.stale]),
				] : [];
				frappe.msgprint({title: __(label), message: [
					"<p>" + escape(__(message.state)) + "</p>",
					...details.map(line => "<p>" + escape(line) + "</p>"),
					...(context?.warnings || []).map(warning => "<p>" + escape(warning) + "</p>"),
					message.note ? "<p>" + escape(message.note) + "</p>" : "",
				].join(""), primary_action: {label: __("View Sender Messages"), action: () => {
					frappe.hide_msgprint();
					frappe.set_route("List", "WhatsApp Message", {type: "Incoming", whatsapp_account: message.whatsapp_account || values.whatsapp_account, intake_sender_key: context?.sender || message.sender});
				}}});
			}, __(label), __(label));
		};
		frm.add_custom_button(__("Preview Sender Context"), () => prompt("preview", "Preview Sender Context"));
		frm.add_custom_button(__("Prepare Sender Context"), () => prompt("prepare_now", "Prepare Sender Context"));
		frm.add_custom_button(__("Retry Selected Context"), () => prompt("retry_selected", "Retry Selected Context", true));
	},
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
