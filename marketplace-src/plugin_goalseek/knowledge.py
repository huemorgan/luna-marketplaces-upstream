"""The wiki seam — durable narrative knowledge with a fallback chain.

Structured execution state stays in ``goalseek_facts``; this module is for
*narrative* knowledge (what a goal is, what was learned, how it ended) that
should compound across goals and plugins:

1. **Curiosity present and mission-bound** → write into the mission wiki
   curiosity maintains (its slug lives on the active ``curiosity_missions``
   row — the same place curiosity's own ``wikibind.py`` reads it; curiosity
   is a co-writer, so pages here are goalseek's own ``goal-*`` / domain
   pages, never rewrites of curiosity's).
2. **plugin-wiki present, no bound mission** → goalseek keeps its own wiki
   (slug ``goalseek``), created idempotently on first write.
3. **Neither** → ``goalseek_notes`` table: same content, no rendering.

Detection is per call through ``ctx.provider_registry`` (the cross-plugin
seam plugin-wiki itself documents) — installing or removing wiki/curiosity
never needs a goalseek restart. Callers use ``write_note`` / ``read_notes``
/ ``find_fact`` and never learn which backend served them.

Compounding: namespaced fact keys (``contact-jane/working_hours``) also land
on a *domain* wiki page (``contact-jane``, section ``working_hours``) so the
NEXT goal touching the same contact starts tuned — ``find_fact`` reads the
DB first, then that page. Authority rules unchanged: wiki-sourced values
enter as ``agent`` authority.

Never raises into a tool path: every wiki failure degrades to the next
backend or to a logged no-op. Writes go through a small scrub that strips
credential-looking strings — never secrets or raw tokens into wiki pages.
"""

from __future__ import annotations

import inspect
import logging
import re
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text

from .models import NoteRow

log = logging.getLogger("plugin-goalseek.knowledge")

# Goalseek's own wiki when no mission wiki is bound (backend 2).
OWN_WIKI_SLUG = "goalseek"
OWN_WIKI_NAME = "Goal-Seek"

# Credential-looking strings never land on a wiki page.
_SECRET_RES = (
    re.compile(r"\b(sk|pk|rk|ghp|gho|xoxb|xoxp|AKIA)[-_][A-Za-z0-9_\-]{8,}\b"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),  # long base64-ish blobs
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),  # long hex (keys, not sha-prefixes)
    re.compile(r"(?i)(password|passwd|secret|token|api[-_]?key)\s*[:=]\s*\S+"),
)


def scrub(md: str) -> str:
    out = str(md or "")
    for rx in _SECRET_RES:
        out = rx.sub("[redacted]", out)
    return out


def goal_page_slug(goal_id: str) -> str:
    return f"goal-{str(goal_id)[:8]}"


def split_fact_key(key: str) -> tuple[str | None, str]:
    """``contact-jane/working_hours`` → ("contact-jane", "working_hours");
    an un-namespaced key has no domain page."""
    key = str(key or "").strip()
    if "/" in key:
        domain, _, field = key.partition("/")
        domain = domain.strip().strip("-")
        field = field.strip()
        if domain and field:
            return domain, field
    return None, key


class Knowledge:
    """One seam, three backends. Bound to the provider registry (live —
    re-checked per call) and goalseek's session factory (notes fallback)."""

    def __init__(self, session_factory, provider_registry=None) -> None:
        self._sf = session_factory
        self._providers = provider_registry
        self._own_wiki_ready = False

    # -- backend resolution -------------------------------------------------

    def _wiki(self) -> Any | None:
        if self._providers is None:
            return None
        try:
            wiki = self._providers.get("wiki")
        except Exception:  # noqa: BLE001 — registry may raise KeyError or worse
            return None
        return wiki if callable(getattr(wiki, "upsert_page", None)) else None

    @staticmethod
    def _multi_wiki(wiki: Any) -> bool:
        """Same feature test as curiosity's wikibind: create_wiki exists AND
        page reads take a ``wiki`` kwarg."""
        if not callable(getattr(wiki, "create_wiki", None)):
            return False
        try:
            return "wiki" in inspect.signature(wiki.get_page).parameters
        except (TypeError, ValueError):
            return False

    async def _mission_wiki_slug(self) -> str | None:
        """The active mission's bound wiki, read where curiosity's own
        wikibind keeps it. Read-only; any failure (curiosity absent, table
        missing) means 'not bound'."""
        try:
            async with self._sf() as s:
                row = (
                    await s.execute(text(
                        "SELECT wiki_id FROM curiosity_missions "
                        "WHERE active AND wiki_id IS NOT NULL LIMIT 1"
                    ))
                ).first()
            return row[0] if row and row[0] else None
        except Exception:  # noqa: BLE001 — no curiosity installed
            return None

    async def backend(self) -> dict[str, Any]:
        """{"backend": "wiki"|"notes", "wiki": slug|None, "multi": bool,
        "provider": obj|None} — resolved fresh on every call."""
        wiki = self._wiki()
        if wiki is None:
            return {"backend": "notes", "wiki": None, "multi": False, "provider": None}
        multi = self._multi_wiki(wiki)
        slug: str | None = None
        if multi:
            slug = await self._mission_wiki_slug()
            if slug is None:
                slug = OWN_WIKI_SLUG
                if not self._own_wiki_ready:
                    try:
                        await wiki.create_wiki(
                            OWN_WIKI_SLUG, OWN_WIKI_NAME,
                            description="Goal-Seek's goal pages and learned domain knowledge.",
                        )
                    except Exception:  # noqa: BLE001 — exists already (idempotent)
                        pass
                    self._own_wiki_ready = True
        return {"backend": "wiki", "wiki": slug, "multi": multi, "provider": wiki}

    def _wk(self, be: dict[str, Any]) -> dict[str, Any]:
        return {"wiki": be["wiki"]} if be["multi"] and be["wiki"] else {}

    # -- page primitives ------------------------------------------------------

    async def _upsert_section(
        self, be: dict[str, Any], slug: str, title: str, header: str, body_md: str,
        *, note: str,
    ) -> bool:
        """Replace-or-append one ``## header`` section on a page (creating the
        page when absent). Only our section is touched — curiosity co-writes
        these wikis, so no destructive page rewrites."""
        wiki = be["provider"]
        wk = self._wk(be)
        body_md = scrub(body_md).strip()
        section = f"## {header}\n\n{body_md}\n"
        try:
            page = await wiki.get_page(slug, **wk)
        except Exception:  # noqa: BLE001
            page = None
        if page is None:
            body = f"# {scrub(title)}\n\n{section}"
        else:
            old = page.get("body") or ""
            rx = re.compile(
                rf"^## {re.escape(header)}\s*$.*?(?=^#{{1,2}} |\Z)",
                re.MULTILINE | re.DOTALL,
            )
            body = rx.sub(section + "\n", old) if rx.search(old) else old.rstrip() + "\n\n" + section
            title = page.get("title") or title
        try:
            await wiki.upsert_page(
                slug, scrub(title)[:120], body,
                summary=scrub(body_md)[:200], note=note, **wk,
            )
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("wiki write failed (%s): %s", slug, e)
            return False

    async def _note_row(self, goal_id: str, title: str, body_md: str) -> dict[str, Any]:
        async with self._sf() as s:
            row = NoteRow(
                goal_id=_uuid.UUID(str(goal_id)),
                title=scrub(title)[:200],
                body_md=scrub(body_md),
            )
            s.add(row)
            await s.commit()
            return {"backend": "notes", "note_id": str(row.id)}

    # -- the public seam --------------------------------------------------------

    async def write_note(self, goal: dict[str, Any], title: str, body_md: str) -> dict[str, Any]:
        """Append narrative to the goal's page (wiki backends) or a notes row.
        ``goal`` is the ``_goal_dict`` shape; returns where the note landed."""
        be = await self.backend()
        if be["backend"] == "wiki":
            slug = goal_page_slug(goal["id"])
            stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
            ok = await self._upsert_section(
                be, slug, goal.get("statement") or "Goal",
                str(title or "Note").strip(),
                f"{body_md}\n\n*({stamp} UTC)*",
                note=f"goal note: {str(title)[:60]}",
            )
            if ok:
                return {"backend": "wiki", "wiki": be["wiki"], "page": slug}
        return await self._note_row(goal["id"], title, body_md)

    async def read_notes(self, goal_id: str) -> list[dict[str, Any]]:
        """Fallback-table notes for a goal (newest first). Wiki-backed notes
        live on the goal page — read that through the wiki."""
        async with self._sf() as s:
            rows = (
                await s.execute(
                    select(NoteRow).where(NoteRow.goal_id == _uuid.UUID(str(goal_id)))
                    .order_by(NoteRow.created_at.desc())
                )
            ).scalars().all()
        return [
            {"id": str(r.id), "title": r.title, "body_md": r.body_md,
             "created_at": r.created_at.isoformat() if r.created_at else None}
            for r in rows
        ]

    # -- lifecycle write-throughs (best-effort, never raise) ---------------------

    async def on_goal_open(self, goal: dict[str, Any]) -> None:
        be = await self.backend()
        if be["backend"] != "wiki":
            return  # notes rows only carry narrative the agent chose to write
        labels = goal.get("outcome_labels") or {}
        label_lines = "\n".join(f"- **{k}** → {v}" for k, v in labels.items()) or "- (base outcomes only)"
        body = (
            f"{goal.get('statement', '')}\n\n"
            f"**Definition of done:** {goal.get('definition_of_done', '')}\n\n"
            f"**Business end-states:**\n{label_lines}\n\n"
            f"Opened by {goal.get('opened_by', 'owner')}."
        )
        await self._upsert_section(
            be, goal_page_slug(goal["id"]), goal.get("statement") or "Goal",
            "Goal", body, note="goal opened",
        )

    async def on_goal_close(self, goal: dict[str, Any]) -> None:
        be = await self.backend()
        if be["backend"] != "wiki":
            return
        reason = goal.get("outcome_reason") or {}
        label = goal.get("outcome_label")
        body = (
            f"**{goal.get('outcome', '?')}**"
            + (f" — “{label}”" if label else "")
            + f"\n\n{reason.get('summary', '')}"
            + (f"\n\nCause: {reason['cause']}" if reason.get("cause") else "")
            + "\n\n*This goal is closed; its lifecycle is immutable.*"
        )
        await self._upsert_section(
            be, goal_page_slug(goal["id"]), goal.get("statement") or "Goal",
            "Outcome", body, note="goal closed",
        )

    async def on_fact_set(
        self, goal: dict[str, Any], key: str, value: Any, source: str = ""
    ) -> None:
        """The compounding step: a namespaced fact (``contact-jane/working_hours``)
        also lands on its domain page, where the NEXT goal's ``find_fact``
        (and curiosity, and the owner in the wiki pane) will see it."""
        domain, field = split_fact_key(key)
        if domain is None:
            return
        be = await self.backend()
        if be["backend"] != "wiki":
            return
        body = f"{value}\n\n*Learned from goal {goal_page_slug(goal['id'])}"
        if source:
            body += f", source: {scrub(str(source))[:120]}"
        body += f", {datetime.now(UTC).strftime('%Y-%m-%d')}.*"
        await self._upsert_section(
            be, domain, domain.replace("-", " ").strip(), field, body,
            note=f"goalseek fact: {field}",
        )

    # -- reading side --------------------------------------------------------------

    async def find_fact(self, key: str) -> dict[str, Any] | None:
        """A wiki-backed value for a namespaced fact key, or None. DB facts are
        the caller's first stop (the gate context already has them) — this is
        the second. Wiki values enter as agent authority."""
        domain, field = split_fact_key(key)
        if domain is None:
            return None
        be = await self.backend()
        if be["backend"] != "wiki":
            return None
        wiki = be["provider"]
        if not callable(getattr(wiki, "get_section", None)):
            return None
        try:
            section = await wiki.get_section(domain, field, **self._wk(be))
        except Exception:  # noqa: BLE001
            return None
        if not section or not (section.get("text") or "").strip():
            return None
        first_line = section["text"].strip().splitlines()[0].strip()
        return {
            "value": {"v": first_line},
            "authority": "agent",
            "source": f"wiki:{be['wiki'] or 'main'}/{domain}#{field}",
        }
