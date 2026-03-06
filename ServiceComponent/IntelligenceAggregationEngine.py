# ServiceComponent/IntelligenceAggregationEngine.py
from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

from VectorDB.VectorDBClient import VectorDBClient

logger = logging.getLogger(__name__)


@dataclass
class AggregationPlanSpec:
    plan_id: str
    collection_name: str
    time_window_sec: int = 24 * 3600
    run_every_sec: int = 3600
    filter_criteria: Dict[str, Any] = None
    limit: int = 50000
    max_points: int = 50000
    method: str = "hdbscan"
    params: Dict[str, Any] = None
    semantic_only: bool = True
    enable_online: bool = True
    online_params: Dict[str, Any] = None
    persist: bool = True
    time_field: str = "timestamp"

    def to_payload(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "collection_name": self.collection_name,
            "time_window_sec": self.time_window_sec,
            "run_every_sec": self.run_every_sec,
            "filter_criteria": self.filter_criteria or {},
            "limit": int(self.limit),
            "max_points": int(self.max_points),
            "method": self.method,
            "params": self.params or {},
            "semantic_only": bool(self.semantic_only),
            "enable_online": bool(self.enable_online),
            "online_params": self.online_params or {},
            "persist": bool(self.persist),
            "time_field": self.time_field,
        }


class IntelligenceAggregationEngine:
    """
    IIS-side wrapper for VectorDB aggregation APIs.
    - Ensure plan exists
    - Trigger offline runs (hourly by IIS scheduler)
    - Read latest offline / online state
    - (Placeholder) Appendix writeback hook (NOT implemented now)
    """

    def __init__(
        self,
        vector_client: VectorDBClient,
        plan_spec: AggregationPlanSpec,
    ):
        self.client = vector_client
        self.plan_spec = plan_spec

        self.last_job_id: Optional[str] = None
        self.last_trigger_at: float = 0.0

    # ----------------------------
    # Plan management
    # ----------------------------

    def ensure_plan(self, overwrite: bool = False) -> Dict[str, Any]:
        """
        Ensure the plan exists on VectorDBService.
        """
        payload = self.plan_spec.to_payload()
        return self.client.register_aggregation_plan(payload, overwrite=overwrite)

    def list_plans(self) -> Dict[str, Any]:
        return self.client.list_aggregation_plans()

    # ----------------------------
    # Offline run
    # ----------------------------

    def trigger_offline(self, overrides: Optional[Dict[str, Any]] = None,
                        time_range: Optional[Tuple[float, float]] = None) -> str:
        """
        Trigger offline aggregation and return job_id.
        """
        res = self.client.run_aggregation_plan(self.plan_spec.plan_id, overrides=overrides, time_range=time_range)
        job_id = res.get("job_id")
        self.last_job_id = job_id
        self.last_trigger_at = time.time()
        return job_id

    def get_job(self, job_id: str) -> Dict[str, Any]:
        return self.client.get_aggregation_job(job_id)

    # ----------------------------
    # Read states
    # ----------------------------

    def get_latest_offline(self) -> Dict[str, Any]:
        return self.client.get_aggregation_offline_latest(self.plan_spec.plan_id)

    def get_online_state(self) -> Dict[str, Any]:
        return self.client.get_aggregation_online_state(self.plan_spec.plan_id)

    def get_cluster_items(self, cluster_id: str, limit: int = 100) -> Dict[str, Any]:
        return self.client.get_aggregation_offline_cluster_items(self.plan_spec.plan_id, cluster_id, limit=limit)

    def find_cluster_of_doc(self, doc_id: str, prefer_online: bool = True) -> Optional[str]:
        """
        Return cluster_id for given doc_id (uuid). Online preferred.
        """
        if prefer_online:
            st = self.get_online_state() or {}
            m = st.get("doc_to_cluster") or {}
            if doc_id in m:
                return m[doc_id]

        off = self.get_latest_offline() or {}
        m2 = off.get("doc_to_cluster") or {}
        return m2.get(doc_id)

    def get_latest_clusters_summary(
            self,
            *,
            sort_by: str = "size",  # "size" | "last_seen" | "cluster_id"
            descending: bool = True,
            limit: int = 200,
            include_noise: bool = True,
    ) -> Dict[str, Any]:
        """
        Return a compact summary of clusters from latest offline result.

        Output schema (example):
        {
          "plan_id": ...,
          "collection_name": ...,
          "version": ...,
          "created_at": ...,
          "time_range": [..., ...] | None,
          "method": ...,
          "params": {...},
          "n_points": ...,
          "n_clusters": ...,
          "n_noise": ...,
          "clusters": [
             {"cluster_id": "cluster_0", "size": 10, "repr_doc_id": "...",
              "repr_preview": "...", "last_seen": 123.0},
             ...
          ],
          "noise": {"size": n, "members_count": n}   # 不返回 members 明细
        }
        """
        latest = self.get_latest_offline() or {}

        # When no offline exists yet
        if not latest or latest.get("version") is None:
            return {
                "plan_id": self.plan_spec.plan_id,
                "collection_name": self.plan_spec.collection_name,
                "version": None,
                "created_at": None,
                "time_range": None,
                "method": None,
                "params": None,
                "n_points": 0,
                "n_clusters": 0,
                "n_noise": 0,
                "clusters": [],
                "noise": {"size": 0, "members_count": 0},
            }

        clusters_obj = latest.get("clusters") or {}
        clusters_list: List[Dict[str, Any]] = []

        for cid, c in clusters_obj.items():
            if not isinstance(c, dict):
                continue
            clusters_list.append({
                "cluster_id": cid,
                "size": int(c.get("size") or 0),
                "repr_doc_id": c.get("repr_doc_id"),
                "repr_preview": c.get("repr_preview") or "",
                "last_seen": c.get("last_seen"),
            })

        # Sorting
        key_fn = None
        if sort_by == "size":
            key_fn = lambda x: x.get("size", 0)
        elif sort_by == "last_seen":
            key_fn = lambda x: (x.get("last_seen") or 0)
        else:
            key_fn = lambda x: x.get("cluster_id") or ""

        clusters_list.sort(key=key_fn, reverse=bool(descending))

        if limit and limit > 0:
            clusters_list = clusters_list[: int(limit)]

        noise = latest.get("noise") or {}
        noise_size = int(noise.get("size") or 0)

        out = {
            "plan_id": latest.get("plan_id") or self.plan_spec.plan_id,
            "collection_name": latest.get("collection_name") or self.plan_spec.collection_name,
            "version": latest.get("version"),
            "created_at": latest.get("created_at"),
            "time_range": latest.get("time_range"),
            "method": latest.get("method"),
            "params": latest.get("params") or {},
            "n_points": int(latest.get("n_points") or 0),
            "n_clusters": int(latest.get("n_clusters") or 0),
            "n_noise": int(latest.get("n_noise") or 0),
            "clusters": clusters_list,
        }

        if include_noise:
            out["noise"] = {"size": noise_size, "members_count": noise_size}

        return out

    # ----------------------------
    # Placeholder: appendix writeback (NOT implemented)
    # ----------------------------

    def writeback_appendix_placeholder(self, offline_result: Dict[str, Any]) -> None:
        """
        Placeholder only. No writeback implementation now.

        offline_result should include:
          plan_id, version, time_range, doc_to_cluster, clusters, collection_name
        """
        # TODO: implement later
        return
