"""Validate a read of the existing mirror without claiming Tally completeness."""

from datetime import date


def validate_sync_metadata(config, latest, completed, failure_id, company):
	if not company or config.get("Company Name") != company:
		raise ValueError("Configured Tally company does not match the PostgreSQL mirror")
	if not latest or latest.get("status") != "success" or not completed:
		raise ValueError("A successful loader import is required before accepting voucher changes")
	if int(failure_id or 0) > int(completed["id"]):
		raise ValueError(
			"A loader failure has not been followed by a completed import; a no-change ping is insufficient"
		)
	if not completed.get("finished_at"):
		raise ValueError("Loader import completion time is missing")
	try:
		transaction = int(config["Last AlterID Transaction"])
		inventory = int(config["Last Voucher Inventory AlterID"])
		start = date.fromisoformat(config["Period From"])
		end = date.fromisoformat(config["Period To"])
	except (KeyError, TypeError, ValueError) as error:
		raise ValueError("Mirror progress markers or export period are missing or invalid") from error
	if transaction < 0 or inventory < transaction or start > end:
		raise ValueError("Inventory refresh is behind voucher headers or the export period is invalid")
	return transaction


def validate_snapshot(state, rows, company, allowed_types):
	if not company or not allowed_types:
		raise ValueError(
			"Configure tally_source_company and tally_fulfillment_voucher_type_guids before importing vouchers"
		)
	if state.get("read_complete") is not True or state.get("source_kind") != "postgres_mirror":
		raise ValueError("A complete database read from the existing PostgreSQL mirror is required")
	if (
		state.get("source_company") != company
		or not state.get("snapshot_id")
		or not state.get("completed_at")
	):
		raise ValueError("Mirror observation company or metadata is invalid")
	if state.get("voucher_count") != len(rows):
		raise ValueError("Mirror observation row count does not match")
	seen = set()
	for row in rows:
		guid = row.get("guid")
		if not guid or guid in seen or row.get("source_company") != company:
			raise ValueError("Mirror contains missing, duplicate, or wrong-company identities")
		seen.add(guid)
		if type(row.get("alterid")) is not int or row["alterid"] < 0:
			raise ValueError("Mirror contains an invalid AlterID")
		if row.get("inactive"):
			raise ValueError("The existing mirror cannot establish Tally cancellation or deletion")
		if not isinstance(row.get("lines"), list):
			raise ValueError("Mirror inventory must be a list")
