"""Local token estimates and conservative reply-thread batching.

The estimate is a preflight guard, not a provider bill: framing and media have
reserves because provider/model tokenization varies. Provider usage remains the
source of truth. No counting request is sent to an AI provider.
"""
import json
from functools import lru_cache


@lru_cache(maxsize=1)
def _encoding():
	import tiktoken
	return tiktoken.get_encoding("o200k_base")


def estimate_input_tokens(common, instructions, schema, payload, media):
	parts = [common, instructions, json.dumps(payload, ensure_ascii=False, default=str),
		json.dumps(schema.model_json_schema(), ensure_ascii=False)]
	for name, binaries in media.items():
		if binaries:
			parts.append("Attachments from message " + name)
	# Covers native-schema/message framing and leaves room for short corrective
	# validation feedback. Images have model-specific costs; do not count bytes
	# as tokens or send base64 through the text tokenizer.
	return sum(len(_encoding().encode(part, disallowed_special=())) for part in parts) + 512 + sum(
		2048 * len(binaries) for binaries in media.values())


def _threads(payload):
	messages = payload["messages"]
	parents = {row["name"]: row["name"] for row in messages}
	aliases = {}
	for row in messages:
		for value in (row["name"], row.get("message_id")):
			if value:
				aliases.setdefault(value, set()).add(row["name"])

	def root(name):
		while parents[name] != name:
			parents[name] = parents[parents[name]]
			name = parents[name]
		return name

	def union(names):
		if names:
			first = root(names[0])
			for name in names[1:]:
				parents[root(name)] = first

	anchored, external = set(), {}
	for row in messages:
		reply = row.get("reply_to_message_id") or (row.get("reply_context") or {}).get("message_id")
		if not reply:
			continue
		local = aliases.get(reply, set())
		if len(local) == 1:
			names = [row["name"], next(iter(local))]
			union(names)
			anchored.update(names)
		elif not local:
			external.setdefault(reply, []).append(row["name"])
			anchored.add(row["name"])
	for names in external.values():
		union(names)
	for request in payload.get("open_requests", []):
		names = [name for name in request.get("source_messages", []) if name in parents]
		union(names)
	# An unthreaded party/warehouse/quantity line might belong to any nearby
	# source. Keep the whole chat indivisible rather than silently detach it.
	if any(row["name"] not in anchored for row in messages):
		return [messages]
	components = {}
	for row in messages:
		components.setdefault(root(row["name"]), []).append(row)
	return list(components.values())


def grouping_batches(config, payload, media, common, instructions, schema):
	def fits(value, binaries):
		return estimate_input_tokens(common, instructions, schema, value, binaries) <= config.max_input_tokens
	if fits(payload, media):
		return [(payload, media)], []
	batches, unresolved = [], []
	for rows in _threads(payload):
		names = {row["name"] for row in rows}
		batch = dict(payload, messages=rows)
		binaries = {name: data for name, data in media.items() if name in names}
		# Keep bounded open summaries and business/learning context intact;
		# dropping them to squeeze under a limit changes grouping semantics.
		if fits(batch, binaries):
			batches.append((batch, binaries))
		else:
			unresolved.extend(row["name"] for row in rows)
	return batches, unresolved
