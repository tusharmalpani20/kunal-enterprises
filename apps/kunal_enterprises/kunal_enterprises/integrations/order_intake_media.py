"""Bounded private downloads after the incoming message transaction is durable."""
from functools import partial
from pathlib import PurePath
from urllib.parse import urlparse
from uuid import uuid4

import frappe
import requests
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

DT = "WhatsApp Message"
MEDIA_TYPES = {"image", "audio", "video", "document", "sticker"}
TIMEOUT = (5, 30)
MAX_BYTES = 32 * 1024 * 1024
MAX_AUTOMATIC_ATTEMPTS = 3
LEASE_MINUTES = 10
MEDIA_ATTENTION = "Attachment download needs attention; use Retry Attachment Download."


def queue_download(name, manual=False):
	"""Claim under a row lock. The caller commits; publication occurs afterward."""
	doc = frappe.get_doc(DT, name, for_update=True)
	if doc.type != "Incoming" or not doc.get("intake_media_id"):
		return dict(state="Not Applicable")
	if doc.attach:
		private = frappe.db.get_value("File", {"file_url": doc.attach, "is_private": 1}, "name")
		if private:
			frappe.db.set_value(DT, name, {"intake_media_state": "Downloaded", "intake_media_note": ""}, update_modified=False)
			return dict(state="Downloaded")
	now = now_datetime()
	if doc.get("intake_media_state") == "Queued" and doc.get("intake_media_queued_at") and get_datetime(doc.intake_media_queued_at) > add_to_date(now, minutes=-LEASE_MINUTES, as_datetime=True):
		return dict(state="Queued")
	attempts = cint(doc.get("intake_media_attempts"))
	if not manual and attempts >= MAX_AUTOMATIC_ATTEMPTS:
		return dict(state="Failed", note="Automatic download attempts exhausted; use Retry Attachment Download.")
	token = uuid4().hex
	frappe.db.set_value(DT, name, dict(intake_media_state="Queued", intake_media_job_token=token,
		intake_media_queued_at=now, intake_media_attempts=attempts + 1,
		intake_media_note="Attachment download is queued; original media reference is preserved."), update_modified=False)
	frappe.db.after_commit.add(partial(_publish, name, token))
	return dict(state="Queued")


def retry_download(name):
	"""Explicit user action: read-only reviewers cannot initiate network work."""
	doc = frappe.get_doc(DT, name)
	doc.check_permission("read")
	doc.check_permission("write")
	return queue_download(name, manual=True)


def _publish(name, token):
	try:
		frappe.enqueue("kunal_enterprises.integrations.order_intake_media.download", queue="short",
			job_id="intake-media-" + token, timeout=120, name=name, token=token)
	except Exception:
		_fail(name, token, "The download queue is unavailable. Use Retry Attachment Download.")
		frappe.db.commit()  # This callback runs after the source transaction committed.


def _fail(name, token, note):
	doc = frappe.get_doc(DT, name, for_update=True)
	if doc.get("intake_media_job_token") == token and doc.get("intake_media_state") == "Queued":
		reasons = list(filter(None, (doc.get("intake_attention") or "").splitlines()))
		if MEDIA_ATTENTION not in reasons:
			reasons.append(MEDIA_ATTENTION)
		frappe.db.set_value(DT, name, dict(intake_media_state="Failed", intake_media_job_token=None,
			intake_media_note=note, intake_status="Needs Attention", intake_attention="\n".join(reasons)), update_modified=False)


def _media_url(url):
	parsed = urlparse(url or "")
	# Meta returns a temporary HTTPS CDN URL. Never follow redirects or let a
	# response make us send the access token to an arbitrary host/local service.
	host = (parsed.hostname or "").lower()
	if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port not in (None, 443) or not (host.endswith(".fbcdn.net") or host.endswith(".facebook.com") or host.endswith(".fbsbx.com")):
		raise ValueError("Unexpected media download host")
	return url


def _fetch(account, media_id):
	base = urlparse(account.url or "https://graph.facebook.com")
	if base.scheme != "https" or base.hostname != "graph.facebook.com" or base.port not in (None, 443):
		raise ValueError("Unexpected Graph API host")
	headers = {"Authorization": "Bearer " + account.get_password("token")}
	metadata = requests.get(f"https://graph.facebook.com/{account.version}/{media_id}", headers=headers,
		timeout=TIMEOUT, allow_redirects=False)
	try:
		metadata.raise_for_status()
		data = metadata.json()
	finally:
		metadata.close()
	response = requests.get(_media_url(data.get("url")), headers=headers, timeout=TIMEOUT,
		allow_redirects=False, stream=True)
	try:
		response.raise_for_status()
		if response.status_code != 200:
			raise ValueError("Unexpected media response")
		if cint(response.headers.get("Content-Length")) > MAX_BYTES:
			raise ValueError("Attachment exceeds download limit")
		parts, size = [], 0
		for chunk in response.iter_content(chunk_size=64 * 1024):
			size += len(chunk)
			if size > MAX_BYTES:
				raise ValueError("Attachment exceeds download limit")
			parts.append(chunk)
		return b"".join(parts), data.get("mime_type") or "application/octet-stream"
	finally:
		response.close()


def download(name, token):
	"""Network calls hold no message locks; a token fences stale workers at save."""
	doc = frappe.get_doc(DT, name)
	if doc.get("intake_media_job_token") != token or doc.get("intake_media_state") != "Queued":
		return dict(state="Stale")
	try:
		account = frappe.get_doc("WhatsApp Account", doc.whatsapp_account)
		content, mime = _fetch(account, doc.intake_media_id)
		current = frappe.get_doc(DT, name, for_update=True)
		if current.get("intake_media_job_token") != token or current.get("intake_media_state") != "Queued":
			return dict(state="Stale")
		if current.intake_media_id != doc.intake_media_id or current.whatsapp_account != doc.whatsapp_account:
			raise ValueError("Media reference changed")
		filename = PurePath(current.get("intake_media_filename") or ("whatsapp-" + name)).name
		file = frappe.get_doc(dict(doctype="File", file_name=filename, is_private=1,
			attached_to_doctype=DT, attached_to_name=name, attached_to_field="attach", content=content))
		file.insert(ignore_permissions=True)
		values = dict(attach=file.file_url, intake_media_mime=mime, intake_media_state="Downloaded",
			intake_media_job_token=None, intake_media_note="")
		reasons = list(filter(None, (current.get("intake_attention") or "").splitlines()))
		if MEDIA_ATTENTION in reasons:
			reasons.remove(MEDIA_ATTENTION)
			values["intake_attention"] = "\n".join(reasons)
			if not reasons and current.get("intake_prepare_state") != "Needs Attention":
				values["intake_status"] = "New"
		if current.get("intake_prepare_state") == "Context Ready":
			values.update(intake_prepare_state="Pending", intake_prepare_note="A downloaded attachment awaits context preparation.")
		frappe.db.set_value(DT, name, values, update_modified=False)
		return dict(state="Downloaded")
	except Exception:
		# Never store provider responses, request exceptions or credentials.
		_fail(name, token, "Attachment download failed. The original media reference is preserved; use Retry Attachment Download.")
		frappe.local.message_log = []
		return dict(state="Failed")
