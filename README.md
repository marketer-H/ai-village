# AI 회관

AI 공부하는 사람들이 모이는 곳. RSS와 구글 뉴스 검색으로 AI 글을 모아 보여주는 정적 사이트입니다.

- 수집 출처: `feeds.json`
- 수집·분류·번역 적용: `python3 scripts/fetch_feeds.py`
- 영어 글 번역: `data/translations.json` (URL → 한국어 제목·요약)
- 직접 고른 추천 글: `data/picks.json` (URL → 한 줄 코멘트)
- 로컬에서 보기: `python3 -m http.server 8765` 후 http://localhost:8765
- 하루 2번 GitHub Actions가 새 글을 수집해 `data/`를 갱신합니다.
