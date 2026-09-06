"""Data models for beautiful_ecommerce_website-backend."""
from pydantic import BaseModel


class ItemCreate(BaseModel):
    name: str
    description: str = ""
    price: float = 0.0


class Item(ItemCreate):
    id: int
