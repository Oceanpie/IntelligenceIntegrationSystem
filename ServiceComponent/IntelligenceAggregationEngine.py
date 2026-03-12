# ServiceComponent/IntelligenceAggregationEngine.py

from __future__ import annotations

import os
import time
import logging
import datetime
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple, List

from GlobalConfig import EXPORT_PATH
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
    time_field: str = "archived_timestamp"

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


def generate_aggregation_plan(profile: str = "hdbscan_fine") -> AggregationPlanSpec:
    """
    Generates an AggregationPlanSpec based on predefined algorithm profiles.
    This allows easy switching between clustering strategies for testing and tuning.

    Available profiles:
    - "hdbscan_balanced": Default density-based clustering, favors stable macro-clusters.
    - "hdbscan_fine": Forces extraction of micro-clusters (leaves) for finer granularity.
    - "agglomerative_strict": Hard cut-off distance, strict similarity grouping.
    - "agglomerative_loose": Hard cut-off distance, looser grouping.
    - "dbscan_standard": Classic DBSCAN, simple density grouping.
    """
    # Base configuration shared across all profiles
    base_config = {
        "plan_id": "agg_intelligence_summary_24h",
        "collection_name": "intelligence_summary",
        "time_window_sec": 24 * 3600,
        "run_every_sec": 3600,
        "max_points": 50000,
        "enable_online": True,
        "online_params": {"T_event": 0.85, "T_dup": 0.95},
        "persist": True,
        "time_field": "archived_timestamp",
    }

    if profile == "hdbscan_balanced":
        return AggregationPlanSpec(
            **base_config,
            method="hdbscan",
            params={
                "min_cluster_size": 3,
                "min_samples": 2,
                "cluster_selection_method": "eom"
            }
        )

    elif profile == "hdbscan_fine":
        return AggregationPlanSpec(
            **base_config,
            method="hdbscan",
            params={
                "min_cluster_size": 2,  # Allow very small clusters
                "min_samples": 1,  # Less conservative core point definition
                "cluster_selection_method": "leaf",  # Force fine-grained micro-clusters
                "cluster_selection_epsilon": 0.0  # Do not merge based on distance
            }
        )

    elif profile == "agglomerative_strict":
        return AggregationPlanSpec(
            **base_config,
            method="agglomerative_threshold",
            params={
                "distance_threshold": 0.25,  # Max cosine distance to be in same cluster
                "metric": "cosine",
                "linkage": "average"
            }
        )

    elif profile == "agglomerative_loose":
        return AggregationPlanSpec(
            **base_config,
            method="agglomerative_threshold",
            params={
                "distance_threshold": 0.45,  # Allows more variance within the cluster
                "metric": "cosine",
                "linkage": "average"
            }
        )

    elif profile == "dbscan_standard":
        return AggregationPlanSpec(
            **base_config,
            method="dbscan",
            params={
                "eps": 0.25,  # Maximum distance between two samples
                "min_samples": 2,
                "metric": "cosine"
            }
        )

    else:
        raise ValueError(f"Unknown aggregation profile: {profile}")


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
                        time_range: Optional[Tuple[float, float]] = None,
                        doc_fetcher: callable = None) -> str:
        """
        Trigger offline aggregation and return job_id.
        同时启动后台线程监控任务，并在完成时生成 Snapshot 文件。
        """
        res = self.client.run_aggregation_plan(self.plan_spec.plan_id, overrides=overrides, time_range=time_range)
        job_id = res.get("job_id")
        self.last_job_id = job_id
        self.last_trigger_at = time.time()

        if job_id:
            threading.Thread(
                target=self._monitor_offline_job,
                args=(job_id, doc_fetcher),
                daemon=True
            ).start()

        return job_id

    def _monitor_offline_job(self, job_id: str, doc_fetcher: callable):
        """
        临时线程：轮询作业状态并生成文本分析报告
        """
        logger.info(f"Started monitoring offline aggregation job: {job_id}")
        while True:
            try:
                job_info = self.get_job(job_id)
                status = job_info.get("status")

                if status == "completed":
                    logger.info(f"Job {job_id} completed. Generating text snapshot...")
                    self._generate_snapshot(job_id, doc_fetcher)
                    break
                elif status == "failed":
                    logger.error(f"Job {job_id} failed. Reason: {job_info.get('error')}")
                    break

                time.sleep(5)  # 每5秒轮询一次
            except Exception as e:
                logger.error(f"Error monitoring job {job_id}: {str(e)}")
                time.sleep(5)

    def _generate_snapshot(self, job_id: str, doc_fetcher: callable):
        try:
            latest = self.get_latest_offline()
            if not latest:
                return

            clusters = latest.get("clusters", {})

            export_folder = os.path.join(EXPORT_PATH, 'clusters')
            os.makedirs(export_folder, exist_ok=True)

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"offline_cluster_snapshot_{timestamp}.txt"
            filepath = os.path.join(export_folder, filename)

            # 收集并获取所需的文章标题以便调试阅读
            all_uuids = set()
            for cid, cinfo in clusters.items():
                if cinfo.get("repr_doc_id"):
                    all_uuids.add(cinfo["repr_doc_id"])
                for member_id in (cinfo.get("members") or []):
                    all_uuids.add(member_id)

            uuid_to_title = {}
            if doc_fetcher and all_uuids:
                docs = doc_fetcher(list(all_uuids))
                if isinstance(docs, dict): docs = [docs]
                for d in docs:
                    if not isinstance(d, dict): continue
                    uid = d.get("UUID")
                    title = d.get("EVENT_TITLE") or d.get("title") or "(No Title)"
                    if uid:
                        uuid_to_title[uid] = title

            # 写入快照
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"=== Offline Clustering Snapshot ===\n")
                f.write(f"Job ID:      {job_id}\n")
                f.write(f"Plan ID:     {latest.get('plan_id')}\n")
                f.write(f"Generated:   {datetime.datetime.now().isoformat()}\n")
                f.write(f"Total Points:{latest.get('n_points', 0)}\n")
                f.write(f"Clusters:    {latest.get('n_clusters', 0)}\n")
                f.write(f"Noise Size:  {latest.get('n_noise', 0)}\n")
                f.write("===================================\n\n")

                sorted_clusters = sorted(clusters.items(), key=lambda x: x[1].get("size", 0), reverse=True)

                for cid, cinfo in sorted_clusters:
                    size = cinfo.get("size", 0)
                    repr_id = cinfo.get("repr_doc_id")
                    repr_title = uuid_to_title.get(repr_id, "Unknown Title / Database Missing")

                    f.write(f"[{cid}] Size: {size}\n")
                    f.write(f"  ★ Representative:\n")
                    f.write(f"     -> {repr_title}\n")
                    # f.write(f"     -> {repr_id} | {repr_title}\n")
                    f.write(f"  ● Members:\n")

                    for mid in cinfo.get("members", []):
                        m_title = uuid_to_title.get(mid, "Unknown Title")
                        f.write(f"     - {m_title}\n")
                        # f.write(f"     - {mid} | {m_title}\n")

                    f.write("\n")

            logger.info(f"Snapshot successfully written to {filepath}")

        except Exception as e:
            logger.error(f"Failed to generate snapshot for {job_id}: {str(e)}")

    # ----------------------------
    # High-level API Abstractions
    # ----------------------------

    def build_rich_clusters_latest(
            self,
            doc_fetcher: callable,
            doc_cleaner: callable,
            limit: int = 200,
            sort_by: str = "score",
            descending: bool = True
    ) -> Dict[str, Any]:
        """
        组合业务逻辑：获取摘要，提取文章本体，清洗，并按请求排序。
        """
        summary = self.get_latest_clusters_summary(
            sort_by="size", descending=True, limit=limit, include_noise=False
        )
        clusters = summary.get("clusters") or []
        if not clusters:
            return summary

        repr_ids = list(dict.fromkeys([c.get("repr_doc_id") for c in clusters if c.get("repr_doc_id")]))
        repr_docs = doc_fetcher(repr_ids) if repr_ids else []
        if isinstance(repr_docs, dict): repr_docs = [repr_docs]
        repr_map = {d.get("UUID"): d for d in (repr_docs or []) if isinstance(d, dict)}

        out_clusters = []
        for c in clusters:
            uuid = c.get("repr_doc_id")
            doc = repr_map.get(uuid) or {}
            title = doc.get("EVENT_TITLE") or doc.get("title") or "(No Title)"
            brief = doc.get("EVENT_BRIEF") or ""

            cleaned_docs = doc_cleaner([doc]) if doc.get('UUID') else []
            cleaned_doc = cleaned_docs[0] if cleaned_docs else {}

            out_clusters.append({
                "cluster_id": c.get("cluster_id"),
                "size": c.get("size", 0),
                "last_seen": c.get("last_seen"),
                "repr_uuid": uuid,
                "repr_title": title,
                "repr_brief": brief,
                "href": f"/intelligence/{uuid}" if uuid else "#",
                "repr_doc": cleaned_doc
            })

        if sort_by == "score":
            out_clusters.sort(
                key=lambda x: float(x.get("repr_doc", {}).get("APPENDIX", {}).get("__TOTAL_SCORE__", 0.0) or 0.0),
                reverse=descending
            )
        elif sort_by == "time":
            out_clusters.sort(
                key=lambda x: str(x.get("repr_doc", {}).get("APPENDIX", {}).get("__TIME_ARCHIVED__", "")),
                reverse=descending
            )
        elif sort_by == "size":
            out_clusters.sort(key=lambda x: x.get("size", 0), reverse=descending)

        summary["clusters"] = out_clusters
        return summary

    def build_rich_cluster_members(
            self,
            cluster_id: str,
            doc_fetcher: callable,
            doc_cleaner: callable,
            offset: int = 0,
            limit: int = 100,
            sort_by: str = "relevance",
            descending: bool = True
    ) -> Dict[str, Any]:
        """
        组合业务逻辑：获取簇内成员切片，提取文章本体，清洗，并按请求排序。
        """
        latest = self.get_latest_offline() or {}
        clusters = latest.get("clusters") or {}
        cobj = clusters.get(cluster_id)
        if not cobj:
            raise ValueError(f"cluster_id not found: {cluster_id}")

        members = cobj.get("members") or []
        total = len(members)

        offset = max(0, offset)
        limit = max(1, min(500, limit))
        sub = members[offset: offset + limit]

        docs = doc_fetcher(sub) if sub else []
        if isinstance(docs, dict): docs = [docs]

        rank = {u: i for i, u in enumerate(sub)}
        cleaned_docs = doc_cleaner([d for d in docs if isinstance(d, dict)])
        cleaned_map = {d.get("UUID"): d for d in cleaned_docs}

        items = []
        for uid in sub:
            if uid not in rank: continue
            cleaned_doc = cleaned_map.get(uid, {})
            title = cleaned_doc.get("EVENT_TITLE") or cleaned_doc.get("title") or "(No Title)"

            items.append({
                "uuid": uid,
                "title": title,
                "href": f"/intelligence/{uid}",
                "doc": cleaned_doc
            })

        if sort_by == "score":
            items.sort(
                key=lambda x: float(x["doc"].get("APPENDIX", {}).get("__TOTAL_SCORE__", 0.0) or 0.0),
                reverse=descending
            )
        elif sort_by == "time":
            items.sort(
                key=lambda x: str(x["doc"].get("APPENDIX", {}).get("__TIME_ARCHIVED__", "")),
                reverse=descending
            )
        else:
            # relevance (Default)
            items.sort(key=lambda x: rank.get(x["uuid"], 10 ** 9))

        return {
            "cluster_id": cluster_id,
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": items
        }

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
