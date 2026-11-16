"""Durable, restricted model-call evidence with independent short transactions."""
import base64
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
import re
from time import monotonic
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from kunal_enterprises.integrations.order_intake_ai_costs import parse_usage, estimate_cost

RUN = "Order Intake AI Run"
CALL = "Order Intake AI Call"
PAYLOAD_FIELDS = ("semantic_input", "request_json", "response_json", "parsed_response", "validation_json")
SECRET_KEYS = {"api_key", "authorization", "access_token", "token", "password", "intake_app_secret", "webhook_verify_token"}


class LoggingFailure(Exception):
	pass


class LoggingAlreadyStarted(Exception):
	pass


def sanitized(value, secrets=()):
	"""Keep complete textual evidence; replace credentials and binary contents."""
	if isinstance(value, bytes):
		return {"binary_reference": True, "sha256": hashlib.sha256(value).hexdigest(), "size_bytes": len(value)}
	if isinstance(value, str):
		if value.startswith("data:") and ";base64," in value:
			prefix, encoded = value.split(";base64,", 1)
			try:
				result = sanitized(base64.b64decode(encoded, validate=True), secrets)
				result["media_type"] = prefix[5:]
				return result
			except ValueError:
				return {"binary_reference": True, "invalid_encoding": True}
		for secret in secrets:
			if secret:
				value = value.replace(secret, "[REDACTED]")
		value = re.sub(r"\bsk-[A-Za-z0-9_-]{16,}", "[REDACTED]", value)
		return re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}", "Bearer [REDACTED]", value)
	if isinstance(value, dict):
		return {str(key): "[REDACTED]" if str(key).lower() in SECRET_KEYS else sanitized(item, secrets) for key, item in value.items()}
	if isinstance(value, (list, tuple, set)):
		return [sanitized(item, secrets) for item in value]
	if is_dataclass(value):
		return {item.name: sanitized(getattr(value, item.name), secrets) for item in fields(value)}
	if hasattr(value, "model_dump"):
		return sanitized(value.model_dump(), secrets)
	if isinstance(value, float) and not math.isfinite(value):
		return {"non_finite_number": str(value)}
	if isinstance(value, (datetime, Decimal)):
		return str(value)
	if value is None or isinstance(value, (int, float, bool)):
		return value
	return sanitized(str(value), secrets)


def _json(value, secrets=()):
	return json.dumps(sanitized(value, secrets), ensure_ascii=False, default=str, allow_nan=False)


class Writer:
	def __init__(self, independent, secrets=()):
		self.independent = independent
		self.secrets = secrets

	def safe_values(self, values):
		result = {}
		for key, value in values.items():
			if isinstance(value, str) and key not in {"name", "parent", "parenttype", "parentfield"}:
				value = sanitized(value, self.secrets)
				if not isinstance(value, str):
					value = _json(value)
			result[key] = value
		return result

	@contextmanager
	def transaction(self):
		if not self.independent:
			class Cursor:
				def execute(self, sql, values):
					self.rows = frappe.db.sql(sql, values)
					return self.rows
				def fetchall(self):
					return self.rows
			yield Cursor()
			return
		connection = frappe.db.get_connection()
		try:
			connection.autocommit(False)
			with connection.cursor() as cursor:
				cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
				cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
				yield cursor
			connection.commit()
		except Exception:
			connection.rollback()
			raise
		finally:
			connection.close()

	def insert(self, cursor, table, values):
		values = self.safe_values(values)
		columns = tuple(values)
		cursor.execute(f"INSERT INTO `tab{table}` ({','.join('`' + key + '`' for key in columns)}) VALUES ({','.join(['%s'] * len(columns))})", tuple(values[key] for key in columns))

	def update(self, cursor, table, name, values):
		values = self.safe_values(values)
		cursor.execute(f"UPDATE `tab{table}` SET {','.join('`' + key + '`=%s' for key in values)} WHERE name=%s", (*values.values(), name))


class RunRecorder:
	def __init__(self, snapshot, config, run_key, independent=True):
		self.name = "AIRUN-" + hashlib.sha256(str(run_key).encode()).hexdigest()[:32]
		self.secrets = (getattr(config, "_intake_api_key", None),)
		self.writer = Writer(independent, self.secrets)
		self.config = config
		self.calls, self.stages = [], []
		self.started = monotonic()
		self.actor = frappe.session.user or "Administrator"
		self.current_call = None
		self.prices = [sanitized(row.as_dict() if hasattr(row, "as_dict") else row) for row in (getattr(config, "pricing", None) or [])]
		stamp = now_datetime()
		values = dict(name=self.name, run_key=run_key, creation=stamp, modified=stamp, owner=self.actor, modified_by=self.actor,
			docstatus=0, idx=0, currency="USD", status="Running", started_at=stamp, anchor_message=snapshot.get("anchor"),
			whatsapp_account=snapshot.get("whatsapp_account"), sender=snapshot.get("sender"), actor=self.actor,
			provider=config.provider, grouping_model=config.grouping_model, extraction_model=config.extraction_model,
			reasoning_effort=config.reasoning_effort, context_digest=snapshot.get("context_digest"),
			source_messages=_json([row["name"] for row in snapshot.get("messages", [])]), input_snapshot=_json(snapshot, self.secrets),
			wire_attempts=0, unknown_usage_calls=0, unknown_cost_calls=0, cost_complete=0)
		try:
			with self.writer.transaction() as cursor:
				self.writer.insert(cursor, RUN, values)
		except Exception as error:
			if error.args and error.args[0] == 1062:
				raise LoggingAlreadyStarted() from None
			raise LoggingFailure("The AI run log could not be created; no provider call was made.") from None

	@classmethod
	def start(cls, snapshot, config, run_key, independent=True):
		return cls(snapshot, config, run_key, independent)

	def _pricing(self, model, tokens=None, service_tier="default"):
		rows = [row for row in self.prices if row.get("provider") == self.config.provider and row.get("model") == model and row.get("rates_confirmed")]
		if tokens is None:
			return rows
		rows = [row for row in rows if (row.get("service_tier") or "default") == (service_tier or "default")]
		valid = []
		for row in rows:
			try:
				if int(row.get("max_context_tokens") or 0) >= tokens:
					valid.append(row)
			except (TypeError, ValueError, OverflowError):
				continue
		rows = sorted(valid, key=lambda row: int(row["max_context_tokens"]))
		if not rows or sum(row["max_context_tokens"] == rows[0]["max_context_tokens"] for row in rows) != 1:
			return None
		return rows[0]

	def capture_snapshot(self, snapshot):
		with self.writer.transaction() as cursor:
			self.writer.update(cursor, RUN, self.name, dict(input_snapshot=_json(snapshot, self.secrets),
				source_messages=_json([row["name"] for row in snapshot.get("messages", [])]),
				context_digest=snapshot.get("context_digest")))

	def _totals(self):
		known = [call for call in self.calls if call.get("usage_known")]
		costs = [call for call in self.calls if call.get("cost_known")]
		provider_costs = [call for call in self.calls if call.get("provider_cost_known")]
		values = dict(wire_attempts=len(self.calls), usage_known_calls=len(known), unknown_usage_calls=len(self.calls) - len(known),
			cost_known_calls=len(costs), unknown_cost_calls=len(self.calls) - len(costs), cost_complete=bool(self.calls) and len(costs) == len(self.calls),
			estimated_cost_usd=sum((call.get("estimated_cost_usd", Decimal(0)) for call in costs), Decimal(0)),
			provider_cost_known_calls=len(provider_costs), provider_cost_usd=sum((call.get("provider_cost_usd", Decimal(0)) for call in provider_costs), Decimal(0)))
		for key in ("input_tokens", "output_tokens", "cached_input_tokens", "cache_write_tokens", "reasoning_tokens"):
			# Preserve every valid reported counter even when another counter is
			# missing. The unknown-call counts still identify incomplete totals.
			values[key] = sum(call.get(key, 0) for call in self.calls)
		return values

	def _save_call(self, index):
		try:
			with self.writer.transaction() as cursor:
				self.writer.update(cursor, CALL, self.calls[index]["name"], self.calls[index])
				self.writer.update(cursor, RUN, self.name, self._totals())
		except Exception:
			raise LoggingFailure("AI call logging is unavailable; the run remains incomplete for review.") from None

	def start_call(self, stage, model, semantic_input, parameters, settings):
		index = len(self.calls)
		stamp = now_datetime()
		call = dict(name=uuid4().hex, creation=stamp, modified=stamp, owner=self.actor, modified_by=self.actor, docstatus=0,
			idx=index + 1, parent=self.name, parenttype=RUN, parentfield="calls", stage=stage, sequence=index + 1,
			provider=self.config.provider, model=model, reasoning_effort=self.config.reasoning_effort, state="Running", started_at=stamp,
			usage_known=0, cost_known=0, provider_cost_known=0,
			semantic_input=_json(dict(messages=semantic_input, parameters=parameters, settings=settings), self.secrets),
			pricing_json=_json(self._pricing(model)))
		try:
			with self.writer.transaction() as cursor:
				self.writer.insert(cursor, CALL, call)
				self.writer.update(cursor, RUN, self.name, dict(wire_attempts=index + 1, unknown_usage_calls=index + 1 - sum(bool(c.get("usage_known")) for c in self.calls), unknown_cost_calls=index + 1 - sum(bool(c.get("cost_known")) for c in self.calls), cost_complete=0))
		except Exception:
			raise LoggingFailure("The AI call log could not be started; no provider call was made.") from None
		self.calls.append(call)
		self.current_call = index
		return index

	def wire_request(self, index, request):
		self.calls[index]["request_json"] = _json(request, self.secrets)
		self._save_call(index)

	def wire_response(self, index, body, status_code, provider_request_id=None):
		call = self.calls[index]
		call.update(response_json=_json(body, self.secrets), http_status=status_code,
			provider_request_id=str(provider_request_id)[:140] if provider_request_id is not None else None)
		usage = parse_usage(body.get("usage") if isinstance(body, dict) else None)
		call["usage_json"] = _json(body.get("usage") if isinstance(body, dict) else None, self.secrets)
		call.update(usage)
		tier = body.get("service_tier") if isinstance(body, dict) else "default"
		price = self._pricing(call["model"], usage["input_tokens"], tier)
		call["pricing_json"] = _json(dict(candidates=self._pricing(call["model"]), selected=price,
			input_tokens=usage["input_tokens"], service_tier=tier or "default"))
		known, cost = estimate_cost(usage, price, tier)
		call.update(cost_known=known, estimated_cost_usd=cost)
		self._save_call(index)

	def finish_call(self, index, response=None, error_note=None):
		call = self.calls[index]
		if response is not None:
			call["parsed_response"] = _json(response, self.secrets)
			if not call.get("response_json"):
				# FunctionModel and other non-HTTP adapters have no reliable raw usage-presence signal.
				call["response_json"] = call["parsed_response"]
		call.update(state="Error" if error_note else "Responded", error_note=error_note,
			finished_at=now_datetime(), duration_seconds=(now_datetime() - call["started_at"]).total_seconds())
		self._save_call(index)

	def validation_feedback(self, error):
		if self.current_call is not None:
			self.calls[self.current_call]["validation_json"] = _json(error, self.secrets)
			self._save_call(self.current_call)

	def stage_result(self, stage, result=None, error=None):
		self.stages.append(dict(stage=stage, result=sanitized(result, self.secrets), error=error))
		try:
			with self.writer.transaction() as cursor:
				self.writer.update(cursor, RUN, self.name, dict(stages_json=_json(self.stages, self.secrets)))
		except Exception:
			raise LoggingFailure("The stage result could not be logged; retained calls need review.") from None

	def stage_failure(self, stage, error):
		chain, current = [], error
		for _ in range(6):
			if current is None:
				break
			entry = dict(type=type(current).__name__)
			errors = getattr(current, "errors", None)
			if callable(errors):
				try:
					entry["validation_errors"] = errors(include_input=True)
				except TypeError:
					entry["validation_errors"] = errors()
			elif errors is not None:
				entry["validation_errors"] = errors
			elif type(current).__name__ not in {"ModelHTTPError", "APIStatusError", "AuthenticationError", "APIConnectionError"}:
				entry["message"] = str(current)
			chain.append(entry)
			current = current.__cause__ or current.__context__
		self.validation_feedback(chain)
		self.stage_result(stage, error=sanitized(chain, self.secrets))

	def finish(self, status, result=None, note="", publication_pending=False):
		if publication_pending and self.writer.independent:
			self._finish("Awaiting Commit", result, note)
			frappe.db.after_commit.add(lambda: self._finish(status, result, note))
			frappe.db.after_rollback.add(lambda: self._finish("Rolled Back", {}, "Draft publication was rolled back; spent provider calls are retained."))
		else:
			self._finish(status, result, note)

	def _finish(self, status, result, note):
		result = result or {}
		values = dict(status=status, finished_at=now_datetime(), duration_seconds=monotonic() - self.started,
			request_ids=_json(list(dict.fromkeys(result.get("created", []) + result.get("proposed", [])))),
			created_request_count=len(result.get("created", [])), updated_request_count=len(result.get("proposed", [])),
			result_json=_json(result, self.secrets), error_note=note, **self._totals())
		try:
			with self.writer.transaction() as cursor:
				for call in self.calls:
					self.writer.update(cursor, CALL, call["name"], call)
				self.writer.update(cursor, RUN, self.name, values)
		except Exception:
			raise LoggingFailure("AI run finalization failed; retained call logs need review.") from None
