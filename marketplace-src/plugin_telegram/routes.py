"""Signed inbound Telegram route and connector status UI."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from . import client, db, provision
from .context import build_context_block
from .directives import OutboundMedia, ParsedReply, parse_turn_result
from .hmac import verify
from .policy import should_respond
from .schemas import EnvelopeError, TelegramEnvelope

log = logging.getLogger("plugin-telegram.routes")

PERSONA = (
    "You are replying as Luna through an official Telegram Bot API bot. Keep the "
    "reply concise and natural for Telegram. In groups, answer only the request "
    "that addressed you and do not dominate the conversation. You may use the "
    "attributed cross-chat context below when relevant, but never expose private "
    "content from one chat into another. Never claim delivery you did not perform. "
    "You may add [[reply]] to quote the triggering message, [[react:emoji]] to "
    "react, and explicit media refs such as [[media:photo:https://…]]. Protocol "
    "markers are removed before delivery."
)

# Proactive Telegram tools are deliberately absent. The route owns delivery,
# preventing a tool send plus returned-text send from creating duplicate replies.
REPLY_TOOLS = ["recall_conversation"]


def register_routes(app, ctx) -> None:
    router = APIRouter(prefix="/api/p/plugin-telegram", tags=["telegram"])

    @router.post("/inbound")
    async def inbound(request: Request):
        try:
            raw = (await request.body()).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(400, "request body must be UTF-8") from exc

        try:
            raw_envelope = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, "invalid json") from exc
        if not isinstance(raw_envelope, dict):
            raise HTTPException(422, "envelope must be an object")
        requested_account = str(raw_envelope.get("account") or "default").strip()
        if not requested_account or len(requested_account) > 256:
            raise HTTPException(422, "invalid account")
        try:
            secret = await client.inbound_secret(ctx, requested_account)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        if secret is None:
            raise HTTPException(401, "unknown account")
        if not verify(
            secret,
            raw,
            request.headers.get("x-tg-timestamp"),
            request.headers.get("x-tg-signature"),
        ):
            raise HTTPException(401, "bad signature")

        try:
            envelope = TelegramEnvelope.from_dict(raw_envelope)
        except EnvelopeError as exc:
            raise HTTPException(422, str(exc)) from exc

        inserted = await db.record_message(
            ctx.engine,
            account=envelope.account,
            event_type=envelope.event_type,
            chat_id=envelope.chat_id,
            chat_kind=envelope.chat_kind,
            chat_name=envelope.chat_name,
            sender_id=envelope.sender_id,
            sender_name=envelope.sender_name,
            from_me=False,
            tg_update_id=envelope.tg_update_id,
            tg_msg_id=envelope.tg_msg_id,
            reply_to_id=envelope.reply_to_id,
            ts=_parse_ts(envelope.ts),
            kind=envelope.kind,
            body=envelope.body,
            edited=envelope.edited,
            mentioned_me=envelope.mentioned_me,
            is_reply_to_me=envelope.is_reply_to_me,
            is_command=envelope.is_command,
            reaction_emoji=envelope.reaction_emoji,
            reaction_old_json=envelope.reaction_old,
            reaction_new_json=envelope.reaction_new,
            media_json=envelope.media.to_dict() if envelope.media else None,
            raw_json=envelope.raw,
        )
        if not inserted:
            return {"ok": True, "answered": False, "reason": "duplicate"}

        env = envelope.to_dict()
        reaction_target = None
        if envelope.event_type == "reaction":
            reaction_target = await db.find_message(
                ctx.engine,
                chat_id=envelope.chat_id,
                tg_msg_id=envelope.tg_msg_id,
                from_me=True,
                account=envelope.account,
            )
        if not should_respond(
            env,
            client.allowed_chat_ids(ctx),
            reaction_targets_me=reaction_target is not None,
        ):
            return {"ok": True, "answered": False, "reason": "policy"}
        if ctx.agent is None:
            raise HTTPException(503, "agent not ready")

        rows = await db.recent_messages(
            ctx.engine, limit=80, account=envelope.account
        )
        prompt = _build_prompt(
            envelope, build_context_block(rows), reaction_target=reaction_target
        )
        await _best_effort_typing(ctx, envelope.chat_id)
        try:
            result, _usage = await ctx.agent.run_turn(
                prompt,
                tools=REPLY_TOOLS,
                memory_read=True,
                memory_write=True,
            )
        except Exception:  # noqa: BLE001
            log.exception("Telegram inbound agent turn failed")
            return {"ok": True, "answered": False, "reason": "agent_error"}

        if _is_agent_error_result(result):
            log.warning("Telegram inbound agent returned an error result")
            return {"ok": True, "answered": False, "reason": "agent_error"}
        parsed = parse_turn_result(result)
        if not parsed.text and not parsed.media and not parsed.reaction:
            return {"ok": True, "answered": False, "reason": "empty"}
        try:
            actions = await _deliver(ctx, envelope, parsed)
        except Exception:  # noqa: BLE001
            log.exception("Telegram gateway delivery failed")
            raise HTTPException(502, "gateway delivery failed") from None
        return {"ok": True, "answered": bool(actions), "actions": actions}

    @router.get("/status")
    async def status():
        configured_account = await client.account_id(ctx) or "default"
        chats = await db.list_chats(
            ctx.engine, limit=100, account=configured_account
        )
        result = await provision.status(ctx)
        result["version"] = "0.2.0"
        result["plugin"] = {
            "known_chats": len(chats),
            "last_activity": chats[0]["last_activity"] if chats else None,
        }
        return result

    @router.post("/connect")
    async def connect(request: Request):
        try:
            payload = await request.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(400, "invalid json") from exc
        if not isinstance(payload, dict):
            raise HTTPException(400, "request body must be an object")
        bot_token = payload.get("bot_token")
        payload.clear()
        try:
            return await provision.connect_bot(ctx, bot_token)
        except provision.ProvisionError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None
        finally:
            bot_token = None

    @router.delete("/connect")
    async def disconnect():
        try:
            return await provision.disconnect_bot(ctx)
        except provision.ProvisionError as exc:
            raise HTTPException(exc.status_code, str(exc)) from None

    @router.get("/ui/settings/", response_class=HTMLResponse)
    async def settings():
        return HTMLResponse(_SETTINGS_HTML.replace("__TG_VERSION__", "0.2.0"))

    app.include_router(router)


async def _deliver(ctx, envelope: TelegramEnvelope, reply: ParsedReply) -> list[str]:
    actions: list[str] = []
    reply_to = envelope.tg_msg_id if reply.reply else None

    if reply.reaction:
        await client.react_message(
            ctx, envelope.chat_id, envelope.tg_msg_id, reply.reaction
        )
        actions.append("reaction")

    caption = reply.text or None
    for index, media in enumerate(reply.media):
        response = await client.send_media(
            ctx,
            envelope.chat_id,
            media.media_type,
            media.source,
            caption=caption if index == 0 else None,
            reply_to=reply_to,
        )
        await _record_delivery(
            ctx,
            envelope,
            response,
            kind=media.media_type,
            body=caption if index == 0 else None,
            media=media,
            reply_to=reply_to,
        )
        actions.append("media")

    if reply.text and not reply.media:
        response = await client.send_message(
            ctx, envelope.chat_id, reply.text, reply_to=reply_to
        )
        await _record_delivery(
            ctx,
            envelope,
            response,
            kind="text",
            body=reply.text,
            reply_to=reply_to,
        )
        actions.append("text")
    return actions


async def _record_delivery(
    ctx,
    envelope: TelegramEnvelope,
    response: dict[str, Any],
    *,
    kind: str,
    body: str | None,
    reply_to: int | None,
    media: OutboundMedia | None = None,
) -> None:
    message_id = client.outbound_message_id(response)
    await db.record_message(
        ctx.engine,
        account=envelope.account,
        event_type="message",
        chat_id=envelope.chat_id,
        chat_kind=envelope.chat_kind,
        chat_name=envelope.chat_name,
        sender_id=None,
        sender_name="Luna",
        from_me=True,
        tg_update_id=None,
        tg_msg_id=message_id,
        reply_to_id=reply_to,
        ts=datetime.now(timezone.utc),
        kind=kind,
        body=body,
        media_json=(
            {"type": media.media_type, "source": media.source} if media else None
        ),
        raw_json=None,
    )


async def _best_effort_typing(ctx, chat_id: str) -> None:
    try:
        await client.send_typing(ctx, chat_id, "typing")
    except Exception:  # noqa: BLE001
        log.warning("Telegram typing action failed", exc_info=True)


def _build_prompt(
    envelope: TelegramEnvelope,
    context_block: str,
    *,
    reaction_target: dict[str, Any] | None = None,
) -> str:
    chat = envelope.chat_name or envelope.chat_id
    sender = envelope.sender_name or envelope.sender_id or "unknown sender"
    if envelope.event_type == "reaction":
        emoji = envelope.reaction_emoji or "<reaction removed or custom emoji>"
        target_body = str((reaction_target or {}).get("body") or "").strip()
        if not target_body:
            target_body = f"<{(reaction_target or {}).get('kind') or 'message'}>"
        current = (
            "[Current Telegram reaction]\n"
            f"Chat: {chat} ({envelope.chat_kind}, id {envelope.chat_id})\n"
            f"From: {sender} (id {envelope.sender_id})\n"
            f"Reaction: {emoji}\n"
            f"Target Luna message: {target_body}\n"
            "A reaction usually needs no textual reply. Output nothing unless a "
            "brief response is genuinely useful."
        )
    else:
        body = (envelope.body or "").strip()
        if not body:
            body = f"<{envelope.media.type if envelope.media else envelope.kind}>"
        current = (
            "[Current Telegram update — respond to this]\n"
            f"Chat: {chat} ({envelope.chat_kind}, id {envelope.chat_id})\n"
            f"From: {sender} (id {envelope.sender_id})\n"
            f"Message: {body}"
        )
    if envelope.media:
        current += "\nMedia: " + json.dumps(
            envelope.media.to_dict(), ensure_ascii=False, separators=(",", ":")
        )
    parts = [PERSONA]
    if context_block:
        parts.append(
            "[Recent Telegram context across known chats — private context]\n"
            + context_block
        )
    parts.extend(
        [
            current,
            (
                "Return only content intended for Telegram. Return nothing when no "
                "reply is warranted."
            ),
        ]
    )
    return "\n\n".join(parts)


def _is_agent_error_result(result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("error") is not None:
        return True
    if str(result.get("type") or "").casefold() == "error":
        return True
    if str(result.get("status") or "").casefold() in {"error", "failed", "failure"}:
        return True
    return result.get("ok") is False or result.get("success") is False


def _parse_ts(value: str | None) -> datetime:
    if value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return (
                parsed.replace(tzinfo=timezone.utc)
                if parsed.tzinfo is None
                else parsed
            )
        except ValueError:
            pass
    return datetime.now(timezone.utc)


_SETTINGS_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Telegram — Luna</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#e8eef4;
background:#101820;margin:0;padding:24px}.card{max-width:680px;margin:0 auto 16px;
background:#172733;border:1px solid #29404f;border-radius:14px;padding:20px}
h2,h3{margin-top:0}code{background:#0e1820;border-radius:7px;padding:2px 6px}
p,li{color:#9eb4c2;line-height:1.55}.pill{display:inline-block;border-radius:999px;
padding:4px 11px;font-size:13px;font-weight:700;background:#344b59}
.pill.ok{background:#2aabee;color:#08131b}.pill.warn{background:#f2b84b;color:#17120a}
.pill.err{background:#e76d7a;color:#190609}label{display:block;margin:14px 0 6px}
input{box-sizing:border-box;width:100%;padding:11px;border:1px solid #3c5666;
border-radius:8px;background:#0e1820;color:#fff}button{border:0;border-radius:8px;
padding:10px 16px;font-weight:700;cursor:pointer;margin:12px 8px 0 0}
#connect{background:#2aabee;color:#06131b}#disconnect{background:transparent;color:#f58b96;
border:1px solid #f58b96}.hidden{display:none}.error{color:#ff9ca6}.bot{font-size:20px;
font-weight:700;color:#65c8f5}.footer{max-width:680px;margin:auto;color:#607b8b;font-size:11px}
</style></head><body>
<div class="card"><h2>Telegram</h2><span class="pill" id="pill">Checking…</span>
<div id="bot" class="bot hidden"></div><p id="message">Checking this Luna…</p>
<div id="connect-form" class="hidden">
<label for="bot-token">BotFather token</label>
<input id="bot-token" type="password" autocomplete="off" spellcheck="false"
placeholder="Paste once to connect">
<button id="connect">Connect Telegram</button>
<p>The token goes directly to the hosted control plane over this server-side
plugin route. The plugin never stores or displays it.</p></div>
<button id="disconnect" class="hidden">Disconnect</button></div>
<div id="manual" class="card hidden"><h3>Self-hosted setup</h3>
<p>This Luna has no hosted control-plane credentials. Configure Telegram manually:</p>
<ul><li><code>LUNA_TELEGRAM_GATEWAY_URL</code> or vault
<code>plugin_telegram.gateway_url</code></li>
<li><code>LUNA_TELEGRAM_ACCOUNT_ID</code> or vault
<code>plugin_telegram.account_id</code></li>
<li><code>LUNA_TELEGRAM_SHARED_SECRET</code> or vault
<code>plugin_telegram.shared_secret</code></li></ul>
<p>Put the BotFather token only in the self-hosted gateway, never in Luna.</p></div>
<div class="card"><h3>BotFather privacy guidance</h3><ol>
<li>Create the bot with <code>@BotFather</code> and add it to each group.</li>
<li>Commands, mentions, and replies work with privacy mode enabled.</li>
<li>To capture ordinary group context, use <code>/setprivacy</code> to disable
privacy, then remove and re-add the bot. The status above reports whether the bot
can read all group messages.</li></ol>
<p>This connector uses the official Bot API, not a personal-account userbot.</p></div>
<div class="footer">plugin-telegram v__TG_VERSION__</div>
<script>
const pill=document.getElementById('pill'), message=document.getElementById('message'),
 bot=document.getElementById('bot'), form=document.getElementById('connect-form'),
 input=document.getElementById('bot-token'), connect=document.getElementById('connect'),
 disconnect=document.getElementById('disconnect'), manual=document.getElementById('manual');
let actionError='';
function visible(el,on){el.classList.toggle('hidden',!on)}
function paint(d){
 const hosted=d&&d.mode==='hosted', username=d&&d.bot&&d.bot.username;
 visible(manual,d&&d.mode==='manual'); visible(form,hosted&&!d.connected);
 visible(disconnect,hosted&&d.connected); visible(bot,Boolean(username));
 bot.textContent=username?'@'+String(username).replace(/^@/,''):'';
 const error=actionError||(d&&d.error)||'';
 pill.className='pill '+(d&&d.connected?'ok':error?'err':'warn');
 pill.textContent=d&&d.connected?'Connected':d&&d.mode==='manual'?'Manual setup':
  error?'Connection problem':'Not connected';
 if(error){message.className='error';message.textContent=error;return}
 message.className='';
 if(d&&d.connected){
  const reads=d.privacy&&d.privacy.can_read_all_group_messages;
  message.textContent='Bot is connected. Group privacy: '+
   (reads?'disabled — ordinary group messages are visible.':
          'enabled — Telegram sends commands, mentions, and replies.');
 }else if(hosted){message.textContent='Paste a BotFather token once to connect this Luna.'}
 else{message.textContent='Use the manual gateway and vault settings below.'}
}
async function refresh(){
 try{const r=await fetch('/api/p/plugin-telegram/status');paint(await r.json())}
 catch(_e){paint({mode:'hosted',error:'Telegram plugin is unreachable.'})}
}
connect.onclick=async function(){
 let token=input.value; input.value=''; actionError=''; connect.disabled=true;
 message.textContent='Connecting…';
 try{
  const body=JSON.stringify({bot_token:token}); token='';
  const r=await fetch('/api/p/plugin-telegram/connect',{method:'POST',
   headers:{'content-type':'application/json'},body});
  const d=await r.json();
  if(!r.ok)throw new Error(d.detail||'Connect failed.');
  actionError='';
  await refresh();
 }catch(e){actionError=String(e.message||'Connect failed.');await refresh()}
 finally{input.value='';connect.disabled=false}
};
input.oninput=function(){actionError=''};
disconnect.onclick=async function(){
 if(!confirm('Disconnect this Telegram bot from Luna?'))return;
 disconnect.disabled=true;
 try{await fetch('/api/p/plugin-telegram/connect',{method:'DELETE'});await refresh()}
 finally{disconnect.disabled=false}
};
refresh();setInterval(refresh,7000);
</script></body></html>"""
