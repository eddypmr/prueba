"""Fusión segura de state.json para commits concurrentes."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def time_key(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.min.replace(tzinfo=timezone.utc)


def merge_states(local, remote):
    merged = dict(remote)
    for key, local_value in local.items():
        remote_value = remote.get(key)

        if key == "_outbox":
            result = dict(remote_value or {})
            for uid, local_alert in (local_value or {}).items():
                if uid not in result:
                    result[uid] = local_alert
                    continue
                remote_alert = result[uid]
                # El acuse de entrega nunca debe revertir a pendiente por
                # una copia antigua del estado (incluso si el push falla).
                preferred = (
                    local_alert if local_alert.get("sent_at")
                    else remote_alert if remote_alert.get("sent_at")
                    else local_alert if int(local_alert.get("attempts", 0))
                        >= int(remote_alert.get("attempts", 0))
                    else remote_alert
                )
                item = dict(preferred)
                item["attempts"] = max(
                    int(local_alert.get("attempts", 0)),
                    int(remote_alert.get("attempts", 0)),
                )
                result[uid] = item
            merged[key] = result
            continue

        if key == "_meta":
            result = dict(remote_value or {})
            for meta_key, value in (local_value or {}).items():
                if meta_key == "last_status_report":
                    if time_key(value) >= time_key(result.get(meta_key)):
                        result[meta_key] = value
                else:
                    result[meta_key] = value
            merged[key] = result
            continue

        if isinstance(local_value, dict) and isinstance(remote_value, dict):
            if time_key(local_value.get("last_changed")) >= time_key(
                remote_value.get("last_changed")
            ):
                merged[key] = local_value
        else:
            merged[key] = local_value

    return merged


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", required=True)
    parser.add_argument("--remote", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    local = json.loads(Path(args.local).read_text(encoding="utf-8"))
    remote = json.loads(Path(args.remote).read_text(encoding="utf-8"))
    merged = merge_states(local, remote)
    Path(args.output).write_text(
        json.dumps(merged, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
