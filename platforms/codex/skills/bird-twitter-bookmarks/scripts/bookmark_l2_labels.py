#!/usr/bin/env python3
"""Bookmark L2 labeling pipeline for Field Theory data.

Workflow:
1) Expand link context (title/description/domain) for unknown bookmarks.
2) Classify L2 labels with model (codex/claude) when available, else heuristics.
3) Persist labels and low-confidence review queue into local SQLite tables.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, build_opener


ALLOWED_LABELS = [
    "agent-framework",
    "memory",
    "benchmark-eval",
    "tooling",
    "workflow",
    "prompting",
    "infra",
    "research",
    "news",
    "resource",
]

KEYWORD_MAP: dict[str, list[str]] = {
    "agent-framework": [
        "agent", "agents", "multi-agent", "orchestr", "langgraph", "autogen", "crewai", "workflow agent",
        "智能体", "代理", "多智能体", "编排", "agent loop"
    ],
    "memory": [
        "memory", "mempalace", "longmem", "long memory", "context", "rag", "retrieval", "vector",
        "记忆", "长记忆", "长期记忆", "上下文记忆", "记忆系统"
    ],
    "benchmark-eval": [
        "benchmark", "eval", "leaderboard", "sota", "score", "accuracy", "longmemeval", "arena",
        "基准", "基准测试", "评测", "测评", "榜单", "满分", "评分"
    ],
    "tooling": [
        "tool", "cli", "sdk", "github", "repo", "open source", "extension", "plugin", "library",
        "工具", "开源", "仓库", "项目", "插件", "脚手架"
    ],
    "workflow": [
        "workflow", "automation", "pipeline", "integration", "process", "ops", "playbook",
        "工作流", "流程", "自动化", "编排流程", "流水线"
    ],
    "prompting": [
        "prompt", "system prompt", "instruction", "reasoning pattern", "few-shot", "chain of thought",
        "提示词", "系统提示", "系统指令", "prompt engineering", "提示工程"
    ],
    "infra": [
        "inference", "serving", "latency", "throughput", "gpu", "vllm", "docker", "k8s", "kubernetes",
        "推理", "部署", "延迟", "吞吐", "算力", "infra", "基础设施"
    ],
    "research": [
        "paper", "arxiv", "study", "preprint", "method", "ablation",
        "论文", "研究", "实验", "方法", "预印本", "学术"
    ],
    "news": [
        "launch", "announced", "release", "just shipped", "breaking", "today", "new model",
        "发布", "上线", "宣布", "刚刚", "更新", "新版本", "开源了"
    ],
    "resource": [
        "tutorial", "guide", "docs", "course", "handbook", "cheatsheet", "collection", "list",
        "教程", "指南", "文档", "课程", "合集", "清单", "资源"
    ],
}


@dataclass
class BookmarkRow:
    id: str
    url: str
    text: str
    author_handle: str | None
    links_json: str | None
    primary_category: str | None
    primary_domain: str | None


@dataclass
class LinkContext:
    source_url: str | None
    resolved_url: str | None
    final_domain: str | None
    title: str | None
    summary: str | None
    fetch_status: str


@dataclass
class LabelResult:
    labels: list[str]
    primary: str
    confidence: float
    reason: str
    source: str


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def informative_char_count(text: str) -> int:
    if not text:
        return 0
    no_urls = re.sub(r"https?://\S+|www\.\S+", " ", text, flags=re.IGNORECASE)
    no_handles = re.sub(r"[@#][\w_]+", " ", no_urls)
    kept = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", no_handles)
    return len(kept)


def is_low_context_signal(
    *,
    text: str,
    oembed_text: str | None,
    title: str | None,
    summary: str | None,
    min_chars: int,
) -> bool:
    merged = " ".join([text or "", oembed_text or "", title or "", summary or ""]).strip()
    return informative_char_count(merged) < min_chars


def parse_json_array(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(v) for v in value if isinstance(v, (str, int, float))]
    except Exception:
        return []
    return []


def choose_engine(preferred: str) -> str | None:
    if preferred in {"none", ""}:
        return None
    if preferred in {"codex", "claude"}:
        return preferred if shutil.which(preferred) else None

    # auto: prefer codex first, then claude
    if shutil.which("codex"):
        return "codex"
    if shutil.which("claude"):
        return "claude"
    return None


def ensure_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bookmark_link_context (
          bookmark_id TEXT PRIMARY KEY,
          source_url TEXT,
          resolved_url TEXT,
          final_domain TEXT,
          title TEXT,
          summary TEXT,
          fetch_status TEXT NOT NULL,
          fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bookmark_labels (
          bookmark_id TEXT NOT NULL,
          label_type TEXT NOT NULL,
          label TEXT NOT NULL,
          confidence REAL,
          source TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (bookmark_id, label_type, label)
        );

        CREATE INDEX IF NOT EXISTS idx_bookmark_labels_type_label
          ON bookmark_labels(label_type, label);

        CREATE TABLE IF NOT EXISTS bookmark_review_queue (
          bookmark_id TEXT PRIMARY KEY,
          reason TEXT NOT NULL,
          score REAL,
          payload_json TEXT,
          updated_at TEXT NOT NULL
        );

        CREATE VIEW IF NOT EXISTS bookmarks_l2_view AS
        SELECT
          b.id,
          b.url,
          b.author_handle,
          b.primary_category,
          b.primary_domain,
          GROUP_CONCAT(CASE WHEN l.label_type='l2' THEN l.label END, ',') AS l2_labels,
          MAX(CASE WHEN l.label_type='l2-primary' THEN l.label END) AS l2_primary,
          MAX(CASE WHEN l.label_type='l2-primary' THEN l.confidence END) AS l2_confidence,
          rq.reason AS review_reason
        FROM bookmarks b
        LEFT JOIN bookmark_labels l ON l.bookmark_id=b.id
        LEFT JOIN bookmark_review_queue rq ON rq.bookmark_id=b.id
        GROUP BY b.id;
        """
    )
    conn.commit()


def fetch_unknown_bookmarks(conn: sqlite3.Connection, category: str, limit: int) -> list[BookmarkRow]:
    sql = textwrap.dedent(
        """
        SELECT id, url, text, author_handle, links_json, primary_category, primary_domain
        FROM bookmarks
        WHERE primary_category = ?
        ORDER BY COALESCE(bookmarked_at, posted_at) DESC
        """
    )
    params: list[Any] = [category]
    if limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    return [
        BookmarkRow(
            id=str(r[0]),
            url=str(r[1] or ""),
            text=str(r[2] or ""),
            author_handle=r[3],
            links_json=r[4],
            primary_category=r[5],
            primary_domain=r[6],
        )
        for r in rows
    ]


def extract_meta(html: str) -> tuple[str | None, str | None]:
    title = None
    desc = None

    patterns_title = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
        r"<title[^>]*>(.*?)</title>",
    ]
    patterns_desc = [
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:description["\'][^>]+content=["\']([^"\']+)["\']',
    ]

    for p in patterns_title:
        m = re.search(p, html, flags=re.IGNORECASE | re.DOTALL)
        if m:
            title = normalize_space(m.group(1))
            break

    for p in patterns_desc:
        m = re.search(p, html, flags=re.IGNORECASE | re.DOTALL)
        if m:
            desc = normalize_space(m.group(1))
            break

    if title:
        title = re.sub(r"<[^>]+>", "", title)
    if desc:
        desc = re.sub(r"<[^>]+>", "", desc)

    return title, desc


def resolve_link_context(source_url: str | None, timeout: int = 12) -> LinkContext:
    if not source_url:
        return LinkContext(None, None, None, None, None, "missing-url")

    opener = build_opener()
    req = Request(
        source_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            final_domain = urlparse(final_url).hostname or ""
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type:
                return LinkContext(source_url, final_url, final_domain, None, None, f"non-html:{content_type or 'unknown'}")

            data = resp.read(250_000)
            html = data.decode("utf-8", errors="ignore")
            title, desc = extract_meta(html)
            status = "ok" if (title or desc) else "html-no-meta"
            return LinkContext(source_url, final_url, final_domain, title, desc, status)
    except Exception as exc:
        return LinkContext(source_url, source_url, urlparse(source_url).hostname, None, None, f"error:{exc.__class__.__name__}")


def fetch_oembed_text(tweet_url: str, timeout: int = 8) -> tuple[str | None, str | None]:
    if not tweet_url:
        return None, None

    endpoint = f"https://publish.twitter.com/oembed?omit_script=1&url={tweet_url}"
    opener = build_opener()
    req = Request(
        endpoint,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        },
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return None, None

    html = str(payload.get("html") or "")
    if not html:
        return None, None

    text = re.sub(r"<[^>]+>", " ", html)
    text = text.replace("&mdash;", " ")
    text = normalize_space(text)
    author = str(payload.get("author_name") or "").strip() or None
    if len(text) > 600:
        text = text[:600]
    return text or None, author


def heuristic_classify(payload: str) -> LabelResult:
    text = payload.lower()
    scores: dict[str, int] = {k: 0 for k in ALLOWED_LABELS}
    for label, keywords in KEYWORD_MAP.items():
        for kw in keywords:
            if kw in text:
                scores[label] += 1

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = [item for item in ranked if item[1] > 0][:3]

    if not top:
        return LabelResult(
            labels=["resource"],
            primary="resource",
            confidence=0.42,
            reason="no-strong-keyword-fallback",
            source="auto:heuristic",
        )

    labels = [name for name, _ in top]
    primary = labels[0]
    top_score = top[0][1]
    confidence = min(0.92, 0.62 + top_score * 0.10)

    return LabelResult(
        labels=labels,
        primary=primary,
        confidence=round(confidence, 3),
        reason=f"keyword-match:{primary}:{top_score}",
        source="auto:heuristic",
    )


def run_engine(engine: str, prompt: str) -> str:
    if engine == "claude":
        cmd = ["claude", "-p", "--output-format", "text", prompt]
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=180).strip()
    cmd = ["codex", "exec", prompt]
    return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=180).strip()


def run_engine_with_profile(
    engine: str,
    prompt: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    timeout: int = 240,
) -> str:
    if engine == "claude":
        cmd = ["claude", "-p", "--output-format", "text", prompt]
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout).strip()

    resolved_model = model or "gpt-5.4-mini"
    with tempfile.NamedTemporaryFile(prefix="codex-last-", suffix=".txt", delete=False) as tmp:
        out_path = tmp.name
    try:
        cmd = ["codex", "exec", "-m", resolved_model]
        if effort:
            cmd += ["-c", f"model_reasoning_effort='{effort}'"]
        cmd += ["-o", out_path, prompt]
        subprocess.run(
            cmd,
            check=True,
            text=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return Path(out_path).read_text(encoding="utf-8", errors="ignore").strip()
    finally:
        try:
            Path(out_path).unlink(missing_ok=True)
        except Exception:
            pass


def parse_model_json(raw: str) -> list[dict[str, Any]]:
    m = re.search(r"\[[\s\S]*\]", raw)
    if not m:
        raise ValueError("model response has no JSON array")
    obj = json.loads(m.group(0))
    if not isinstance(obj, list):
        raise ValueError("model response is not a JSON array")
    return obj


def classify_with_model(
    engine: str,
    batch: list[dict[str, Any]],
    *,
    model: str | None = None,
    effort: str | None = None,
    timeout: int = 240,
) -> dict[str, LabelResult]:
    items = []
    for item in batch:
        context = item["context"].replace("\n", " ")[:1200]
        items.append(f"id={item['id']} | context={context}")

    prompt = textwrap.dedent(
        f"""
        You are labeling X bookmarks into a fixed L2 taxonomy.

        Allowed labels (choose 1-3 only from this list):
        {", ".join(ALLOWED_LABELS)}

        Return only valid JSON array:
        [
          {{"id":"...","labels":["..."],"primary":"...","confidence":0.0,"reason":"..."}}
        ]

        Constraints:
        - labels must be from allowed list only
        - primary must be one of labels
        - confidence must be 0~1
        - no markdown

        Bookmarks:
        {chr(10).join(items)}
        """
    ).strip()

    raw = run_engine_with_profile(engine, prompt, model=model, effort=effort, timeout=timeout)
    arr = parse_model_json(raw)

    out: dict[str, LabelResult] = {}
    for row in arr:
        bid = str(row.get("id", "")).strip()
        if not bid:
            continue
        raw_labels = row.get("labels") or []
        labels = [str(x).strip().lower() for x in raw_labels if str(x).strip().lower() in ALLOWED_LABELS]
        if not labels:
            continue
        primary = str(row.get("primary", labels[0])).strip().lower()
        if primary not in labels:
            primary = labels[0]
        try:
            conf = float(row.get("confidence", 0.5))
        except Exception:
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        reason = str(row.get("reason", "model")).strip()[:200]
        source = f"auto:{engine}"
        if engine == "codex":
            source = f"auto:{engine}:{model or 'default'}:{effort or 'default'}"
        out[bid] = LabelResult(
            labels=list(dict.fromkeys(labels[:3])),
            primary=primary,
            confidence=round(conf, 3),
            reason=reason or "model",
            source=source,
        )
    return out


def run_model_batches(
    *,
    engine: str,
    prepared: list[dict[str, Any]],
    batch_size: int,
    verbose: bool,
    model: str | None,
    effort: str | None,
    timeout: int,
    pass_name: str,
) -> tuple[dict[str, LabelResult], int]:
    out: dict[str, LabelResult] = {}
    failed_batches = 0
    for i in range(0, len(prepared), batch_size):
        batch = prepared[i : i + batch_size]
        try:
            batch_out = classify_with_model(
                engine,
                batch,
                model=model,
                effort=effort,
                timeout=timeout,
            )
            out.update(batch_out)
        except Exception as exc:
            failed_batches += 1
            if verbose:
                idx = i // batch_size + 1
                print(f"{pass_name} batch {idx} failed: {exc}", file=sys.stderr)
    return out, failed_batches


def save_link_context(conn: sqlite3.Connection, bookmark_id: str, context: LinkContext) -> None:
    conn.execute(
        """
        INSERT INTO bookmark_link_context(
          bookmark_id, source_url, resolved_url, final_domain, title, summary, fetch_status, fetched_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(bookmark_id) DO UPDATE SET
          source_url=excluded.source_url,
          resolved_url=excluded.resolved_url,
          final_domain=excluded.final_domain,
          title=excluded.title,
          summary=excluded.summary,
          fetch_status=excluded.fetch_status,
          fetched_at=excluded.fetched_at
        """,
        (
            bookmark_id,
            context.source_url,
            context.resolved_url,
            context.final_domain,
            context.title,
            context.summary,
            context.fetch_status,
            utc_now(),
        ),
    )


def save_labels(
    conn: sqlite3.Connection,
    bookmark_id: str,
    result: LabelResult,
    min_confidence: float,
    dry_run: bool,
) -> None:
    payload = {
        "labels": result.labels,
        "primary": result.primary,
        "confidence": result.confidence,
        "reason": result.reason,
        "source": result.source,
    }

    if dry_run:
        return

    now = utc_now()
    conn.execute(
        "DELETE FROM bookmark_labels WHERE bookmark_id=? AND label_type IN ('l2','l2-primary') AND source LIKE 'auto:%'",
        (bookmark_id,),
    )

    for label in result.labels:
        conn.execute(
            """
            INSERT INTO bookmark_labels(bookmark_id, label_type, label, confidence, source, updated_at)
            VALUES (?, 'l2', ?, ?, ?, ?)
            ON CONFLICT(bookmark_id, label_type, label) DO UPDATE SET
              confidence=excluded.confidence,
              source=excluded.source,
              updated_at=excluded.updated_at
            """,
            (bookmark_id, label, result.confidence, result.source, now),
        )

    conn.execute(
        """
        INSERT INTO bookmark_labels(bookmark_id, label_type, label, confidence, source, updated_at)
        VALUES (?, 'l2-primary', ?, ?, ?, ?)
        ON CONFLICT(bookmark_id, label_type, label) DO UPDATE SET
          confidence=excluded.confidence,
          source=excluded.source,
          updated_at=excluded.updated_at
        """,
        (bookmark_id, result.primary, result.confidence, result.source, now),
    )

    if result.confidence < min_confidence:
        conn.execute(
            """
            INSERT INTO bookmark_review_queue(bookmark_id, reason, score, payload_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(bookmark_id) DO UPDATE SET
              reason=excluded.reason,
              score=excluded.score,
              payload_json=excluded.payload_json,
              updated_at=excluded.updated_at
            """,
            (bookmark_id, f"low-confidence<{min_confidence}", result.confidence, json.dumps(payload, ensure_ascii=False), now),
        )
    else:
        conn.execute("DELETE FROM bookmark_review_queue WHERE bookmark_id=?", (bookmark_id,))


def build_context_text(row: BookmarkRow, link: LinkContext, oembed_text: str | None = None, oembed_author: str | None = None) -> str:
    parts = [
        f"author:{row.author_handle or 'unknown'}",
        f"text:{normalize_space(row.text)}",
        f"domain:{link.final_domain or ''}",
        f"title:{link.title or ''}",
        f"summary:{link.summary or ''}",
        f"url:{link.resolved_url or link.source_url or ''}",
        f"tweet_url:{row.url}",
        f"oembed_author:{oembed_author or ''}",
        f"oembed_text:{oembed_text or ''}",
    ]
    return " | ".join(parts)


def classify_unknown(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    ensure_tables(conn)

    rows = fetch_unknown_bookmarks(conn, args.category, args.limit)
    if not rows:
        print("No unknown bookmarks found.")
        return 0

    engine = choose_engine(args.engine)
    if args.verbose:
        print(f"Selected engine: {engine or 'none'}")

    prepared: list[dict[str, Any]] = []
    for row in rows:
        links = parse_json_array(row.links_json)
        source_url = links[0] if links else None
        if args.use_link_fetch:
            ctx = resolve_link_context(source_url, timeout=args.fetch_timeout)
        else:
            ctx = LinkContext(source_url, source_url, urlparse(source_url).hostname if source_url else None, None, None, "skipped")
        oembed_text = None
        oembed_author = None
        if args.use_oembed and (not ctx.title and not ctx.summary):
            oembed_text, oembed_author = fetch_oembed_text(row.url, timeout=min(8, args.fetch_timeout + 4))

        if not args.dry_run:
            save_link_context(conn, row.id, ctx)
        low_context = is_low_context_signal(
            text=row.text,
            oembed_text=oembed_text,
            title=ctx.title,
            summary=ctx.summary,
            min_chars=args.min_context_chars,
        )
        prepared.append(
            {
                "id": row.id,
                "row": row,
                "link": ctx,
                "context": build_context_text(row, ctx, oembed_text, oembed_author),
                "low_context": low_context,
            }
        )

    model_results: dict[str, LabelResult] = {}
    model_failed_batches = 0
    stage2_candidates = 0
    stage2_overrides = 0

    if engine:
        model_results, model_failed_batches = run_model_batches(
            engine=engine,
            prepared=prepared,
            batch_size=args.batch_size,
            verbose=args.verbose,
            model=args.stage1_model,
            effort=args.stage1_effort,
            timeout=args.model_timeout,
            pass_name="stage1",
        )

        if args.two_stage and model_results:
            stage2_ids = {bid for bid, res in model_results.items() if res.confidence < args.min_confidence}
            if stage2_ids:
                stage2_candidates = len(stage2_ids)
                stage2_input = [item for item in prepared if item["id"] in stage2_ids]
                stage2_results, stage2_failed = run_model_batches(
                    engine=engine,
                    prepared=stage2_input,
                    batch_size=max(1, args.stage2_batch_size),
                    verbose=args.verbose,
                    model=args.stage2_model,
                    effort=args.stage2_effort,
                    timeout=max(args.model_timeout, args.stage2_timeout),
                    pass_name="stage2",
                )
                model_failed_batches += stage2_failed
                stage2_overrides = len(stage2_results)
                for bid, result in stage2_results.items():
                    model_results[bid] = result

    wrote = 0
    low_conf = 0
    fallback_count = 0
    low_context_items = 0

    for item in prepared:
        bid = item["id"]
        result = model_results.get(bid)
        if not result:
            fallback_count += 1
            result = heuristic_classify(item["context"])

        if item.get("low_context"):
            low_context_items += 1
            capped_conf = min(result.confidence, args.low_context_cap)
            if capped_conf != result.confidence:
                result = LabelResult(
                    labels=result.labels,
                    primary=result.primary,
                    confidence=round(capped_conf, 3),
                    reason=f"{result.reason}|low-context",
                    source=result.source,
                )

        if result.confidence < args.min_confidence:
            low_conf += 1

        save_labels(conn, bid, result, args.min_confidence, args.dry_run)
        wrote += 1

        if args.verbose:
            print(
                f"{bid} -> primary={result.primary}, labels={','.join(result.labels)}, "
                f"conf={result.confidence:.2f}, source={result.source}"
            )

    if not args.dry_run:
        conn.commit()

    print("L2 classify complete")
    print(f"- processed: {len(rows)}")
    print(f"- labeled: {wrote}")
    print(f"- low-confidence queued: {low_conf}")
    print(f"- heuristic fallback used: {fallback_count}")
    print(f"- engine: {engine or 'none'}")
    print(f"- model failed batches: {model_failed_batches}")
    if engine:
        print(
            f"- stage1 profile: {args.stage1_model}/{args.stage1_effort} | "
            f"stage2 profile: {args.stage2_model}/{args.stage2_effort} | two-stage: {args.two_stage}"
        )
        print(f"- stage2 candidates: {stage2_candidates}")
        print(f"- stage2 overrides: {stage2_overrides}")
    print(f"- low-context capped: {low_context_items} (cap={args.low_context_cap})")
    print(f"- dry-run: {args.dry_run}")
    return 0


def show_report(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    ensure_tables(conn)

    total = conn.execute("SELECT COUNT(*) FROM bookmarks").fetchone()[0]
    unknown = conn.execute("SELECT COUNT(*) FROM bookmarks WHERE primary_category='unknown'").fetchone()[0]
    l2_primary = conn.execute(
        "SELECT COUNT(DISTINCT bookmark_id) FROM bookmark_labels WHERE label_type='l2-primary'"
    ).fetchone()[0]
    queued = conn.execute("SELECT COUNT(*) FROM bookmark_review_queue").fetchone()[0]

    print("L2 label report")
    print(f"- total bookmarks: {total}")
    print(f"- unknown (L1): {unknown}")
    print(f"- with L2 primary: {l2_primary}")
    print(f"- review queue: {queued}")

    print("\nTop L2 primary labels")
    rows = conn.execute(
        """
        SELECT label, COUNT(*)
        FROM bookmark_labels
        WHERE label_type='l2-primary'
        GROUP BY label
        ORDER BY COUNT(*) DESC, label ASC
        LIMIT 20
        """
    ).fetchall()
    if not rows:
        print("- (none)")
    else:
        for label, cnt in rows:
            print(f"- {label}: {cnt}")
    return 0


def show_review_queue(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(db_path)
    ensure_tables(conn)

    sql = textwrap.dedent(
        """
        SELECT rq.bookmark_id, rq.score, rq.reason, b.author_handle, b.url, substr(b.text, 1, 120)
        FROM bookmark_review_queue rq
        LEFT JOIN bookmarks b ON b.id = rq.bookmark_id
        ORDER BY COALESCE(rq.score, 0) ASC, rq.updated_at DESC
        LIMIT ?
        """
    )
    rows = conn.execute(sql, (args.limit,)).fetchall()

    if not rows:
        print("Review queue is empty.")
        return 0

    for row in rows:
        bid, score, reason, author, url, text = row
        print(f"{bid}  conf={score if score is not None else 'n/a'}  {reason}")
        print(f"  @{author or '?'}  {url or ''}")
        print(f"  {normalize_space(text or '')}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="L2 labeling pipeline for ft bookmarks")
    parser.add_argument("--db", default="~/.ft-bookmarks/bookmarks.db", help="SQLite path (default: ~/.ft-bookmarks/bookmarks.db)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_bootstrap = sub.add_parser("bootstrap", help="Create local tables/views used by L2 labeling")
    p_bootstrap.set_defaults(func=lambda args: bootstrap_only(args))

    p_classify = sub.add_parser("classify-unknown", help="Classify unknown bookmarks into local L2 labels")
    p_classify.add_argument("--category", default="unknown", help="L1 category filter (default: unknown)")
    p_classify.add_argument("--limit", type=int, default=0, help="Max rows to process; 0 means all")
    p_classify.add_argument("--engine", default="auto", choices=["auto", "codex", "claude", "none"], help="Model engine")
    p_classify.add_argument("--batch-size", type=int, default=20, help="Model batch size")
    p_classify.add_argument("--min-confidence", type=float, default=0.7, help="Below this goes to review queue")
    p_classify.add_argument("--model-timeout", type=int, default=240, help="Model call timeout seconds")
    p_classify.add_argument("--two-stage", action="store_true", default=True, help="Enable second-pass reclassification for low confidence")
    p_classify.add_argument("--single-stage", action="store_false", dest="two_stage", help="Disable second-pass reclassification")
    p_classify.add_argument("--stage1-model", default="gpt-5.4-mini", help="Stage1 model for codex engine")
    p_classify.add_argument("--stage1-effort", default="medium", choices=["low", "medium", "high", "xhigh"], help="Stage1 reasoning effort for codex")
    p_classify.add_argument("--stage2-model", default="gpt-5.4-mini", help="Stage2 model for codex engine")
    p_classify.add_argument("--stage2-effort", default="high", choices=["low", "medium", "high", "xhigh"], help="Stage2 reasoning effort for codex")
    p_classify.add_argument("--stage2-batch-size", type=int, default=10, help="Stage2 model batch size")
    p_classify.add_argument("--stage2-timeout", type=int, default=300, help="Stage2 model timeout seconds")
    p_classify.add_argument("--min-context-chars", type=int, default=24, help="Treat as low-context if informative chars are below this threshold")
    p_classify.add_argument("--low-context-cap", type=float, default=0.55, help="Max confidence for low-context items")
    p_classify.add_argument("--fetch-timeout", type=int, default=12, help="HTTP timeout seconds when expanding link context")
    p_classify.add_argument("--skip-link-fetch", action="store_false", dest="use_link_fetch", default=True, help="Skip source-link HTML fetch (faster)")
    p_classify.add_argument("--use-oembed", action="store_true", default=True, help="Use Twitter oEmbed as fallback text source")
    p_classify.add_argument("--no-oembed", action="store_false", dest="use_oembed", help="Disable Twitter oEmbed fallback")
    p_classify.add_argument("--dry-run", action="store_true", help="Compute only, do not write")
    p_classify.add_argument("--verbose", action="store_true", help="Verbose logs")
    p_classify.set_defaults(func=classify_unknown)

    p_report = sub.add_parser("report", help="Show L2 coverage and top labels")
    p_report.set_defaults(func=show_report)

    p_review = sub.add_parser("review", help="List low-confidence review queue")
    p_review.add_argument("--limit", type=int, default=30, help="Max rows")
    p_review.set_defaults(func=show_review_queue)

    return parser


def bootstrap_only(args: argparse.Namespace) -> int:
    db_path = Path(args.db).expanduser()
    if not db_path.exists():
        print(f"DB not found: {db_path}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(db_path)
    ensure_tables(conn)
    conn.commit()
    print("L2 tables/views are ready.")
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
