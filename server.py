import os, re, math, requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=".", static_url_path="")
NETKEIBA_RE = re.compile(r"(?:race_id=|/race/)(\d{10,12})")

def parse_row(row):
    num = None
    for sel in [".Umaban", ".Num", "[class*='Umaban']", "[class*='umaban']", "[class*='Num']"]:
        el = row.select_one(sel)
        if el:
            m = re.search(r"\b([1-9]|1[0-8])\b", el.get_text(" ", strip=True))
            if m:
                num = int(m.group(1)); break
    a = row.select_one("a[href*='/horse/']")
    name = a.get_text(" ", strip=True) if a else ""
    raw = row.get_text(" ", strip=True)
    if not raw or num is None:
        return None
    return {"number": num, "name": name, "raw": raw}

def fetch_race(url):
    m = NETKEIBA_RE.search(url)
    if not m:
        raise ValueError("netkeibaのレースURLからrace_idを取得できませんでした。")
    race_id = m.group(1)
    r = requests.get(
        url,
        headers={"User-Agent":"Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"},
        timeout=15
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else f"Race {race_id}"

    rows = []
    for sel in ["tr.HorseList", "tr.HorseList_Item", "tr[class*='HorseList']"]:
        rows = soup.select(sel)
        if rows: break

    horses, seen = [], set()
    for row in rows:
        h = parse_row(row)
        if h and h["number"] not in seen:
            seen.add(h["number"]); horses.append(h)

    if not horses:
        for a in soup.select("a[href*='/horse/']"):
            p = a.find_parent("tr")
            h = parse_row(p) if p else None
            if h and h["number"] not in seen:
                seen.add(h["number"]); horses.append(h)

    horses.sort(key=lambda x:x["number"])
    return {"race_id":race_id, "title":title, "horses":horses}

@app.get("/")
def index():
    return send_from_directory(".", "index.html")

@app.post("/api/race")
def api_race():
    url = ((request.get_json(silent=True) or {}).get("url") or "").strip()
    if not url:
        return jsonify({"error":"netkeibaのレースURLを入力してください。"}),400
    try:
        return jsonify(fetch_race(url))
    except requests.RequestException as e:
        return jsonify({"error":f"レースページを取得できませんでした: {e}"}),502
    except Exception as e:
        return jsonify({"error":str(e)}),400

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","5000")),debug=False)
