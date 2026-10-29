"""Shared execution limits for the serialized Tally pipeline."""


TALLY_JOB_TIMEOUT_SECONDS = 3600
RECONCILIATION_LOCK_SECONDS = 3900

# Shared by voucher import and retention so tied refresh times select the same state.
VOUCHER_CHECKPOINT_ORDER = "source_refreshed_at desc, creation desc, name desc"


if RECONCILIATION_LOCK_SECONDS <= TALLY_JOB_TIMEOUT_SECONDS:
	raise RuntimeError("The reconciliation lock lease must outlive the Tally worker timeout")
