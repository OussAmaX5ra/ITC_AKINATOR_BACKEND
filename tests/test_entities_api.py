"""
tests/test_entities_api.py — Tests for Entity Management Blueprint (Task 4.4).
"""

import io
import json
import pytest

from app.extensions import db
from app.models.entity import Entity, EntityCategory
from app.models.user import User, UserRole
from app.repositories.entity_repo import EntityRepository
from app.repositories.user_repo import UserRepository
from app.utils.security import generate_jwt, hash_password


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def entity_users(app):
    """Seed admin and operator users for entity API testing."""
    with app.app_context():
        existing = User.query.filter(User.username.in_(["ent_admin", "ent_operator"])).all()
        for u in existing:
            db.session.delete(u)
        db.session.commit()

        admin = UserRepository.create(
            username="ent_admin",
            email="ent_admin@itc.dz",
            password_hash=hash_password("admin_pass"),
            role=UserRole.ADMIN,
        )
        operator = UserRepository.create(
            username="ent_operator",
            email="ent_operator@itc.dz",
            password_hash=hash_password("op_pass"),
            role=UserRole.OPERATOR,
        )

        admin_token = generate_jwt(user_id=admin.id, role="admin")
        op_token = generate_jwt(user_id=operator.id, role="operator")

        return {
            "admin_token": admin_token,
            "operator_token": op_token,
        }


@pytest.fixture
def sample_entities(app):
    """Seed initial sample entities for testing."""
    with app.app_context():
        # Clean entities created in earlier entity tests
        Entity.query.delete()
        db.session.commit()

        e1 = EntityRepository.create(
            name="Marie Curie",
            category=EntityCategory.CHARACTER,
            names_i18n={"en": "Marie Curie", "fr": "Marie Curie"},
            attributes={"is_scientist": 1.0, "is_female": 1.0},
            is_approved=True,
        )
        e2 = EntityRepository.create(
            name="Albert Einstein",
            category=EntityCategory.CHARACTER,
            names_i18n={"en": "Albert Einstein"},
            attributes={"is_scientist": 1.0, "has_mustache": 1.0},
            is_approved=True,
        )
        e3 = EntityRepository.create(
            name="Golden Eagle",
            category=EntityCategory.ANIMAL,
            attributes={"can_fly": 1.0, "is_carnivore": 1.0},
            is_approved=False,
        )
        return {"curie_id": e1.id, "einstein_id": e2.id, "eagle_id": e3.id}


# ── GET /api/entities ─────────────────────────────────────────────────────────


def test_list_entities_pagination(client, entity_users, sample_entities):
    resp = client.get(
        "/api/entities?page=1&limit=2",
        headers={"Authorization": f"Bearer {entity_users['operator_token']}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert "entities" in data
    assert len(data["entities"]) == 2
    assert data["total"] == 3
    assert data["page"] == 1
    assert data["limit"] == 2


def test_list_entities_filter_by_category(client, entity_users, sample_entities):
    resp = client.get(
        "/api/entities?category=animal",
        headers={"Authorization": f"Bearer {entity_users['operator_token']}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["entities"][0]["name"] == "Golden Eagle"


def test_list_entities_filter_by_is_approved(client, entity_users, sample_entities):
    resp = client.get(
        "/api/entities?is_approved=false",
        headers={"Authorization": f"Bearer {entity_users['operator_token']}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["entities"][0]["name"] == "Golden Eagle"


def test_list_entities_search(client, entity_users, sample_entities):
    resp = client.get(
        "/api/entities?search=Curie",
        headers={"Authorization": f"Bearer {entity_users['operator_token']}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["total"] == 1
    assert data["entities"][0]["name"] == "Marie Curie"


def test_list_entities_invalid_category(client, entity_users):
    resp = client.get(
        "/api/entities?category=invalid_cat",
        headers={"Authorization": f"Bearer {entity_users['operator_token']}"},
    )
    assert resp.status_code == 400


def test_list_entities_unauthorized(client):
    resp = client.get("/api/entities")
    assert resp.status_code == 401


# ── POST /api/entities ────────────────────────────────────────────────────────


def test_create_entity_admin_success(client, entity_users):
    payload = {
        "name": "Nikola Tesla",
        "category": "character",
        "names_i18n": {"en": "Nikola Tesla"},
        "attributes": {"is_inventor": 1.0, "is_scientist": 1.0},
        "is_approved": True,
    }
    resp = client.post(
        "/api/entities",
        json=payload,
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["name"] == "Nikola Tesla"
    assert data["category"] == "character"
    assert data["is_approved"] is True


def test_create_entity_duplicate_conflict(client, entity_users, sample_entities):
    payload = {
        "name": "Marie Curie",
        "category": "character",
    }
    resp = client.post(
        "/api/entities",
        json=payload,
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 409
    assert "already exists" in resp.get_json()["detail"]


def test_create_entity_forbidden_for_operator(client, entity_users):
    resp = client.post(
        "/api/entities",
        json={"name": "Test Entity", "category": "object"},
        headers={"Authorization": f"Bearer {entity_users['operator_token']}"},
    )
    assert resp.status_code == 403


# ── PUT /api/entities/{id} ───────────────────────────────────────────────────


def test_update_entity_admin_success(client, entity_users, sample_entities):
    e_id = sample_entities["einstein_id"]
    payload = {
        "name": "Albert Einstein (Nobel Laureate)",
        "attributes": {"is_scientist": 1.0, "has_mustache": 1.0, "won_nobel": 1.0},
    }
    resp = client.put(
        f"/api/entities/{e_id}",
        json=payload,
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "Albert Einstein (Nobel Laureate)"
    assert data["attributes"]["won_nobel"] == 1.0


def test_update_entity_not_found(client, entity_users):
    resp = client.put(
        "/api/entities/999999",
        json={"name": "Unknown"},
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 404


def test_update_entity_conflict(client, entity_users, sample_entities):
    # Try to rename Einstein to Marie Curie (which already exists in character category)
    e_id = sample_entities["einstein_id"]
    resp = client.put(
        f"/api/entities/{e_id}",
        json={"name": "Marie Curie"},
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 409


# ── DELETE /api/entities/{id} ────────────────────────────────────────────────


def test_delete_entity_soft_deletes(client, entity_users, sample_entities):
    e_id = sample_entities["curie_id"]
    resp = client.delete(
        f"/api/entities/{e_id}",
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    # Verify entity is still in DB but is_approved is now False
    entity = EntityRepository.get_by_id(e_id)
    assert entity is not None
    assert entity.is_approved is False


def test_delete_entity_not_found(client, entity_users):
    resp = client.delete(
        "/api/entities/999999",
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 404


# ── POST /api/entities/seed ──────────────────────────────────────────────────


def test_seed_entities_via_json_body(client, entity_users):
    payload = [
        {"name": "Laptop", "category": "object", "attributes": {"is_electronic": 1.0}},
        {"name": "Dolphin", "category": "animal", "attributes": {"is_mammal": 1.0, "can_swim": 1.0}},
    ]
    resp = client.post(
        "/api/entities/seed",
        json=payload,
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["imported_count"] >= 2


def test_seed_entities_via_json_file_upload(client, entity_users):
    raw_json = json.dumps([
        {"name": "Leonardo da Vinci", "category": "character", "attributes": {"is_artist": 1.0}},
    ]).encode("utf-8")

    data = {
        "file": (io.BytesIO(raw_json), "entities.json"),
    }
    resp = client.post(
        "/api/entities/seed",
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["imported_count"] >= 1


def test_seed_entities_via_csv_file_upload(client, entity_users):
    csv_content = (
        "name,category,attributes\n"
        'Telescope,object,"{""is_optical"": 1.0}"\n'
        'Microscope,object,"{""is_optical"": 1.0}"\n'
    ).encode("utf-8")

    data = {
        "file": (io.BytesIO(csv_content), "seed.csv"),
    }
    resp = client.post(
        "/api/entities/seed",
        data=data,
        content_type="multipart/form-data",
        headers={"Authorization": f"Bearer {entity_users['admin_token']}"},
    )
    assert resp.status_code == 200
    assert resp.get_json()["imported_count"] >= 2


def test_seed_entities_forbidden_for_operator(client, entity_users):
    resp = client.post(
        "/api/entities/seed",
        json=[{"name": "Forbidden Entity", "category": "object"}],
        headers={"Authorization": f"Bearer {entity_users['operator_token']}"},
    )
    assert resp.status_code == 403
