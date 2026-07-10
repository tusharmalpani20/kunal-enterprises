"""Backfill stable snapshot identities for records created before GUID-based sync."""

import frappe


def execute():
	if not frappe.db.has_column("Tally Stock Snapshot", "tally_snapshot_key"):
		return

	collisions = frappe.db.sql(
		"""
		SELECT CONCAT(item.tally_guid, ':', godown.tally_guid) AS snapshot_key
		FROM `tabTally Stock Snapshot` snapshot
		INNER JOIN `tabTally Item` item ON item.name = snapshot.item
		INNER JOIN `tabTally Godown` godown ON godown.name = snapshot.godown
		WHERE COALESCE(snapshot.tally_snapshot_key, '') = ''
		GROUP BY item.tally_guid, godown.tally_guid
		HAVING COUNT(*) > 1
		""",
		pluck=True,
	)
	if collisions:
		frappe.throw(
			"Cannot backfill Tally Stock Snapshot keys; duplicate item/godown pairs: "
			+ ", ".join(collisions[:10])
		)

	existing_collisions = frappe.db.sql(
		"""
		SELECT CONCAT(item.tally_guid, ':', godown.tally_guid) AS snapshot_key
		FROM `tabTally Stock Snapshot` snapshot
		INNER JOIN `tabTally Item` item ON item.name = snapshot.item
		INNER JOIN `tabTally Godown` godown ON godown.name = snapshot.godown
		INNER JOIN `tabTally Stock Snapshot` keyed
			ON keyed.tally_snapshot_key = CONCAT(item.tally_guid, ':', godown.tally_guid)
		WHERE COALESCE(snapshot.tally_snapshot_key, '') = ''
		""",
		pluck=True,
	)
	if existing_collisions:
		frappe.throw(
			"Cannot backfill Tally Stock Snapshot keys; keys already exist: "
			+ ", ".join(existing_collisions[:10])
		)

	frappe.db.sql(
		"""
		UPDATE `tabTally Stock Snapshot` snapshot
		INNER JOIN `tabTally Item` item ON item.name = snapshot.item
		INNER JOIN `tabTally Godown` godown ON godown.name = snapshot.godown
		SET snapshot.tally_snapshot_key = CONCAT(item.tally_guid, ':', godown.tally_guid)
		WHERE COALESCE(snapshot.tally_snapshot_key, '') = ''
			AND COALESCE(item.tally_guid, '') != ''
			AND COALESCE(godown.tally_guid, '') != ''
		"""
	)
