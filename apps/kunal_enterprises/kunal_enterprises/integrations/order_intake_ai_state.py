"""AI-owned attention markers, kept separate from capture and media warnings."""
FAILURE_WARNING = "AI: Processing needs attention; original messages are retained."
UNRESOLVED_WARNING = "AI: Some content remains unresolved; review original messages and linked drafts."
QUEUE_WARNING = "AI: This context could not be queued; review and prepare this sender again."
REVIEW_PREFIX = "AI: Needs review: "
OWNED_WARNINGS = {FAILURE_WARNING, UNRESOLVED_WARNING, QUEUE_WARNING}
TRANSFER_NOTE = "Retry moved to a newer sender context; older sources remain available for review."


def coverage_attention(message, unresolved, reasons=None):
	"""Clear only warnings resolved by this AI result; other stages own theirs."""
	previous = (message.get("intake_attention") or "").splitlines()
	owned = lambda line: line in OWNED_WARNINGS or line.startswith(REVIEW_PREFIX)
	remaining = [line for line in previous if not owned(line)]
	values = {}
	if unresolved:
		if reasons:
			# Keep each reason on one line; source text cannot inject fake markers.
			clean = list(dict.fromkeys(" ".join(str(reason).split())[:300] for reason in reasons if str(reason or "").strip()))
			remaining.extend(REVIEW_PREFIX + reason for reason in clean[:3])
			if not clean:
				remaining.append(UNRESOLVED_WARNING)
			if len(clean) > 3:
				remaining.append(REVIEW_PREFIX + "More details are listed on the intake request.")
		else:
			remaining.append(UNRESOLVED_WARNING)
		values["intake_status"] = "Needs Attention"
	if remaining != previous:
		values["intake_attention"] = "\n".join(remaining)
	if (not unresolved and not remaining and any(owned(line) for line in previous)
		and message.get("intake_status") == "Needs Attention"
		and message.get("intake_prepare_state") != "Needs Attention"
		and message.get("intake_media_state") != "Failed"):
		values["intake_status"] = "New"
	return values
