import os,re,requests
from bs4 import BeautifulSoup
from flask import Flask,jsonify,request,send_from_directory

app=Flask(__name__,static_folder=".",static_url_path="")
RACE_ID_RE=re.compile(r"(?:race_id=|/race/)(\d{10,12})")

def unique_horse_links(node):
    seen={}
    for a in node.select("a[href*='/horse/']"):
        name=a.get_text(" ",strip=True)
        href=(a.get("href") or "").split("?")[0]
        if name and href and href not in seen:
            seen[href]=(name,a)
    return list(seen.values())

def parse_number_near_anchor(a,name):
    cur=a
    for _ in range(6):
        if cur is None: break
        # Explicit attributes/classes first
        for el in cur.select("[data-umaban],[data-horse-no],[data-number],.Umaban,.Num,.WakuNum,.WakuNumBox,[class*='Umaban'],[class*='umaban']"):
            txt=el.get_text(" ",strip=True)
            m=re.search(r"(?<!\d)(1[0-8]|[1-9])(?!\d)",txt)
            if m: return int(m.group(1))
        txt=re.sub(r"\s+"," ",cur.get_text(" ",strip=True))
        pos=txt.find(name)
        if pos>=0:
            before=txt[max(0,pos-100):pos]
            nums=list(re.finditer(r"(?<!\d)(1[0-8]|[1-9])(?!\d)",before))
            if nums:
                return int(nums[-1].group(1))
        cur=cur.parent
    return None

def build_items(links):
    items=[]
    for name,a in links:
        items.append({
            "name":name,
            "href":a.get("href",""),
            "number":parse_number_near_anchor(a,name)
        })
    return items

def candidate_sets(soup):
    sets=[]
    selectors=[
        "tr.HorseList","tr[class*='HorseList']",
        "li.HorseList","li[class*='HorseList']",
        "div.HorseList","div[class*='HorseList']",
        ".Shutuba_Table","[class*='Shutuba']",
        ".RaceTable","[class*='RaceTable']",
        "table"
    ]
    for sel in selectors:
        for node in soup.select(sel):
            links=unique_horse_links(node)
            n=len(links)
            if 2<=n<=18:
                sets.append(build_items(links))
    # Every ancestor of every horse link is also a candidate.
    for a in soup.select("a[href*='/horse/']"):
        cur=a
        for _ in range(7):
            if cur is None: break
            links=unique_horse_links(cur)
            n=len(links)
            if 2<=n<=18:
                sets.append(build_items(links))
            cur=cur.parent
    # Whole page candidate, if it contains a plausible number of horse links.
    links=unique_horse_links(soup)
    if 2<=len(links)<=18:
        sets.append(build_items(links))
    return sets

def score_candidate(items):
    # Prefer the largest plausible group; a real entry list is normally the
    # largest contiguous group of horse-detail links on a shutuba page.
    n=len(items)
    numbered=sum(x["number"] is not None for x in items)
    unique_nums=len({x["number"] for x in items if x["number"] is not None})
    return (n, numbered, unique_nums)

def fetch_race(url):
    m=RACE_ID_RE.search(url)
    if not m: raise ValueError("netkeibaのレースURLからrace_idを取得できませんでした。")
    race_id=m.group(1)

    r=requests.get(url,headers={"User-Agent":"Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"},timeout=20)
    r.raise_for_status()
    soup=BeautifulSoup(r.text,"html.parser")
    title=soup.title.get_text(" ",strip=True) if soup.title else f"Race {race_id}"

    candidates=candidate_sets(soup)
    if not candidates:
        return {"race_id":race_id,"title":title,"horses":[],"horse_link_count":len(unique_horse_links(soup))}

    # Critical v9 change: don't take the first 4/5-link container.
    # Choose the largest plausible horse group.
    best=max(candidates,key=score_candidate)

    # Deduplicate and keep all detected horses.
    by_href={}
    for x in best:
        by_href[x["href"].split("?")[0]]=x
    horses=list(by_href.values())

    # If duplicate numbers occur, only remove duplicates when the same horse
    # link is duplicated; do not throw away legitimate horses just because
    # number parsing was imperfect.
    known=[x for x in horses if x["number"] is not None]
    unknown=[x for x in horses if x["number"] is None]
    known.sort(key=lambda x:x["number"])
    horses=known+unknown

    return {
        "race_id":race_id,
        "title":title,
        "horses":horses,
        "horse_link_count":len(unique_horse_links(soup))
    }

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
