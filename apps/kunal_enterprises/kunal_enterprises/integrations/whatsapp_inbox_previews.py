"""Bounded thumbnails from source-owned local files; never fetch remote media."""
import hashlib
import io
import os
from pathlib import Path
import resource
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
from urllib.parse import unquote
import warnings

import frappe
from PIL import Image, ImageOps

from kunal_enterprises.api.order_intake_conversation import _file_reference
from kunal_enterprises.api.whatsapp_inbox import _account, _sender_key

MAX_BYTES = 32 * 1024 * 1024
MAX_PIXELS = 25_000_000
RENDERER = "inbox-preview-v1"
UNAVAILABLE = {"available": False, "note": "Preview unavailable. Open the original attachment."}


def _owned_file(url, source):
    reference = _file_reference(url, SimpleNamespace(name=None), {source.name})
    if not reference["available"]:
        return None
    path = (Path(frappe.get_site_path("private", "files")) / unquote(reference["url"]).removeprefix("/private/files/")).resolve()
    return reference, path


def _png(data):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValueError("Image too large")
            image.seek(0)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((480, 480))
            image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue(), image.width, image.height


def _limits():
    # Poppler parses untrusted PDFs out of process, with bounded resources.
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _render(data, kind):
    if kind != "pdf":
        return _png(data)
    executable = shutil.which("pdftoppm")
    if not executable:
        raise ValueError("PDF renderer unavailable")
    with tempfile.TemporaryDirectory(prefix="inbox-preview-") as directory:
        source, target = Path(directory) / "source.pdf", Path(directory) / "cover"
        source.write_bytes(data)
        subprocess.run([executable, "-f", "1", "-singlefile", "-scale-to", "480", "-png", str(source), str(target)],
            check=True, timeout=20, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            preexec_fn=_limits, env={**os.environ, "OMP_NUM_THREADS": "1"})
        return _png(target.with_suffix(".png").read_bytes())


def get_preview(account, sender, name):
    _account(account)
    if not isinstance(name, str) or not name or len(name) > 140 or not isinstance(sender, str) or len(sender) > 200:
        frappe.throw("Invalid message.")
    # Query filters (including permission-query hooks) and document permissions
    # are both required, matching the incoming history endpoint's boundary.
    if not frappe.get_list("WhatsApp Message", filters={"name": name,
            "type": "Incoming", "whatsapp_account": account}, fields=["name"], limit_page_length=1):
        frappe.throw("Message is outside this chat or is not permitted.", frappe.PermissionError)
    source = frappe.get_doc("WhatsApp Message", name)
    source.check_permission("read")
    if source.type != "Incoming" or source.whatsapp_account != account or _sender_key(source.get("from")) != _sender_key(sender):
        frappe.throw("Message is outside this chat.", frappe.PermissionError)
    owned = _owned_file(source.attach, source)
    if not owned:
        return dict(UNAVAILABLE)
    kind = "pdf" if (source.intake_media_mime or "").lower() == "application/pdf" or owned[1].suffix.lower() == ".pdf" else "image"
    created = None
    savepoint = "inbox_preview"
    try:
        # Serialize generation across requests until commit/rollback; no source mutation.
        locked = frappe.db.sql("SELECT * FROM `tabWhatsApp Message` WHERE name=%s FOR UPDATE", source.name, as_dict=True)
        source.update(locked[0])
        source.check_permission("read")
        if source.type != "Incoming" or source.whatsapp_account != account or _sender_key(source.get("from")) != _sender_key(sender):
            return dict(UNAVAILABLE)
        owned = _owned_file(source.attach, source)
        if not owned or owned[1].stat().st_size > MAX_BYTES:
            return dict(UNAVAILABLE)
        with owned[1].open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        if not data or len(data) > MAX_BYTES:
            return dict(UNAVAILABLE)
        kind = "pdf" if data.startswith(b"%PDF-") else "image"
        key = hashlib.sha256((RENDERER + source.name).encode() + data).hexdigest()
        cache_name = "wa-preview-" + key
        cached = frappe.db.get_value("File", cache_name, ["file_url", "attached_to_doctype", "attached_to_name", "is_private"], as_dict=True)
        if cached:
            if cached.attached_to_doctype != "WhatsApp Message" or cached.attached_to_name != source.name or not cached.is_private:
                return dict(UNAVAILABLE)
            reference = _owned_file(cached.file_url, source)
            if not reference or not frappe.get_doc("File", cache_name).has_permission("read"):
                return dict(UNAVAILABLE)
            with Image.open(reference[1]) as image:
                width, height = image.size
            return dict(available=True, url=reference[0]["url"], width=width, height=height, kind=kind)
        content, width, height = _render(data, kind)
        frappe.db.savepoint(savepoint)
        created = frappe.get_doc(dict(doctype="File", file_name=cache_name + ".png", is_private=1,
            attached_to_doctype="WhatsApp Message", attached_to_name=source.name, content=content))
        # Derived previews must not add chat activity, comments or notifications.
        created.create_attachment_record = lambda: None
        created.insert(ignore_permissions=True, set_name=cache_name)
        reference = _owned_file(created.file_url, source)
        if not reference:
            raise ValueError("Preview unavailable")
        # GET normally rolls back; commit only this derived file on successful requests.
        frappe.local.flags.commit = True
        return dict(available=True, url=reference[0]["url"], width=width, height=height, kind=kind)
    except Exception:
        if created is not None:
            frappe.db.rollback(save_point=savepoint)
            created.on_rollback()
        return dict(UNAVAILABLE)
