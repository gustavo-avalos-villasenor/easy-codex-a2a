"""Usage: python a2a_client.py 'mensaje' 'http://IP-TAILSCALE:8766'."""

import json
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    prompt = sys.argv[1]
    base_url = sys.argv[2].rstrip("/")

    card_url = base_url + "/.well-known/agent-card.json"
    try:
        with urlopen(card_url, timeout=10) as response:
            card = json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(f"No pude leer la Agent Card: {exc}") from exc

    description = card.get("description", "")
    marker = "contextId: "
    if marker not in description:
        raise SystemExit("La Agent Card no anuncia el contextId dedicado.")
    context_id = description.split(marker, 1)[1].split(";", 1)[0].strip()
    interfaces = card.get("supportedInterfaces", [])
    if not interfaces or not interfaces[0].get("url"):
        raise SystemExit("La Agent Card no anuncia endpoint JSON-RPC.")
    endpoint = interfaces[0]["url"]

    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "contextId": context_id,
                "parts": [{"text": prompt}],
            }
        },
    }
    request = Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "A2A-Version": "1.0"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=300) as response:
            result = json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise SystemExit(f"No pude completar la petición A2A: {exc}") from exc

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if "error" in result:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
