#!/usr/bin/env python3
"""Bulk collect image alt text from Bluesky for dataset creation.

This script favors Bluesky's public APIs and AT Protocol data structures instead of
scraping rendered HTML. It supports three acquisition modes:

1. author-feed: crawl one or more author feeds through the public AppView API.
2. search-posts: collect posts matching one or more search queries.
3. jetstream: subscribe to Bluesky's simplified JSON stream for broad live sampling.

Outputs are written as JSONL and optionally CSV, with one row per image/alt-text pair.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlencode

import requests

try:
    import websocket  # type: ignore
except ImportError:  # pragma: no cover
    websocket = None

APPVIEW_BASE = "https://public.api.bsky.app"
DEFAULT_JETSTREAM_WS = "wss://jetstream1.us-east.bsky.network/subscribe"
USER_AGENT = "bluesky-alt-text-dataset-builder/0.1"
REQUEST_TIMEOUT = 30
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 3
BASE_BACKOFF_SECONDS = 1.0


@dataclass
class AltTextRow:
    source_mode: str
    collected_at: str
    author_handle: Optional[str]
    author_did: Optional[str]
    post_uri: Optional[str]
    post_cid: Optional[str]
    indexed_at: Optional[str]
    created_at: Optional[str]
    text: Optional[str]
    langs_json: str
    alt_text: str
    image_index: int
    image_alt_length: int
    image_count_in_post: int
    image_mime_type: Optional[str]
    image_ref: Optional[str]
    image_thumb_url: Optional[str]
    image_fullsize_url: Optional[str]
    query: Optional[str]
    cursor: Optional[str]
    raw_record_json: str


# ---------------------------------------------------------------------------
# Checkpoint / Deduplication / Progress
# ---------------------------------------------------------------------------

def _derive_checkpoint_path(output_jsonl: str) -> str:
    directory = os.path.dirname(os.path.abspath(output_jsonl))
    basename = os.path.basename(output_jsonl)
    stem = basename[:-3] if basename.endswith(".gz") else basename
    return os.path.join(directory, f".{stem}.checkpoint.json")


def _derive_dedup_path(output_jsonl: str) -> str:
    directory = os.path.dirname(os.path.abspath(output_jsonl))
    basename = os.path.basename(output_jsonl)
    stem = basename[:-3] if basename.endswith(".gz") else basename
    return os.path.join(directory, f".{stem}.dedup.sqlite3")


class CheckpointStore:
    """Persist cursor state per key to a JSON file with atomic writes."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._state: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self._state = json.load(f)
            logging.info("Loaded checkpoint with %d entries from %s", len(self._state), self.path)

    def _save(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def get_cursor(self, key: str) -> Optional[str]:
        return self._state.get(key)

    def save_cursor(self, key: str, cursor: str) -> None:
        self._state[key] = cursor
        self._save()

    def get_jetstream_cursor(self) -> Optional[int]:
        val = self._state.get("__jetstream__")
        if val is not None:
            return int(val)
        return None


class DeduplicationDB:
    """SQLite-backed dedup keyed on (post_cid, image_index)."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            "  post_cid TEXT NOT NULL,"
            "  image_index INTEGER NOT NULL,"
            "  PRIMARY KEY (post_cid, image_index)"
            ")"
        )
        self._conn.commit()
        count = self._conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
        if count > 0:
            logging.info("Loaded dedup DB with %d entries from %s", count, path)

    def seen(self, post_cid: Optional[str], image_index: int) -> bool:
        if post_cid is None:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM seen WHERE post_cid = ? AND image_index = ?",
            (post_cid, image_index),
        ).fetchone()
        return row is not None

    def mark(self, post_cid: Optional[str], image_index: int) -> None:
        if post_cid is None:
            return
        self._conn.execute(
            "INSERT OR IGNORE INTO seen (post_cid, image_index) VALUES (?, ?)",
            (post_cid, image_index),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


class ProgressTracker:
    """Emit structured log lines every N rows."""

    def __init__(self, interval: int = 1000) -> None:
        self.interval = interval
        self._last_report_count = 0
        self._start_time = time.monotonic()
        self._last_report_time = self._start_time

    def tick(self, stats: Dict[str, int], key: Optional[str] = None, cursor: Optional[str] = None) -> None:
        rows = stats.get("rows_written", 0)
        if rows - self._last_report_count >= self.interval:
            now = time.monotonic()
            elapsed = now - self._start_time
            rate = rows / elapsed if elapsed > 0 else 0
            recent_elapsed = now - self._last_report_time
            recent_rows = rows - self._last_report_count
            recent_rate = recent_rows / recent_elapsed if recent_elapsed > 0 else 0
            logging.info(
                "Progress: rows_written=%d, rate=%.1f rows/sec (recent %.1f rows/sec), key=%s, cursor=%s",
                rows, rate, recent_rate, key, cursor,
            )
            self._last_report_count = rows
            self._last_report_time = now


# ---------------------------------------------------------------------------
# Dataset Writer
# ---------------------------------------------------------------------------

class DatasetWriter:
    def __init__(
        self,
        output_jsonl: str,
        output_csv: Optional[str] = None,
        compress: bool = False,
        append: bool = False,
        shard_size: int = 0,
    ) -> None:
        self.output_jsonl = output_jsonl
        self.output_csv = output_csv
        self.compress = compress
        self.append = append
        self.shard_size = shard_size
        self.row_count = 0
        self.jsonl_handle = None
        self.csv_handle = None
        self.csv_writer = None
        self._shard_index = 0
        self._shard_row_count = 0
        self._base_jsonl = output_jsonl
        self._base_csv = output_csv

    def _shard_path(self, base: str, index: int) -> str:
        if base.endswith(".gz"):
            inner = base[:-3]
            stem, ext = os.path.splitext(inner)
            return f"{stem}-{index:05d}{ext}.gz"
        stem, ext = os.path.splitext(base)
        return f"{stem}-{index:05d}{ext}"

    def _current_jsonl_path(self) -> str:
        if self.shard_size <= 0:
            return self._base_jsonl
        return self._shard_path(self._base_jsonl, self._shard_index + 1)

    def _current_csv_path(self) -> Optional[str]:
        if self._base_csv is None:
            return None
        if self.shard_size <= 0:
            return self._base_csv
        return self._shard_path(self._base_csv, self._shard_index + 1)

    def _detect_resume_shard(self) -> None:
        if self.shard_size <= 0:
            return
        idx = 0
        while True:
            path = self._shard_path(self._base_jsonl, idx + 1)
            if not os.path.exists(path):
                break
            idx += 1
        if idx > 0:
            self._shard_index = idx - 1
            last_path = self._shard_path(self._base_jsonl, idx)
            try:
                if last_path.endswith(".gz"):
                    with gzip.open(last_path, "rt", encoding="utf-8") as f:
                        self._shard_row_count = sum(1 for _ in f)
                else:
                    with open(last_path, "r", encoding="utf-8") as f:
                        self._shard_row_count = sum(1 for _ in f)
            except (OSError, gzip.BadGzipFile):
                self._shard_row_count = 0
            logging.info("Resuming at shard %d with %d rows", idx, self._shard_row_count)

    def _open_handles(self, jsonl_path: str, csv_path: Optional[str], mode: str, write_csv_header: bool) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(jsonl_path)), exist_ok=True)
        if self.compress or jsonl_path.endswith(".gz"):
            self.jsonl_handle = gzip.open(jsonl_path, mode + "t", encoding="utf-8")
        else:
            self.jsonl_handle = open(jsonl_path, mode, encoding="utf-8")

        if csv_path:
            os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
            if self.compress or csv_path.endswith(".gz"):
                self.csv_handle = gzip.open(csv_path, mode + "t", encoding="utf-8", newline="")
            else:
                self.csv_handle = open(csv_path, mode, encoding="utf-8", newline="")
            self.csv_writer = csv.DictWriter(self.csv_handle, fieldnames=list(AltTextRow.__annotations__.keys()))
            if write_csv_header:
                self.csv_writer.writeheader()

    def __enter__(self) -> "DatasetWriter":
        if self.append and self.shard_size > 0:
            self._detect_resume_shard()

        jsonl_path = self._current_jsonl_path()
        csv_path = self._current_csv_path()
        mode = "a" if self.append else "w"

        csv_file_exists = csv_path and os.path.exists(csv_path) and os.path.getsize(csv_path) > 0
        write_csv_header = not (self.append and csv_file_exists)

        self._open_handles(jsonl_path, csv_path, mode, write_csv_header)
        return self

    def write(self, row: AltTextRow) -> None:
        if self.shard_size > 0 and self._shard_row_count >= self.shard_size:
            self._rotate()
        payload = asdict(row)
        if self.jsonl_handle is None:
            raise RuntimeError("DatasetWriter.write() called outside of context manager")
        self.jsonl_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        if self.csv_writer is not None:
            self.csv_writer.writerow(payload)
        self.row_count += 1
        self._shard_row_count += 1

    def _rotate(self) -> None:
        if self.jsonl_handle is not None:
            self.jsonl_handle.close()
        if self.csv_handle is not None:
            self.csv_handle.close()

        self._shard_index += 1
        self._shard_row_count = 0

        jsonl_path = self._current_jsonl_path()
        csv_path = self._current_csv_path()
        logging.info("Rotating to shard %d: %s", self._shard_index + 1, jsonl_path)
        self._open_handles(jsonl_path, csv_path, "w", write_csv_header=True)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.jsonl_handle is not None:
            self.jsonl_handle.close()
        if self.csv_handle is not None:
            self.csv_handle.close()


# ---------------------------------------------------------------------------
# Bluesky API Client
# ---------------------------------------------------------------------------

class BlueskyAPIError(RuntimeError):
    def __init__(self, endpoint: str, status_code: int, response_text: str, url: str) -> None:
        super().__init__(f"Bluesky API error on {endpoint}: HTTP {status_code}")
        self.endpoint = endpoint
        self.status_code = status_code
        self.response_text = response_text
        self.url = url


def _retry_wait(response: requests.Response, attempt: int) -> float:
    """Calculate retry wait, respecting Retry-After header on 429."""
    if response.status_code == 429:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.5)
            except ValueError:
                pass
    return BASE_BACKOFF_SECONDS * (2 ** attempt)


class BlueskyClient:
    def __init__(self, appview_base: str = APPVIEW_BASE, auth_bearer: Optional[str] = None) -> None:
        self.appview_base = appview_base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        })
        if auth_bearer:
            self.session.headers["Authorization"] = f"Bearer {auth_bearer}"

    def get_json(self, endpoint: str, **params: Any) -> Dict[str, Any]:
        url = f"{self.appview_base}/xrpc/{endpoint}"
        clean_params = {k: v for k, v in params.items() if v is not None}
        last_exc: Optional[Exception] = None

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.session.get(url, params=clean_params, timeout=REQUEST_TIMEOUT)
                if response.ok:
                    return response.json()
                if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                    wait = _retry_wait(response, attempt)
                    logging.warning(
                        "Retryable HTTP %s on %s, attempt %d/%d, waiting %.1fs",
                        response.status_code, endpoint, attempt + 1, MAX_RETRIES, wait,
                    )
                    time.sleep(wait)
                    continue
                raise BlueskyAPIError(
                    endpoint=endpoint,
                    status_code=response.status_code,
                    response_text=response.text[:2000],
                    url=response.url,
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    wait = BASE_BACKOFF_SECONDS * (2 ** attempt)
                    logging.warning(
                        "Connection error on %s, attempt %d/%d, waiting %.1fs: %s",
                        endpoint, attempt + 1, MAX_RETRIES, wait, exc,
                    )
                    time.sleep(wait)
                    continue
                raise
        assert last_exc is not None, "unreachable: retry loop exited without raising"
        raise last_exc

    def get_author_feed(
        self,
        actor: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        filter_value: str = "posts_with_media",
    ) -> Dict[str, Any]:
        return self.get_json(
            "app.bsky.feed.getAuthorFeed",
            actor=actor,
            cursor=cursor,
            limit=limit,
            filter=filter_value,
        )

    def search_posts(
        self,
        query: str,
        cursor: Optional[str] = None,
        limit: int = 100,
        sort: str = "latest",
        since: Optional[str] = None,
        until: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.get_json(
            "app.bsky.feed.searchPosts",
            q=query,
            cursor=cursor,
            limit=limit,
            sort=sort,
            since=since,
            until=until,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_text_file(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip() and not line.strip().startswith("#")]


def load_values(inline_values: Optional[Sequence[str]], file_path: Optional[str]) -> List[str]:
    values = list(inline_values or [])
    if file_path:
        values.extend(parse_text_file(file_path))
    seen = set()
    ordered = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _normalize_time_us(time_us: Any) -> Optional[str]:
    """Convert a Jetstream time_us integer to ISO 8601 UTC string."""
    if time_us is None:
        return None
    if isinstance(time_us, int):
        return datetime.fromtimestamp(time_us / 1_000_000, tz=timezone.utc).isoformat()
    return str(time_us)


def extract_blob_ref(image_obj: Dict[str, Any]) -> Optional[str]:
    image_blob = image_obj.get("image") or {}
    ref = image_blob.get("ref")
    if isinstance(ref, dict):
        return ref.get("$link")
    if isinstance(ref, str):
        return ref
    return None


# ---------------------------------------------------------------------------
# Image Embed Extraction (handles images and recordWithMedia)
# ---------------------------------------------------------------------------

def _extract_images_from_embed(
    record_embed: Dict[str, Any],
    view_embed: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return (record_images, view_images) from images or recordWithMedia embed types."""
    embed_type = record_embed.get("$type", "")

    if embed_type == "app.bsky.embed.images":
        return record_embed.get("images") or [], view_embed.get("images") or []

    if embed_type == "app.bsky.embed.recordWithMedia":
        media = record_embed.get("media") or {}
        if media.get("$type") == "app.bsky.embed.images":
            view_media = view_embed.get("media") or {}
            return media.get("images") or [], view_media.get("images") or []

    return [], []


def _extract_images_from_record_embed(embed: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return record-layer images from images or recordWithMedia embed types (no view layer)."""
    embed_type = embed.get("$type", "")
    if embed_type == "app.bsky.embed.images":
        return embed.get("images") or []
    if embed_type == "app.bsky.embed.recordWithMedia":
        media = embed.get("media") or {}
        if media.get("$type") == "app.bsky.embed.images":
            return media.get("images") or []
    return []


# ---------------------------------------------------------------------------
# Row Building and Extraction
# ---------------------------------------------------------------------------

def build_row(
    *,
    source_mode: str,
    record: Dict[str, Any],
    image_obj: Dict[str, Any],
    image_index: int,
    image_count_in_post: int,
    author_handle: Optional[str],
    author_did: Optional[str],
    post_uri: Optional[str],
    post_cid: Optional[str],
    indexed_at: Optional[str],
    query: Optional[str],
    cursor: Optional[str],
    image_thumb_url: Optional[str] = None,
    image_fullsize_url: Optional[str] = None,
) -> AltTextRow:
    alt_text = image_obj.get("alt") or ""
    image_blob = image_obj.get("image") or {}
    return AltTextRow(
        source_mode=source_mode,
        collected_at=utc_now(),
        author_handle=author_handle,
        author_did=author_did,
        post_uri=post_uri,
        post_cid=post_cid,
        indexed_at=indexed_at,
        created_at=record.get("createdAt"),
        text=record.get("text"),
        langs_json=json.dumps(record.get("langs") or [], ensure_ascii=False),
        alt_text=alt_text,
        image_index=image_index,
        image_alt_length=len(alt_text),
        image_count_in_post=image_count_in_post,
        image_mime_type=image_blob.get("mimeType"),
        image_ref=extract_blob_ref(image_obj),
        image_thumb_url=image_thumb_url,
        image_fullsize_url=image_fullsize_url,
        query=query,
        cursor=cursor,
        raw_record_json=json.dumps(record, ensure_ascii=False, separators=(",", ":")),
    )


def extract_rows_from_post(
    post: Dict[str, Any],
    source_mode: str,
    query: Optional[str],
    cursor: Optional[str],
) -> List[AltTextRow]:
    """Extract image alt-text rows from a post object (AppView shape)."""
    record = post.get("record") or {}
    embed = record.get("embed") or {}
    view_embed = post.get("embed") or {}

    record_images, view_images = _extract_images_from_embed(embed, view_embed)
    if not record_images:
        return []

    rows: List[AltTextRow] = []
    author = post.get("author") or {}
    for image_index, image_obj in enumerate(record_images):
        alt_text = image_obj.get("alt")
        if not alt_text:
            continue
        view_image = view_images[image_index] if image_index < len(view_images) else {}
        rows.append(
            build_row(
                source_mode=source_mode,
                record=record,
                image_obj=image_obj,
                image_index=image_index,
                image_count_in_post=len(record_images),
                author_handle=author.get("handle"),
                author_did=author.get("did"),
                post_uri=post.get("uri"),
                post_cid=post.get("cid"),
                indexed_at=post.get("indexedAt"),
                query=query,
                cursor=cursor,
                image_thumb_url=view_image.get("thumb"),
                image_fullsize_url=view_image.get("fullsize"),
            )
        )
    return rows


def extract_rows_from_jetstream_event(event: Dict[str, Any], cursor: Optional[str] = None) -> List[AltTextRow]:
    if event.get("kind") != "commit":
        return []
    if event.get("commit", {}).get("collection") != "app.bsky.feed.post":
        return []
    if event.get("commit", {}).get("operation") not in {"create", "update"}:
        return []

    record = event.get("commit", {}).get("record") or {}
    embed = record.get("embed") or {}

    images = _extract_images_from_record_embed(embed)
    if not images:
        return []

    did = event.get("did")
    commit = event.get("commit") or {}
    post_uri = None
    if did and commit.get("collection") and commit.get("rkey"):
        post_uri = f"at://{did}/{commit['collection']}/{commit['rkey']}"

    rows: List[AltTextRow] = []
    for image_index, image_obj in enumerate(images):
        alt_text = image_obj.get("alt")
        if not alt_text:
            continue
        rows.append(
            build_row(
                source_mode="jetstream",
                record=record,
                image_obj=image_obj,
                image_index=image_index,
                image_count_in_post=len(images),
                author_handle=None,
                author_did=did,
                post_uri=post_uri,
                post_cid=commit.get("cid"),
                indexed_at=_normalize_time_us(event.get("time_us")),
                query=None,
                cursor=cursor,
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Collection: Unified Pagination
# ---------------------------------------------------------------------------

def _paginate_and_collect(
    *,
    writer: DatasetWriter,
    source_mode: str,
    keys: Sequence[str],
    max_posts_per_key: int,
    page_limit: int,
    pause_seconds: float,
    fetch_page: Callable[[str, Optional[str], int], Dict[str, Any]],
    extract_items: Callable[[Dict[str, Any]], List[Dict[str, Any]]],
    dedup_db: Optional[DeduplicationDB] = None,
    checkpoint: Optional[CheckpointStore] = None,
    progress: Optional[ProgressTracker] = None,
) -> Dict[str, int]:
    stats: Dict[str, int] = {"posts_seen": 0, "rows_written": 0, "keys": len(keys)}

    for key in keys:
        cursor = None
        if checkpoint is not None:
            saved = checkpoint.get_cursor(key)
            if saved == "__DONE__":
                logging.info("Skipping completed key: %s", key)
                continue
            cursor = saved

        posts_seen_for_key = 0
        logging.info("Collecting %s for key=%s (cursor=%s)", source_mode, key, cursor)

        try:
            while True:
                payload = fetch_page(key, cursor, page_limit)
                items = extract_items(payload)
                if not items:
                    break

                for item in items:
                    stats["posts_seen"] += 1
                    posts_seen_for_key += 1
                    rows = extract_rows_from_post(item, source_mode=source_mode, query=key, cursor=cursor)
                    for row in rows:
                        if dedup_db is not None and dedup_db.seen(row.post_cid, row.image_index):
                            continue
                        writer.write(row)
                        if dedup_db is not None:
                            dedup_db.mark(row.post_cid, row.image_index)
                        stats["rows_written"] += 1
                    if posts_seen_for_key >= max_posts_per_key:
                        break

                if posts_seen_for_key >= max_posts_per_key:
                    break

                next_cursor = payload.get("cursor")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor

                if checkpoint is not None:
                    checkpoint.save_cursor(key, cursor)

                if progress is not None:
                    progress.tick(stats, key=key, cursor=cursor)

                if pause_seconds:
                    time.sleep(pause_seconds)
        except BlueskyAPIError as exc:
            stats["keys_failed"] = stats.get("keys_failed", 0) + 1
            logging.warning("Skipping key=%s due to API error: HTTP %s (%s)", key, exc.status_code, exc.response_text[:200])
            continue

        if checkpoint is not None:
            checkpoint.save_cursor(key, "__DONE__")

    return stats


def collect_author_feed(
    client: BlueskyClient,
    writer: DatasetWriter,
    actors: Sequence[str],
    max_posts_per_actor: int,
    page_limit: int,
    pause_seconds: float,
    dedup_db: Optional[DeduplicationDB] = None,
    checkpoint: Optional[CheckpointStore] = None,
    progress: Optional[ProgressTracker] = None,
) -> Dict[str, int]:
    def fetch_page(actor: str, cursor: Optional[str], limit: int) -> Dict[str, Any]:
        return client.get_author_feed(actor=actor, cursor=cursor, limit=limit)

    def extract_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [item["post"] for item in (payload.get("feed") or []) if item.get("post")]

    return _paginate_and_collect(
        writer=writer, source_mode="author_feed", keys=actors,
        max_posts_per_key=max_posts_per_actor, page_limit=page_limit,
        pause_seconds=pause_seconds, fetch_page=fetch_page,
        extract_items=extract_items, dedup_db=dedup_db,
        checkpoint=checkpoint, progress=progress,
    )


def collect_search_posts(
    client: BlueskyClient,
    writer: DatasetWriter,
    queries: Sequence[str],
    max_posts_per_query: int,
    page_limit: int,
    pause_seconds: float,
    sort: str,
    since: Optional[str],
    until: Optional[str],
    dedup_db: Optional[DeduplicationDB] = None,
    checkpoint: Optional[CheckpointStore] = None,
    progress: Optional[ProgressTracker] = None,
) -> Dict[str, int]:
    def fetch_page(query: str, cursor: Optional[str], limit: int) -> Dict[str, Any]:
        return client.search_posts(query=query, cursor=cursor, limit=limit, sort=sort, since=since, until=until)

    def extract_items(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        return payload.get("posts") or []

    return _paginate_and_collect(
        writer=writer, source_mode="search_posts", keys=queries,
        max_posts_per_key=max_posts_per_query, page_limit=page_limit,
        pause_seconds=pause_seconds, fetch_page=fetch_page,
        extract_items=extract_items, dedup_db=dedup_db,
        checkpoint=checkpoint, progress=progress,
    )


# ---------------------------------------------------------------------------
# Collection: Jetstream
# ---------------------------------------------------------------------------

def build_jetstream_url(
    base_url: str,
    wanted_collections: Sequence[str],
    wanted_dids: Sequence[str],
    cursor: Optional[int],
) -> str:
    params: List[Tuple[str, str]] = []
    for collection in wanted_collections:
        params.append(("wantedCollections", collection))
    for did in wanted_dids:
        params.append(("wantedDids", did))
    if cursor is not None:
        params.append(("cursor", str(cursor)))
    query = urlencode(params, doseq=True)
    return f"{base_url}?{query}" if query else base_url


def collect_jetstream(
    writer: DatasetWriter,
    jetstream_url: str,
    max_events: int,
    max_rows: int,
    duration_seconds: int,
    wanted_dids: Sequence[str],
    cursor: Optional[int],
    dedup_db: Optional[DeduplicationDB] = None,
    checkpoint: Optional[CheckpointStore] = None,
    progress: Optional[ProgressTracker] = None,
) -> Dict[str, int]:
    if websocket is None:
        raise RuntimeError(
            "Jetstream mode requires the 'websocket-client' package. Install it with: pip install websocket-client"
        )

    deadline = time.time() + duration_seconds if duration_seconds > 0 else None
    stats: Dict[str, int] = {"events_seen": 0, "rows_written": 0}
    last_time_us = cursor
    reconnect_attempt = 0

    while True:
        if deadline is not None and time.time() >= deadline:
            break

        url = build_jetstream_url(
            base_url=jetstream_url,
            wanted_collections=["app.bsky.feed.post"],
            wanted_dids=wanted_dids,
            cursor=last_time_us,
        )
        logging.info("Connecting to %s", url)

        try:
            ws = websocket.create_connection(url, timeout=REQUEST_TIMEOUT)
            events_since_connect = 0
            try:
                while True:
                    if deadline is not None and time.time() >= deadline:
                        break
                    if max_events > 0 and stats["events_seen"] >= max_events:
                        break
                    if max_rows > 0 and stats["rows_written"] >= max_rows:
                        break

                    message = ws.recv()
                    if not message:
                        continue
                    event = json.loads(message)
                    events_since_connect += 1
                    if events_since_connect >= 100:
                        reconnect_attempt = 0
                    stats["events_seen"] += 1

                    time_us = event.get("time_us")
                    if time_us is not None:
                        last_time_us = time_us

                    stream_cursor = str(time_us) if time_us is not None else None
                    rows = extract_rows_from_jetstream_event(event, cursor=stream_cursor)
                    for row in rows:
                        if dedup_db is not None and dedup_db.seen(row.post_cid, row.image_index):
                            continue
                        writer.write(row)
                        if dedup_db is not None:
                            dedup_db.mark(row.post_cid, row.image_index)
                        stats["rows_written"] += 1
                        if max_rows > 0 and stats["rows_written"] >= max_rows:
                            break

                    if checkpoint is not None and stats["events_seen"] % 1000 == 0:
                        checkpoint.save_cursor("__jetstream__", str(last_time_us))

                    if progress is not None:
                        progress.tick(stats, cursor=stream_cursor)
            finally:
                ws.close()
        except Exception as exc:
            is_retryable = isinstance(exc, (OSError, ConnectionError))
            if websocket is not None:
                is_retryable = is_retryable or isinstance(exc, websocket.WebSocketException)
            if not is_retryable or reconnect_attempt >= MAX_RETRIES:
                raise
            wait = BASE_BACKOFF_SECONDS * (2 ** reconnect_attempt)
            logging.warning(
                "Jetstream disconnected: %s. Reconnecting in %.1fs (attempt %d/%d)",
                exc, wait, reconnect_attempt + 1, MAX_RETRIES,
            )
            time.sleep(wait)
            reconnect_attempt += 1
            continue

        break  # normal exit

    if checkpoint is not None and last_time_us is not None:
        checkpoint.save_cursor("__jetstream__", str(last_time_us))

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


def add_shared_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-jsonl", required=True, help="Path to output JSONL file.")
    parser.add_argument("--output-csv", help="Optional path to output CSV file.")
    parser.add_argument("--gzip", action="store_true", help="Compress output files with gzip.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging.")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint, append to existing output, and deduplicate rows.")
    parser.add_argument("--shard-size", type=int, default=0, help="Rotate output files every N rows. 0 means no sharding.")
    parser.add_argument("--progress-interval", type=int, default=1000, help="Log progress every N rows. 0 to disable.")


def add_shared_api_args(parser: argparse.ArgumentParser, default_pause: float = 0.25) -> None:
    parser.add_argument("--page-limit", type=int, default=100, choices=range(1, 101), metavar="1-100")
    parser.add_argument("--pause-seconds", type=float, default=default_pause, help="Delay between paginated requests.")
    parser.add_argument("--appview-base", default=APPVIEW_BASE, help="Bluesky AppView base URL.")
    parser.add_argument("--auth-bearer", default=os.getenv("BLUESKY_BEARER_TOKEN"), help="Optional bearer token.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bulk collect Bluesky image alt text into dataset-friendly files.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    author_parser = subparsers.add_parser("author-feed", help="Collect alt text from one or more author feeds.")
    author_parser.add_argument("--actor", action="append", help="Actor handle or DID. Can be passed multiple times.")
    author_parser.add_argument("--actors-file", help="Text file containing one actor handle/DID per line.")
    author_parser.add_argument("--max-posts-per-actor", type=int, default=500, help="Stop after this many feed items per actor.")
    add_shared_api_args(author_parser, default_pause=0.25)
    add_shared_output_args(author_parser)

    search_parser = subparsers.add_parser("search-posts", help="Collect alt text from search results.")
    search_parser.add_argument("--query", action="append", help="Search query. Can be passed multiple times.")
    search_parser.add_argument("--queries-file", help="Text file containing one query per line.")
    search_parser.add_argument("--max-posts-per-query", type=int, default=500, help="Stop after this many posts per query.")
    search_parser.add_argument("--sort", choices=["latest", "top"], default="latest")
    search_parser.add_argument("--since", help="Optional ISO timestamp or date accepted by the API.")
    search_parser.add_argument("--until", help="Optional ISO timestamp or date accepted by the API.")
    add_shared_api_args(search_parser, default_pause=0.5)
    add_shared_output_args(search_parser)

    jetstream_parser = subparsers.add_parser("jetstream", help="Collect alt text from the live Jetstream stream.")
    jetstream_parser.add_argument("--jetstream-url", default=DEFAULT_JETSTREAM_WS, help="Jetstream websocket URL.")
    jetstream_parser.add_argument("--wanted-did", action="append", help="Optional DID filter. Can be repeated.")
    jetstream_parser.add_argument("--wanted-dids-file", help="Text file containing one DID per line.")
    jetstream_parser.add_argument("--cursor", type=int, help="Optional unix microseconds cursor to begin playback from.")
    jetstream_parser.add_argument("--duration-seconds", type=int, default=300, help="Stop after this many seconds. Set 0 for unlimited.")
    jetstream_parser.add_argument("--max-events", type=int, default=0, help="Stop after this many Jetstream events. 0 means unlimited.")
    jetstream_parser.add_argument("--max-rows", type=int, default=1000, help="Stop after this many dataset rows. 0 means unlimited.")
    add_shared_output_args(jetstream_parser)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.verbose)

    checkpoint = None
    dedup_db = None
    append = False

    if args.resume:
        append = True
        checkpoint_path = _derive_checkpoint_path(args.output_jsonl)
        os.makedirs(os.path.dirname(os.path.abspath(checkpoint_path)), exist_ok=True)
        checkpoint = CheckpointStore(checkpoint_path)
        dedup_path = _derive_dedup_path(args.output_jsonl)
        dedup_db = DeduplicationDB(dedup_path)

    progress = None
    if args.progress_interval > 0:
        progress = ProgressTracker(interval=args.progress_interval)

    try:
        with DatasetWriter(
            args.output_jsonl,
            args.output_csv,
            compress=args.gzip,
            append=append,
            shard_size=args.shard_size,
        ) as writer:
            if args.mode == "author-feed":
                actors = load_values(args.actor, args.actors_file)
                if not actors:
                    parser.error("author-feed requires at least one --actor or --actors-file entry")
                client = BlueskyClient(appview_base=args.appview_base, auth_bearer=args.auth_bearer)
                stats = collect_author_feed(
                    client=client,
                    writer=writer,
                    actors=actors,
                    max_posts_per_actor=args.max_posts_per_actor,
                    page_limit=args.page_limit,
                    pause_seconds=args.pause_seconds,
                    dedup_db=dedup_db,
                    checkpoint=checkpoint,
                    progress=progress,
                )
            elif args.mode == "search-posts":
                queries = load_values(args.query, args.queries_file)
                if not queries:
                    parser.error("search-posts requires at least one --query or --queries-file entry")
                client = BlueskyClient(appview_base=args.appview_base, auth_bearer=args.auth_bearer)
                stats = collect_search_posts(
                    client=client,
                    writer=writer,
                    queries=queries,
                    max_posts_per_query=args.max_posts_per_query,
                    page_limit=args.page_limit,
                    pause_seconds=args.pause_seconds,
                    sort=args.sort,
                    since=args.since,
                    until=args.until,
                    dedup_db=dedup_db,
                    checkpoint=checkpoint,
                    progress=progress,
                )
            elif args.mode == "jetstream":
                wanted_dids = load_values(args.wanted_did, args.wanted_dids_file)
                js_cursor = args.cursor
                if js_cursor is None and checkpoint is not None:
                    js_cursor = checkpoint.get_jetstream_cursor()
                stats = collect_jetstream(
                    writer=writer,
                    jetstream_url=args.jetstream_url,
                    max_events=args.max_events,
                    max_rows=args.max_rows,
                    duration_seconds=args.duration_seconds,
                    wanted_dids=wanted_dids,
                    cursor=js_cursor,
                    dedup_db=dedup_db,
                    checkpoint=checkpoint,
                    progress=progress,
                )
            else:  # pragma: no cover
                parser.error(f"Unknown mode: {args.mode}")
    except (requests.ConnectionError, requests.Timeout) as exc:
        logging.error("Network error after retries exhausted: %s", exc)
        return 1
    except BlueskyAPIError as exc:
        if exc.endpoint == "app.bsky.feed.searchPosts" and exc.status_code == 403:
            logging.error(
                "Search mode was rejected with HTTP 403. This endpoint may require authentication on the selected host. "
                "Supply --auth-bearer or set BLUESKY_BEARER_TOKEN, or use author-feed / jetstream mode instead. URL=%s",
                exc.url,
            )
        else:
            logging.error(
                "API request failed for %s with HTTP %s. URL=%s Response=%s",
                exc.endpoint,
                exc.status_code,
                exc.url,
                exc.response_text,
            )
        return 1
    finally:
        if dedup_db is not None:
            dedup_db.close()

    logging.info("Finished with stats: %s", json.dumps(stats, ensure_ascii=False))
    logging.info("Rows written: %s", writer.row_count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
