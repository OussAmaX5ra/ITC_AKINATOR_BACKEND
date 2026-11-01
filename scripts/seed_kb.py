"""
scripts/seed_kb.py — CLI script to seed the Knowledge Base entities.

Usage:
    python scripts/seed_kb.py [path_to_json_file]
    Defaults to: data/seed_entities.json
"""

import json
import os
import sys

# Ensure repository root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.extensions import db
from app.models.entity import Entity, EntityCategory, EntitySource


def seed_entities(filepath: str = "data/seed_entities.json") -> None:
    if not os.path.exists(filepath):
        print(f"Error: Seed file not found at '{filepath}'")
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        print("Error: JSON file must contain a list of entity objects.")
        sys.exit(1)

    app = create_app(os.getenv("FLASK_ENV", "development"))
    with app.app_context():
        inserted = 0
        updated = 0

        for item in data:
            name = item.get("name")
            category_str = item.get("category", "character").lower()
            names_i18n = item.get("names_i18n", {})
            attributes = item.get("attributes", {})

            try:
                category = EntityCategory(category_str)
            except ValueError:
                print(f"Skipping '{name}': Invalid category '{category_str}'")
                continue

            existing = Entity.query.filter_by(name=name, category=category).first()
            if existing:
                existing.names_i18n = names_i18n
                existing.attributes = attributes
                existing.is_approved = True
                updated += 1
            else:
                new_entity = Entity(
                    name=name,
                    category=category,
                    names_i18n=names_i18n,
                    attributes=attributes,
                    source=EntitySource.SEED,
                    is_approved=True,
                )
                db.session.add(new_entity)
                inserted += 1

        db.session.commit()
        print(f"Seeding completed: {inserted} inserted, {updated} updated.")


if __name__ == "__main__":
    file_arg = sys.argv[1] if len(sys.argv) > 1 else "data/seed_entities.json"
    seed_entities(file_arg)
