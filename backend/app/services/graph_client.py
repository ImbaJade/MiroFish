"""图谱客户端适配层。

支持三种后端：
- zep: 使用 zep-cloud（原有行为）
- local: 使用本地 JSON + 混合检索（离线模式）
- mem0: 使用 mem0 作为语义记忆增强（未安装时自动降级到 local）
"""

from __future__ import annotations

import json
import math
import os
import re
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger("mirofish.graph_client")


try:
    from zep_cloud.types import EpisodeData, EntityEdgeSourceTarget
except ImportError:
    class EpisodeData:
        def __init__(self, data: str, type: str = "text"):
            self.data = data
            self.type = type

        def dict(self) -> Dict[str, str]:
            return {"data": self.data, "type": self.type}

        def model_dump(self) -> Dict[str, str]:
            return self.dict()


    class EntityEdgeSourceTarget:
        def __init__(self, source: str, target: str):
            self.source = source
            self.target = target

        def dict(self) -> Dict[str, str]:
            return {"source": self.source, "target": self.target}

        def model_dump(self) -> Dict[str, str]:
            return self.dict()


def _obj(**kwargs):
    return SimpleNamespace(**kwargs)


def _normalize_api_key(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return api_key
    key = api_key.strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    return key or None


def _prepare_mem0_openai_env() -> None:
    """为 mem0 初始化准备 OpenAI 兼容环境变量。"""
    openai_api_key = _normalize_api_key(os.environ.get("OPENAI_API_KEY"))
    if not openai_api_key:
        openai_api_key = _normalize_api_key(Config.EMBEDDING_API_KEY) or _normalize_api_key(Config.LLM_API_KEY)
        if openai_api_key:
            os.environ["OPENAI_API_KEY"] = openai_api_key

    # 部分离线 OpenAI 兼容服务并不验证 key，这里兜底一个占位值，避免 mem0 客户端初始化即失败
    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = "offline-local-key"

    openai_base_url = os.environ.get("OPENAI_BASE_URL")
    if not openai_base_url:
        openai_base_url = Config.EMBEDDING_API_BASE_URL or Config.LLM_BASE_URL
        if openai_base_url:
            os.environ["OPENAI_BASE_URL"] = openai_base_url



def _disable_mem0_telemetry() -> None:
    """Explicitly disable mem0 telemetry in offline/intranet environments."""
    os.environ.setdefault("MEM0_TELEMETRY", "False")


class _LocalStore:
    def __init__(self):
        self.root = Path(__file__).resolve().parents[2] / "uploads" / "local_graph_store"
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, graph_id: str) -> Path:
        return self.root / f"{graph_id}.json"

    def load(self, graph_id: str) -> Dict[str, Any]:
        p = self._path(graph_id)
        if not p.exists():
            return {
                "graph_id": graph_id,
                "meta": {},
                "ontology": {"entity_types": [], "edge_types": []},
                "nodes": [],
                "edges": [],
                "episodes": [],
            }
        return json.loads(p.read_text(encoding="utf-8"))

    def save(self, graph_id: str, data: Dict[str, Any]) -> None:
        self._path(graph_id).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete(self, graph_id: str) -> None:
        p = self._path(graph_id)
        if p.exists():
            p.unlink()


class _TextFeatures:
    @staticmethod
    def tokenize(text: str) -> List[str]:
        if not text:
            return []
        raw = re.findall(r"[A-Za-z][A-Za-z0-9_]{1,}|[\u4e00-\u9fff]{2,8}", text.lower())
        stop = {
            "我们", "你们", "他们", "这个", "那个", "以及", "进行", "可以", "然后", "一个", "没有", "需要", "平台",
            "the", "and", "for", "that", "with", "this", "from", "are", "was", "were", "will", "have", "has",
        }
        return [t for t in raw if t not in stop]

    @staticmethod
    def lexical_score(query_terms: List[str], text: str) -> float:
        if not query_terms:
            return 0.0
        lower = (text or "").lower()
        return float(sum(1 for t in query_terms if t in lower))

    @staticmethod
    def cosine_counter(a: Counter, b: Counter) -> float:
        if not a or not b:
            return 0.0
        common = set(a.keys()) & set(b.keys())
        dot = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)


class _LocalNodeAPI:
    def __init__(self, store: _LocalStore, graph_api: "_LocalGraphAPI"):
        self._store = store
        self._graph_api = graph_api

    def get_by_graph_id(self, graph_id: str, limit: int = 100, uuid_cursor: Optional[str] = None):
        g = self._store.load(graph_id)
        items = g["nodes"]
        start = 0
        if uuid_cursor:
            for i, n in enumerate(items):
                if n["uuid"] == uuid_cursor:
                    start = i + 1
                    break
        page = items[start:start + limit]
        return [
            _obj(
                uuid_=n["uuid"], uuid=n["uuid"], name=n["name"], labels=n.get("labels", []),
                summary=n.get("summary", ""), attributes=n.get("attributes", {})
            )
            for n in page
        ]

    def get_entity_edges(self, node_uuid: str):
        graph_id = self._graph_api._find_graph_by_node(node_uuid)
        if not graph_id:
            return []
        g = self._store.load(graph_id)
        return [
            _obj(
                uuid_=e["uuid"], uuid=e["uuid"], name=e.get("name", "related_to"), fact=e.get("fact", ""),
                source_node_uuid=e["source_node_uuid"], target_node_uuid=e["target_node_uuid"], attributes=e.get("attributes", {}),
                created_at=e.get("created_at"), valid_at=e.get("valid_at"), invalid_at=e.get("invalid_at"), expired_at=e.get("expired_at")
            )
            for e in g["edges"] if e["source_node_uuid"] == node_uuid or e["target_node_uuid"] == node_uuid
        ]

    def get(self, uuid_: str):
        graph_id = self._graph_api._find_graph_by_node(uuid_)
        if not graph_id:
            return None
        g = self._store.load(graph_id)
        for n in g["nodes"]:
            if n["uuid"] == uuid_:
                return _obj(
                    uuid_=n["uuid"], uuid=n["uuid"], name=n["name"], labels=n.get("labels", []),
                    summary=n.get("summary", ""), attributes=n.get("attributes", {})
                )
        return None


class _LocalEdgeAPI:
    def __init__(self, store: _LocalStore):
        self._store = store

    def get_by_graph_id(self, graph_id: str, limit: int = 100, uuid_cursor: Optional[str] = None):
        g = self._store.load(graph_id)
        items = g["edges"]
        start = 0
        if uuid_cursor:
            for i, e in enumerate(items):
                if e["uuid"] == uuid_cursor:
                    start = i + 1
                    break
        page = items[start:start + limit]
        return [
            _obj(
                uuid_=e["uuid"], uuid=e["uuid"], name=e.get("name", "related_to"), fact=e.get("fact", ""),
                source_node_uuid=e["source_node_uuid"], target_node_uuid=e["target_node_uuid"], attributes=e.get("attributes", {}),
                created_at=e.get("created_at"), valid_at=e.get("valid_at"), invalid_at=e.get("invalid_at"), expired_at=e.get("expired_at")
            )
            for e in page
        ]


class _LocalEpisodeAPI:
    def __init__(self, store: _LocalStore, graph_api: "_LocalGraphAPI"):
        self._store = store
        self._graph_api = graph_api

    def get(self, uuid_: str):
        graph_id = self._graph_api._find_graph_by_episode(uuid_)
        if not graph_id:
            return None
        g = self._store.load(graph_id)
        for ep in g["episodes"]:
            if ep["uuid"] == uuid_:
                return _obj(uuid_=ep["uuid"], uuid=ep["uuid"], content=ep.get("content", ""), processed=True)
        return None


class _LocalGraphAPI:
    def __init__(self, store: _LocalStore):
        self._store = store
        self.node = _LocalNodeAPI(store, self)
        self.edge = _LocalEdgeAPI(store)
        self.episode = _LocalEpisodeAPI(store, self)

    def _find_graph_by_node(self, node_uuid: str) -> Optional[str]:
        for p in self._store.root.glob("*.json"):
            g = json.loads(p.read_text(encoding="utf-8"))
            if any(n["uuid"] == node_uuid for n in g.get("nodes", [])):
                return g["graph_id"]
        return None

    def _find_graph_by_episode(self, episode_uuid: str) -> Optional[str]:
        for p in self._store.root.glob("*.json"):
            g = json.loads(p.read_text(encoding="utf-8"))
            if any(ep["uuid"] == episode_uuid for ep in g.get("episodes", [])):
                return g["graph_id"]
        return None

    def create(self, graph_id: str, name: str, description: str = ""):
        data = self._store.load(graph_id)
        data["meta"] = {"name": name, "description": description, "created_at": datetime.utcnow().isoformat()}
        self._store.save(graph_id, data)

    def delete(self, graph_id: str):
        self._store.delete(graph_id)

    def set_ontology(self, graph_ids: List[str], entities: Any = None, edges: Any = None):
        for gid in graph_ids:
            g = self._store.load(gid)
            entity_types = []
            if isinstance(entities, list):
                entity_types = [e.get("name") for e in entities if isinstance(e, dict) and e.get("name")]
            elif isinstance(entities, dict):
                entity_types = list(entities.keys())
            edge_types = []
            if isinstance(edges, list):
                edge_types = [e.get("name") for e in edges if isinstance(e, dict) and e.get("name")]
            elif isinstance(edges, dict):
                edge_types = list(edges.keys())
            g["ontology"] = {"entity_types": entity_types, "edge_types": edge_types}
            self._store.save(gid, g)

    def add_batch(self, graph_id: str, data: Optional[List[EpisodeData]] = None, type: str = "text", source_description: str = "", episodes: Optional[List[EpisodeData]] = None):
        episode_uuids = []
        payload = data if data is not None else (episodes or [])
        for ep in payload:
            episode_uuids.append(self.add(graph_id=graph_id, type=type, data=ep.data, source_description=source_description))
        return _obj(episode_uuids=episode_uuids)

    def add(self, graph_id: str, type: str, data: str, source_description: str = ""):
        g = self._store.load(graph_id)
        episode_uuid = uuid.uuid4().hex
        g["episodes"].append({
            "uuid": episode_uuid,
            "type": type,
            "content": data,
            "source_description": source_description,
            "created_at": datetime.utcnow().isoformat(),
        })
        self._extract_graph(g, data)
        self._store.save(graph_id, g)
        return episode_uuid

    def _extract_graph(self, g: Dict[str, Any], text: str):
        entity_types = g.get("ontology", {}).get("entity_types", [])
        tokens = _TextFeatures.tokenize(text)
        uniq = []
        for t in tokens:
            if t not in uniq:
                uniq.append(t)
            if len(uniq) >= 24:
                break

        node_map = {n["name"]: n for n in g["nodes"]}
        node_ids = []
        for i, name in enumerate(uniq):
            node = node_map.get(name)
            if not node:
                label = entity_types[i % len(entity_types)] if entity_types else "Entity"
                node = {
                    "uuid": uuid.uuid4().hex,
                    "name": name,
                    "labels": ["Entity", label] if label != "Entity" else ["Entity"],
                    "summary": f"离线抽取实体：{name}",
                    "attributes": {"source": "local_extractor"},
                }
                g["nodes"].append(node)
                node_map[name] = node
            node_ids.append(node["uuid"])

        # 使用滑动窗口共现建边，尽量还原“关系网”体验
        for i in range(len(node_ids)):
            for j in range(i + 1, min(i + 4, len(node_ids))):
                src, tgt = node_ids[i], node_ids[j]
                src_name, tgt_name = uniq[i], uniq[j]
                g["edges"].append({
                    "uuid": uuid.uuid4().hex,
                    "name": "co_occurs_with",
                    "fact": f"{src_name} 与 {tgt_name} 在同一语境中共现",
                    "source_node_uuid": src,
                    "target_node_uuid": tgt,
                    "attributes": {"source": "local_extractor", "distance": j - i},
                    "created_at": datetime.utcnow().isoformat(),
                })

    def _rank_nodes_and_edges(self, g: Dict[str, Any], query: str, limit: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[str]]:
        query_terms = _TextFeatures.tokenize(query)
        q_counter = Counter(query_terms)

        node_scores: List[Tuple[float, Dict[str, Any]]] = []
        for n in g.get("nodes", []):
            text = f"{n.get('name','')} {n.get('summary','')} {' '.join(n.get('labels', []))}"
            terms = _TextFeatures.tokenize(text)
            score = 0.7 * _TextFeatures.lexical_score(query_terms, text) + 1.3 * _TextFeatures.cosine_counter(q_counter, Counter(terms))
            if score > 0:
                node_scores.append((score, n))

        edge_scores: List[Tuple[float, Dict[str, Any]]] = []
        node_by_uuid = {n["uuid"]: n for n in g.get("nodes", [])}
        for e in g.get("edges", []):
            src_name = node_by_uuid.get(e["source_node_uuid"], {}).get("name", "")
            tgt_name = node_by_uuid.get(e["target_node_uuid"], {}).get("name", "")
            text = f"{e.get('fact','')} {e.get('name','')} {src_name} {tgt_name}"
            terms = _TextFeatures.tokenize(text)
            score = 0.8 * _TextFeatures.lexical_score(query_terms, text) + 1.2 * _TextFeatures.cosine_counter(q_counter, Counter(terms))
            if score > 0:
                edge_scores.append((score, e))

        # 邻域扩展：把命中节点相关边抬分，增强“图谱连通感”
        top_node_ids = {n["uuid"] for _, n in sorted(node_scores, key=lambda x: x[0], reverse=True)[: max(1, limit // 2)]}
        boosted = []
        for s, e in edge_scores:
            if e["source_node_uuid"] in top_node_ids or e["target_node_uuid"] in top_node_ids:
                s += 0.6
            boosted.append((s, e))
        edge_scores = boosted

        top_nodes = [n for _, n in sorted(node_scores, key=lambda x: x[0], reverse=True)[:limit]]
        top_edges = [e for _, e in sorted(edge_scores, key=lambda x: x[0], reverse=True)[:limit]]
        facts = [e.get("fact", "") for e in top_edges if e.get("fact")]
        return top_nodes, top_edges, facts

    def search(self, graph_id: str, query: str, scope: str = "edges", limit: int = 20, reranker: str = "rrf", search_type: str = "node_edge"):
        g = self._store.load(graph_id)
        top_nodes, top_edges, facts = self._rank_nodes_and_edges(g, query, limit)

        if scope == "nodes":
            top_edges = []
            facts = []
        elif scope == "edges":
            top_nodes = []

        node_objs = [
            _obj(
                uuid_=n["uuid"], uuid=n["uuid"], name=n.get("name", ""), labels=n.get("labels", []),
                summary=n.get("summary", ""), attributes=n.get("attributes", {})
            )
            for n in top_nodes
        ]
        edge_objs = [
            _obj(
                uuid_=e["uuid"], uuid=e["uuid"], name=e.get("name", "related_to"), fact=e.get("fact", ""),
                source_node_uuid=e["source_node_uuid"], target_node_uuid=e["target_node_uuid"], attributes=e.get("attributes", {})
            )
            for e in top_edges
        ]
        return _obj(facts=facts, nodes=node_objs, edges=edge_objs)


class LocalGraphClient:
    is_local = True

    def __init__(self):
        store = _LocalStore()
        self.graph = _LocalGraphAPI(store)


class Mem0GraphClient:
    """在 local 图谱基础上，叠加 mem0 语义记忆检索增强。"""

    is_local = True

    def __init__(self):
        self._fallback = LocalGraphClient()
        self.graph = self._fallback.graph
        self._mem0 = None
        self._enabled = False

        try:
            _disable_mem0_telemetry()
            _prepare_mem0_openai_env()

            from mem0 import Memory  # type: ignore

            mem0_llm_config = {
                "model": Config.MEM0_MODEL_NAME,
            }
            if os.environ.get("OPENAI_API_KEY"):
                mem0_llm_config["api_key"] = os.environ.get("OPENAI_API_KEY")
            if os.environ.get("OPENAI_BASE_URL"):
                mem0_llm_config["openai_base_url"] = os.environ.get("OPENAI_BASE_URL")

            cfg = {
                "version": "v1.1",
                "llm": {
                    "provider": "openai",
                    "config": mem0_llm_config,
                },
                "vector_store": {
                    "provider": "chroma",
                    "config": {
                        "collection_name": "mirofish_mem0",
                        "path": str(Path(__file__).resolve().parents[2] / "uploads" / "mem0_store"),
                    },
                },
            }
            self._mem0 = Memory.from_config(cfg)
            self._enabled = True
            logger.info("Mem0GraphClient initialized with local Chroma store")
        except Exception as e:
            logger.warning(
                "mem0 not available, fallback to local graph only: %s. "
                "If you want MEMORY_BACKEND=mem0, run: "
                "cd backend && uv sync && uv pip install --python .venv/bin/python -r requirements.txt",
                e,
            )

        original_add = self.graph.add
        original_add_batch = self.graph.add_batch
        original_search = self.graph.search

        def add_with_mem0(graph_id: str, type: str, data: str, source_description: str = ""):
            ep_uuid = original_add(graph_id=graph_id, type=type, data=data, source_description=source_description)
            if self._enabled and self._mem0:
                try:
                    self._mem0.add(data, user_id=graph_id, metadata={"graph_id": graph_id, "source": source_description or "graph_add"})
                except Exception as ex:
                    logger.warning(f"mem0 add failed, continue with local graph: {ex}")
            return ep_uuid

        def add_batch_with_mem0(graph_id: str, data: Optional[List[EpisodeData]] = None, type: str = "text", source_description: str = "", episodes: Optional[List[EpisodeData]] = None):
            payload = data if data is not None else (episodes or [])
            uuids = []
            for ep in payload:
                uuids.append(add_with_mem0(graph_id=graph_id, type=type, data=ep.data, source_description=source_description))
            return _obj(episode_uuids=uuids)

        def search_with_mem0(graph_id: str, query: str, scope: str = "edges", limit: int = 20, reranker: str = "rrf", search_type: str = "node_edge"):
            base = original_search(graph_id=graph_id, query=query, scope=scope, limit=limit, reranker=reranker, search_type=search_type)
            if self._enabled and self._mem0:
                try:
                    memories = self._mem0.search(query, user_id=graph_id, limit=max(3, min(12, limit)))
                    mem_facts = []
                    for item in memories:
                        if isinstance(item, dict):
                            mem_text = item.get("memory") or item.get("text") or ""
                        else:
                            mem_text = str(item)
                        if mem_text:
                            mem_facts.append(f"[mem0] {mem_text}")
                    if mem_facts:
                        merged_facts = (base.facts or []) + mem_facts
                        return _obj(facts=merged_facts[: limit * 2], nodes=base.nodes, edges=base.edges)
                except Exception as ex:
                    logger.warning(f"mem0 search failed, fallback to local search: {ex}")
            return base

        self.graph.add = add_with_mem0
        self.graph.add_batch = add_batch_with_mem0
        self.graph.search = search_with_mem0


class ZepGraphClient:
    is_local = False

    def __init__(self, api_key: str):
        from zep_cloud.client import Zep

        self._client = Zep(api_key=api_key)
        self.graph = self._client.graph


def get_graph_client(api_key: Optional[str] = None):
    backend = (Config.MEMORY_BACKEND or "zep").lower()

    if backend == "local":
        return LocalGraphClient()

    if backend == "mem0":
        return Mem0GraphClient()

    key = api_key or Config.ZEP_API_KEY
    if not key:
        raise ValueError("ZEP_API_KEY 未配置")
    return ZepGraphClient(key)
