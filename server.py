import os, re, requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder=".", static_url_path="")

RACE_ID_RE = re.compile(r"(?:race_id=|/race/)(\d{10,12})")

def horse_links_in(node):
    seen = {}
    for a in node.select("a[href*='/horse/']"):
        name = a.get_text(" ", strip=True)
        href = (a.get("href") or "").split("?")[0]
        if not name or not href:
            continue
        seen[href] = (name, a)
    return list(seen.values())

def number_from_text(text, name=""):
    text = re.sub(r"\s+", " ", text or "").strip()

    # Strong signals first.
    patterns = [
        r"馬番\s*[:：]?\s*(1[0-8]|[1-9])\b",
        r"馬番\s*(1[0-8]|[1-9])\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return int(m.group(1))

    # If the horse name is present, use the nearest number immediately before it.
    if name:
        pos = text.find(name)
        if pos >= 0:
            prefix = text[max(0, pos - 80):pos]
            nums = list(re.finditer(r"(?<!\d)(1[0-8]|[1-9])(?!\d)", prefix))
            if nums:
                return int(nums[-1].group(1))

    # Common explicit number-like class/attribute text.
    return None

def parse_candidate_container(container):
    items = []
    for name, a in horse_links_in(container):
        num = None

        # Search the anchor and a few ancestors for explicit horse-number elements.
        cur = a
        for _ in range(5):
            if cur is None:
                break
            selectors = [
                "[data-umaban]", "[data-horse-no]", "[data-number]",
                ".Umaban", ".Num", ".WakuNum", ".WakuNumBox",
                "[class*='Umaban']", "[class*='umaban']"
            ]
            for sel in selectors:
                try:
                    el = cur.select_one(sel)
                except Exception:
                    el = None
                if el:
                    raw = el.get_text(" ", strip=True)
                    m = re.search(r"(?<!\d)(1[0-8]|[1-9])(?!\d)", raw)
                    if m:
                        num = int(m.group(1))
                        break
            if num is not None:
                break

            txt = cur.get_text(" ", strip=True)
            num = number_from_text(txt, name)
            if num is not None:
                break
            cur = cur.parent

        items.append({
            "number": num,
            "name": name,
            "href": a.get("href", ""),
            "raw": a.parent.get_text(" ", strip=True) if a.parent else name
        })
    return items

def fetch_race(url):
    m = RACE_ID_RE.search(url)
    if not m:
        raise ValueError("netkeibaのレースURLからrace_idを取得できませんでした。")

    race_id = m.group(1)
    r = requests.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
            )
        },
        timeout=20
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else f"Race {race_id}"

    # 1) Prefer entry-list rows. This avoids unrelated horse links elsewhere on the page.
    candidates = []
    row_selectors = [
        "tr.HorseList", "tr[class*='HorseList']",
        "li.HorseList", "li[class*='HorseList']",
        "div.HorseList", "div[class*='HorseList']",
        ".Shutuba_Table tr", ".RaceTable tr",
        "table tr"
    ]

    for sel in row_selectors:
        rows = soup.select(sel)
        if not rows:
            continue
        found = []
        for row in rows:
            hs = parse_candidate_container(row)
            if hs:
                found.extend(hs)
        # Prefer a plausible full field of 2-18 unique horses.
        unique = {}
        for x in found:
            unique[x["href"].split("?")[0] if x["href"] else x["name"]] = x
        if 2 <= len(unique) <= 18:
            candidates = list(unique.values())
            break
        if len(found) > len(candidates):
            candidates = found

    # 2) If row classes differ, find a parent container around horse links
    # containing a plausible number of unique horses.
    if len(candidates) < 2:
        anchors = soup.select("a[href*='/horse/']")
        for a in anchors:
            cur = a
            for _ in range(7):
                if cur is None:
                    break
                hs = horse_links_in(cur)
                if 2 <= len(hs) <= 18:
                    candidates = parse_candidate_container(cur)
                    break
                cur = cur.parent
            if len(candidates) >= 2:
                break

    # 3) Last resort: use unique horse-detail links, but only if page contains
    # a plausible entry count. Horse-detail links are much safer than arbitrary text.
    if len(candidates) < 2:
        hs = horse_links_in(soup)
        if 2 <= len(hs) <= 18:
            candidates = parse_candidate_container(soup)

    # Deduplicate by horse URL/name.
    unique = {}
    for x in candidates:
        key = x["href"].split("?")[0] if x["href"] else x["name"]
        if key not in unique:
            unique[key] = x
        elif unique[key]["number"] is None and x["number"] is not None:
            unique[key] = x

    horses = list(unique.values())

    # Assign real numbers where confidently parsed. If a number is missing,
    # keep the horse rather than silently dropping it; frontend marks it "番号未取得".
    numbered = [x for x in horses if x["number"] is not None]
    unnumbered = [x for x in horses if x["number"] is None]

    # Remove duplicate known horse numbers.
    by_num = {}
    for x in numbered:
        by_num.setdefault(x["number"], x)
    numbered = list(by_num.values())
    numbered.sort(key=lambda x: x["number"])

    # Preserve unnumbered horses after numbered horses.
    horses = numbered + unnumbered

    return {
        "race_id": race_id,
        "title": title,
        "horses": horses,
        "horse_link_count": len(horse_links_in(soup))
    }

@app.get("/")
def index():
    return send_from_directory(".", "index.html")

@app.post("/api/race")
def api_race():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"error": "netkeibaのレースURLを入力してください。"}), 400

    try:
        return jsonify(fetch_race(url))
    except requests.RequestException as e:
        return jsonify({"error": f"レースページを取得できませんでした: {e}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=False)
