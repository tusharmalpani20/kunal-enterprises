"""Validate voucher order lists. Reference and inventory OrderNo are not matching inputs."""

from datetime import date


def order_candidates(details, order_number):
	if details is None:
		if order_number is not None:
			raise ValueError("Order number exists without extracted order details")
		return [], "Voucher order details have not been extracted"
	if not isinstance(details, list):
		raise ValueError("Voucher order details must be a list or null")
	numbers = set()
	for entry in details:
		if not isinstance(entry, dict) or not isinstance(entry.get("order_number"), str):
			raise ValueError("Invalid voucher order entry")
		number = entry["order_number"].strip()
		if len(number) > 140 or any(ord(char) < 32 or ord(char) == 127 for char in number):
			raise ValueError("Voucher order number has invalid length or control characters")
		if number:
			numbers.add(number)
		order_date = entry.get("order_date")
		if order_date is not None:
			if not isinstance(order_date, str) or len(order_date) != 10:
				raise ValueError("Invalid voucher order date")
			if date.fromisoformat(order_date).isoformat() != order_date:
				raise ValueError("Voucher order date must use YYYY-MM-DD")
	numbers = sorted(numbers)
	expected = numbers[0] if len(numbers) == 1 else None
	if order_number != expected:
		raise ValueError("Voucher order number disagrees with extracted order details")
	return numbers, "Multiple order numbers require quantity allocation review" if len(numbers) > 1 else ""
