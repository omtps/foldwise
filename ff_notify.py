"""Push a short message to your phone/PC chat: ntfy.sh topic URL (free, no account), a Discord webhook, or any URL that accepts a JSON POST."""
import json
import urllib.request


def send(url, title, text, timeout=15):
    """POST the notification. Returns the HTTP status. The address you set decides where it goes; nothing else is sent."""
    url = (url or "").strip()
    if not url.lower().startswith(("https://", "http://")):
        raise ValueError("The notification address must start with https://")
    headers = {"User-Agent": "Foldwise"}
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        body = json.dumps({"content": f"**{title}**\n{text}"[:1900]}).encode()
        headers["Content-Type"] = "application/json"
    elif "ntfy" in url:
        body = text.encode("utf-8")
        headers["Title"] = title.encode("ascii", "replace").decode()
        headers["Content-Type"] = "text/plain; charset=utf-8"
    else:
        body = json.dumps({"title": title, "text": text, "message": text}).encode()
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data=body, headers=headers), timeout=timeout) as r:
        return r.status
