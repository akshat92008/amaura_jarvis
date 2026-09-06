"""API routes for beautiful_ecommerce_website-backend."""
from fastapi import APIRouter, HTTPException
from app.models import Item, ItemCreate

router = APIRouter()
items_db: dict[int, Item] = {}
_counter = 0


@router.get("/items")
async def list_items():
    return list(items_db.values())


@router.post("/items", status_code=201)
async def create_item(item: ItemCreate):
    global _counter
    _counter += 1
    new = Item(id=_counter, **item.model_dump())
    items_db[_counter] = new
    return new


@router.get("/items/{item_id}")
async def get_item(item_id: int):
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    return items_db[item_id]


@router.delete("/items/{item_id}")
async def delete_item(item_id: int):
    if item_id not in items_db:
        raise HTTPException(status_code=404, detail="Item not found")
    del items_db[item_id]
    return {"deleted": item_id}
