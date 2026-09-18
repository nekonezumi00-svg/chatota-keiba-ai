import os
import re
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=".", static_url_path="")

NETKEIBA_RE = re.compile(r"(?:race_id=|/race/)(\d{10,12})")

def fetch_race(url):
    m = NETKEIBA_RE.search(url)
    if not m:
        raise ValueError("netkeibaのレースURLからrace_idを取得できませんでした。")
    race_id = m.group(1)

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    title = soup.title.get_text(" ", strip=True) if soup.title else f"Race {race_id}"

    horses = []
    selectors = [
        "tr.HorseList",
        "tr.HorseList_Item",
        "div.HorseList",
        "tr[class*='HorseList']",
    ]
    rows = []
    for sel in selectors:
        rows = soup.select(sel)
        if rows:
            break

    for row in rows:
        txt = row.get_text(" ", strip=True)
        if txt:
            horses.append({"raw": txt})

    # Fallback: collect horse links if row selectors did not match.
    if not horses:
        seen = set()
        for a in soup.select("a[href*='/horse/']"):
            name = a.get_text(" ", strip=True)
            href = a.get("href", "")
            if name and name not in seen:
                seen.add(name)
                horses.append({"raw": name, "href": href})

    return {"race_id": race_id, "title": title, "horses": horses}

@app.get("/")
def index():
    return send_from_directory(".", "index.html")

@app.post("/api/race")
def api_race():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "netkeibaのレースURLを入力してください。"}), 400
    try:
        return jsonify(fetch_race(url))
    except requests.RequestException as e:
        return jsonify({"error": f"レースページを取得できませんでした: {e}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
