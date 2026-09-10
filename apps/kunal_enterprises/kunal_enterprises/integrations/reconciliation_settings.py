"""Shared execution limits for the serialized Tally pipeline."""


TALLY_JOB_TIMEOUT_SECONDS = 3600
RECONCILIATION_LOCK_SECONDS = 3900


if RECONCILIATION_LOCK_SECONDS <= TALLY_JOB_TIMEOUT_SECONDS:
	raise RuntimeError("The reconciliation lock lease must outlive the Tally worker timeout")
