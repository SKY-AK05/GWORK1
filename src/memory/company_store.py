"""Durable, evidence-linked company intelligence memory.

This store is intentionally separate from the short-lived page/search cache. Every
claim and structured observation is append-only and points to a stored source.
Previous model conclusions are never promoted to verified facts automatically.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB = Path(os.getenv("COMPANY_MEMORY_DB", "~/.cache/deepresearch/company_intelligence.sqlite3")).expanduser()
SCHEMA_VERSION = "1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-") or "unknown"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class CompanyMemoryStore:
    def __init__(self, db_path: str | Path = DEFAULT_DB) -> None:
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profiles (
                    id INTEGER PRIMARY KEY, canonical_key TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL, jurisdiction TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, url TEXT NOT NULL,
                    title TEXT, platform TEXT, source_category TEXT, publication_date TEXT,
                    retrieved_at TEXT NOT NULL, UNIQUE(profile_id, url, retrieved_at),
                    FOREIGN KEY(profile_id) REFERENCES profiles(id)
                );
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, entity_type TEXT NOT NULL,
                    name TEXT NOT NULL, jurisdiction TEXT, registration_number TEXT, website TEXT,
                    status TEXT, confidence TEXT NOT NULL, verification_status TEXT NOT NULL,
                    observed_at TEXT NOT NULL, source_id INTEGER, evidence_excerpt TEXT,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id), FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE TABLE IF NOT EXISTS aliases (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, alias TEXT NOT NULL,
                    alias_type TEXT, confidence TEXT NOT NULL, verification_status TEXT NOT NULL,
                    observed_at TEXT NOT NULL, source_id INTEGER, evidence_excerpt TEXT,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id), FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE TABLE IF NOT EXISTS relationships (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, from_name TEXT NOT NULL,
                    relationship_type TEXT NOT NULL, to_name TEXT NOT NULL, confidence TEXT NOT NULL,
                    verification_status TEXT NOT NULL, observed_at TEXT NOT NULL, source_id INTEGER,
                    evidence_excerpt TEXT, FOREIGN KEY(profile_id) REFERENCES profiles(id), FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, name TEXT NOT NULL,
                    description TEXT, confidence TEXT NOT NULL, verification_status TEXT NOT NULL,
                    observed_at TEXT NOT NULL, source_id INTEGER, evidence_excerpt TEXT,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id), FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE TABLE IF NOT EXISTS customers (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, name TEXT NOT NULL,
                    relationship_type TEXT, confidence TEXT NOT NULL, verification_status TEXT NOT NULL,
                    observed_at TEXT NOT NULL, source_id INTEGER, evidence_excerpt TEXT,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id), FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE TABLE IF NOT EXISTS people (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, name TEXT NOT NULL,
                    person_type TEXT, confidence TEXT NOT NULL, verification_status TEXT NOT NULL,
                    observed_at TEXT NOT NULL, source_id INTEGER, evidence_excerpt TEXT,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id), FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE TABLE IF NOT EXISTS role_changes (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, person_name TEXT NOT NULL,
                    role TEXT, change_type TEXT NOT NULL, event_date TEXT, confidence TEXT NOT NULL,
                    verification_status TEXT NOT NULL, observed_at TEXT NOT NULL, source_id INTEGER,
                    evidence_excerpt TEXT, FOREIGN KEY(profile_id) REFERENCES profiles(id), FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE TABLE IF NOT EXISTS dated_events (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, event_type TEXT NOT NULL,
                    event_date TEXT, description TEXT NOT NULL, confidence TEXT NOT NULL,
                    verification_status TEXT NOT NULL, observed_at TEXT NOT NULL, source_id INTEGER,
                    evidence_excerpt TEXT, FOREIGN KEY(profile_id) REFERENCES profiles(id), FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE TABLE IF NOT EXISTS claims (
                    id INTEGER PRIMARY KEY, profile_id INTEGER NOT NULL, subject TEXT NOT NULL,
                    predicate TEXT NOT NULL, object_value TEXT NOT NULL, claim_status TEXT NOT NULL,
                    confidence TEXT NOT NULL, verification_status TEXT NOT NULL, observed_at TEXT NOT NULL,
                    source_id INTEGER NOT NULL, evidence_excerpt TEXT NOT NULL,
                    FOREIGN KEY(profile_id) REFERENCES profiles(id), FOREIGN KEY(source_id) REFERENCES sources(id)
                );
                CREATE INDEX IF NOT EXISTS idx_claims_profile ON claims(profile_id, subject, predicate);
                CREATE INDEX IF NOT EXISTS idx_sources_profile ON sources(profile_id, retrieved_at);
                CREATE INDEX IF NOT EXISTS idx_events_profile ON dated_events(profile_id, event_date);
                INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1.0');
                """
            )

    def _profile(self, conn: sqlite3.Connection, company_name: str, jurisdiction: str | None) -> int:
        key = f"{normalize_key(company_name)}:{normalize_key(jurisdiction or '')}"
        now = utc_now()
        conn.execute(
            "INSERT INTO profiles(canonical_key, display_name, jurisdiction, created_at, updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(canonical_key) DO UPDATE SET updated_at=excluded.updated_at",
            (key, company_name.strip() or "Unknown", jurisdiction, now, now),
        )
        return int(conn.execute("SELECT id FROM profiles WHERE canonical_key=?", (key,)).fetchone()[0])

    def _source(self, conn: sqlite3.Connection, profile_id: int, item: dict[str, Any], retrieved_at: str | None = None) -> int:
        url = str(item.get("url") or item.get("source_url") or "").strip()
        if not url:
            raise ValueError("Every stored observation requires a source URL")
        retrieved = retrieved_at or item.get("retrieved_at") or utc_now()
        conn.execute(
            "INSERT OR IGNORE INTO sources(profile_id,url,title,platform,source_category,publication_date,retrieved_at) VALUES(?,?,?,?,?,?,?)",
            (profile_id, url, item.get("title") or item.get("source_title"), item.get("platform"), item.get("source_category"), item.get("publication_date"), retrieved),
        )
        row = conn.execute("SELECT id FROM sources WHERE profile_id=? AND url=? AND retrieved_at=?", (profile_id, url, retrieved)).fetchone()
        return int(row[0])

    def _insert_observation(self, conn: sqlite3.Connection, table: str, profile_id: int, values: dict[str, Any]) -> None:
        columns = ["profile_id", *values.keys()]
        placeholders = ",".join("?" for _ in columns)
        conn.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})", [profile_id, *values.values()])

    def record_run(self, company_name: str, jurisdiction: str | None, *, sources: Iterable[dict[str, Any]], identities: Iterable[dict[str, Any]] = (), relationships: Iterable[dict[str, Any]] = (), roles: Iterable[dict[str, Any]] = (), events: Iterable[dict[str, Any]] = (), workforce: Iterable[dict[str, Any]] = (), hiring: Iterable[dict[str, Any]] = (), claims: Iterable[dict[str, Any]] = (), business_analysis: dict[str, Any] | None = None, aliases: Iterable[dict[str, Any]] = (), products: Iterable[dict[str, Any]] = (), customers: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
        """Append one research observation set; no prior row is overwritten."""
        now = utc_now()
        with self._connect() as conn:
            profile_id = self._profile(conn, company_name, jurisdiction)
            source_ids: dict[str, int] = {}
            for source in sources:
                try:
                    source_ids[str(source.get("url") or source.get("source_url"))] = self._source(conn, profile_id, source)
                except ValueError:
                    continue

            def source_id(item: dict[str, Any]) -> int | None:
                url = str(item.get("source_url") or item.get("url") or "")
                return source_ids.get(url) or (self._source(conn, profile_id, item) if url else None)

            for item in identities:
                sid = source_id(item)
                if sid:
                    self._insert_observation(conn, "entities", profile_id, {"entity_type": "candidate", "name": str(item.get("candidate_name") or item.get("name") or "Unknown"), "jurisdiction": item.get("jurisdiction"), "registration_number": item.get("candidate_id") or item.get("company_number"), "website": item.get("website"), "status": item.get("match_status"), "confidence": item.get("confidence", "low"), "verification_status": item.get("verification_status", "candidate"), "observed_at": now, "source_id": sid, "evidence_excerpt": _json(item.get("evidence", []))})
            for item in aliases:
                sid = source_id(item)
                if sid:
                    self._insert_observation(conn, "aliases", profile_id, {"alias": str(item.get("alias") or item.get("name") or "Unknown"), "alias_type": item.get("alias_type"), "confidence": item.get("confidence", "low"), "verification_status": item.get("verification_status", "candidate"), "observed_at": now, "source_id": sid, "evidence_excerpt": str(item.get("evidence") or item.get("evidence_excerpt") or "")})
            for item in relationships:
                sid = source_id(item)
                if sid:
                    self._insert_observation(conn, "relationships", profile_id, {"from_name": company_name, "relationship_type": item.get("relationship_type", "related"), "to_name": str(item.get("related_name") or item.get("to_name") or "Unknown"), "confidence": item.get("confidence", "low"), "verification_status": item.get("verification_status", "candidate"), "observed_at": now, "source_id": sid, "evidence_excerpt": str(item.get("evidence") or item.get("evidence_excerpt") or "")})
            for item in products:
                sid = source_id(item)
                if sid:
                    self._insert_observation(conn, "products", profile_id, {"name": str(item.get("name") or item.get("product") or "Unknown"), "description": item.get("description"), "confidence": item.get("confidence", "low"), "verification_status": item.get("verification_status", "candidate"), "observed_at": now, "source_id": sid, "evidence_excerpt": str(item.get("evidence") or "")})
            for item in customers:
                sid = source_id(item)
                if sid:
                    self._insert_observation(conn, "customers", profile_id, {"name": str(item.get("name") or item.get("customer") or "Unknown"), "relationship_type": item.get("relationship_type"), "confidence": item.get("confidence", "low"), "verification_status": item.get("verification_status", "candidate"), "observed_at": now, "source_id": sid, "evidence_excerpt": str(item.get("evidence") or "")})
            for item in [*roles, *workforce]:
                sid = source_id(item)
                if sid:
                    self._insert_observation(conn, "people", profile_id, {"name": str(item.get("person_name") or item.get("name") or "Unknown"), "person_type": item.get("role") or item.get("signal_type"), "confidence": item.get("confidence", "low"), "verification_status": item.get("verification_status", "candidate"), "observed_at": now, "source_id": sid, "evidence_excerpt": str(item.get("evidence") or item.get("evidence_excerpt") or "")})
                if item.get("person_name") or item.get("name"):
                    if sid:
                        self._insert_observation(conn, "role_changes", profile_id, {"person_name": str(item.get("person_name") or item.get("name")), "role": item.get("role"), "change_type": item.get("change_type") or item.get("signal_type") or item.get("role_status", "role_observation"), "event_date": item.get("event_date"), "confidence": item.get("confidence", "low"), "verification_status": item.get("verification_status", "candidate"), "observed_at": now, "source_id": sid, "evidence_excerpt": str(item.get("evidence") or item.get("evidence_excerpt") or "")})
            for item in events:
                sid = source_id(item)
                if sid:
                    self._insert_observation(conn, "dated_events", profile_id, {"event_type": item.get("event_type", "development"), "event_date": item.get("event_date"), "description": str(item.get("evidence") or item.get("description") or ""), "confidence": item.get("confidence", "low"), "verification_status": item.get("verification_status", "candidate"), "observed_at": now, "source_id": sid, "evidence_excerpt": str(item.get("evidence") or "")})
            claim_count = 0
            for item in claims:
                sid = source_id(item)
                if sid and item.get("evidence_excerpt"):
                    self._insert_observation(conn, "claims", profile_id, {"subject": str(item.get("subject") or company_name), "predicate": str(item.get("predicate") or "observation"), "object_value": str(item.get("object_value") or ""), "claim_status": item.get("claim_status", "unknown"), "confidence": item.get("confidence", "low"), "verification_status": item.get("verification_status", "unverified"), "observed_at": now, "source_id": sid, "evidence_excerpt": str(item["evidence_excerpt"])})
                    claim_count += 1
            return {"profile_id": profile_id, "profile_key": normalize_key(company_name), "stored_at": now, "sources_added": len(source_ids), "claims_added": claim_count}

    def load_context(self, company_name: str, jurisdiction: str | None, *, stale_after_days: int = 30) -> dict[str, Any]:
        """Load recent findings plus stale/conflicting gaps before a new run."""
        key = f"{normalize_key(company_name)}:{normalize_key(jurisdiction or '')}"
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_after_days)).isoformat()
        with self._connect() as conn:
            profile = conn.execute("SELECT * FROM profiles WHERE canonical_key=?", (key,)).fetchone()
            if not profile:
                return {
                    "found": False,
                    "profile": None,
                    "findings": [],
                    "entities": [],
                    "people": [],
                    "relationships": [],
                    "products": [],
                    "customers": [],
                    "dated_events": [],
                    "role_changes": [],
                    "stale_findings": [],
                    "conflicts": [],
                    "missing": ["No prior durable company profile exists."],
                    "schema_version": SCHEMA_VERSION,
                }
            pid = profile["id"]
            rows = conn.execute(
                "SELECT c.*, s.url AS source_url, s.title, s.retrieved_at FROM claims c "
                "JOIN sources s ON s.id=c.source_id WHERE c.profile_id=? "
                "ORDER BY c.observed_at DESC LIMIT 250",
                (pid,),
            ).fetchall()
            findings = [dict(row) for row in rows]
            stale = [row for row in findings if (row.get("retrieved_at") or "") < cutoff]

            entities = [dict(r) for r in conn.execute("SELECT * FROM entities WHERE profile_id=? ORDER BY observed_at DESC LIMIT 50", (pid,)).fetchall()]
            people = [dict(r) for r in conn.execute("SELECT * FROM people WHERE profile_id=? ORDER BY observed_at DESC LIMIT 50", (pid,)).fetchall()]
            relationships = [dict(r) for r in conn.execute("SELECT * FROM relationships WHERE profile_id=? ORDER BY observed_at DESC LIMIT 50", (pid,)).fetchall()]
            products = [dict(r) for r in conn.execute("SELECT * FROM products WHERE profile_id=? ORDER BY observed_at DESC LIMIT 50", (pid,)).fetchall()]
            customers = [dict(r) for r in conn.execute("SELECT * FROM customers WHERE profile_id=? ORDER BY observed_at DESC LIMIT 50", (pid,)).fetchall()]
            events = [dict(r) for r in conn.execute("SELECT * FROM dated_events WHERE profile_id=? ORDER BY observed_at DESC LIMIT 50", (pid,)).fetchall()]
            role_changes = [dict(r) for r in conn.execute("SELECT * FROM role_changes WHERE profile_id=? ORDER BY observed_at DESC LIMIT 50", (pid,)).fetchall()]

            conflicts: list[dict[str, Any]] = []
            grouped: dict[tuple[str, str], set[str]] = {}
            for row in findings:
                grouped.setdefault((row["subject"], row["predicate"]), set()).add(row["object_value"])
            for (subject, predicate), values in grouped.items():
                if len(values) > 1:
                    conflicts.append({"subject": subject, "predicate": predicate, "values": sorted(values), "status": "conflicting"})
            missing = []
            if not findings:
                missing.append("No source-linked claims are stored.")
            if stale:
                missing.append(f"{len(stale)} stored findings are older than {stale_after_days} days.")
            if conflicts:
                missing.append(f"{len(conflicts)} claim groups contain conflicting values.")
            return {
                "found": True,
                "profile": dict(profile),
                "findings": findings,
                "entities": entities,
                "people": people,
                "relationships": relationships,
                "products": products,
                "customers": customers,
                "dated_events": events,
                "role_changes": role_changes,
                "stale_findings": stale,
                "conflicts": conflicts,
                "missing": missing,
                "schema_version": SCHEMA_VERSION,
            }

    def detect_diff(self, company_name: str, jurisdiction: str | None, current_findings: dict[str, Any]) -> dict[str, Any]:
        """Detect meaningful changes between stored history and current run findings."""
        context = self.load_context(company_name, jurisdiction)
        if not context["found"]:
            return {"has_prior_history": False, "changes": []}

        prior_people = {p["name"].lower() for p in context.get("people", []) if p.get("name")}
        curr_people = {
            (r.get("person_name") or r.get("name", "")).lower()
            for r in (current_findings.get("role_records") or current_findings.get("roles") or [])
            if (r.get("person_name") or r.get("name"))
        }

        prior_products = {p["name"].lower() for p in context.get("products", []) if p.get("name")}
        curr_products = {
            str(item).lower()
            for item in (current_findings.get("products") or [])
        }

        changes = []
        new_people = curr_people - prior_people
        if new_people and prior_people:
            changes.append({"type": "new_leadership_or_personnel", "items": sorted(list(new_people))})

        departures = prior_people - curr_people
        if departures and prior_people:
            changes.append({"type": "unmentioned_prior_personnel", "items": sorted(list(departures))})

        new_prods = curr_products - prior_products
        if new_prods and prior_products:
            changes.append({"type": "new_products_or_services", "items": sorted(list(new_prods))})

        return {
            "has_prior_history": True,
            "profile_updated_at": context["profile"].get("updated_at") if context.get("profile") else None,
            "changes_detected": len(changes) > 0,
            "changes": changes,
        }

    def summary(self, company_name: str, jurisdiction: str | None) -> dict[str, Any]:
        context = self.load_context(company_name, jurisdiction)
        return {
            "found": context["found"],
            "findings": len(context.get("findings", [])),
            "stale": len(context.get("stale_findings", [])),
            "conflicts": len(context.get("conflicts", [])),
            "entities": len(context.get("entities", [])),
            "people": len(context.get("people", [])),
            "db_path": str(self.db_path),
        }
