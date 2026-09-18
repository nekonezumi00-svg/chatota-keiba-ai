import os,re,requests
from bs4 import BeautifulSoup
from flask import Flask,jsonify,request,send_from_directory

app=Flask(__name__,static_folder=".",static_url_path="")
RACE_ID_RE=re.compile(r"(?:race_id=|/race/)(\d{10,12})")

def clean(s):
    return re.sub(r"\s+"," ",s or "").strip()

def horse_name_from_anchor(a):
    t=clean(a.get_text(" ",strip=True))
    # Netkeiba commonly appends this to the horse-detail link.
    t=re.sub(r"\s*のデータベース\s*$","",t)
    return t

def is_horse_anchor(a):
    href=(a.get("href") or "")
    text=clean(a.get_text(" ",strip=True))
    return "/horse/" in href and text and (
        "データベース" in text or
        a.select_one("img") is not None or
        len(text)<=40
    )

def unique_horse_anchors(node):
    seen={}
    for a in node.select("a[href*='/horse/']"):
        if not is_horse_anchor(a):
            continue
        name=horse_name_from_anchor(a)
        href=(a.get("href") or "").split("?")[0]
        if name and href and href not in seen:
            seen[href]=(name,a)
    return list(seen.values())

def find_row_container(a):
    # Prefer the smallest ancestor that looks like a runner row:
    # it contains the horse link plus jockey link or weight-like text.
    cur=a
    best=None
    for depth in range(1,9):
        cur=cur.parent
        if cur is None: break
        txt=clean(cur.get_text(" ",strip=True))
        if len(txt)>1800: continue
        jockey_links=cur.select("a[href*='/jockey/']")
        weight=re.search(r"(?:斤量|負担重量)\s*[:：]?\s*(?:[0-9]{2}(?:\.[0-9])?)",txt)
        if jockey_links or weight:
            best=cur
            # If it contains only one horse link, this is almost certainly its row.
            if len(unique_horse_anchors(cur))==1:
                return cur
    return best or a.parent

def explicit_number(container):
    selectors=[
        "[data-umaban]","[data-horse-no]","[data-number]",
        ".Umaban","[class*='Umaban']","[class*='umaban']",
        ".HorseNum","[class*='HorseNum']"
    ]
    for sel in selectors:
        try:
            els=container.select(sel)
        except Exception:
            els=[]
        for el in els:
            txt=clean(el.get_text(" ",strip=True))
            m=re.search(r"(?<!\d)(1[0-8]|[1-9])(?!\d)",txt)
            if m:
                return int(m.group(1))
    return None

def number_from_structure(container,name):
    # Inspect integer-only cells/spans. If two numbers exist, netkeiba's
    # first is often frame number and the second is horse number.
    vals=[]
    for el in container.select("th,td,span,div"):
        txt=clean(el.get_text(" ",strip=True))
        if re.fullmatch(r"(?:1[0-8]|[1-9])",txt):
            vals.append(int(txt))
    if vals:
        # Preserve order but remove immediate duplicates.
        compact=[]
        for n in vals:
            if not compact or compact[-1]!=n:
                compact.append(n)
        if len(compact)>=2:
            return compact[1]
        # If only one value exists, use it only when there is no frame marker.
        if len(compact)==1:
            return compact[0]

    txt=clean(container.get_text(" ",strip=True))
    pos=txt.find(name)
    if pos>=0:
        before=txt[max(0,pos-140):pos]
        nums=list(re.finditer(r"(?<!\d)(1[0-8]|[1-9])(?!\d)",before))
        if len(nums)>=2:
            return int(nums[-1].group(1))
        if nums:
            return int(nums[-1].group(1))
    return None

def parse_anchor(a):
    name=horse_name_from_anchor(a)
    row=find_row_container(a)
    raw=clean(row.get_text(" ",strip=True)) if row else name

    number=explicit_number(row) if row else None
    if number is None and row:
        number=number_from_structure(row,name)

    jockey=""
    if row:
        for sel in ["a[href*='/jockey/']",".Jockey",".Jockey_Name",".JockeyName","[class*='Jockey']"]:
            try: el=row.select_one(sel)
            except Exception: el=None
            if el:
                jockey=clean(el.get_text(" ",strip=True))
                if jockey: break

    weight=""
    if row:
        for sel in [".Kinryo",".Weight",".Barei","[class*='Kinryo']","[class*='Weight']","[class*='Barei']"]:
            try: el=row.select_one(sel)
            except Exception: el=None
            if el:
                weight=clean(el.get_text(" ",strip=True))
                if weight: break
    if not weight:
        m=re.search(r"(?:斤量|負担重量)\s*[:：]?\s*([0-9]{2}(?:\.[0-9])?)",raw)
        if m: weight=m.group(1)

    odds=""
    if row:
        for sel in [".Odds",".Odds_Ninki","[class*='Odds']"]:
            try: el=row.select_one(sel)
            except Exception: el=None
            if el:
                odds=clean(el.get_text(" ",strip=True))
                if odds: break

    return {"number":number,"name":name,"jockey":jockey,"weight":weight,"odds":odds,"raw":raw}

def get_horses(soup):
    # Primary: horse-detail links whose visible text is the database-style
    # runner link. These were the 13 actual runners seen in v9.
    anchors=[]
    for a in soup.select("a[href*='/horse/']"):
        if is_horse_anchor(a):
            anchors.append(a)

    # Deduplicate by URL.
    unique={}
    for a in anchors:
        href=(a.get("href") or "").split("?")[0]
        if href and href not in unique:
            unique[href]=a

    # Prefer a set of 2-18 links that share a plausible race-entry container.
    # Score each ancestor by how many unique horse links it contains.
    candidates=[]
    for a in unique.values():
        cur=a
        for _ in range(8):
            cur=cur.parent
            if cur is None: break
            hs=unique_horse_anchors(cur)
            if 2<=len(hs)<=18:
                candidates.append((len(hs),cur,hs))

    if candidates:
        # Largest group wins. This prevents the v10 "zero rows" problem while
        # avoiding arbitrary small groups.
        _,container,hs=max(candidates,key=lambda x:x[0])
        links=hs
    else:
        links=[(horse_name_from_anchor(a),a) for a in unique.values()]

    horses=[parse_anchor(a) for _,a in links]

    # If we got an implausibly large collection, prefer only links with a
    # database-style visible label, which is the actual runner list on the
    # mobile page.
    if len(horses)>18:
        db=[a for a in unique.values() if "データベース" in clean(a.get_text(" ",strip=True))]
        if 2<=len(db)<=18:
            horses=[parse_anchor(a) for a in db]

    # Deduplicate by horse name.
    out=[];seen=set()
    for h in horses:
        if h["name"] in seen: continue
        seen.add(h["name"]);out.append(h)

    # Sort only if numbers are both present and unique.
    nums=[h["number"] for h in out]
    if len(out)>=2 and all(n is not None for n in nums) and len(set(nums))==len(nums):
        out.sort(key=lambda x:x["number"])

    return out

def fetch_race(url):
    m=RACE_ID_RE.search(url)
    if not m: raise ValueError("netkeibaのレースURLからrace_idを取得できませんでした。")
    race_id=m.group(1)

    r=requests.get(
        url,
        headers={"User-Agent":"Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"},
        timeout=20
    )
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    title=clean(soup.title.get_text(" ",strip=True)) if soup.title else f"Race {race_id}"
    horses=get_horses(soup)

    return {"race_id":race_id,"title":title,"horses":horses}

@app.get("/")
def index(): return send_from_directory(".","index.html")

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
