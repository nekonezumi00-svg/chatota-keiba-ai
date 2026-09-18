import os,re,requests
from bs4 import BeautifulSoup
from flask import Flask,jsonify,request,send_from_directory

app=Flask(__name__,static_folder=".",static_url_path="")
RACE_ID_RE=re.compile(r"(?:race_id=|/race/)(\d{10,12})")

def clean(s):
    return re.sub(r"\s+"," ",s or "").strip()

def first_text(node, selectors):
    for sel in selectors:
        el=node.select_one(sel)
        if el:
            t=clean(el.get_text(" ",strip=True))
            if t:return t
    return ""

def parse_row(row):
    raw=clean(row.get_text(" ",strip=True))

    # Horse name: prefer the dedicated Horse_Name area. Do NOT use arbitrary
    # horse links from the page because netkeiba also has "horse database" links.
    name=first_text(row,[
        ".Horse_Name",".HorseName",
        "[class*='Horse_Name']","[class*='HorseName']"
    ])
    if not name:
        for a in row.select("a[href*='/horse/']"):
            t=clean(a.get_text(" ",strip=True))
            if t and "データベース" not in t:
                name=t
                break
    if not name:
        return None

    # Remove a possible suffix that belongs to a database link.
    name=re.sub(r"\s*のデータベース\s*$","",name)

    # Horse number: exact number classes first.
    number=None
    for sel in [".Umaban","[class*='Umaban']",".HorseNum","[class*='HorseNum']"]:
        el=row.select_one(sel)
        if el:
            m=re.search(r"(?<!\d)(1[0-8]|[1-9])(?!\d)",clean(el.get_text(" ",strip=True)))
            if m:
                number=int(m.group(1));break

    # Fallback: in an entry row the first two small integer cells are normally
    # frame number and horse number; the second is the horse number.
    if number is None:
        vals=[]
        for cell in row.select("th,td"):
            t=clean(cell.get_text(" ",strip=True))
            if re.fullmatch(r"(?:1[0-8]|[1-9])",t):
                vals.append(int(t))
        if len(vals)>=2:
            number=vals[1]

    # Jockey: dedicated class/link.
    jockey=first_text(row,[
        ".Jockey",".Jockey_Name",".JockeyName",
        "[class*='Jockey']"
    ])
    if not jockey:
        a=row.select_one("a[href*='/jockey/']")
        if a:jockey=clean(a.get_text(" ",strip=True))

    # Weight/斤量.
    weight=first_text(row,[
        ".Barei",".Weight",".Kinryo",
        "[class*='Barei']","[class*='Weight']","[class*='Kinryo']"
    ])
    if not weight:
        m=re.search(r"(?:斤量|負担重量)\s*([0-9]{2}(?:\.[0-9])?)",raw)
        if m:weight=m.group(1)

    # Odds if present in the row.
    odds=""
    for sel in [".Odds",".Odds_Ninki","[class*='Odds']"]:
        el=row.select_one(sel)
        if el:
            odds=clean(el.get_text(" ",strip=True))
            if odds:break

    return {
        "number":number,
        "name":name,
        "jockey":jockey,
        "weight":weight,
        "odds":odds,
        "raw":raw
    }

def get_entry_rows(soup):
    # Strictly prefer the actual entry table. This prevents unrelated
    # "○○のデータベース" links from being mistaken for runners.
    selectors=[
        "tr.HorseList",
        "tr[class*='HorseList']",
        ".Shutuba_Table tr",
        "table.Shutuba_Table tr",
        "table[class*='Shutuba'] tr"
    ]
    for sel in selectors:
        rows=soup.select(sel)
        parsed=[]
        for row in rows:
            x=parse_row(row)
            if x:parsed.append(x)
        # A plausible race field has at least 2 and at most 18 runners.
        if 2<=len(parsed)<=18:
            return parsed

    # Fallback: inspect table rows, but only accept rows that contain an
    # explicit horse name area or a horse link that is NOT a database link.
    rows=[]
    for row in soup.find_all("tr"):
        x=parse_row(row)
        if x:rows.append(x)
    if 2<=len(rows)<=18:return rows
    return []

def fetch_race(url):
    m=RACE_ID_RE.search(url)
    if not m:raise ValueError("netkeibaのレースURLからrace_idを取得できませんでした。")
    race_id=m.group(1)

    r=requests.get(
        url,
        headers={"User-Agent":"Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"},
        timeout=20
    )
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    title=clean(soup.title.get_text(" ",strip=True)) if soup.title else f"Race {race_id}"

    horses=get_entry_rows(soup)

    # Deduplicate by actual horse name while keeping order from the entry table.
    out=[];seen=set()
    for h in horses:
        key=h["name"]
        if key in seen:continue
        seen.add(key);out.append(h)

    # Sort only when real horse numbers are available and unique.
    nums=[h["number"] for h in out if h["number"] is not None]
    if len(nums)==len(out) and len(set(nums))==len(nums):
        out.sort(key=lambda x:x["number"])

    return {"race_id":race_id,"title":title,"horses":out}

@app.get("/")
def index():return send_from_directory(".","index.html")

@app.post("/api/race")
def api_race():
    body=request.get_json(silent=True) or {}
    url=(body.get("url") or "").strip()
    if not url:return jsonify({"error":"netkeibaのレースURLを入力してください。"}),400
    try:return jsonify(fetch_race(url))
    except requests.RequestException as e:return jsonify({"error":f"レースページを取得できませんでした: {e}"}),502
    except Exception as e:return jsonify({"error":str(e)}),400

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT","5000")),debug=False)
