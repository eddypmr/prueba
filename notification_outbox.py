"""Cola persistente para las alertas del monitor One Piece."""
import hashlib
import os
from datetime import datetime, timezone

import requests


OUTBOX_KEY = "_outbox"


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def queue_alert(state, source, transition_id, message, kind="stock"):
    """El aviso se guarda en state.json ANTES de cualquier envío a Telegram."""
    if not source or not transition_id or not message:
        raise ValueError("Las alertas requieren origen, transición y mensaje")
    identifier = hashlib.sha256(
        f"{source}|{transition_id}|{kind}|{message}".encode("utf-8")
    ).hexdigest()[:32]
    outbox = state.setdefault(OUTBOX_KEY, {})
    if identifier not in outbox:
        outbox[identifier] = {
            "source": source,
            "kind": kind,
            "message": message,
            "created_at": timestamp(),
            "sent_at": None,
            "attempts": 0,
        }
        print(f"📥 Aviso {kind} en cola: {source} ({identifier[:8]})")
    return identifier


def pending_report_exists(state):
    return any(
        entry.get("kind") == "report" and not entry.get("sent_at")
        for entry in state.get(OUTBOX_KEY, {}).values()
    )


def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("⚠️ Telegram no configurado. El aviso permanece pendiente.")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message, "disable_web_page_preview": True},
            timeout=15,
        )
        # Un HTTP 200 no basta: exigimos el 'ok' real de la API de Telegram.
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code == 200 and payload.get("ok") is True:
            print("📲 Telegram confirmó la recepción del aviso.")
            return True

        retry_after = (payload.get("parameters") or {}).get("retry_after")
        print(
            f"⚠️ Telegram rechazó el aviso (HTTP {response.status_code}; "
            f"retry_after={retry_after}). Se reintentará."
        )
        return False
    except requests.RequestException as exc:
        # No registrar la URL de la excepción: contiene el token del bot.
        print(f"⚠️ Telegram no disponible ({type(exc).__name__}); se reintentará.")
        return False


def dispatch_pending(state, sender=send_telegram, persist=None, now=timestamp, limit=30):
    """Entrega pendiente; el acuse se persiste después de cada intento.

    El monitor primero confirma la cola en GitHub. Este despachador se invoca
    solo después de que el commit de la cola haya terminado correctamente.
    """
    processed = sent = 0
    outbox = state.setdefault(OUTBOX_KEY, {})
    ordered = sorted(
        outbox.items(), key=lambda pair: (pair[1].get("created_at", ""), pair[0])
    )
    for identifier, item in ordered:
        if item.get("sent_at"):
            continue
        if processed >= limit:
            break
        processed += 1
        success = False
        try:
            success = bool(sender(item["message"]))
        except Exception as exc:
            print(f"⚠️ Error de envío ({type(exc).__name__}); se reintentará.")
        item["attempts"] = int(item.get("attempts", 0)) + 1
        item["last_attempt_at"] = now()
        if success:
            item["sent_at"] = item["last_attempt_at"]
            sent += 1
            if item.get("kind") == "report":
                state.setdefault("_meta", {})["last_status_report"] = item["sent_at"]
        if persist is not None:
            persist(state)
        if not success:
            # No saturar Telegram ante HTTP 429, un corte de red o credenciales malas.
            break

    remaining = sum(1 for item in outbox.values() if not item.get("sent_at"))
    print(f"📨 Cola Telegram: {sent} entregados, {remaining} pendientes.")
    return sent, remaining
