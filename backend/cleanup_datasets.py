"""
Interactive cleanup for junk/broken datasets accumulated during development.

Run from backend/ with venv activated:
    python cleanup_datasets.py

Lists every dataset with an index, you type which numbers to delete
(comma-separated, or 'broken' to auto-select only datasets with no audit
data on their latest version). Nothing is deleted until you confirm.
"""

import sys
sys.path.insert(0, ".")

from app.core.db import get_connection
from app.core.versioning import list_all_datasets


def delete_dataset(dataset_id: str):
    conn = get_connection()
    version_ids = [
        r["version_id"]
        for r in conn.execute(
            "SELECT version_id FROM dataset_versions WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchall()
    ]

    for vid in version_ids:
        conn.execute("DELETE FROM audit_results WHERE dataset_version_id = ?", (vid,))
        conn.execute("DELETE FROM records WHERE dataset_version_id = ?", (vid,))

    conn.execute("DELETE FROM dataset_versions WHERE dataset_id = ?", (dataset_id,))
    conn.execute("DELETE FROM datasets WHERE dataset_id = ?", (dataset_id,))
    conn.commit()
    conn.close()


def main():
    datasets = list_all_datasets()
    if not datasets:
        print("No datasets found.")
        return

    print(f"\n{'#':<4}{'Name':<25}{'Versions':<10}{'Status':<20}{'Created':<25}")
    print("-" * 84)
    for i, d in enumerate(datasets):
        status = "VERIFIED" if d["latest_integrity_status"] == "VERIFIED" else "INVALID"
        if not d["latest_has_audit"]:
            status = "BROKEN (no audit)"
        print(f"{i:<4}{d['name']:<25}{d['version_count']:<10}{status:<20}{d['created_at']:<25}")

    print("\nType comma-separated numbers to delete, 'broken' to select only")
    print("BROKEN rows automatically, or 'quit' to exit without changes.")
    choice = input("> ").strip()

    if choice == "quit" or not choice:
        print("No changes made.")
        return

    if choice == "broken":
        to_delete = [d for d in datasets if not d["latest_has_audit"]]
    else:
        try:
            indices = [int(x.strip()) for x in choice.split(",")]
            to_delete = [datasets[i] for i in indices]
        except (ValueError, IndexError):
            print("Invalid input, no changes made.")
            return

    if not to_delete:
        print("Nothing matched, no changes made.")
        return

    print("\nAbout to permanently delete:")
    for d in to_delete:
        print(f"  - {d['name']} ({d['version_count']} version(s))")

    confirm = input(f"\nDelete these {len(to_delete)} dataset(s)? Type 'yes' to confirm: ").strip()
    if confirm != "yes":
        print("Cancelled, no changes made.")
        return

    for d in to_delete:
        delete_dataset(d["dataset_id"])
        print(f"Deleted: {d['name']}")

    print(f"\nDone. {len(to_delete)} dataset(s) removed.")


if __name__ == "__main__":
    main()