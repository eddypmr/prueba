"""Entrega los avisos previamente confirmados en state.json de GitHub."""
import json
from pathlib import Path

from notification_outbox import dispatch_pending

STATE = Path("state.json")


def persist_local(state):
    # Se salva tras CADA intento, de modo que el siguiente commit recoja los
    # acuses recibidos incluso si un envío posterior falla.
    STATE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main():
    state = json.loads(STATE.read_text(encoding="utf-8"))
    dispatch_pending(state, persist=persist_local)


if __name__ == "__main__":
    main()
