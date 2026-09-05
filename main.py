"""JSON-backed REST API for the personal inventory application."""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator


DATA_FILE = Path(os.environ.get("VAULT_DATA_FILE", "data/inventory.json"))
DATA_LOCK = threading.RLock()
EMPTY_DATA = {"schema_version": 3, "categories": [], "locations": [], "owners": [], "items": [], "tag_templates": []}


class NamePayload(BaseModel):
    name: Annotated[str, Field(max_length=80)]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("名称不能为空")
        return value


class TagTemplatePayload(NamePayload):
    type: str  # "text" | "date" | "number" | "select"
    choices: list[str] | None = None

    @model_validator(mode="after")
    def validate_select_choices(self) -> TagTemplatePayload:
        if self.type == "select":
            if not self.choices:
                raise ValueError("下拉框类型的标签模板必须提供选项 (choices)")
            # Clean and filter empty choices
            cleaned = [c.strip() for c in self.choices if c and c.strip()]
            if len(cleaned) < 2:
                raise ValueError("下拉框至少需要2个有效的选项")
            self.choices = cleaned
        else:
            self.choices = None
        return self


class CategoryOptions(BaseModel):
    has_usage_count: bool = True
    allow_small_items: bool = False


class CategoryPayload(NamePayload):
    options: CategoryOptions = Field(default_factory=CategoryOptions)


class LocationPayload(NamePayload):
    parent_id: str | None = None


class TagItem(BaseModel):
    type: str  # "category" | "location" | "owner" | "price" | "date" | "text" | "number" | "select"
    name: str | None = None  # For text/number/date tags, e.g. "品牌", "购买日期", "累计使用次数"
    value: str | int | float | None = None
    template_id: str | None = None


class ItemPayload(BaseModel):
    name: Annotated[str, Field(max_length=100)]
    quantity: Annotated[int, Field(ge=1)] = 1
    notes: Annotated[str, Field(max_length=2000)] = ""
    tags: list[TagItem] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("物品名称不能为空")
        return value

    @field_validator("notes")
    @classmethod
    def clean_notes(cls, value: str) -> str:
        return value.strip()


class UsagePayload(BaseModel):
    delta: int

    @field_validator("delta")
    @classmethod
    def validate_delta(cls, value: int) -> int:
        if value == 0:
            raise ValueError("调整次数不能为零")
        return value


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def load_data() -> dict:
    with DATA_LOCK:
        if not DATA_FILE.exists():
            return {key: value.copy() if isinstance(value, list) else value for key, value in EMPTY_DATA.items()}
        try:
            data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise HTTPException(status_code=500, detail="数据文件损坏，请从备份恢复") from error
        if isinstance(data, dict):
            if "owners" not in data:
                data["owners"] = []
            if "tag_templates" not in data:
                data["tag_templates"] = []
            data["schema_version"] = 3
        if not isinstance(data, dict) or any(key not in data for key in EMPTY_DATA):
            raise HTTPException(status_code=500, detail="数据文件格式无效")
        return data


def save_data(data: dict) -> None:
    with DATA_LOCK:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        temporary = DATA_FILE.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, DATA_FILE)


def find_by_id(records: list[dict], record_id: str, label: str) -> dict:
    record = next((record for record in records if record["id"] == record_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail=f"未找到{label}")
    return record


def ensure_unique_name(records: list[dict], name: str, label: str, excluded_id: str | None = None) -> None:
    normalized = name.casefold()
    if any(record["name"].casefold() == normalized and record["id"] != excluded_id for record in records):
        raise HTTPException(status_code=409, detail=f"{label}名称已存在")


def location_path(location_id: str, locations: list[dict]) -> str:
    indexed = {location["id"]: location for location in locations}
    names: list[str] = []
    seen: set[str] = set()
    current_id: str | None = location_id
    while current_id:
        if current_id in seen or current_id not in indexed:
            return "位置数据异常"
        seen.add(current_id)
        current = indexed[current_id]
        names.append(current["name"])
        current_id = current.get("parent_id")
    return " / ".join(reversed(names))


def serialize_item(item: dict, data: dict) -> dict:
    result = item.copy()
    resolved_tags = []

    # Extract calculations from tags
    price_cents = None
    purchase_date_str = None
    usage_count = None

    for tag in item.get("tags", []):
        tag_type = tag["type"]
        tag_name = tag.get("name")
        tag_value = tag.get("value")

        resolved_tag = tag.copy()

        if tag_type == "category":
            category = next((c for c in data["categories"] if c["id"] == tag_value), None)
            resolved_tag["resolved_name"] = category["name"] if category else "未知类别"
        elif tag_type == "location":
            location = next((l for c in data["locations"] if (l := c)["id"] == tag_value), None)
            resolved_tag["resolved_name"] = location_path(tag_value, data["locations"]) if location else "未知位置"
        elif tag_type == "owner":
            owner = next((o for o in data["owners"] if o["id"] == tag_value), None)
            resolved_tag["resolved_name"] = owner["name"] if owner else "未知所有者"
        elif tag_type == "price":
            price_cents = int(tag_value) if tag_value is not None else None
            resolved_tag["resolved_name"] = "价格"
        elif tag_type == "date":
            # If name is Purchase Date or similar, track it
            purchase_date_str = str(tag_value) if tag_value else None
            resolved_tag["resolved_name"] = tag_name or "日期"
        elif tag_type == "number" and tag_name in ("使用次数", "累计使用次数", "usage_count"):
            usage_count = int(tag_value) if tag_value is not None else None
            resolved_tag["resolved_name"] = tag_name
        else:
            resolved_tag["resolved_name"] = tag_name or tag_type

        resolved_tags.append(resolved_tag)

    result["resolved_tags"] = resolved_tags

    # Dynamic Cost Calculation
    result["cost_per_use_cents"] = None
    result["cost_per_day_cents"] = None

    if price_cents is not None:
        if usage_count is not None and usage_count > 0:
            result["cost_per_use_cents"] = round(price_cents / usage_count)
        if purchase_date_str:
            try:
                purchased = date.fromisoformat(purchase_date_str)
                days_owned = max(1, (date.today() - purchased).days + 1)
                result["days_owned"] = days_owned
                result["cost_per_day_cents"] = round(price_cents / days_owned)
            except ValueError:
                pass

    return result


app = FastAPI(title="小金库 API", version="1.0.0")
allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "VAULT_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://10.126.126.11:5173,http://10.126.126.10:5173"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_store_api_responses(request: Request, call_next) -> Response:
    """API 响应一律不缓存，确保刷新页面时永远取到最新数据。

    浏览器/代理若缓存了旧的 GET 响应（例如标签模板为空时的响应），
    刷新后就会看到"数据消失了"，实际上后端 JSON 文件里一直保存着。
    """
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health() -> dict:
    data = load_data()
    return {"status": "ok", "items": len(data["items"])}


@app.get("/api/categories")
def list_categories() -> list[dict]:
    return load_data()["categories"]


@app.post("/api/categories", status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryPayload) -> dict:
    data = load_data()
    ensure_unique_name(data["categories"], payload.name, "类别")
    category = {
        "id": new_id("cat"),
        "name": payload.name,
        "options": payload.options.model_dump(),
        "created_at": now_iso()
    }
    data["categories"].append(category)
    save_data(data)
    return category


@app.put("/api/categories/{category_id}")
def update_category(category_id: str, payload: CategoryPayload) -> dict:
    data = load_data()
    category = find_by_id(data["categories"], category_id, "类别")
    ensure_unique_name(data["categories"], payload.name, "类别", category_id)
    category["name"] = payload.name
    category["options"] = payload.options.model_dump()
    save_data(data)
    return category


@app.delete("/api/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_category(category_id: str) -> Response:
    data = load_data()
    find_by_id(data["categories"], category_id, "类别")
    if any(item["category_id"] == category_id for item in data["items"]):
        raise HTTPException(status_code=409, detail="该类别仍被物品使用，无法删除")
    data["categories"] = [category for category in data["categories"] if category["id"] != category_id]
    save_data(data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/locations")
def list_locations() -> list[dict]:
    data = load_data()
    return [{**location, "path": location_path(location["id"], data["locations"])} for location in data["locations"]]


@app.post("/api/locations", status_code=status.HTTP_201_CREATED)
def create_location(payload: LocationPayload) -> dict:
    data = load_data()
    ensure_unique_name(data["locations"], payload.name, "位置")
    if payload.parent_id:
        find_by_id(data["locations"], payload.parent_id, "父位置")
    location = {"id": new_id("loc"), "name": payload.name, "parent_id": payload.parent_id, "created_at": now_iso()}
    data["locations"].append(location)
    save_data(data)
    return {**location, "path": location_path(location["id"], data["locations"])}


@app.put("/api/locations/{location_id}")
def update_location(location_id: str, payload: LocationPayload) -> dict:
    data = load_data()
    location = find_by_id(data["locations"], location_id, "位置")
    ensure_unique_name(data["locations"], payload.name, "位置", location_id)
    if payload.parent_id:
        find_by_id(data["locations"], payload.parent_id, "父位置")
        descendant_ids = {location_id}
        changed = True
        while changed:
            changed = False
            for candidate in data["locations"]:
                if candidate.get("parent_id") in descendant_ids and candidate["id"] not in descendant_ids:
                    descendant_ids.add(candidate["id"])
                    changed = True
        if payload.parent_id in descendant_ids:
            raise HTTPException(status_code=409, detail="位置不能成为自身或子位置的下级")
    location.update({"name": payload.name, "parent_id": payload.parent_id})
    save_data(data)
    return {**location, "path": location_path(location_id, data["locations"])}


@app.delete("/api/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: str) -> Response:
    data = load_data()
    find_by_id(data["locations"], location_id, "位置")
    if any(item["location_id"] == location_id for item in data["items"]):
        raise HTTPException(status_code=409, detail="该位置仍被物品使用，无法删除")
    if any(location.get("parent_id") == location_id for location in data["locations"]):
        raise HTTPException(status_code=409, detail="该位置仍包含子位置，无法删除")
    data["locations"] = [location for location in data["locations"] if location["id"] != location_id]
    save_data(data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/owners")
def list_owners() -> list[dict]:
    return load_data()["owners"]


@app.get("/api/templates")
def list_templates() -> list[dict]:
    return load_data()["tag_templates"]


@app.post("/api/templates", status_code=status.HTTP_201_CREATED)
def create_template(payload: TagTemplatePayload) -> dict:
    data = load_data()
    ensure_unique_name(data["tag_templates"], payload.name, "标签模板")
    template = {"id": new_id("tmpl"), **payload.model_dump(), "created_at": now_iso()}
    data["tag_templates"].append(template)
    save_data(data)
    return template


@app.put("/api/templates/{template_id}")
def update_template(template_id: str, payload: TagTemplatePayload) -> dict:
    data = load_data()
    template = find_by_id(data["tag_templates"], template_id, "标签模板")
    ensure_unique_name(data["tag_templates"], payload.name, "标签模板", template_id)
    template.update(payload.model_dump())
    save_data(data)
    return template


@app.delete("/api/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: str) -> Response:
    data = load_data()
    find_by_id(data["tag_templates"], template_id, "标签模板")
    data["tag_templates"] = [t for t in data["tag_templates"] if t["id"] != template_id]
    save_data(data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/owners", status_code=status.HTTP_201_CREATED)
def create_owner(payload: NamePayload) -> dict:
    data = load_data()
    ensure_unique_name(data["owners"], payload.name, "所有者")
    owner = {"id": new_id("own"), "name": payload.name, "created_at": now_iso()}
    data["owners"].append(owner)
    save_data(data)
    return owner


@app.put("/api/owners/{owner_id}")
def update_owner(owner_id: str, payload: NamePayload) -> dict:
    data = load_data()
    owner = find_by_id(data["owners"], owner_id, "所有者")
    ensure_unique_name(data["owners"], payload.name, "所有者", owner_id)
    owner["name"] = payload.name
    save_data(data)
    return owner


@app.delete("/api/owners/{owner_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_owner(owner_id: str) -> Response:
    data = load_data()
    find_by_id(data["owners"], owner_id, "所有者")
    if any(item.get("owner_id") == owner_id for item in data["items"]):
        raise HTTPException(status_code=409, detail="该所有者仍被物品使用，无法删除")
    data["owners"] = [owner for owner in data["owners"] if owner["id"] != owner_id]
    save_data(data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def validate_item_references(payload: ItemPayload, data: dict) -> None:
    for tag in payload.tags:
        if tag.type == "category" and tag.value:
            find_by_id(data["categories"], str(tag.value), "类别")
        elif tag.type == "location" and tag.value:
            find_by_id(data["locations"], str(tag.value), "位置")
        elif tag.type == "owner" and tag.value:
            find_by_id(data["owners"], str(tag.value), "所有者")


@app.get("/api/items")
def list_items(q: str = "") -> list[dict]:
    data = load_data()
    query = q.strip().casefold()
    items = []
    for item in data["items"]:
        serialized = serialize_item(item, data)
        # Search across name, tag names, or tag values (both original and resolved names)
        if query:
            name_match = query in serialized["name"].casefold()
            tag_match = False
            for r_tag in serialized["resolved_tags"]:
                tag_type = r_tag["type"]
                tag_name = (r_tag.get("name") or "").casefold()
                tag_res_name = (r_tag.get("resolved_name") or "").casefold()
                tag_val_str = str(r_tag.get("value") or "").casefold()

                if query in tag_name or query in tag_res_name or query in tag_val_str:
                    tag_match = True
                    break

            if not name_match and not tag_match:
                continue

        items.append(serialized)
    return sorted(items, key=lambda item: item["updated_at"], reverse=True)


@app.post("/api/items", status_code=status.HTTP_201_CREATED)
def create_item(payload: ItemPayload) -> dict:
    data = load_data()
    validate_item_references(payload, data)
    timestamp = now_iso()
    item = {"id": new_id("item"), **payload.model_dump(mode="json"), "created_at": timestamp, "updated_at": timestamp}
    data["items"].append(item)
    save_data(data)
    return serialize_item(item, data)


@app.get("/api/items/{item_id}")
def get_item(item_id: str) -> dict:
    data = load_data()
    return serialize_item(find_by_id(data["items"], item_id, "物品"), data)


@app.put("/api/items/{item_id}")
def update_item(item_id: str, payload: ItemPayload) -> dict:
    data = load_data()
    item = find_by_id(data["items"], item_id, "物品")
    validate_item_references(payload, data)
    item.update(payload.model_dump(mode="json"))
    item["updated_at"] = now_iso()
    save_data(data)
    return serialize_item(item, data)


@app.delete("/api/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(item_id: str) -> Response:
    data = load_data()
    find_by_id(data["items"], item_id, "物品")
    data["items"] = [item for item in data["items"] if item["id"] != item_id]
    save_data(data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.post("/api/items/{item_id}/usage")
def adjust_usage(item_id: str, payload: UsagePayload) -> dict:
    data = load_data()
    item = find_by_id(data["items"], item_id, "物品")

    # Find usage_count tag or create it
    tags = item.setdefault("tags", [])
    usage_tag = next((t for t in tags if t["type"] == "number" and t.get("name") in ("使用次数", "累计使用次数", "usage_count")), None)

    if not usage_tag:
        usage_tag = {"type": "number", "name": "累计使用次数", "value": 0}
        tags.append(usage_tag)

    current_val = int(usage_tag["value"] or 0)
    usage_count = current_val + payload.delta
    if usage_count < 0:
        raise HTTPException(status_code=409, detail="使用次数不能小于零")

    usage_tag["value"] = usage_count
    item["updated_at"] = now_iso()
    save_data(data)
    return serialize_item(item, data)


@app.get("/api/summary")
def summary() -> dict:
    data = load_data()
    item_count = len(data["items"])

    # Count valuable/pricey items based on tag availability
    valuable_count = 0
    total_cents = 0

    for item in data["items"]:
        price_tag = next((t for t in item.get("tags", []) if t["type"] == "price"), None)
        if price_tag and price_tag.get("value") is not None:
            valuable_count += 1
            total_cents += int(price_tag["value"])

    # Basic entity matching counts
    category_counts = []
    for cat in data["categories"]:
        cnt = sum(1 for item in data["items"] if any(t["type"] == "category" and t["value"] == cat["id"] for t in item.get("tags", [])))
        category_counts.append({"id": cat["id"], "name": cat["name"], "count": cnt})

    location_counts = []
    for loc in data["locations"]:
        cnt = sum(1 for item in data["items"] if any(t["type"] == "location" and t["value"] == loc["id"] for t in item.get("tags", [])))
        location_counts.append({"id": loc["id"], "name": loc["name"], "path": location_path(loc["id"], data["locations"]), "count": cnt})

    owner_counts = []
    for own in data["owners"]:
        cnt = sum(1 for item in data["items"] if any(t["type"] == "owner" and t["value"] == own["id"] for t in item.get("tags", [])))
        owner_counts.append({"id": own["id"], "name": own["name"], "count": cnt})

    return {
        "item_count": item_count,
        "valuable_item_count": valuable_count,
        "valuable_purchase_total_cents": total_cents,
        "category_counts": category_counts,
        "location_counts": location_counts,
        "owner_counts": owner_counts,
    }


FRONTEND_DIR = Path(__file__).parent / "frontend"
if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn

    # HTTPS 反向代理已由全局命令 ngh 独立管理，不再在此注册：
    #   ngh add vault 6011 --https 6012
    # （后端 6011 = uvicorn 实际监听端口；对外 HTTPS 6012，docker-compose 已单独发布）

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=6011,
        reload=False,
    )
