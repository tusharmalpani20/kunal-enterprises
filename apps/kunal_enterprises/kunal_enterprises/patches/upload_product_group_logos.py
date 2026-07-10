"""One-off patch to attach already-uploaded product group logos.

Run via: bench execute kunal_enterprises.patches.upload_product_group_logos.upload
"""

import frappe


EXPECTED_LOGO_MAPPING = [
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

# Backward-compatible alias for tests and ad-hoc imports.
LOGO_MAPPING = EXPECTED_LOGO_MAPPING


def upload():
    results = {
        "attached": [],
        "skipped": [],
        "missing_file_url": [],
        "missing_group": [],
    }

    uploaded_files = {
        (file.attached_to_name, file.file_name): file.file_url
        for file in frappe.get_all(
            "File",
            filters={"attached_to_doctype": "Tally Stock Group"},
            fields=["attached_to_name", "file_name", "file_url"],
            order_by="creation desc",
        )
    }

    for filename, group_name in EXPECTED_LOGO_MAPPING:
        file_url = uploaded_files.get((group_name, filename))
        if not file_url:
            results["missing_file_url"].append({"filename": filename, "group": group_name})
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

        frappe.db.set_value(
            "Tally Stock Group", group_name,
            "product_group_logo", file_url,
            update_modified=False,
        )
        frappe.db.commit()

        results["attached"].append(
            {"filename": filename, "group": group_name, "file_url": file_url},
        )

    return results
