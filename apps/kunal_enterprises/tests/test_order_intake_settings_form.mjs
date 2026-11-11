import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import vm from "node:vm";
import test from "node:test";

const source = readFileSync(new URL("../kunal_enterprises/kunal_enterprises/doctype/order_intake_settings/order_intake_settings.js", import.meta.url), "utf8");
function form() {
	let handlers;
	const buttons = new Map(), calls = [], messages = [], prompts = [], routes = [];
	const frappe = {
		ui: {form: {on: (_, value) => { handlers = value; }}},
		prompt: (fields, callback, title, action) => prompts.push({fields, callback, title, action}),
		call: async args => {calls.push(args); return {message: {state: "Preview", note: "<script>untrusted</script>", tokens: ["private-job-token"], sender: "919000000049", whatsapp_account: "TEST WA"}};},
		msgprint: args => messages.push(args),
		hide_msgprint: () => {},
		set_route: (...args) => routes.push(args),
		utils: {escape_html: value => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")},
	};
	vm.runInNewContext(source, {frappe, __: x => x});
	const frm = {set_intro: () => {}, add_custom_button: (name, action) => buttons.set(name, action)};
	handlers.refresh(frm);
	return {buttons, calls, messages, prompts, routes};
}

test("preview requires account and sender and makes a read-only GET", async () => {
	const f = form();
	f.buttons.get("Preview Sender Context")();
	assert.equal(f.prompts.length, 1);
	assert.deepEqual(Array.from(f.prompts[0].fields, field => [field.fieldname, field.reqd]), [["whatsapp_account", 1], ["sender", 1]]);
	await f.prompts[0].callback({whatsapp_account: "TEST WA", sender: "919000000049"});
	assert.equal(f.calls[0].type, "GET");
	assert.equal(f.calls[0].method, "kunal_enterprises.api.order_intake_queue.preview");
});

test("manual preparation explicitly posts one selected sender", async () => {
	const f = form();
	f.buttons.get("Prepare Sender Context")();
	await f.prompts[0].callback({whatsapp_account: "TEST WA", sender: "919000000049"});
	assert.equal(f.calls[0].type, "POST");
	assert.equal(f.calls[0].method, "kunal_enterprises.api.order_intake_queue.prepare_now");
	assert.equal(f.calls[0].args.sender, "919000000049");
	assert.equal(f.calls[0].freeze, true);
});

test("context results are escaped before HTML display", async () => {
	const f = form();
	f.buttons.get("Preview Sender Context")();
	await f.prompts[0].callback({whatsapp_account: "TEST WA", sender: "919000000049"});
	assert.equal(f.messages.length, 1);
	assert.ok(f.messages[0].message.includes("&lt;script&gt;"));
	assert.ok(!f.messages[0].message.includes("<script>"));
	assert.ok(!f.messages[0].message.includes("private-job-token"));
});


test("sender history uses the normalized server identity rather than formatted input", async () => {
	const f = form();
	f.buttons.get("Preview Sender Context")();
	await f.prompts[0].callback({whatsapp_account: "TEST WA", sender: "+91 90000 00049"});
	f.messages[0].primary_action.action();
	assert.equal(f.routes.length, 1);
	assert.equal(f.routes[0][2].intake_sender_key, "919000000049");
	assert.equal(f.routes[0][2].whatsapp_account, "TEST WA");
	assert.equal(f.routes[0][2].from, undefined);
});

test("manual recovery requires explicit message links and posts only selected IDs", async () => {
	const f = form();
	f.buttons.get("Retry Selected Context")();
	const selection = f.prompts[0].fields.find(field => field.fieldname === "messages");
	assert.equal(selection.fieldtype, "Table");
	assert.equal(selection.reqd, 1);
	assert.equal(selection.fields[0].options, "WhatsApp Message");
	await f.prompts[0].callback({whatsapp_account: "TEST WA", sender: "919000000049", messages: [{message: "MSG-1"}, {message: "MSG-2"}, {}]});
	assert.equal(f.calls[0].method, "kunal_enterprises.api.order_intake_queue.retry_selected");
	assert.equal(f.calls[0].type, "POST");
	assert.deepEqual(Array.from(f.calls[0].args.messages), ["MSG-1", "MSG-2"]);
});
