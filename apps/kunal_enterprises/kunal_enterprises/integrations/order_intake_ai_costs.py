"""Provider-reported usage and explicit USD rate snapshots; unknown is not free."""
from decimal import Decimal, DecimalException
import math


# Frappe Currency is DECIMAL(21,9). Reserve room for all 100 configured
# wire attempts in a run, so malformed provider costs cannot overflow either
# a call row or its aggregate and discard the raw response evidence.
MAX_CALL_COST_USD = Decimal("9999999999")


def _valid_cost(value):
	return value.is_finite() and 0 <= value <= MAX_CALL_COST_USD


def _count(value):
	if not isinstance(value, (int, float)) or isinstance(value, bool):
		return None
	if not 0 <= value <= 2_147_483_647 or not math.isfinite(value) or int(value) != value:
		return None
	return int(value)


def parse_usage(raw):
	raw = raw if isinstance(raw, dict) else {}
	input_count = _count(raw.get("prompt_tokens", raw.get("input_tokens")))
	output_count = _count(raw.get("completion_tokens", raw.get("output_tokens")))
	inputs = raw.get("prompt_tokens_details", raw.get("input_tokens_details")) or {}
	outputs = raw.get("completion_tokens_details", raw.get("output_tokens_details")) or {}
	inputs = inputs if isinstance(inputs, dict) else {}
	outputs = outputs if isinstance(outputs, dict) else {}
	# These optional breakdowns default to zero in the OpenAI usage contract.
	cache_read = _count(inputs.get("cached_tokens", 0))
	cache_write = _count(inputs.get("cache_write_tokens", 0))
	reasoning = _count(outputs.get("reasoning_tokens", 0))
	known = None not in (input_count, output_count, cache_read, cache_write, reasoning)
	if known:
		known = cache_read + cache_write <= input_count and reasoning <= output_count
	actual = raw.get("cost")
	try:
		actual = Decimal(str(actual)) if actual is not None else None
		if actual is not None and not _valid_cost(actual):
			actual = None
	except (DecimalException, ValueError):
		actual = None
	return dict(usage_known=bool(known), input_tokens=input_count or 0, output_tokens=output_count or 0,
		cached_input_tokens=cache_read or 0, cache_write_tokens=cache_write or 0, reasoning_tokens=reasoning or 0,
		provider_cost_known=actual is not None, provider_cost_usd=actual or Decimal(0))


def estimate_cost(usage, pricing, service_tier="default"):
	if not usage.get("usage_known") or not pricing or not pricing.get("rates_confirmed"):
		return False, Decimal(0)
	if (pricing.get("service_tier") or "default") != (service_tier or "default"):
		return False, Decimal(0)
	if usage["cached_input_tokens"] and not pricing.get("cached_rate_confirmed"):
		return False, Decimal(0)
	if usage["cache_write_tokens"] and not pricing.get("cache_write_rate_confirmed"):
		return False, Decimal(0)
	try:
		maximum = pricing.get("max_context_tokens")
		if not maximum or usage["input_tokens"] > int(maximum):
			return False, Decimal(0)
		rates = {name: Decimal(str(pricing.get(name) or 0)) for name in
			("input_per_million", "cached_input_per_million", "output_per_million", "cache_write_per_million")}
		if any(not value.is_finite() or value < 0 for value in rates.values()):
			return False, Decimal(0)
		uncached = usage["input_tokens"] - usage["cached_input_tokens"] - usage["cache_write_tokens"]
		cost = (uncached * rates["input_per_million"] + usage["cached_input_tokens"] * rates["cached_input_per_million"]
			+ usage["cache_write_tokens"] * rates["cache_write_per_million"] + usage["output_tokens"] * rates["output_per_million"]) / Decimal(1_000_000)
		# Reasoning tokens are already included in output_tokens.
		return (True, cost) if _valid_cost(cost) else (False, Decimal(0))
	except (DecimalException, ValueError, TypeError, OverflowError):
		return False, Decimal(0)
