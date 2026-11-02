# AI 쇼츠 자동 생성기

상품 URL · 상품 정보 · 사진 · 영상을 넣으면 Claude Code 가 보고 대본/장면을 짜고,
Windows TTS 와 ffmpeg 로 9:16 쇼츠(MP4)를 만든다. 말로 수정하기, 장면 직접 수정, 버전 기록 지원.

## 필요
- Windows, Python 3.11+, ffmpeg (PATH)
- Claude Code 로그인 (`irm https://claude.ai/install.ps1 | iex` 후 `claude` → `/login`)

## 실행
```
python app.py
```
브라우저에서 http://127.0.0.1:8766 이 열린다. 기본 BGM·효과음은 첫 실행 때 자동 생성된다.

CLI: `python shorts.py --help`
