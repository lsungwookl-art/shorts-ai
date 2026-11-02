# AI 쇼츠 자동 생성기

상품 URL · 상품 정보 · 사진 · 영상을 넣으면 Claude Code 가 보고 대본/장면을 짜고,
Windows TTS 와 ffmpeg 로 9:16 쇼츠(MP4)를 만든다. 말로 수정하기, 장면 직접 수정, 버전 기록 지원.

## 설치

파이썬 패키지는 필요 없다(표준 라이브러리만 사용). 아래 프로그램만 있으면 된다.

### 필수
| 항목 | 이유 | 설치 |
|---|---|---|
| Windows 10/11 | 음성은 Windows 내장 TTS, 글꼴은 `C:\Windows\Fonts` 사용. Mac/Linux 미지원 | - |
| 한국어 음성 (Microsoft Heami) | AI 음성 6종이 모두 이 음성 기반 | 한국어 Windows 는 보통 기본 포함. 없으면 설정 > 시간 및 언어 > 언어 및 지역 > 한국어 > 언어 옵션 > 음성 |
| Python 3 | 실행 | python.org (설치 시 "Add to PATH" 체크) |
| ffmpeg / ffprobe | 영상 렌더링 | `winget install Gyan.FFmpeg` |
| Claude Code + 로그인 | AI 기획·수정·캡션 (Claude 유료 구독 Pro 이상) | `irm https://claude.ai/install.ps1 \| iex` 후 `claude` 실행 → `/login` |

### 선택
- **GPT**: Codex CLI + ChatGPT 계정 로그인. Node.js 필요. `npm i -g @openai/codex` 후 `codex login`.
  AI 설정 > 모델에서 GPT-5.6 Terra/Luna 선택. 무료 계정은 사용 한도에 금방 걸린다.
- **인스타그램 스킬**: 아래 "인스타그램 스킬" 참고. 저장소에 포함되어 있지 않다.
- **글꼴**: 맑은 고딕은 기본. HY·휴먼 계열은 한컴오피스 등이 설치된 PC 에만 있고, 없으면 목록에서 빠진다.

> 테스트 환경: Windows 11, Python 3.14, ffmpeg 8.1. 다른 버전/깨끗한 PC 에서의 설치는 아직 검증하지 않았다.

## 실행
```
python app.py
```
브라우저에서 http://127.0.0.1:8766 이 열린다. 기본 BGM·효과음은 첫 실행 때 자동 생성된다.

CLI: `python shorts.py --help`

## 인스타그램 스킬 (선택)
`~/.claude/skills` 에 `ig-reel`, `ig-human`, `ig-caption` 이 있으면 자동으로 쓴다. 없으면 건너뛴다.
- ig-reel: 훅 공식 26개로 훅 후보 3개를 쓰고 가장 좋은 것을 첫 장면에
- ig-human: `humanize.py` 로 대본·캡션의 줄표·숨은 문자 제거
- ig-caption: "캡션 만들기" 버튼, `caption.py` 점검 (영어 기준이라 한글 판정 일부는 참고용)
