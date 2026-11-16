"""Publish validated suggestions atomically without replacing reviewer selections."""
import json
import re

import frappe
from frappe.utils import get_datetime

from kunal_enterprises.integrations.order_intake_ai_models import AIProblem
from kunal_enterprises.integrations.order_intake_contacts import contacts_from_source
from kunal_enterprises.integrations.order_intake_ai_review import preserve_existing_items, review_questions
from kunal_enterprises.integrations.order_intake_ai_state import coverage_attention, TRANSFER_NOTE
from kunal_enterprises.integrations.order_intake_ai_updates import (
	proposal_changes_values, proposal_signature, prune_noop_updates, reference_key,
)


def attachments(messages, warnings, media_metadata=None):
	result = []
	for message in messages:
		name = message["name"]
		if message.get("attach"):
			result.append(dict(reference_type="File", file=message["attach"],
				label=message.get("intake_media_filename") or "WhatsApp attachment", source_message=name,
				page_count=(media_metadata or {}).get(name, {}).get('page_count'),
				review_status="Needs Manual Review" if warnings.get(name) else "Not Reviewed"))
		if message.get("intake_media_id") and not message.get("attach"):
			warnings.setdefault(name, []).append("Attachment download is not yet available; review the original message and retry download.")
		if message.get("intake_has_location"):
			result.append(dict(reference_type="Location", label=message.get("intake_location_name") or "WhatsApp location",
				latitude=message.get("intake_latitude"), longitude=message.get("intake_longitude"),
				location_address=message.get("intake_location_address"), source_message=name, review_status="Not Reviewed"))
		if (message.get("intake_original_type") or message.get("content_type")) in ("contacts", "contact"):
			contacts, warning = contacts_from_source(message)
			if warning:
				warnings.setdefault(name, []).append(warning)
			for contact in contacts:
				for phone in contact['phones'] or [{}]:
					result.append(dict(reference_type="Contact", label=contact['name'] or "Shared contact",
						contact_name=contact['name'], contact_number=phone.get('phone') or phone.get('wa_id'),
						source_message=name, review_status="Not Reviewed"))
		for url in dict.fromkeys(re.findall(r'https?://[^\s<>"\x00-\x20]+', message.get("message") or "")):
			result.append(dict(reference_type="External Link", external_url=url, label="Shared link (not opened)",
				source_message=name, review_status="Not Reviewed"))
	# A payload may repeat a card or URL; one reference per source identity suffices.
	return list({reference_key(row): row for row in result}.values())


def _proposal(extraction, refs, warnings):
	data = extraction.model_dump()
	data["source_messages"] = sorted(refs)
	data["media_warnings"] = {name: warnings[name] for name in refs if warnings.get(name)}
	return data


def _received_bounds(doc):
	"""Server-derived times follow the complete linked ledger, including late arrivals."""
	names = [row.message for row in doc.source_messages]
	rows = frappe.get_all("WhatsApp Message", filters={"name": ("in", names)},
		fields=["intake_received_at", "creation"], limit_page_length=0) if names else []
	times = [get_datetime(row.intake_received_at or row.creation) for row in rows if row.intake_received_at or row.creation]
	if times:
		doc.first_received_at, doc.last_received_at = min(times), max(times)


def publish(snapshot, grouping, extractions, warnings, media_metadata=None):
	"""Caller holds account and source locks and has checked the snapshot fence."""
	messages = {row["name"]: row for row in snapshot["messages"]}
	context_only = set(snapshot.get("context_only_ids") or [])
	coverage = {name: {"requests": frappe.parse_json(messages[name].get("intake_ai_coverage") or "{}").get("requests", []),
		"unresolved": name in grouping.unresolved_message_ids} for name in messages if name not in context_only}
	created, proposed = [], []
	reasons = {name: list(warnings.get(name) or []) for name in messages}
	for index, (group, extraction) in enumerate(zip(grouping.groups, extractions, strict=True)):
		refs = group.message_ids
		rows = [messages[name] for name in refs]
		references = attachments(rows, warnings, media_metadata)
		questions = list(extraction.unresolved_questions)
		relationship_note = getattr(group, 'relationship_note', None)
		if relationship_note:
			questions.append(relationship_note)
		for name in refs:
			questions.extend(warnings.get(name, []))
		if group.target_request:
			doc = frappe.get_doc("Order Intake Request", group.target_request, for_update=True)
			old = next((r for r in snapshot["open_requests"] if r["name"] == doc.name), None)
			if not old or str(doc.modified) != old["modified"]:
				raise AIProblem("A related request changed during AI processing; prepare and review the updated context.", True)
			# Even Pending Review drafts may already contain human edits. Propose
			# changes instead of guessing which current fields are safe to replace.
			updates = frappe.parse_json(doc.proposed_updates or "[]")
			updates, removed_noops = prune_noop_updates(doc, updates)
			proposal = preserve_existing_items(_proposal(extraction, refs, warnings), doc)
			if relationship_note:
				proposal.setdefault('review_warnings', []).append(relationship_note)
			for item in proposal['items']:
				item['quantity_unknown'] = item.get('quantity') is None
			questions.extend(proposal.get('review_warnings', []))
			keys = {reference_key(row): row for row in doc.attachments}
			new_references = [row for row in references if reference_key(row) not in keys]
			if new_references:
				proposal['new_references'] = new_references
			changed = proposal_changes_values(proposal, doc)
			duplicate = any(proposal_signature(update) == proposal_signature(proposal) for update in updates)
			appended = changed and not duplicate
			if appended:
				if sum(not update.get("reviewed_at") for update in updates) >= 50:
					raise AIProblem("The request has too many pending suggestions; review them before processing more messages.")
				updates.append(proposal)
			doc.proposed_updates = json.dumps(updates, ensure_ascii=False)
			known = {row.message for row in doc.source_messages}
			new_sources = set(refs) - known
			for name in refs:
				if name not in known:
					doc.append("source_messages", {"message": name, "association_note": "New message; review suggested changes." if changed else "Additional message; existing values already represent this request."})
			reference_metadata_changed = False
			for row in references:
				key = reference_key(row)
				if key not in keys:
					doc.append("attachments", row)
				elif row.get('page_count') is not None:
					# Refresh inspected metadata without replacing review notes/status.
					reference_metadata_changed |= keys[key].page_count != row['page_count']
					keys[key].page_count = row['page_count']
			if appended or removed_noops or new_sources or new_references or reference_metadata_changed:
				_received_bounds(doc)
				doc.save(ignore_permissions=True)
				proposed.append(doc.name)
		else:
			doc = frappe.get_doc(dict(doctype="Order Intake Request", source="WhatsApp", request_type=extraction.request_type,
				status="Pending Review", customer_text=extraction.customer_text, salesperson_text=extraction.salesperson_text, whatsapp_account=snapshot["whatsapp_account"], sender_number=snapshot["sender"],
				sender_name=rows[0].get("profile_name"), estimated_interpretation=extraction.summary,
				unresolved_questions="\n".join(dict.fromkeys(questions)), delivery_address=extraction.delivery_address,
				delivery_contact_name=extraction.delivery_contact_name, delivery_contact_number=extraction.delivery_contact_number,
				source_messages=[dict(message=name) for name in refs], attachments=references,
				items=[dict(original_text=i.original_text, source_message=i.source_message, quantity=i.quantity, quantity_unknown=int(i.quantity is None),
					unit=i.unit, warehouse_text=i.warehouse_text, warehouse_source_message=i.warehouse_source_message,
					notes=i.notes) for i in extraction.items]))
			_received_bounds(doc)
			# Matching happens inside the publication transaction, using only
			# master records and confirmed evidence; no additional provider calls.
			from kunal_enterprises.integrations.order_intake_match_requests import match_new_document
			from uuid import uuid4
			for item in doc.items:
				item.row_key = item.row_key or uuid4().hex
			match_new_document(doc)
			doc.ai_initial_values = json.dumps(dict(request_type=doc.request_type, customer=doc.customer,
				sales_employee=doc.sales_employee, items=[{key: row.get(key) for key in
					('row_key', 'item', 'godown', 'original_text', 'warehouse_text')} for row in doc.items]), ensure_ascii=False)
			doc.unresolved_questions = '\n'.join(review_questions(doc, questions))
			previous = frappe.flags.intake_matching_write
			try:
				frappe.flags.intake_matching_write = True
				doc.insert(ignore_permissions=True)
			finally:
				frappe.flags.intake_matching_write = previous
			created.append(doc.name)
		for name in refs:
			if name not in coverage:
				continue
			reasons[name].extend(questions or ['This message could not be assigned confidently to an order; review its linked request.'])
			if name in coverage:
				coverage[name]["requests"].append(doc.name)
				coverage[name]["unresolved"] |= name in extraction.unresolved_message_ids or bool(warnings.get(name)) or bool(relationship_note) or bool(group.target_request and changed and proposal.get("review_warnings"))
	for name, value in coverage.items():
		value["requests"] = list(dict.fromkeys(value["requests"]))
		values = {"intake_ai_coverage": json.dumps(value)}
		current = frappe.db.get_value("WhatsApp Message", name,
			["intake_attention", "intake_status", "intake_prepare_state", "intake_media_state", "intake_ai_note"], as_dict=True)
		values.update(coverage_attention(current, value["unresolved"], reasons[name]))
		if name != snapshot["anchor"]:
			values.update(intake_ai_state="Unresolved" if value["unresolved"] else "Drafted",
				intake_ai_attempts=0, intake_ai_retry_at=None,
				intake_ai_note="Linked drafts are ready for review; no Order was created.")
		if current.intake_ai_note == TRANSFER_NOTE:
			values.update(intake_ai_state="Unresolved" if value["unresolved"] else "Drafted", intake_ai_attempts=0,
				intake_ai_note="Included in a newer sender context; linked drafts are ready for review.")
		frappe.db.set_value("WhatsApp Message", name, values, update_modified=False)
	return dict(created=created, proposed=proposed, unresolved=[name for name, value in coverage.items() if value["unresolved"]])
