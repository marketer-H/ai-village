#!/usr/bin/env python3
"""feeds.json의 RSS/Atom 피드를 읽어 data/articles.json을 갱신한다."""
import html, json, re, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
MAX_PER_FEED = 20
SCAN_LIMIT = 60
AI_WORDS = ["ai", "인공지능", "챗gpt", "chatgpt", "gpt", "생성형", "llm", "클로드", "claude", "제미나이", "gemini", "코파일럿", "copilot", "딥러닝", "머신러닝", "오픈ai", "앤트로픽", "딥시크"]
MAX_TOTAL = 800
ATOM = "{http://www.w3.org/2005/Atom}"


# 위에서부터 먼저 걸리는 분야로 분류한다. 어디에도 안 걸리면 공식 출처는 "공식 자료", 나머지는 "기타".
CATEGORIES = [
    ("영상·이미지", ["영상", "동영상", "편집", "이미지", "사진", "그림", "음악", "음성", "목소리", "video", "sora", "veo", "image", "photo", "music", "audio", "voice", "midjourney", "runway", "diffusion"]),
    ("생활·교육", ["시니어", "노인", "어르신", "중장년", "교육", "학교", "학생", "수업", "일상", "생활", "건강", "의료", "보이스피싱", "사기", "육아", "여행", "요리", "활용법", "배우", "강좌", "입문"]),
    ("SNS·마케팅", ["sns", "인스타", "유튜브", "틱톡", "쇼츠", "블로그", "마케팅", "광고", "콘텐츠", "크리에이터", "소셜", "instagram", "youtube", "tiktok", "social", "creator", "marketing", "ads", "seo"]),
    ("업무 활용", ["업무용", "업무 효율", "직장인", "생산성", "자동화", "엑셀", "문서", "회의", "보고서", "코딩", "에이전트 활용", "워크플로", "workflow", "productivity", "excel", "microsoft 365", "copilot", "coding", "workspace", "chatgpt work", "assistant"]),
]
OFFICIAL_SOURCES = {"OpenAI", "Google AI", "Hugging Face"}
OFFICIAL, DEFAULT_CATEGORY = "공식 자료", "기타"


def classify(a):
    text = (a["title"] + " " + a["summary"]).lower()
    for name, words in CATEGORIES:
        if has_any(text, words):
            return name
    return OFFICIAL if a["source"] in OFFICIAL_SOURCES else DEFAULT_CATEGORY


def clean(text, limit=200):
    text = html.unescape(re.sub(r"<[^>]+>", "", text or ""))
    if re.match(r"\s*submitted by", text):  # 레딧 링크 글의 의미 없는 요약
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def page_date(url):
    """피드에 날짜가 없는 글은 본문 페이지의 발행일(JSON-LD, og 메타)을 읽는다. 못 찾으면 None."""
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ai-articles/1.0)"}
    try:
        try:
            r = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=15)
        except urllib.error.HTTPError as e:
            if e.code != 308 or not e.headers.get("Location"):  # 구버전 Python은 308을 따라가지 못한다
                raise
            r = urllib.request.urlopen(urllib.request.Request(urljoin(url, e.headers["Location"]), headers=headers), timeout=15)
        with r:
            body = r.read(400_000).decode("utf-8", "ignore")
    except Exception:
        return None
    m = (re.search(r'datePublished\\?"\s*:\s*\\?"([^"\\]+)', body)
         or re.search(r'article:published_time"\s+content="([^"]+)', body)
         or re.search(r'content="([^"]+)"\s+property="article:published_time', body))
    time.sleep(0.5)
    return parse_date(m.group(1)) if m else None


def parse_date(raw):
    if not raw:
        return None
    try:
        d = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def has_any(text, words):
    """영문 키워드는 단어 시작 경계에서만, 한글은 부분 일치로 찾는다."""
    for w in words:
        if w.isascii():
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + (r"(?![a-z])" if len(w) <= 3 else ""), text):
                return True
        elif w in text:
            return True
    return False


def is_ai(text):
    return has_any(text.lower(), AI_WORDS)


def fetch(feed):
    req = urllib.request.Request(feed["url"], headers={"User-Agent": "Mozilla/5.0 (compatible; ai-articles/1.0)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        root = ET.fromstring(r.read())
    out = []
    for item in root.iter("item"):
        out.append((item.findtext("title"), item.findtext("link"),
                    item.findtext("description"), item.findtext("pubDate"),
                    item.findtext("source")))
    for entry in root.iter(ATOM + "entry"):
        link = entry.find(ATOM + "link")
        out.append((entry.findtext(ATOM + "title"),
                    link.get("href") if link is not None else None,
                    entry.findtext(ATOM + "summary") or entry.findtext(ATOM + "content"),
                    entry.findtext(ATOM + "published") or entry.findtext(ATOM + "updated"),
                    None))
    articles = []
    for title, link, desc, date, origin in out[:SCAN_LIMIT]:
        if len(articles) >= MAX_PER_FEED:
            break
        if not title or not link:
            continue
        if feed.get("ai_only") and not is_ai(title + " " + (desc or "")):
            continue
        if origin:
            # 구글 뉴스: 제목 끝의 " - 매체명"을 떼고 원 매체명을 출처로 쓴다.
            title = re.sub(r"\s+-\s+" + re.escape(origin) + r"$", "", title)
            desc = ""  # 구글 뉴스 description은 제목 반복이라 버린다.
        when = parse_date(date) or page_date(link.strip())
        if when is None:
            continue  # 발행일을 알 수 없는 글은 '최근 글'을 흐리지 않도록 건너뛴다
        article = {
            "title": clean(title, 150), "url": link.strip(), "summary": clean(desc),
            "source": origin or feed["name"], "date": when.isoformat(),
        }
        if feed.get("category"):
            article["category_hint"] = feed["category"]
        if feed.get("hot") and len(articles) < 10:
            article["hot"] = True  # 인기순 피드의 상위 글
        articles.append(article)
    return articles


def apply_translations(articles):
    """data/translations.json(URL → 한국어 제목·요약)을 적용하고, 번역이 안 된 영어 글을 untranslated.json에 남긴다."""
    path = ROOT / "data" / "translations.json"
    tr = json.loads(path.read_text()) if path.exists() else {}
    missing = []
    for a in articles:
        if re.search("[가-힣]", a["title"]):
            continue
        t = tr.get(a["url"])
        if t:
            a.setdefault("title_en", a["title"])
            a["title"], a["summary"] = t["title"], t["summary"]
        else:
            missing.append({"url": a["url"], "title": a["title"], "summary": a["summary"]})
    (ROOT / "data" / "untranslated.json").write_text(json.dumps(missing, ensure_ascii=False, indent=1))
    return len(missing)


def bigrams(title):
    t = re.sub(r"[^0-9a-z가-힣]", "", title.lower())
    return {t[i:i + 2] for i in range(len(t) - 1)}


STOPWORDS = {"ai", "인공지능", "공개", "출시", "개최", "발표", "서비스", "기술", "기업", "시장", "국내", "글로벌", "신규", "도입", "추진", "강화", "확대", "업무", "활용", "자동화", "교육", "생활", "일상", "지원", "운영", "프로그램", "과정", "시민", "대상", "선정", "수상", "참여", "협력", "체결", "개발", "구축", "시대", "사례", "플랫폼", "솔루션", "기반", "통해", "위한", "이용", "사용", "the", "and", "for", "with", "how", "new"}


def keywords(title):
    """제목의 핵심 단어 집합. 한글은 조사 차이를 줄이려고 앞 3글자만 쓴다."""
    words = re.findall(r"[A-Za-z0-9]{2,}|[가-힣]{2,}", title.lower())
    return {w[:3] if re.match("[가-힣]", w) else w for w in words if w not in STOPWORDS}


def same_story(g1, k1, g2, k2, threshold):
    return len(g1 & g2) / max(len(g1 | g2), 1) >= threshold or (len(k1 & k2) >= 3 and len(k1 & k2) / max(min(len(k1), len(k2)), 1) >= 0.5)


def dedupe(articles, prior, threshold=0.4):
    """제목이 비슷한 글(같은 사건)은 먼저 나온 하나만 남기고, 몇 곳이 다뤘는지를 buzz로 센다."""
    clusters = []  # [대표 글, 제목 bigram, 출처 집합, 핵심 단어]
    for a in articles:
        g, k = bigrams(a["title"]), keywords(a["title"])
        for c in clusters:
            if same_story(g, k, c[1], c[3], threshold):
                c[2].add(a["source"])
                if a.get("hot"):
                    c[0]["hot"] = True
                break
        else:
            clusters.append([a, g, {a["source"]}, k])
    for rep, _, sources, _k in clusters:
        score = len(sources) + (2 if rep.get("hot") else 0)  # 레딧 주간 인기글은 두 곳이 다룬 것으로 친다
        rep["buzz"] = max(score, prior.get(rep["url"], 0))  # 오래된 글이 피드에서 빠져도 점수가 줄지 않게
        rep.pop("hot", None)
    return [c[0] for c in clusters]


def main():
    feeds = json.loads((ROOT / "feeds.json").read_text())
    path = ROOT / "data" / "articles.json"
    by_url = {a["url"]: a for a in json.loads(path.read_text())}
    prior = {u: a.get("buzz", 0) for u, a in by_url.items()}
    for i, feed in enumerate(feeds):
        if i:
            time.sleep(8 if "reddit.com" in feed["url"] else 1.5)  # 레딧은 요청이 몰리면 429로 막는다
        try:
            got = fetch(feed)
        except Exception as e:
            print(f"skip {feed['name']}: {e}", file=sys.stderr)
            continue
        for a in got:
            by_url[a["url"]] = a
        print(f"{feed['name']}: {len(got)}")
    for a in by_url.values():
        a["category"] = a.get("category_hint") or classify(a)
    merged = sorted(by_url.values(), key=lambda a: a["date"], reverse=True)
    left = apply_translations(merged)  # 번역한 한국어 제목으로 비교해야 영어 글과 한국어 기사가 같은 사건으로 묶인다
    merged = dedupe(merged, prior)[:MAX_TOTAL]
    path.write_text(json.dumps(merged, ensure_ascii=False, indent=1))
    print(f"total {len(merged)} (번역 대기 {left})")


if __name__ == "__main__":
    main()
