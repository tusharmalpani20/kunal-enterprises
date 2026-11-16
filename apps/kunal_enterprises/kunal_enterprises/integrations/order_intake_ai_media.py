"""Bounded local attachments for model input; links are never downloaded here."""
import warnings
from io import BytesIO
from pathlib import Path
from time import monotonic

import frappe
from PIL import Image
from pydantic_ai import BinaryContent
from pypdf import PdfReader

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_JOB_BYTES = 16 * 1024 * 1024
MAX_JOB_FILES = 10
MAX_IMAGE_PIXELS = 20_000_000
MEDIA_TYPES = {"image", "document", "audio", "video", "sticker"}
IMAGE_MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def build_media(messages, config, deadline=None, metadata=None):
	"""Return model binary inputs and per-message review warnings, never raw exceptions.

	Only private File records attached to the same WhatsApp message may leave
	this site. Unsupported, over-limit and unavailable evidence stays manual.
	"""
	inputs, notes = {}, {}
	size, count = 0, 0
	for message in messages:
		name, url = message.get("name"), message.get("attach")
		if deadline is not None and monotonic() >= deadline:
			if url or (message.get("intake_original_type") or message.get("content_type")) in MEDIA_TYPES:
				notes[name] = ["Attachment preparation reached the job time limit; retained for manual review."]
			continue
		if not url:
			if (message.get("intake_original_type") or message.get("content_type")) in MEDIA_TYPES:
				notes[name] = ["Attachment has not been downloaded; review the original media manually."]
			continue
		try:
			if not url.startswith("/private/files/"):
				raise ValueError("Only local private attachments are eligible")
			file = frappe.db.get_value("File", {"file_url": url, "is_private": 1,
				"attached_to_doctype": "WhatsApp Message", "attached_to_name": name},
				["name", "file_url", "is_private", "attached_to_doctype", "attached_to_name"], as_dict=True)
			if not file or not file.get("is_private") or file.get("attached_to_doctype") != "WhatsApp Message" or file.get("attached_to_name") != name or file.get("file_url") != url:
				raise ValueError("Attachment ownership unavailable")
			root = Path(frappe.get_site_path("private", "files")).resolve()
			path = (root / url.removeprefix("/private/files/")).resolve()
			if not path.is_relative_to(root) or path == root:
				raise ValueError("Attachment outside private files")
			if count >= MAX_JOB_FILES:
				notes[name] = ["Attachment exceeds the automatic file/byte budget; retained for manual review."]
				continue
			# Parsing rejected PDFs/images still consumes resources. Count each
			# attempted private file and every byte read, not only accepted inputs.
			count += 1
			length = path.stat().st_size
			if length > MAX_FILE_BYTES or size + length > MAX_JOB_BYTES:
				notes[name] = ["Attachment exceeds the automatic file/byte budget; retained for manual review."]
				continue
			# Limit the read as well as stat: the file could grow between the two.
			with path.open("rb") as stream:
				data = stream.read(min(MAX_FILE_BYTES, MAX_JOB_BYTES - size) + 1)
			size += len(data)
			if len(data) > MAX_FILE_BYTES or size > MAX_JOB_BYTES:
				raise ValueError("Attachment changed beyond byte budget")
			if deadline is not None and monotonic() >= deadline:
				notes[name] = ["Attachment preparation reached the job time limit; retained for manual review."]
				continue
			file_metadata = {}
			mime, note = _inspect(data, config, metadata=file_metadata)
			if metadata is not None and file_metadata:
				metadata[name] = file_metadata
			if note:
				notes[name] = [note]
				continue
			inputs[name] = [BinaryContent(data, media_type=mime, identifier=name)]
		except Exception:
			# Exceptions can contain private paths, source text or parser payloads.
			notes[name] = ["Attachment could not be safely read; retained for manual review."]
	return inputs, notes


def _inspect(data, config, metadata=None):
	if data.startswith(b"%PDF-"):
		reader = PdfReader(BytesIO(data), strict=True)
		if reader.is_encrypted:
			return None, "Encrypted PDF requires manual review."
		pages = len(reader.pages)
		if metadata is not None:
			metadata['page_count'] = pages
		if not pages or pages > int(config.get("pdf_page_limit") or 10):
			return None, f"PDF has {pages} pages and exceeds the configured automatic page limit; retained for manual review."
		return "application/pdf", None
	with warnings.catch_warnings():
		warnings.simplefilter("error", Image.DecompressionBombWarning)
		with Image.open(BytesIO(data)) as image:
			if image.width * image.height > MAX_IMAGE_PIXELS or image.format not in IMAGE_MIMES or getattr(image, "n_frames", 1) != 1:
				return None, "Unsupported or oversized image requires manual review."
			mime = IMAGE_MIMES[image.format]
			image.verify()
		return mime, None
