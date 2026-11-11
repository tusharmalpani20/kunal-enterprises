"""Privatize exact WhatsApp file URLs without breaking shared attachment references."""
from functools import partial
import filecmp
import hashlib
import os
from pathlib import Path
from urllib.parse import unquote
from uuid import uuid4

import frappe


PUBLIC_SETTINGS = {"Website Settings", "Navbar Settings", "Website Theme"}


def _attachment_fields():
	fields = {}
	for table, parent in (("DocField", "parent"), ("Custom Field", "dt")):
		for row in frappe.get_all(table, filters={"fieldtype": ["in", ["Attach", "Attach Image"]]}, fields=[parent, "fieldname"]):
			fields.setdefault(row[parent], set()).add(row.fieldname)
	return fields


def _references(url, attachment_fields):
	"""Find real Attach fields, including reused URLs without a matching File link."""
	refs = []
	for doctype, fields in attachment_fields.items():
		meta = frappe.get_meta(doctype)
		if meta.is_virtual or (not meta.issingle and not frappe.db.table_exists(doctype)):
			continue
		for field in fields:
			if meta.issingle:
				if frappe.db.get_single_value(doctype, field, cache=False) == url:
					refs.append((doctype, doctype, field))
			else:
				for name in frappe.get_all(doctype, filters={field: url}, pluck="name", limit_page_length=0):
					refs.append((doctype, name, field))
	return refs


def _public_parent(doctype, name):
	doc = frappe.get_doc(doctype, name)
	if doc.meta.istable and doc.parenttype and doc.parent:
		doc = frappe.get_doc(doc.parenttype, doc.parent)
	if doc.doctype in PUBLIC_SETTINGS:
		return True
	if doc.meta.has_web_view and (doc.get("published") or doc.get("is_published")):
		return True
	return bool(frappe.has_permission(doc.doctype, "read", doc=doc, user="Guest"))


def _restore(source, target):
	if source.exists():
		target.parent.mkdir(parents=True, exist_ok=True)
		os.replace(source, target)


def _remove(path):
	path.unlink(missing_ok=True)


def _md5(path):
	value = hashlib.md5(usedforsecurity=False)
	with path.open("rb") as stream:
		for chunk in iter(lambda: stream.read(1024 * 1024), b""):
			value.update(chunk)
	return value.hexdigest()


def _move(url, content_hash):
	public_root = Path(frappe.get_site_path("public", "files")).resolve()
	source = Path(frappe.get_site_path("public", unquote(url).lstrip("/"))).resolve()
	if not source.is_relative_to(public_root):
		frappe.throw("WhatsApp attachment has an invalid public file path")
	relative = source.relative_to(public_root)
	target = Path(frappe.get_site_path("private", "files", str(relative))).resolve()
	private_root = Path(frappe.get_site_path("private", "files")).resolve()
	if not target.is_relative_to(private_root):
		frappe.throw("WhatsApp attachment has an invalid private file path")
	target.parent.mkdir(parents=True, exist_ok=True)
	if not source.exists():
		# A process may have stopped after moving bytes but before committing DB.
		if not (target.is_file() and content_hash and _md5(target) == content_hash):
			frappe.throw("WhatsApp attachment bytes are missing; privacy migration stopped without changing its references")
	elif target.exists():
		if not target.is_file() or not filecmp.cmp(source, target, shallow=False):
			frappe.throw("A different private attachment already uses this filename; privacy migration stopped without overwriting it")
		# Preserve the original until commit so a failed migration can restore it.
		backup = Path(frappe.get_site_path("private", "backups", "wa-privacy-" + uuid4().hex))
		backup.parent.mkdir(parents=True, exist_ok=True)
		os.replace(source, backup)
		frappe.db.before_rollback.add(partial(_restore, backup, source))
		frappe.db.after_commit.add(partial(_remove, backup))
	else:
		os.replace(source, target)
		# Before rollback ensures fixtures' own File rollback deletion sees the
		# restored original path; existing files likewise retain their bytes.
		frappe.db.before_rollback.add(partial(_restore, target, source))
	return "/private/files/" + relative.as_posix()


def execute():
	if not frappe.db.exists("DocType", "WhatsApp Message"):
		return
	attachment_fields = _attachment_fields()
	while True:
		rows = frappe.db.sql("""SELECT DISTINCT f.file_url FROM `tabFile` f WHERE f.is_private=0
			AND f.file_url LIKE '/files/%%' AND
			(f.attached_to_doctype='WhatsApp Message' OR EXISTS
			(SELECT 1 FROM `tabWhatsApp Message` w WHERE w.type='Incoming' AND w.attach=f.file_url))
			ORDER BY f.file_url LIMIT 100""", as_dict=True)
		if not rows:
			break
		for row in rows:
			url = row.file_url
			files = frappe.get_all("File", filters={"file_url": url}, fields=["name", "content_hash", "attached_to_doctype", "attached_to_name"], limit_page_length=0)
			refs = _references(url, attachment_fields)
			parents = {(dt, name) for dt, name, _ in refs}
			parents.update((f.attached_to_doctype, f.attached_to_name) for f in files if f.attached_to_doctype and f.attached_to_name)
			for doctype, name in parents:
				if frappe.db.exists(doctype, name) and _public_parent(doctype, name):
					frappe.throw("This WhatsApp attachment is also used by a public page or public settings. Review that shared use before making it private; nothing was moved")
			private_url = _move(url, next((f.content_hash for f in files if f.content_hash), None))
			# File.save() would update every equal-content hash globally, including
			# unrelated physical URLs. Restrict changes to this exact moved blob.
			for file in files:
				frappe.db.set_value("File", file.name, {"is_private": 1, "file_url": private_url}, update_modified=False)
			for doctype, name, field in refs:
				if frappe.get_meta(doctype).issingle:
					frappe.db.set_single_value(doctype, field, private_url)
				else:
					frappe.db.set_value(doctype, name, field, private_url, update_modified=False)
