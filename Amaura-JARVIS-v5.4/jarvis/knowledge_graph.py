from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from jarvis.paths import get_data_dir

import logging
log = logging.getLogger(__name__)


@dataclass
class Entity:
    id: str
    name: str
    entity_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class Relation:
    id: str
    source_id: str
    target_id: str
    relation_type: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class KnowledgeGraph:
    """Relational Knowledge Graph for JARVIS using SQLite."""

    def __init__(self):
        self._db_path = get_data_dir() / "knowledge_graph.db"
        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._lock, self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS entities (
                  id TEXT PRIMARY KEY,
                  name TEXT NOT NULL,
                  entity_type TEXT NOT NULL,
                  properties TEXT,  -- JSON
                  created_at TEXT,
                  updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS relations (
                  id TEXT PRIMARY KEY,
                  source_id TEXT NOT NULL REFERENCES entities(id),
                  target_id TEXT NOT NULL REFERENCES entities(id),
                  relation_type TEXT NOT NULL,
                  properties TEXT,  -- JSON
                  created_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_entity_name ON entities(name);
                CREATE INDEX IF NOT EXISTS idx_entity_type ON entities(entity_type);
                CREATE INDEX IF NOT EXISTS idx_rel_source ON relations(source_id);
                CREATE INDEX IF NOT EXISTS idx_rel_target ON relations(target_id);
                CREATE INDEX IF NOT EXISTS idx_rel_type ON relations(relation_type);
            """)

    def add_entity(self, name: str, entity_type: str, properties: dict[str, Any] | None = None) -> Entity:
        """Upserts: if entity with same name+type exists, updates properties."""
        properties = properties or {}
        now = datetime.now(timezone.utc).isoformat()
        
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, properties, created_at FROM entities WHERE name = ? AND entity_type = ?",
                (name, entity_type)
            )
            row = cursor.fetchone()
            
            if row:
                entity_id = row["id"]
                existing_props = json.loads(row["properties"] or "{}")
                existing_props.update(properties)
                created_at = row["created_at"]
                
                cursor.execute(
                    "UPDATE entities SET properties = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(existing_props), now, entity_id)
                )
                return Entity(
                    id=entity_id,
                    name=name,
                    entity_type=entity_type,
                    properties=existing_props,
                    created_at=created_at,
                    updated_at=now
                )
            else:
                entity_id = str(uuid.uuid4())
                cursor.execute(
                    "INSERT INTO entities (id, name, entity_type, properties, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (entity_id, name, entity_type, json.dumps(properties), now, now)
                )
                return Entity(
                    id=entity_id,
                    name=name,
                    entity_type=entity_type,
                    properties=properties,
                    created_at=now,
                    updated_at=now
                )

    def add_relation(self, source_name: str, target_name: str, relation_type: str, properties: dict[str, Any] | None = None) -> Relation:
        """Auto-creates entities if they don't exist, prevents duplicate relations."""
        source = self.query_entity(source_name) or self.add_entity(source_name, 'concept')
        target = self.query_entity(target_name) or self.add_entity(target_name, 'concept')
        
        properties = properties or {}
        now = datetime.now(timezone.utc).isoformat()
        
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, properties, created_at FROM relations WHERE source_id = ? AND target_id = ? AND relation_type = ?",
                (source.id, target.id, relation_type)
            )
            row = cursor.fetchone()
            
            if row:
                relation_id = row["id"]
                created_at = row["created_at"]
                if properties:
                    existing_props = json.loads(row["properties"] or "{}")
                    existing_props.update(properties)
                    cursor.execute(
                        "UPDATE relations SET properties = ? WHERE id = ?",
                        (json.dumps(existing_props), relation_id)
                    )
                else:
                    existing_props = json.loads(row["properties"] or "{}")
                    
                return Relation(
                    id=relation_id,
                    source_id=source.id,
                    target_id=target.id,
                    relation_type=relation_type,
                    properties=existing_props,
                    created_at=created_at
                )
            else:
                relation_id = str(uuid.uuid4())
                cursor.execute(
                    "INSERT INTO relations (id, source_id, target_id, relation_type, properties, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (relation_id, source.id, target.id, relation_type, json.dumps(properties), now)
                )
                return Relation(
                    id=relation_id,
                    source_id=source.id,
                    target_id=target.id,
                    relation_type=relation_type,
                    properties=properties,
                    created_at=now
                )

    def query_entity(self, name: str) -> Entity | None:
        """Query entity by name."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM entities WHERE name = ? ORDER BY updated_at DESC LIMIT 1", (name,))
            row = cursor.fetchone()
            if not row:
                return None
            return Entity(
                id=row["id"],
                name=row["name"],
                entity_type=row["entity_type"],
                properties=json.loads(row["properties"] or "{}"),
                created_at=row["created_at"],
                updated_at=row["updated_at"]
            )

    def query_relations(self, entity_name: str, direction: str = 'both', relation_type: str | None = None) -> list[dict]:
        """Returns list of {"relation": "uses", "entity": "FastAPI", "direction": "outgoing"}"""
        entity = self.query_entity(entity_name)
        if not entity:
            return []
            
        results = []
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            
            if direction in ('outgoing', 'both'):
                query = """
                    SELECT r.relation_type, e.name as target_name 
                    FROM relations r 
                    JOIN entities e ON r.target_id = e.id 
                    WHERE r.source_id = ?
                """
                params = [entity.id]
                if relation_type:
                    query += " AND r.relation_type = ?"
                    params.append(relation_type)
                    
                for row in cursor.execute(query, params):
                    results.append({
                        "relation": row["relation_type"],
                        "entity": row["target_name"],
                        "direction": "outgoing"
                    })
                    
            if direction in ('incoming', 'both'):
                query = """
                    SELECT r.relation_type, e.name as source_name 
                    FROM relations r 
                    JOIN entities e ON r.source_id = e.id 
                    WHERE r.target_id = ?
                """
                params = [entity.id]
                if relation_type:
                    query += " AND r.relation_type = ?"
                    params.append(relation_type)
                    
                for row in cursor.execute(query, params):
                    results.append({
                        "relation": row["relation_type"],
                        "entity": row["source_name"],
                        "direction": "incoming"
                    })
                    
        return results

    def query_path(self, from_name: str, to_name: str, max_depth: int = 3) -> list[list[dict]] | None:
        """BFS to find connection paths between two entities."""
        start_entity = self.query_entity(from_name)
        end_entity = self.query_entity(to_name)
        
        if not start_entity or not end_entity:
            return None
            
        if start_entity.id == end_entity.id:
            return [[]]
            
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Queue stores tuples of (current_entity_id, path_so_far)
            queue = [(start_entity.id, [])]
            paths_found = []
            visited = set([start_entity.id])
            
            while queue:
                current_id, current_path = queue.pop(0)
                
                if len(current_path) >= max_depth:
                    continue
                    
                # Find all neighbors (outgoing and incoming)
                neighbors = []
                
                # Outgoing
                for row in cursor.execute("SELECT relation_type, target_id FROM relations WHERE source_id = ?", (current_id,)):
                    neighbors.append((row["target_id"], row["relation_type"], "outgoing"))
                    
                # Incoming
                for row in cursor.execute("SELECT relation_type, source_id FROM relations WHERE target_id = ?", (current_id,)):
                    neighbors.append((row["source_id"], row["relation_type"], "incoming"))
                    
                for next_id, rel_type, direction in neighbors:
                    # Fetch next entity name
                    cursor.execute("SELECT name FROM entities WHERE id = ?", (next_id,))
                    next_entity_name = cursor.fetchone()["name"]
                    
                    step = {
                        "relation": rel_type,
                        "entity": next_entity_name,
                        "direction": direction
                    }
                    
                    new_path = current_path + [step]
                    
                    if next_id == end_entity.id:
                        paths_found.append(new_path)
                    elif next_id not in visited:
                        visited.add(next_id)
                        queue.append((next_id, new_path))
                        
            return paths_found if paths_found else None

    def get_neighborhood(self, entity_name: str, depth: int = 1) -> dict:
        """Returns the entity and all connected entities up to N hops."""
        entity = self.query_entity(entity_name)
        if not entity:
            return {}
            
        entities = {entity.id: entity}
        relations = []
        
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            
            current_layer = {entity.id}
            
            for _ in range(depth):
                next_layer = set()
                
                for current_id in current_layer:
                    # Outgoing relations
                    for row in cursor.execute("SELECT id, target_id, relation_type, properties, created_at FROM relations WHERE source_id = ?", (current_id,)):
                        rel_id = row["id"]
                        target_id = row["target_id"]
                        
                        rel = Relation(
                            id=rel_id,
                            source_id=current_id,
                            target_id=target_id,
                            relation_type=row["relation_type"],
                            properties=json.loads(row["properties"] or "{}"),
                            created_at=row["created_at"]
                        )
                        relations.append(rel)
                        next_layer.add(target_id)
                        
                        if target_id not in entities:
                            ent_row = cursor.execute("SELECT * FROM entities WHERE id = ?", (target_id,)).fetchone()
                            if ent_row:
                                entities[target_id] = Entity(
                                    id=ent_row["id"],
                                    name=ent_row["name"],
                                    entity_type=ent_row["entity_type"],
                                    properties=json.loads(ent_row["properties"] or "{}"),
                                    created_at=ent_row["created_at"],
                                    updated_at=ent_row["updated_at"]
                                )
                                
                    # Incoming relations
                    for row in cursor.execute("SELECT id, source_id, relation_type, properties, created_at FROM relations WHERE target_id = ?", (current_id,)):
                        rel_id = row["id"]
                        source_id = row["source_id"]
                        
                        rel = Relation(
                            id=rel_id,
                            source_id=source_id,
                            target_id=current_id,
                            relation_type=row["relation_type"],
                            properties=json.loads(row["properties"] or "{}"),
                            created_at=row["created_at"]
                        )
                        relations.append(rel)
                        next_layer.add(source_id)
                        
                        if source_id not in entities:
                            ent_row = cursor.execute("SELECT * FROM entities WHERE id = ?", (source_id,)).fetchone()
                            if ent_row:
                                entities[source_id] = Entity(
                                    id=ent_row["id"],
                                    name=ent_row["name"],
                                    entity_type=ent_row["entity_type"],
                                    properties=json.loads(ent_row["properties"] or "{}"),
                                    created_at=ent_row["created_at"],
                                    updated_at=ent_row["updated_at"]
                                )
                                
                current_layer = next_layer
                
        # Deduplicate relations
        unique_relations = {r.id: r for r in relations}
        
        return {
            "root": entity,
            "entities": list(entities.values()),
            "relations": list(unique_relations.values())
        }

    def search_entities(self, query: str, entity_type: str | None = None, limit: int = 10) -> list[Entity]:
        """LIKE search on entity names."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            
            sql = "SELECT * FROM entities WHERE name LIKE ?"
            params = [f"%{query}%"]
            
            if entity_type:
                sql += " AND entity_type = ?"
                params.append(entity_type)
                
            sql += " ORDER BY updated_at DESC LIMIT ?"
            params.append(limit)
            
            entities = []
            for row in cursor.execute(sql, params):
                entities.append(Entity(
                    id=row["id"],
                    name=row["name"],
                    entity_type=row["entity_type"],
                    properties=json.loads(row["properties"] or "{}"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"]
                ))
            return entities

    def get_stats(self) -> dict:
        """Returns stats about the graph."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            
            total_entities = cursor.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            total_relations = cursor.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
            
            entity_types = {}
            for row in cursor.execute("SELECT entity_type, COUNT(*) as count FROM entities GROUP BY entity_type"):
                entity_types[row["entity_type"]] = row["count"]
                
            relation_types = {}
            for row in cursor.execute("SELECT relation_type, COUNT(*) as count FROM relations GROUP BY relation_type"):
                relation_types[row["relation_type"]] = row["count"]
                
            return {
                "total_entities": total_entities,
                "total_relations": total_relations,
                "entity_types": entity_types,
                "relation_types": relation_types
            }

    def to_prompt_context(self, entity_name: str) -> str:
        """Generates a readable knowledge context for the system prompt."""
        entity = self.query_entity(entity_name)
        if not entity:
            return f"[KNOWLEDGE GRAPH — {entity_name}]\n  No data found."
            
        relations = self.query_relations(entity_name, direction='outgoing')
        
        lines = []
        lines.append(f"[KNOWLEDGE GRAPH — {entity.name}]")
        lines.append(f"  Type: {entity.entity_type}")
        
        # Group relations by type
        grouped_relations = {}
        for rel in relations:
            rel_type = rel["relation"]
            target_name = rel["entity"]
            grouped_relations.setdefault(rel_type, []).append(target_name)
            
        for rel_type, targets in grouped_relations.items():
            targets_str = ", ".join(targets)
            lines.append(f"  • {rel_type} → {targets_str}")
            
        return "\n".join(lines)

    def export_dot(self, limit: int = 100) -> str:
        """Export graph as DOT format for visualization."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            
            lines = ["digraph KnowledgeGraph {", "  node [shape=box];"]
            
            # Fetch relations
            relations = list(cursor.execute("SELECT source_id, target_id, relation_type FROM relations LIMIT ?", (limit,)))
            
            entity_ids = set()
            for row in relations:
                entity_ids.add(row["source_id"])
                entity_ids.add(row["target_id"])
                
            # Fetch entities
            if entity_ids:
                placeholders = ",".join("?" * len(entity_ids))
                for row in cursor.execute(f"SELECT id, name, entity_type FROM entities WHERE id IN ({placeholders})", tuple(entity_ids)):
                    node_id = row["id"].replace("-", "_")
                    label = f'{row["name"]} ({row["entity_type"]})'
                    lines.append(f'  {node_id} [label="{label}"];')
                    
            for row in relations:
                source = row["source_id"].replace("-", "_")
                target = row["target_id"].replace("-", "_")
                rel_type = row["relation_type"]
                lines.append(f'  {source} -> {target} [label="{rel_type}"];')
                
            lines.append("}")
            return "\n".join(lines)


# Thread-safe singleton
_knowledge_graph_instance: KnowledgeGraph | None = None
_instance_lock = threading.Lock()

def get_knowledge_graph() -> KnowledgeGraph:
    global _knowledge_graph_instance
    if _knowledge_graph_instance is None:
        with _instance_lock:
            if _knowledge_graph_instance is None:
                _knowledge_graph_instance = KnowledgeGraph()
    return _knowledge_graph_instance


KNOWLEDGE_GRAPH_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "add_knowledge_entity",
            "description": "Add an entity (person, project, technology, concept) to JARVIS's knowledge graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The name of the entity."},
                    "entity_type": {"type": "string", "description": "Type of entity ('person', 'project', 'technology', 'file', 'concept', 'decision', 'organization')."},
                    "properties": {"type": "object", "description": "Additional arbitrary key-value metadata.", "additionalProperties": {"type": "string"}}
                },
                "required": ["name", "entity_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_knowledge_relation",
            "description": "Add a relationship between two entities in the knowledge graph.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_name": {"type": "string", "description": "Name of the source entity."},
                    "target_name": {"type": "string", "description": "Name of the target entity."},
                    "relation_type": {"type": "string", "description": "Type of relation ('uses', 'depends_on', 'created_by', 'replaces', 'conflicts_with', 'related_to', 'part_of', 'works_on', 'prefers', 'knows')."},
                    "properties": {"type": "object", "description": "Additional metadata (e.g. confidence).", "additionalProperties": {"type": "string"}}
                },
                "required": ["source_name", "target_name", "relation_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge",
            "description": "Query the knowledge graph about an entity and its connections.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_name": {"type": "string", "description": "The name of the entity to query."},
                    "direction": {"type": "string", "description": "Direction of relations ('incoming', 'outgoing', 'both').", "default": "both"},
                    "relation_type": {"type": "string", "description": "Optional relation type to filter by."}
                },
                "required": ["entity_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_graph",
            "description": "Search for entities in the knowledge graph by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search string to match entity names."},
                    "entity_type": {"type": "string", "description": "Optional entity type to filter by."},
                    "limit": {"type": "integer", "description": "Maximum number of results.", "default": 10}
                },
                "required": ["query"]
            }
        }
    }
]


def tool_add_knowledge_entity(name: str, entity_type: str, properties: dict | None = None) -> str:
    kg = get_knowledge_graph()
    entity = kg.add_entity(name=name, entity_type=entity_type, properties=properties)
    return json.dumps(asdict(entity), indent=2)


def tool_add_knowledge_relation(source_name: str, target_name: str, relation_type: str, properties: dict | None = None) -> str:
    kg = get_knowledge_graph()
    rel = kg.add_relation(source_name=source_name, target_name=target_name, relation_type=relation_type, properties=properties)
    return json.dumps(asdict(rel), indent=2)


def tool_query_knowledge(entity_name: str, direction: str = "both", relation_type: str | None = None) -> str:
    kg = get_knowledge_graph()
    res = kg.query_relations(entity_name=entity_name, direction=direction, relation_type=relation_type)
    return json.dumps(res, indent=2)


def tool_search_knowledge_graph(query: str, entity_type: str | None = None, limit: int = 10) -> str:
    kg = get_knowledge_graph()
    entities = kg.search_entities(query=query, entity_type=entity_type, limit=limit)
    return json.dumps([asdict(e) for e in entities], indent=2)


KNOWLEDGE_GRAPH_DISPATCH = {
    "add_knowledge_entity": tool_add_knowledge_entity,
    "add_knowledge_relation": tool_add_knowledge_relation,
    "query_knowledge": tool_query_knowledge,
    "search_knowledge_graph": tool_search_knowledge_graph,
}
