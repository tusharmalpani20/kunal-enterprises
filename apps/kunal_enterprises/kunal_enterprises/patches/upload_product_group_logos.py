"""One-off patch to upload product group logos and attach them to Tally Stock Group rows.

Run via: bench execute kunal_enterprises.patches.upload_product_group_logos.upload
"""
import os

import frappe
from frappe.utils.file_manager import save_file


LOGOS_DIR = "/Volumes/a909SSD/Development/Kunal-Enterprises/ke-enterprises-product-logos"

LOGO_MAPPING = [
    ("ascend_acrylic.jpeg", "ASCEND ACRYLIC"),
    ("ascend_interiors.jpeg", "ASCEND PLUS"),
    ("archidply.jpeg", "ARCHID VENEER"),
    ("century_particle_board.jpeg", "CENTURY PLB (4410)"),
    ("century_prowood_mdf.jpeg", "CENTURY PLAIN MDF"),
    ("centuryply_maxima_ply.jpeg", "MAXIMA MR PLY"),
    ("design_tree.jpeg", "DESIGN TREE"),
    ("e3_hdmr_mdf.jpeg", "E3 MDF"),
    ("greenpanel.jpeg", "GREENPANEL"),
    ("grid.jpeg", "GRID LAM"),
    ("infra_market.jpeg", "INFRA MARKET"),
    ("maria_decor.jpeg", "MARIA DECOR"),
    ("merino.jpeg", "Merino Industries Limited"),
    ("mikasa.jpeg", "MIKASA"),
    ("phoolwari.jpeg", "PHULWARI"),
    ("rare_and_unique.jpeg", "RARE & UNIQUE"),
    ("shalom_10.jpeg", "SHALOM LOUVERS"),
    ("teqora.jpeg", "TEQORA ACRYLIC"),
]


def upload():
    results = {"attached": [], "skipped": [], "missing_file": [], "missing_group": []}

    for filename, group_name in LOGO_MAPPING:
        filepath = os.path.join(LOGOS_DIR, filename)
        if not os.path.isfile(filepath):
            results["missing_file"].append({"filename": filename, "group": group_name})
            continue

        if not frappe.db.exists("Tally Stock Group", group_name):
            results["missing_group"].append({"filename": filename, "group": group_name})
            continue

        existing_logo = frappe.db.get_value(
            "Tally Stock Group", group_name, "product_group_logo",
        )
        if existing_logo:
            results["skipped"].append(
                {"filename": filename, "group": group_name, "existing_logo": existing_logo},
            )
            continue

        with open(filepath, "rb") as f:
            content = f.read()

        file_doc = save_file(
            fname=filename,
            content=content,
            dt="Tally Stock Group",
            dn=group_name,
            is_private=0,
        )

        frappe.db.set_value(
            "Tally Stock Group", group_name,
            "product_group_logo", file_doc.file_url,
            update_modified=False,
        )
        frappe.db.commit()

        results["attached"].append(
            {"filename": filename, "group": group_name, "file_url": file_doc.file_url},
        )

    return results
