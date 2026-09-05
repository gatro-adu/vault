from datetime import date, timedelta
from fastapi.testclient import TestClient
import main


def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_FILE", tmp_path / "inventory.json")
    return TestClient(main.app)


def create_basics(client):
    category = client.post("/api/categories", json={
        "name": "电子产品",
        "options": {"has_usage_count": True, "allow_small_items": True}
    }).json()
    home = client.post("/api/locations", json={"name": "家"}).json()
    drawer = client.post("/api/locations", json={"name": "书桌抽屉", "parent_id": home["id"]}).json()
    return category, home, drawer


def test_create_search_and_persist_item_with_tags(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    category, _, drawer = create_basics(client)

    tags = [
        {"type": "category", "value": category["id"]},
        {"type": "location", "value": drawer["id"]},
        {"type": "price", "value": 199900},
        {"type": "date", "name": "购买日期", "value": str(date.today() - timedelta(days=9))},
        {"type": "number", "name": "累计使用次数", "value": 10}
    ]

    response = client.post("/api/items", json={
        "name": "降噪耳机",
        "quantity": 1,
        "notes": "有防噪功能",
        "tags": tags
    })
    assert response.status_code == 201
    item = response.json()

    # The backend resolves values in serialized return payload
    assert item["cost_per_use_cents"] == 19990
    assert item["cost_per_day_cents"] == 19990

    # Search by category name (tag name) or location path or name or tag value
    assert len(client.get("/api/items?q=耳机").json()) == 1
    assert len(client.get("/api/items?q=电子").json()) == 1
    assert len(client.get("/api/items?q=抽屉").json()) == 1


def test_usage_count_adjustment_via_tag(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    category, _, drawer = create_basics(client)

    tags = [
        {"type": "category", "value": category["id"]},
        {"type": "price", "value": 100000},
        {"type": "number", "name": "累计使用次数", "value": 0}
    ]

    created = client.post("/api/items", json={
        "name": "相机",
        "quantity": 1,
        "tags": tags
    }).json()

    assert created["cost_per_use_cents"] is None

    # Adjust usage
    response = client.post(f"/api/items/{created['id']}/usage", json={"delta": 2})
    assert response.status_code == 200
    changed = response.json()

    # Verify updated usage count tag and cost
    usage_tag = next(t for t in changed["resolved_tags"] if t["type"] == "number" and t["name"] == "累计使用次数")
    assert usage_tag["value"] == 2
    assert changed["cost_per_use_cents"] == 50000


def test_custom_tag_templates_crud(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    # 1. Create a tag template
    response = client.post("/api/templates", json={"name": "保修期", "type": "date"})
    assert response.status_code == 201
    tmpl = response.json()
    assert tmpl["name"] == "保修期"
    assert tmpl["type"] == "date"
    assert "id" in tmpl

    # 2. List templates
    templates = client.get("/api/templates").json()
    assert len(templates) == 1
    assert templates[0]["id"] == tmpl["id"]

    # 3. Duplicate template check
    response = client.post("/api/templates", json={"name": "保修期", "type": "text"})
    assert response.status_code == 409

    # 4. Delete template
    response = client.delete(f"/api/templates/{tmpl['id']}")
    assert response.status_code == 204
    templates = client.get("/api/templates").json()
    assert len(templates) == 0


def test_select_type_template_validation_and_crud(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)

    # Try to create select without choices
    response = client.post("/api/templates", json={"name": "品牌", "type": "select"})
    assert response.status_code == 422

    # Try to create select with too few choices
    response = client.post("/api/templates", json={"name": "品牌", "type": "select", "choices": ["Apple"]})
    assert response.status_code == 422

    # Try to create with empty string choices
    response = client.post("/api/templates", json={"name": "品牌", "type": "select", "choices": ["Apple", "   ", " "]})
    assert response.status_code == 422

    # Create successfully
    response = client.post("/api/templates", json={"name": "品牌", "type": "select", "choices": ["Apple", "Xiaomi", "Huawei"]})
    assert response.status_code == 201
    tmpl = response.json()
    assert tmpl["name"] == "品牌"
    assert tmpl["type"] == "select"
    assert tmpl["choices"] == ["Apple", "Xiaomi", "Huawei"]

    # Update choices via PUT
    response = client.put(f"/api/templates/{tmpl['id']}", json={"name": "品牌名", "type": "select", "choices": ["Apple", "Xiaomi", "Huawei", "Sony"]})
    assert response.status_code == 200
    updated = response.json()
    assert updated["name"] == "品牌名"
    assert updated["choices"] == ["Apple", "Xiaomi", "Huawei", "Sony"]

    # Create an item with this select tag template
    category, _, drawer = create_basics(client)
    tags = [
        {"type": "category", "value": category["id"]},
        {"type": "location", "value": drawer["id"]},
        {"type": "select", "name": "品牌名", "value": "Sony", "template_id": tmpl["id"]}
    ]
    response = client.post("/api/items", json={
        "name": "无线降噪耳机",
        "quantity": 1,
        "tags": tags
    })
    assert response.status_code == 201
    item = response.json()
    assert len(item["tags"]) == 3
    select_tag = next(t for t in item["tags"] if t["type"] == "select")
    assert select_tag["name"] == "品牌名"
    assert select_tag["value"] == "Sony"
    assert select_tag["template_id"] == tmpl["id"]


def test_location_cannot_be_moved_under_descendant(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    _, home, drawer = create_basics(client)
    response = client.put(f"/api/locations/{home['id']}", json={"name": "家", "parent_id": drawer["id"]})
    assert response.status_code == 409
