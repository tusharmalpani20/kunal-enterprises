from collections import OrderedDict
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re

import frappe
import openpyxl
import xlrd

from kunal_enterprises.cron.tally_sync import sync_stock_snapshots


EXCEL_STOCK_SOURCE_TABLE = "tally_stock_excel"
SUPPORTED_EXTENSIONS = {".xls", ".xlsx", ".xlsm"}


def import_tally_stock_excel_file(file_url):
	from frappe.utils.file_manager import get_file_path

	return import_tally_stock_excel_path(get_file_path(file_url))


def import_tally_stock_excel_path(file_path):
	return sync_stock_snapshots(
		parse_tally_stock_excel(file_path),
		source_table=EXCEL_STOCK_SOURCE_TABLE,
	)


def parse_tally_stock_excel(file_path):
	path = Path(file_path)
	if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
		frappe.throw("Only .xls, .xlsx, and .xlsm Tally stock files can be imported")

	rows = list(_iter_excel_rows(path))
	as_on_date = _report_date(rows)
	records = OrderedDict()
	current_item = None

	for row in rows:
		particular = row["particular"]
		godown = row["godown"]

		if _is_header_or_total(particular):
			current_item = None
			continue

		if particular and not godown:
			current_item = None if row["bold"] else particular
			continue

		if godown and current_item:
			key = (current_item, godown)
			quantity = _number(row["quantity"])
			if key not in records:
				records[key] = {
					"item": current_item,
					"godown": godown,
					"quantity": Decimal("0"),
				}
				if as_on_date:
					records[key]["as_on_date"] = as_on_date
			records[key]["quantity"] += quantity

	for record in records.values():
		record["quantity"] = float(record["quantity"])
	return list(records.values())


def _iter_excel_rows(path):
	if path.suffix.lower() == ".xls":
		yield from _iter_xls_rows(path)
	else:
		yield from _iter_xlsx_rows(path)


def _iter_xlsx_rows(path):
	workbook = openpyxl.load_workbook(path, data_only=True, read_only=False)
	sheet = workbook.worksheets[0]
	for row in sheet.iter_rows(min_row=1, max_col=3):
		particular_cell, godown_cell, quantity_cell = row
		yield {
			"particular": _text(particular_cell.value),
			"godown": _text(godown_cell.value),
			"quantity": quantity_cell.value,
			"bold": bool(particular_cell.font and particular_cell.font.bold),
		}


def _iter_xls_rows(path):
	workbook = xlrd.open_workbook(path, formatting_info=True)
	sheet = workbook.sheet_by_index(0)
	for row_index in range(sheet.nrows):
		particular = sheet.cell_value(row_index, 0) if sheet.ncols > 0 else ""
		godown = sheet.cell_value(row_index, 1) if sheet.ncols > 1 else ""
		quantity = sheet.cell_value(row_index, 2) if sheet.ncols > 2 else ""
		yield {
			"particular": _text(particular),
			"godown": _text(godown),
			"quantity": quantity,
			"bold": _xls_cell_bold(workbook, sheet, row_index, 0),
		}


def _xls_cell_bold(workbook, sheet, row_index, column_index):
	try:
		xf_index = sheet.cell_xf_index(row_index, column_index)
		font_index = workbook.xf_list[xf_index].font_index
		return bool(workbook.font_list[font_index].bold)
	except (IndexError, ValueError):
		return False


def _report_date(rows):
	for row in rows[:5]:
		match = re.search(r"Particulars\s*-\s*(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})", row["particular"])
		if not match:
			continue
		day, month, year = match.groups()
		year = int(year)
		if year < 100:
			year += 2000
		return f"{year:04d}-{int(month):02d}-{int(day):02d}"
	return None


def _is_header_or_total(value):
	if not value:
		return False
	cleaned = value.strip().lower()
	return cleaned.startswith("particulars") or cleaned == "grand total"


def _text(value):
	if value is None:
		return ""
	if isinstance(value, float) and value.is_integer():
		return str(int(value))
	return str(value).strip()


def _number(value):
	if value in (None, ""):
		return Decimal("0")
	try:
		return Decimal(str(value).replace(",", "").strip())
	except (InvalidOperation, ValueError):
		return Decimal("0")
