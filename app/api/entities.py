"""
app/api/entities.py — Knowledge base entity management and bulk seeding endpoints.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.api.auth import jwt_required, role_required
from app.api.schemas import (
    BulkSeedResponse,
    CreateEntityRequest,
    EntityListResponse,
    EntityResponse,
    UpdateEntityRequest,
)
from app.models.entity import Entity, EntityCategory, EntitySource
from app.repositories.entity_repo import EntityRepository

logger = logging.getLogger(__name__)

entities_bp = Blueprint("entities", __name__, url_prefix="/api/entities")


# ── REST Endpoints ────────────────────────────────────────────────────────────


@entities_bp.get("")
@jwt_required
def list_entities() -> Any:
    """
    GET /api/entities — Paginated list of knowledge base entities.
    Query parameters:
      - category: 'character' | 'animal' | 'object'
      - is_approved: 'true' | 'false' | '1' | '0'
      - search: string filter on entity name
      - page: int (default 1)
      - limit: int (default 20, max 100)
    Protected: Valid JWT access token required.
    """
    category_param = request.args.get("category")
    category_filter: Optional[EntityCategory] = None
    if category_param:
        try:
            category_filter = EntityCategory(category_param.lower())
        except ValueError:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "code": 400,
                        "detail": f"Invalid category '{category_param}'. Must be one of: {[c.value for c in EntityCategory]}.",
                    }
                ),
                400,
            )

    approved_param = request.args.get("is_approved")
    is_approved_filter: Optional[bool] = None
    if approved_param is not None:
        val = approved_param.lower()
        if val in ("true", "1"):
            is_approved_filter = True
        elif val in ("false", "0"):
            is_approved_filter = False
        else:
            return (
                jsonify(
                    {
                        "error": "Bad Request",
                        "code": 400,
                        "detail": "Invalid 'is_approved' parameter. Use true/false or 1/0.",
                    }
                ),
                400,
            )

    search_query = request.args.get("search", "").strip() or None

    try:
        page = max(1, int(request.args.get("page", 1)))
        limit = min(100, max(1, int(request.args.get("limit", 20))))
    except ValueError:
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": "Page and limit must be positive integers."}),
            400,
        )

    offset = (page - 1) * limit

    entities = EntityRepository.list_entities(
        category=category_filter,
        is_approved=is_approved_filter,
        search=search_query,
        limit=limit,
        offset=offset,
    )
    total = EntityRepository.count_entities(
        category=category_filter,
        is_approved=is_approved_filter,
        search=search_query,
    )

    response_data = EntityListResponse(
        entities=[EntityResponse(**e.to_dict()) for e in entities],
        total=total,
        page=page,
        limit=limit,
    )
    return jsonify(response_data.model_dump()), 200


@entities_bp.post("")
@role_required("admin")
def create_entity() -> Any:
    """
    POST /api/entities — Create a new knowledge base entity.
    Protected: Admin role required.
    Expects JSON: { "name": "...", "category": "...", "names_i18n": {...}, "attributes": {...} }
    Returns 201 Created: EntityResponse
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid or missing JSON body."}),
            400,
        )

    try:
        req = CreateEntityRequest(**payload)
    except ValidationError as err:
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}),
            400,
        )

    # Check for existing duplicate entity in the same category
    existing = EntityRepository.get_by_name_and_category(req.name, req.category)
    if existing:
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "code": 409,
                    "detail": f"Entity '{req.name}' already exists in category '{req.category.value}'.",
                }
            ),
            409,
        )

    entity = EntityRepository.create(
        name=req.name,
        category=req.category,
        names_i18n=req.names_i18n,
        attributes=req.attributes,
        source=EntitySource.SEED,
        is_approved=req.is_approved,
    )

    logger.info("Admin created new entity: %s (id=%d, category=%s)", entity.name, entity.id, entity.category.value)
    return jsonify(EntityResponse(**entity.to_dict()).model_dump()), 201


@entities_bp.put("/<int:entity_id>")
@role_required("admin")
def update_entity(entity_id: int) -> Any:
    """
    PUT /api/entities/{id} — Update an entity's name, translations, category, or attributes.
    Protected: Admin role required.
    Returns 200 OK: EntityResponse
    """
    entity = EntityRepository.get_by_id(entity_id)
    if not entity:
        return (
            jsonify({"error": "Not Found", "code": 404, "detail": f"Entity with id {entity_id} not found."}),
            404,
        )

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": "Invalid or missing JSON body."}),
            400,
        )

    try:
        req = UpdateEntityRequest(**payload)
    except ValidationError as err:
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": err.errors()}),
            400,
        )

    updates: Dict[str, Any] = {}
    if req.name is not None:
        updates["name"] = req.name
    if req.category is not None:
        updates["category"] = req.category
    if req.names_i18n is not None:
        updates["names_i18n"] = req.names_i18n
    if req.attributes is not None:
        updates["attributes"] = req.attributes
    if req.is_approved is not None:
        updates["is_approved"] = req.is_approved

    # Check for name/category collision with another entity
    target_name = updates.get("name", entity.name)
    target_category = updates.get("category", entity.category)
    existing = EntityRepository.get_by_name_and_category(target_name, target_category)
    if existing and existing.id != entity.id:
        return (
            jsonify(
                {
                    "error": "Conflict",
                    "code": 409,
                    "detail": f"Another entity with name '{target_name}' in category '{target_category.value}' already exists.",
                }
            ),
            409,
        )

    updated = EntityRepository.update(entity_id, **updates)
    logger.info("Admin updated entity: %s (id=%d)", updated.name, updated.id)
    return jsonify(EntityResponse(**updated.to_dict()).model_dump()), 200


@entities_bp.delete("/<int:entity_id>")
@role_required("admin")
def delete_entity(entity_id: int) -> Any:
    """
    DELETE /api/entities/{id} — Soft delete / mark entity as unapproved.
    Protected: Admin role required.
    Returns 200 OK: confirmation message.
    """
    entity = EntityRepository.get_by_id(entity_id)
    if not entity:
        return (
            jsonify({"error": "Not Found", "code": 404, "detail": f"Entity with id {entity_id} not found."}),
            404,
        )

    EntityRepository.update(entity_id, is_approved=False)
    logger.info("Admin soft-deleted entity: %s (id=%d)", entity.name, entity.id)
    return (
        jsonify(
            {
                "status": "ok",
                "message": "Entity soft-deleted (marked as unapproved).",
                "entity_id": entity_id,
            }
        ),
        200,
    )


@entities_bp.post("/seed")
@role_required("admin")
def seed_entities() -> Any:
    """
    POST /api/entities/seed — Bulk import entities from an uploaded JSON/CSV file or JSON body.
    Protected: Admin role required.
    Accepts:
      - Multipart file upload with key 'file' (.json or .csv)
      - OR JSON array directly in request body: [ { "name": "...", "category": "..." }, ... ]
    Returns 200 OK: BulkSeedResponse
    """
    items_to_import: List[Dict[str, Any]] = []

    # 1. Check for file upload (multipart/form-data)
    uploaded_file = request.files.get("file")
    if uploaded_file and uploaded_file.filename:
        filename = uploaded_file.filename.lower()
        content_bytes = uploaded_file.read()
        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return (
                jsonify({"error": "Bad Request", "code": 400, "detail": "File must be valid UTF-8 encoded text."}),
                400,
            )

        if filename.endswith(".json"):
            try:
                parsed_json = json.loads(content_str)
                if isinstance(parsed_json, dict) and "entities" in parsed_json:
                    parsed_json = parsed_json["entities"]
                if not isinstance(parsed_json, list):
                    return (
                        jsonify({"error": "Bad Request", "code": 400, "detail": "JSON file must contain a list of entities."}),
                        400,
                    )
                items_to_import = parsed_json
            except json.JSONDecodeError as err:
                return (
                    jsonify({"error": "Bad Request", "code": 400, "detail": f"Malformed JSON file: {err}"}),
                    400,
                )

        elif filename.endswith(".csv"):
            try:
                reader = csv.DictReader(io.StringIO(content_str))
                for row in reader:
                    name = row.get("name", "").strip()
                    if not name:
                        continue
                    cat_val = row.get("category", "character").strip()
                    names_i18n_raw = row.get("names_i18n", "{}")
                    try:
                        names_i18n = json.loads(names_i18n_raw) if isinstance(names_i18n_raw, str) and names_i18n_raw.startswith("{") else {}
                    except Exception:
                        names_i18n = {}

                    attrs_raw = row.get("attributes", "{}")
                    try:
                        attrs = json.loads(attrs_raw) if isinstance(attrs_raw, str) and attrs_raw.startswith("{") else {}
                    except Exception:
                        attrs = {}

                    items_to_import.append(
                        {
                            "name": name,
                            "category": cat_val,
                            "names_i18n": names_i18n,
                            "attributes": attrs,
                            "is_approved": True,
                        }
                    )
            except Exception as err:
                return (
                    jsonify({"error": "Bad Request", "code": 400, "detail": f"Failed to parse CSV file: {err}"}),
                    400,
                )
        else:
            return (
                jsonify({"error": "Bad Request", "code": 400, "detail": "Uploaded file must be a .json or .csv file."}),
                400,
            )

    # 2. Check for JSON body
    if not items_to_import:
        payload = request.get_json(silent=True)
        if isinstance(payload, list):
            items_to_import = payload
        elif isinstance(payload, dict) and isinstance(payload.get("entities"), list):
            items_to_import = payload["entities"]

    if not items_to_import:
        return (
            jsonify(
                {
                    "error": "Bad Request",
                    "code": 400,
                    "detail": "No entities provided. Upload a .json or .csv file with key 'file' or supply a JSON array.",
                }
            ),
            400,
        )

    # 3. Validate entries and bulk insert
    cleaned_items: List[Dict[str, Any]] = []
    for idx, item in enumerate(items_to_import):
        if not isinstance(item, dict):
            continue
        name = item.get("name", "").strip() if isinstance(item.get("name"), str) else ""
        if not name:
            continue
        cat_str = item.get("category", "character")
        try:
            category = EntityCategory(cat_str.lower() if isinstance(cat_str, str) else cat_str)
        except ValueError:
            category = EntityCategory.CHARACTER

        cleaned_items.append(
            {
                "name": name,
                "category": category,
                "names_i18n": item.get("names_i18n", {}),
                "attributes": item.get("attributes", {}),
                "source": EntitySource.SEED,
                "is_approved": bool(item.get("is_approved", True)),
            }
        )

    if not cleaned_items:
        return (
            jsonify({"error": "Bad Request", "code": 400, "detail": "No valid entity objects could be parsed."}),
            400,
        )

    imported_count = EntityRepository.bulk_insert(cleaned_items)
    logger.info("Admin bulk-seeded %d entities (processed %d items)", imported_count, len(cleaned_items))

    response_data = BulkSeedResponse(
        status="ok",
        imported_count=imported_count,
        message=f"Successfully imported {imported_count} entities.",
    )
    return jsonify(response_data.model_dump()), 200
