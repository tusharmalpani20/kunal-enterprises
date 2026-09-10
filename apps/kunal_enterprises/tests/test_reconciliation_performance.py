import json
import unittest
from collections import defaultdict
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kunal_enterprises.cron import reconciliation_engine as engine
from kunal_enterprises.cron.tally_sync import _master_reconciliation_fingerprint
from kunal_enterprises.integrations import reconciliation_queue, voucher_snapshot
from kunal_enterprises.integrations.reconciliation_queue import _order_inputs, _work_problem
from kunal_enterprises.integrations.reconciliation_settings import (
	RECONCILIATION_LOCK_SECONDS,
	TALLY_JOB_TIMEOUT_SECONDS,
)
from kunal_enterprises.integrations.tally_postgres import _full_reconciliation_completed_today


def voucher(name, order=None, pending=None, status="Active"):
	return SimpleNamespace(
		name=name,
		tally_guid="guid-" + name,
		order_number=order,
		reference_number=None,
		source_pending_references=json.dumps(pending or []),
		source_status=status,
	)


class ReconciliationScopeTests(unittest.TestCase):
	def test_lock_lease_outlives_worker_timeout(self):
		self.assertGreater(RECONCILIATION_LOCK_SECONDS, TALLY_JOB_TIMEOUT_SECONDS)

	def test_malformed_work_item_forces_full_fallback(self):
		row = SimpleNamespace(
			generation=1,
			full_reconciliation=0,
			reference_number=None,
			voucher=None,
		)
		self.assertEqual(_work_problem([row], 1, 1000), "malformed_work_item")

	def test_only_a_completed_nightly_pass_suppresses_the_guarded_retry(self):
		manual = SimpleNamespace(
			started_at="2026-09-10 01:00:00",
			source_metadata=json.dumps({"mode": "full", "trigger": None}),
		)
		nightly = SimpleNamespace(
			started_at="2026-09-10 02:17:00",
			source_metadata=json.dumps({"mode": "full", "trigger": "nightly_safety"}),
		)
		with (
			patch("kunal_enterprises.integrations.tally_postgres.nowdate", return_value="2026-09-10"),
			patch("kunal_enterprises.integrations.tally_postgres.frappe.get_all", return_value=[manual]),
		):
			self.assertFalse(_full_reconciliation_completed_today())
		with (
			patch("kunal_enterprises.integrations.tally_postgres.nowdate", return_value="2026-09-10"),
			patch("kunal_enterprises.integrations.tally_postgres.frappe.get_all", return_value=[nightly]),
		):
			self.assertTrue(_full_reconciliation_completed_today())

	def test_reference_scope_expands_the_complete_multi_hop_chain(self):
		rows = [
			voucher("one", "A", ["B"]),
			voucher("two", "B", ["C"]),
			voucher("three", "C"),
			voucher("unrelated", "Z"),
		]
		refs_for_voucher, by_reference = engine._reference_graph(rows)

		selected_vouchers, selected_references = engine._expand_scope(
			set(), {"A"}, refs_for_voucher, by_reference
		)

		self.assertEqual(selected_vouchers, {"one", "two", "three"})
		self.assertEqual(selected_references, {"A", "B", "C"})

	def test_unverified_voucher_blocks_the_complete_connected_chain(self):
		rows = [voucher("one", "A", ["B"]), voucher("two", "B", ["C"], "Unverified")]
		refs_for_voucher, _ = engine._reference_graph(rows)

		blocked = engine._blocked_references(rows, refs_for_voucher, defaultdict(list))

		self.assertEqual(blocked, {"A", "B", "C"})

	def test_legacy_reference_blocks_connected_current_vouchers(self):
		rows = [voucher("one", "A", ["B"]), voucher("two", "B")]
		refs_for_voucher, _ = engine._reference_graph(rows)

		blocked = engine._blocked_references(rows, refs_for_voucher, {"A": [object()]})

		self.assertEqual(blocked, {"A", "B"})

	def test_legacy_pending_references_join_the_blocked_component(self):
		rows = [voucher("current", "B", ["C"])]
		refs_for_voucher, _ = engine._reference_graph(rows)
		legacy = voucher("legacy", pending=["B"])
		legacy.tally_guid = None

		blocked = engine._blocked_references(rows, refs_for_voucher, {"A": [legacy]})

		self.assertEqual(blocked, {"A", "B", "C"})

	def test_legacy_voucher_seed_expands_from_its_historical_reference(self):
		legacy = voucher("legacy")
		legacy.tally_guid = None
		legacy.reference_number = "A"
		rows = [legacy, voucher("current", "A")]
		refs_for_voucher, by_reference = engine._reference_graph(rows)

		selected_vouchers, selected_references = engine._expand_scope(
			{"legacy"}, set(), refs_for_voucher, by_reference
		)

		self.assertEqual(selected_vouchers, {"legacy", "current"})
		self.assertEqual(selected_references, {"A"})

	def test_legacy_pending_reference_bridges_incremental_scope(self):
		legacy = voucher("legacy", pending=["B"])
		legacy.tally_guid = None
		legacy.reference_number = "A"
		current = voucher("current", "B")
		refs_for_voucher, by_reference = engine._reference_graph([current])
		legacy_by_reference = {"A": [legacy], "B": [legacy]}
		scope_by_reference = engine._scope_graph_with_legacy(
			by_reference,
			refs_for_voucher,
			legacy_by_reference,
		)

		selected_vouchers, selected_references = engine._expand_scope(
			set(), {"A"}, refs_for_voucher, scope_by_reference
		)

		self.assertEqual(selected_vouchers, {"legacy", "current"})
		self.assertEqual(selected_references, {"A", "B"})

	def test_malformed_pending_references_fail_closed(self):
		row = voucher("bad")
		row.source_pending_references = "not-json"
		with patch.object(engine.frappe, "throw", side_effect=ValueError("invalid")):
			with self.assertRaisesRegex(ValueError, "invalid"):
				engine._reference_graph([row])

	def test_snapshot_apply_rejects_non_list_pending_references(self):
		row = SimpleNamespace(name="bad", source_pending_references='{"A": true}')
		with patch.object(voucher_snapshot.frappe, "throw", side_effect=ValueError("invalid")):
			with self.assertRaisesRegex(ValueError, "invalid"):
				voucher_snapshot._held_references(row)

	def test_invalidation_hook_rejects_malformed_pending_references(self):
		row = SimpleNamespace(
			name="bad",
			get=lambda field, default=None: '{"A": true}' if field == "source_pending_references" else default,
		)
		fake_frappe = SimpleNamespace(
			parse_json=json.loads,
			throw=Mock(side_effect=ValueError("invalid")),
		)
		with patch.object(reconciliation_queue, "frappe", fake_frappe):
			with self.assertRaisesRegex(ValueError, "invalid"):
				reconciliation_queue._pending_references(row)

	def test_order_invalidation_inputs_are_semantic_and_stable(self):
		order = SimpleNamespace(
			get=lambda field, default=None: getattr(order, field, default),
			portal_reference_number="KE-1",
			customer="CUSTOMER-1",
			status="Placed",
			items=[SimpleNamespace(item="ITEM-1", requested_quantity=4)],
		)
		self.assertEqual(_order_inputs(order), ("KE-1", "CUSTOMER-1", "Placed", (("ITEM-1", "4"),)))

	def test_master_fingerprint_is_order_independent_but_change_sensitive(self):
		first = {
			"items": [
				{"item_name": "A", "tally_guid": "1", "uom": "PCS", "is_active": 1},
				{"item_name": "B", "tally_guid": "2", "uom": "PCS", "is_active": 1},
			]
		}
		second = {"items": list(reversed(first["items"]))}
		changed = {"items": [dict(first["items"][0], uom="BOX"), first["items"][1]]}

		self.assertEqual(_master_reconciliation_fingerprint(first), _master_reconciliation_fingerprint(second))
		self.assertNotEqual(
			_master_reconciliation_fingerprint(first), _master_reconciliation_fingerprint(changed)
		)

	def test_unchanged_hold_refreshes_evidence_without_document_save(self):
		document = SimpleNamespace(
			name="voucher",
			order_number=None,
			source_pending_references="[]",
			source_status="Unverified",
			source_observation="null",
			source_error="missing",
			reconciliation_state="Manual Review",
			reconciled=0,
			is_new=lambda: False,
			save=Mock(),
		)
		database = SimpleNamespace(set_value=Mock(), get_value=Mock(return_value=None))
		with patch.object(voucher_snapshot, "frappe", SimpleNamespace(db=database)):
			changed = voucher_snapshot._hold(
				document,
				{"snapshot_id": "new", "completed_at": "2026-09-10 01:00:00"},
				None,
				"missing",
			)

		self.assertFalse(changed)
		document.save.assert_not_called()
		database.set_value.assert_called_once()

	def test_held_freshness_updates_are_batched(self):
		database = SimpleNamespace(set_value=Mock())
		with patch.object(voucher_snapshot, "frappe", SimpleNamespace(db=database)):
			voucher_snapshot._bulk_refresh_held_vouchers(
				{f"voucher-{index:04d}" for index in range(1201)},
				{"snapshot_id": "new", "completed_at": "2026-09-10 01:00:00"},
			)

		self.assertEqual(database.set_value.call_count, 3)
		self.assertEqual(
			[len(call.args[1]["name"][1]) for call in database.set_value.call_args_list],
			[500, 500, 201],
		)

	def test_hold_repairs_inconsistent_reconciliation_state(self):
		document = SimpleNamespace(
			name="voucher",
			order_number=None,
			source_pending_references="[]",
			source_status="Unverified",
			source_observation="null",
			source_error="missing",
			reconciliation_state="Matched",
			reconciled=1,
			is_new=lambda: False,
			save=Mock(),
		)
		database = SimpleNamespace(set_value=Mock(), get_value=Mock(return_value=None))
		with patch.object(voucher_snapshot, "frappe", SimpleNamespace(db=database)):
			changed = voucher_snapshot._hold(
				document,
				{"snapshot_id": "new", "completed_at": "2026-09-10 01:00:00"},
				None,
				"missing",
			)

		self.assertTrue(changed)
		document.save.assert_called_once()
		database.set_value.assert_not_called()


if __name__ == "__main__":
	unittest.main()
