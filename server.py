import os,re,requests
from bs4 import BeautifulSoup
from flask import Flask,jsonify,request,send_from_directory

app=Flask(__name__,static_folder=".",static_url_path="")
RACE_ID_RE=re.compile(r"(?:race_id=|/race/)(\d{10,12})")

def clean(s):
    return re.sub(r"\s+"," ",s or "").strip()

def horse_name(a):
    return re.sub(r"\s*のデータベース\s*$","",clean(a.get_text(" ",strip=True)))

def horse_anchors(node):
    seen={}
    for a in node.select("a[href*='/horse/']"):
        n=horse_name(a); h=(a.get("href") or "").split("?")[0]
        if n and h and h not in seen:
            seen[h]=(n,a)
    return list(seen.values())

def numeric_values(node):
    vals=[]
    for el in node.select("[data-umaban],[data-horse-no],[data-number],.Umaban,.umaban,.HorseNum,.HorseNumber,.Num,.WakuNum,.WakuNumBox,td,th,span"):
        t=clean(el.get_text(" ",strip=True))
        # Only accept short, standalone integer fields.
        if re.fullmatch(r"(?:1[0-8]|[1-9])",t):
            vals.append((int(t),el))
        for attr in ("data-umaban","data-horse-no","data-number"):
            v=el.get(attr)
            if v and re.fullmatch(r"(?:1[0-8]|[1-9])",v):
                vals.append((int(v),el))
    return vals

def find_row(a):
    # First look for a table row containing this horse.
    tr=a.find_parent("tr")
    if tr:
        return tr
    # Otherwise find the smallest ancestor containing this horse and either
    # a jockey link or several short numeric fields.
    cur=a
    best=a.parent
    for _ in range(8):
        cur=cur.parent if cur else None
        if cur is None: break
        if len(clean(cur.get_text(" ",strip=True)))>2500: continue
        if cur.select("a[href*='/jockey/']") or len(numeric_values(cur))>=2:
            best=cur
            if len(horse_anchors(cur))==1:
                return cur
    return best

def extract_number(a,row,name):
    # 1. Explicit horse-number fields.
    for node in (row,a):
        for n,_ in numeric_values(node):
            return n

    # 2. Inspect raw HTML around this exact horse link. This catches hidden
    # data attributes/classes that may not be visible in text.
    try:
        html=str(a.parent)
        patterns=[
            r'data-(?:umaban|horse-no|number)=["\'](1[0-8]|[1-9])["\']',
            r'class=["\'][^"\']*(?:Umaban|umaban|HorseNum)[^"\']*["\'][^>]*>\s*(1[0-8]|[1-9])\s*<',
        ]
        for pat in patterns:
            m=re.search(pat,html,re.I)
            if m:return int(m.group(1))
    except Exception:
        pass

    # 3. In the row text, choose the numeric token immediately before the
    # horse name. This is a fallback only.
    txt=clean(row.get_text(" ",strip=True))
    p=txt.find(name)
    if p>=0:
        before=txt[max(0,p-180):p]
        ns=list(re.finditer(r"(?<!\d)(1[0-8]|[1-9])(?!\d)",before))
        if ns:return int(ns[-1].group(1))
    return None

def extract_jockey(row):
    # Get the jockey from an actual jockey link/class if possible.
    for sel in ["a[href*='/jockey/']",".Jockey",".Jockey_Name",".JockeyName",
                "[class*='Jockey']"]:
        try: el=row.select_one(sel)
        except Exception: el=None
        if el:
            t=clean(el.get_text(" ",strip=True))
            if t:return t

    # Fallback: remove weight-like trailing number from a likely jockey field.
    return ""

def extract_weight(row):
    # Weight is usually a standalone numeric cell around 50-60kg.
    for sel in [".Kinryo",".Weight",".Barei","[class*='Kinryo']",
                "[class*='Weight']","[class*='Barei']"]:
        try: el=row.select_one(sel)
        except Exception: el=None
        if el:
            t=clean(el.get_text(" ",strip=True))
            m=re.search(r"(?:5[0-9]|6[0-9])(?:\.[05])?",t)
            if m:return m.group(0)

    txt=clean(row.get_text(" ",strip=True))
    # Prefer a 50-60 number immediately following a jockey-looking token.
    nums=list(re.finditer(r"(?<!\d)(5[0-9](?:\.[05])?|6[0-9](?:\.[05])?)(?!\d)",txt))
    if nums:return nums[-1].group(1)
    return ""

def parse_horse(a):
    name=horse_name(a)
    row=find_row(a)
    raw=clean(row.get_text(" ",strip=True)) if row else name
    number=extract_number(a,row,name)
    jockey=extract_jockey(row)
    weight=extract_weight(row)

    # The screenshot showed the weight appended to jockey. Clean that case.
    if jockey and weight:
        jockey=re.sub(r"\s*"+re.escape(weight)+r"\s*$","",jockey).strip()

    odds=""
    for sel in [".Odds",".Odds_Ninki","[class*='Odds']"]:
        try:el=row.select_one(sel)
        except Exception:el=None
        if el:
            odds=clean(el.get_text(" ",strip=True))
            if odds:break

    return {"number":number,"name":name,"jockey":jockey,"weight":weight,
            "odds":odds,"raw":raw}

def get_horses(soup):
    all_links=horse_anchors(soup)
    if not all_links:return []

    # Find the largest plausible group of horse links in one container.
    candidates=[]
    for _,a in all_links:
        cur=a
        for _ in range(8):
            cur=cur.parent if cur else None
            if cur is None:break
            hs=horse_anchors(cur)
            if 2<=len(hs)<=18:
                candidates.append((len(hs),hs))
    if candidates:
        links=max(candidates,key=lambda x:x[0])[1]
    else:
        links=all_links

    horses=[parse_horse(a) for _,a in links]

    # Deduplicate by horse URL.
    out=[];seen=set()
    for h in horses:
        key=h["name"]
        if key not in seen:
            seen.add(key);out.append(h)

    # If every number is available and unique, sort by number.
    nums=[h["number"] for h in out]
    if len(out) and all(n is not None for n in nums) and len(set(nums))==len(nums):
        out.sort(key=lambda x:x["number"])

    return out

def fetch_race(url):
    m=RACE_ID_RE.search(url)
    if not m:raise ValueError("netkeibaのレースURLからrace_idを取得できませんでした。")
    race_id=m.group(1)
    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"},timeout=20)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    title=clean(soup.title.get_text(" ",strip=True)) if soup.title else f"Race {race_id}"
    horses=get_horses(soup)
    return {"race_id":race_id,"title":title,"horses":horses}

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
