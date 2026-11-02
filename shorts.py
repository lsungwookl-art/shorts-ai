"""AI 쇼츠 자동 생성기 엔진 (메이커 셀링 도우미 AI 숏폼 방식 재현)

상품 URL(또는 내 자료) -> Claude Code 로그인 세션으로 대본/장면 설계 -> Windows TTS
-> ffmpeg 렌더링(9:16 MP4) -> 버전별 저장. 화면은 app.py.

CLI:
  python shorts.py new https://상품URL --shop 메이커몰
  python shorts.py new --info 상품정보.txt --images 이미지폴더 --opts opts.json
  python shorts.py edit 프로젝트폴더 "첫 장면 제목을 더 크게" [--from 2]
  python shorts.py rerender 프로젝트폴더 --plan plan.json [--opts opts.json]   (AI 없이 다시 렌더링)
  python shorts.py restore 프로젝트폴더 2      (v2 를 새 버전으로 복원)
  python shorts.py thumb 프로젝트폴더 [버전]
"""
import argparse, copy, html, json, re, shutil, subprocess, sys, time, urllib.request, wave
from pathlib import Path
from urllib.parse import urljoin

HERE = Path(__file__).resolve().parent
BGM_DIR, ASSETS = HERE / "bgm", HERE / "assets"
FONT_DIR = "C\\:/Windows/Fonts/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"}

FONTS = {"맑은 고딕 Bold": "malgunbd.ttf", "맑은 고딕": "malgun.ttf", "Noto Sans KR": "NotoSansKR-VF.ttf",
         "Noto Serif KR": "NotoSerifKR-VF.ttf", "굴림": "gulim.ttc", "바탕": "batang.ttc", "함초롬바탕": "HANBatang.ttf",
         "HY헤드라인M": "H2HDRM.TTF", "HY견고딕": "H2GTRE.TTF", "HY엽서M": "H2PORM.TTF",
         "휴먼둥근헤드라인": "HMKMRHD.TTF", "휴먼아미체": "HMKMAMI.TTF"}
FONTS = {k: v for k, v in FONTS.items() if Path("C:/Windows/Fonts", v).exists()}

# ponytail: Windows 내장 한국어 음성은 Heami(여성) 하나뿐 -> 남성은 피치를 낮춰 만든다. 더 자연스러운 음성은 TTS API 연동 시 교체.
VOICES = {"f1": ("여성 1 - 차분함", 0, 1.0), "f2": ("여성 2 - 밝고 발랄함", 2, 1.07), "f3": ("여성 3 - 또박또박", -1, 1.0),
          "m1": ("남성 1 - 부드러움", 1, 0.80), "m2": ("남성 2 - 중저음", 0, 0.72), "m3": ("남성 3 - 활기참", 3, 0.82)}
MOTIONS = ["zoomin", "zoomout", "panleft", "panright", "panup", "pandown"]
TRANSITIONS = ["fade", "slideup", "slideleft", "wipeleft", "zoomin", "circleopen", "dissolve"]
TEMPO = {"fast": (0.8, 0.35), "normal": (1.0, 0.25), "slow": (1.25, 0.15)}  # (길이 배수, 움직임 양)

STYLE = dict(font="맑은 고딕 Bold", size=78, color="#FFE14D", border_color="#000000", border_w=3, shadow=False,
             bg_color="#000000", bg_alpha=0.55, spacing=0, line_spacing=12, align="C", x=50, y=66)
SUB = dict(STYLE, font="맑은 고딕 Bold", size=46, color="#FFFFFF", border_w=2, bg_alpha=0.6, y=86)
SHOP = dict(STYLE, font="맑은 고딕 Bold", size=44, color="#FFFFFF", border_w=0, bg_alpha=0.35, y=6)
TEMPLATES = {
    "dynamic": ("다이내믹 자막형", "전체 화면 상품 이미지 + 큰 노란 자막. 짧고 임팩트 있는 문구",
                dict(caption=STYLE, subtitle=SUB, shop=SHOP)),
    "collage": ("콜라주 형태", "2x2 이미지 콜라주 위 가운데 컬러 박스 자막. 여러 컷/구성/색상 강조",
                dict(caption=dict(STYLE, size=80, color="#FFFFFF", bg_color="#FF3B6B", bg_alpha=0.92, border_w=0, y=45),
                     subtitle=SUB, shop=SHOP)),
    "search": ("검색 시나리오형", "검색창에 키워드를 입력하고 결과로 상품이 나오는 흐름. 고객이 검색할 문제/키워드 중심",
               dict(caption=dict(STYLE, size=70, color="#111111", border_w=0, bg_alpha=0, y=76),
                    subtitle=dict(SUB, color="#333333", bg_alpha=0, border_w=0, y=87),
                    shop=dict(SHOP, color="#555555", bg_alpha=0, y=4))),
    "black": ("프리미엄 블랙형", "검은 배경 위 정사각 이미지 + 흰색 고급스러운 자막. 차분하고 고급스러운 톤",
              dict(caption=dict(STYLE, size=70, color="#FFFFFF", bg_alpha=0, border_w=0, y=76),
                   subtitle=dict(SUB, bg_alpha=0, y=87), shop=dict(SHOP, bg_alpha=0))),
}
DEFAULT_OPTS = dict(shop="", shop_pos="auto", ai_mark=True, seconds=20, template="dynamic", voice="f2",
                    bgm="auto", bgm_volume=0.15, sfx=True, subtitles=False, model="opus", effort="medium",
                    tempo="normal", motion="auto", transition="fade", text_mode="video", res="1080x1920", fps=30,
                    styles=None)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if r.returncode:
        sys.exit(f"실패: {cmd[0]}\n{(r.stderr or r.stdout)[-2000:]}")
    return r.stdout


def write(path, text, spacing=0):
    if spacing:  # ponytail: drawtext 에 자간 옵션이 없어 얇은 공백(U+2009)을 끼워 근사
        text = "\n".join(("\u2009" * int(spacing)).join(line) for line in text.split("\n"))
    Path(path).write_text(text, encoding="utf-8", newline="\n")


def merge_opts(*parts):
    o = copy.deepcopy(DEFAULT_OPTS)
    for p in parts:
        o.update({k: v for k, v in (p or {}).items() if k in DEFAULT_OPTS})
    return o


def styles_for(opt):
    st = copy.deepcopy(TEMPLATES[opt["template"]][2])
    for el, s in (opt.get("styles") or {}).items():
        if el in st:
            st[el].update(s)
    if opt["shop_pos"] == "auto":
        st["shop"].update(x=50, y=TEMPLATES[opt["template"]][2]["shop"]["y"], align="C")
    return st


# ---------- 기본 BGM / 효과음 (영상의 기본 BGM 2곡처럼 내장. 첫 실행 때 합성) ----------
def ensure_assets():
    BGM_DIR.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)
    pick = lambda prog, n: "+".join(f"if(between(mod(t,{len(prog) * 2}),{i * 2},{i * 2 + 2 - 1e-6}),{c[n]},0)" for i, c in enumerate(prog))
    pop = [(261.6, 329.6, 392.0), (196.0, 246.9, 293.7), (220.0, 261.6, 329.6), (174.6, 220.0, 261.6)]
    calm = [(220.0, 261.6, 329.6), (174.6, 220.0, 261.6), (261.6, 329.6, 392.0), (196.0, 246.9, 293.7)]
    f = lambda prog: [pick(prog, n) for n in range(3)]
    a, b, c = f(pop)
    bright = (f"0.05*(sin(2*PI*({a})*t)+sin(2*PI*({b})*t)+sin(2*PI*({c})*t))*(0.5+0.5*exp(-4*mod(t,0.5)))"
              f"+0.12*sin(PI*({a})*t)*exp(-5*mod(t,0.5))+0.3*sin(2*PI*55*t)*exp(-25*mod(t,0.5))"
              f"+0.03*(random(0)*2-1)*exp(-60*mod(t+0.25,0.5))")
    a, b, c = f(calm)
    soft = f"0.06*(sin(2*PI*({a})*t)+sin(2*PI*({b})*t)+0.7*sin(2*PI*({c})*t))*(1-exp(-3*mod(t,2)))*exp(-0.4*mod(t,2))+0.06*sin(PI*({a})*t)"
    for name, expr, extra in (("밝은 팝.wav", bright, "lowpass=f=6000"), ("차분한 감성.wav", soft, "aecho=0.8:0.6:120:0.35,lowpass=f=3000")):
        if not (BGM_DIR / name).exists():
            run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=44100:d=16", "-af", f"{extra},volume=0.9", "-ac", "2", str(BGM_DIR / name)])
    if not (ASSETS / "sfx.wav").exists():
        run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.45:c=pink:a=0.6",
             "-f", "lavfi", "-i", "aevalsrc='0.4*sin(2*PI*(600+2500*t)*t)*exp(-28*t)':s=44100:d=0.2",
             "-filter_complex", "[0]bandpass=f=1500:w=1200,afade=t=in:d=0.15,afade=t=out:st=0.15:d=0.3,volume=0.5[w];"
                                "[1]adelay=120|120[p];[w][p]amix=inputs=2:normalize=0", "-ac", "2", "-ar", "44100", str(ASSETS / "sfx.wav")])


def bgm_list():
    return sorted(p.name for p in BGM_DIR.glob("*") if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".ogg"))


# ---------- 미디어 (사진 + 영상 클립) ----------
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".img"}  # .img: 이전 버전 프로젝트 호환
VID_EXT = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}


def media_files(proj):
    d = proj / "img"
    return sorted(p.resolve() for p in d.iterdir() if p.suffix.lower() in IMG_EXT | VID_EXT) if d.exists() else []


def is_video(p):
    return Path(p).suffix.lower() in VID_EXT


def duration(p):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).strip()
    return float(out) if out and out != "N/A" else 0.0


def prepare_media(proj):
    """Claude 가 Read 도구로 볼 미리보기(vision/NN.jpg)를 만들고 미디어 설명 목록을 돌려준다.
    영상은 25/50/75% 지점 3컷을 시간 표시와 함께 가로로 붙인다."""
    vis = proj.resolve() / "vision"
    vis.mkdir(exist_ok=True)
    desc = []
    for i, p in enumerate(media_files(proj)):
        out = vis / f"{i:02d}.jpg"
        if is_video(p):
            dur = duration(p)
            ts = [round(dur * f, 1) for f in (0.25, 0.5, 0.75)]
            if not out.exists():
                ins = sum((["-ss", str(t), "-i", str(p)] for t in ts), [])
                cells = ";".join(f"[{j}:v]scale=360:640:force_original_aspect_ratio=decrease,pad=360:640:(ow-iw)/2:(oh-ih)/2,"
                                 f"drawtext=fontfile='{FONT_DIR}malgunbd.ttf':text='{t}s':fontsize=40:fontcolor=yellow:"
                                 f"box=1:boxcolor=black@0.6:x=12:y=12,trim=end_frame=1[c{j}]" for j, t in enumerate(ts))
                run(["ffmpeg", "-y", *ins, "-filter_complex", f"{cells};[c0][c1][c2]hstack=inputs=3", "-frames:v", "1", str(out)])
            desc.append(f"{i}: 영상 클립 {dur:.1f}초 (미리보기 vision/{i:02d}.jpg = {ts[0]}s/{ts[1]}s/{ts[2]}s 지점 3컷)")
        else:
            if not out.exists():
                run(["ffmpeg", "-y", "-i", str(p), "-vf", "scale=768:768:force_original_aspect_ratio=decrease", "-frames:v", "1", str(out)])
            desc.append(f"{i}: 사진 (미리보기 vision/{i:02d}.jpg)")
    return desc


def image_ext(data):
    return ".jpg" if data[:3] == b"\xff\xd8\xff" else ".png" if data[:4] == b"\x89PNG" else \
        ".webp" if data[:4] == b"RIFF" and data[8:12] == b"WEBP" else None


# ---------- 인스타그램 스킬 연동 (~/.claude/skills 의 ig-reel / ig-human / ig-caption, 없으면 건너뜀) ----------
SKILLS = Path.home() / ".claude" / "skills"


def skill(name, file):
    p = SKILLS / name / file
    return p if p.exists() else None


def reel_guide():
    """ig-reel 의 훅 공식 26개와 규칙을 기획 프롬프트용으로. (hookscore.py 는 영어 전용이라 쓰지 않음)"""
    p = skill("ig-reel", "hooks.json")
    if not p:
        return ""
    d = json.loads(p.read_text(encoding="utf-8"))
    forms = "\n".join(f"#{h['id']} {h['name']}: {h['template']} (예: {h['example']}) 용도: {h['best_for']} 주의: {h['trap']}"
                      for h in d["hooks"])
    rules = "\n".join(f"- {r}" for r in d.get("rules", []))
    return f"""
[ig-reel 스킬: 릴스 훅 공식과 규칙. 영어 예시는 참고만 하고 한국어로 자연스럽게 적용]
{rules}
- 인사·도입부("안녕하세요", "오늘 소개할") 금지. 첫 장면 narration 이 곧 훅이고 2초 안에 말할 수 있어야 한다.
- 마지막 장면은 훅이 약속한 것을 전달하고 요청은 하나만. 마지막 문장에 훅의 단어 하나를 다시 써서 다시 보기로 이어지게.
- caption(화면 큰 글씨)은 6단어 이하.
- 아래 공식 중 상품에 맞는 서로 다른 공식 3개로 훅 후보(hooks)를 쓰고, 가장 좋은 하나를 chosen=true 로 표시해 첫 장면에 쓴다.
훅 공식:
{forms}
"""


def humanize(texts):
    """ig-human 의 humanize.py 로 줄표·숨은 문자 같은 기계적 흔적을 지운다. (detect.py 점수는 영어 전용이라 쓰지 않음)"""
    script = skill("ig-human", "humanize.py")
    if not script or not texts:
        return texts, 0
    sep = "\n@@@@\n"
    tmp = HERE / "shorts_out" / "_tmp" / f"h{time.time_ns()}.txt"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(sep.join(texts), encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(tmp)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    tmp.unlink(missing_ok=True)
    out = r.stdout.rstrip("\n").split(sep) if r.returncode == 0 else []
    if len(out) != len(texts):  # 형식이 깨지면 원문 유지
        return texts, 0
    return out, sum(a != b for a, b in zip(texts, out))


def polish(plan):
    sc = plan["scenes"]
    texts, n = humanize([s["narration"] for s in sc] + [s["caption"] for s in sc])
    for i, s in enumerate(sc):
        s["narration"], s["caption"] = texts[i], texts[len(sc) + i]
    if n:
        print(f"  ig-human: 문장 {n}곳의 기계적 흔적(줄표, 숨은 문자 등)을 다듬음", flush=True)
    return plan


CAPTION_SCHEMA = {"type": "object", "required": ["caption", "search_terms"], "properties": {
    "caption": {"type": "string"}, "search_terms": {"type": "array", "items": {"type": "string"}}}}


def make_caption(proj, ver):
    """ig-caption 지침으로 인스타 캡션을 쓰고 caption.py 로 점검한다."""
    plan, opt = load_version(proj, ver)
    guide = skill("ig-caption", "SKILL.md")
    info = (proj / "info.txt").read_text(encoding="utf-8") if (proj / "info.txt").exists() else ""
    script = "\n".join(f"- {s['narration']}" for s in plan["scenes"])
    print(f"v{ver} 영상의 인스타그램 캡션 작성 중 ({'ig-caption 스킬 지침' if guide else '기본 지침'})...", flush=True)
    data = ask_claude(f"""아래 쇼츠(릴스)에 붙일 인스타그램 캡션을 한국어로 써라.
- 이 영상은 첫 2초 훅이 이미 있다(Job A). 캡션은 두 번째 훅이 아니라 맥락, 요청 하나, 검색어를 담는다.
- 첫 줄은 125자 안에서 완결되게. 인사·해시태그·이모지로 시작하지 마라.
- 본문은 짧은 문단 2~4개, 문단 사이 빈 줄. 사람이 검색창에 칠 검색어 2~3개를 문장 안에 자연스럽게 넣고 search_terms 에도 적어라.
- 요청은 하나(예: 댓글로 키워드 남기기, 저장하기). 링크 금지. 해시태그는 맨 아래 줄에 3~5개, 구체적인 것만.
- 상품 정보와 대본에 없는 사실은 지어내지 마라. 상점명: {opt['shop'] or '없음'}
{('[ig-caption 스킬 지침]' + chr(10) + guide.read_text(encoding='utf-8')) if guide else ''}

[영상 대본]
{script}

[상품 정보]
{info.strip() or '(없음)'}""", opt["model"], opt["effort"], schema_=CAPTION_SCHEMA)
    (cap,), n = humanize([data["caption"].strip()])
    out = proj / f"caption_v{ver}.txt"
    write(out, cap)
    report = ""
    if lint := skill("ig-caption", "caption.py"):
        r = subprocess.run([sys.executable, str(lint), str(out), "--keywords", ",".join(data.get("search_terms", []))],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        report = (r.stdout + "\n※ caption.py 는 영어 기준이라 한글 해시태그 개수, 숫자, 요청(CTA) 판정은 참고용입니다.").strip()
    write(proj / f"caption_v{ver}_check.txt", report)
    print(cap + ("\n\n" + report if report else ""), flush=True)
    return out


# ---------- 1. 상품 정보 수집 ----------
def scrape(url, img_dir):
    page = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read().decode("utf-8", "replace")
    meta = lambda p: (m.group(1) if (m := re.search(p, page, re.I | re.S)) else "")
    title = meta(r'property="og:title"\s+content="([^"]*)') or meta(r"<title>(.*?)</title>")
    desc = meta(r'property="og:description"\s+content="([^"]*)') or meta(r'name="description"\s+content="([^"]*)')
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body)))[:6000]
    srcs = [meta(r'property="og:image"\s+content="([^"]*)')]
    srcs += re.findall(r'<img[^>]+(?:data-src|src)="([^"]+\.(?:jpe?g|png|webp)[^"]*)"', page, re.I)
    imgs = []
    for s in dict.fromkeys(filter(None, srcs)):
        if len(imgs) >= 10:
            break
        try:
            data = urllib.request.urlopen(urllib.request.Request(urljoin(url, html.unescape(s)), headers=UA), timeout=15).read()
        except Exception:
            continue
        if len(data) > 15_000 and (ext := image_ext(data)):  # 아이콘/스페이서/gif 제외
            p = img_dir / f"{len(imgs):02d}{ext}"
            p.write_bytes(data)
            imgs.append(p)
    return f"상품명: {html.unescape(title).strip()}\n설명: {html.unescape(desc).strip()}\n페이지 본문: {text}", imgs


# ---------- 2. Claude Code 로 대본/장면 설계 ----------
def schema():
    bgms = bgm_list()
    return {"type": "object", "required": ["title", "keyword", "bgm", "scenes"], "properties": {
        "title": {"type": "string"},
        "keyword": {"type": "string"},
        "bgm": {"enum": bgms} if bgms else {"type": "string"},
        "brightness": {"type": "number"},
        "hooks": {"type": "array", "items": {"type": "object", "required": ["formula", "line", "chosen"], "properties": {
            "formula": {"type": "string"}, "line": {"type": "string"}, "on_screen": {"type": "string"}, "chosen": {"type": "boolean"}}}},
        "scenes": {"type": "array", "items": {"type": "object",
                   "required": ["narration", "caption", "image", "seconds", "motion"], "properties": {
                       "narration": {"type": "string"}, "caption": {"type": "string"}, "image": {"type": "integer"},
                       "seconds": {"type": "number"}, "motion": {"enum": MOTIONS}, "caption_size": {"type": "integer"},
                       "clip_start": {"type": "number"}}}}}}


GPT_MODELS = {"gpt-5.6-terra": "GPT-5.6 Terra", "gpt-5.6-luna": "GPT-5.6 Luna"}  # ChatGPT 계정 Codex 에서 쓸 수 있는 모델


def strict(s):
    """OpenAI 구조화 출력 규칙: 모든 속성 required + additionalProperties false. 선택 속성은 null 허용."""
    s = copy.deepcopy(s)
    if s.get("type") == "object":
        req = set(s.get("required", []))
        props = {k: strict(v) for k, v in s.get("properties", {}).items()}
        s["properties"] = {k: v if k in req else {"anyOf": [v, {"type": "null"}]} for k, v in props.items()}
        s["required"], s["additionalProperties"] = list(props), False
    elif s.get("type") == "array":
        s["items"] = strict(s["items"])
    return s


def drop_nulls(x):
    if isinstance(x, dict):
        return {k: drop_nulls(v) for k, v in x.items() if v is not None}
    return [drop_nulls(v) for v in x] if isinstance(x, list) else x


def ask_gpt(prompt, model, effort, see_dir=None, schema_=None):
    """ChatGPT 계정으로 로그인한 Codex CLI 로 GPT 를 부른다. 이미지는 첨부(-i), 읽기 전용 샌드박스."""
    exe = shutil.which("codex") or sys.exit("Codex CLI 미설치: npm i -g @openai/codex 후 codex login (ChatGPT 계정)")
    tmp = HERE / "shorts_out" / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    sch, out = tmp / f"s{time.time_ns()}.json", tmp / f"o{time.time_ns()}.json"
    sch.write_text(json.dumps(strict(schema_ or schema()), ensure_ascii=False), encoding="utf-8")
    imgs = sum((["-i", str(p)] for p in sorted(Path(see_dir, "vision").glob("*.jpg"))), []) if see_dir else []
    # 사용자 설정(MCP 서버, 기본 모델 등)·규칙·플러그인·앱을 불러오지 않는 최소 실행
    r = subprocess.run([exe, "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
                        "-s", "read-only", "-c", "features.plugins=false", "-c", "features.apps=false",
                        "-m", model, "-c", f"model_reasoning_effort={effort}", *imgs,
                        "--output-schema", str(sch), "-o", str(out), "--json", "-"],
                       input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=see_dir or tmp)
    sch.unlink(missing_ok=True)
    if not out.exists():
        errs = [json.loads(l).get("error", {}).get("message") or json.loads(l).get("message")
                for l in r.stdout.splitlines() if l.startswith("{") and '"error"' in l and "turn" in l]
        msg = (errs[-1] if errs else (r.stderr or r.stdout)[-1500:]) or "알 수 없는 오류"
        hint = "\n-> PowerShell 에서 codex login 으로 ChatGPT 계정 로그인을 확인하세요." if re.search(r"auth|login|401", msg, re.I) else ""
        sys.exit(f"GPT(Codex) 오류: {msg}{hint}")
    data = json.loads(out.read_text(encoding="utf-8"))
    out.unlink(missing_ok=True)
    return drop_nulls(data)


def ask_claude(prompt, model, effort, see_dir=None, schema_=None):
    """see_dir 를 주면 그 폴더 안 이미지를 Claude 가 Read 도구로 직접 본다(읽기 전용). GPT 모델이면 Codex 로."""
    if model in GPT_MODELS:
        return ask_gpt(prompt, model, effort, see_dir, schema_)
    exe = shutil.which("claude") or sys.exit("Claude Code 미설치: PowerShell 에서 irm https://claude.ai/install.ps1 | iex 후 claude 로그인")
    tools = ["--tools", "Read", "--allowedTools", "Read"] if see_dir else ["--tools", ""]
    # --safe-mode: 이 PC 의 MCP 서버·플러그인·스킬·CLAUDE.md 를 불러오지 않음 (호출당 입력 약 55만 -> 3천 토큰)
    r = subprocess.run([exe, "-p", "--safe-mode", "--strict-mcp-config", "--model", model, "--effort", effort, *tools,
                        "--output-format", "json", "--json-schema", json.dumps(schema_ or schema(), ensure_ascii=False)],
                       input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=see_dir)
    try:
        res = json.loads(r.stdout)
    except json.JSONDecodeError:
        sys.exit(f"Claude Code 실행 실패:\n{(r.stderr or r.stdout)[-2000:]}")
    if res.get("is_error"):
        msg = str(res.get("result"))
        hint = "\n-> PowerShell 에서 claude 실행 후 /login 으로 다시 로그인하세요." if re.search(r"auth|login", msg, re.I) else ""
        sys.exit(f"Claude Code 오류: {msg}{hint}")
    data = res.get("structured_output") or res.get("result")
    if isinstance(data, str):
        data = json.loads(re.search(r"\{.*\}", data, re.S).group(0))
    return data


def plan_prompt(info, media, opt):
    t = TEMPLATES[opt["template"]]
    see = (f"먼저 아래 미리보기 이미지를 모두 확인해 상품 생김새·색·특징·각 컷의 장면을 직접 봐라 "
           f"(Read 도구로 열거나, 첨부된 경우 첨부 순서 = 미디어 번호).\n"
           + "\n".join(media)) if media else "미디어 없음 (image 는 0)"
    return f"""너는 쇼핑몰 숏폼 광고 기획자다. 아래 상품 정보와 미디어로 {opt['seconds']}초 세로형 쇼츠를 설계해라.
- 템플릿: {t[0]} ({t[1]})
- 장면 6~9개. narration 은 TTS 로 읽을 짧은 한 문장(존댓말, 15자 내외). 마지막은 "{opt['shop'] or '저희 스토어'}에서 만나보세요." 류의 마무리.
- caption 은 화면 큰 글씨(10자 이내, 필요하면 \\n 으로 2줄).
- image 는 장면 내용과 실제로 맞는 미디어 번호(0~{max(len(media) - 1, 0)}). 같은 미디어만 반복하지 말고 골고루.
- 영상 클립을 고른 장면은 clip_start(초)로 쓸 구간 시작점을 정한다(미리보기 3컷 시간 참고, 클립 길이 - 장면 길이 이내).
- seconds 합계는 약 {opt['seconds']}초. motion 은 장면마다 다양하게(사진에만 적용).
- keyword 는 고객이 검색창에 칠 만한 짧은 검색어(검색 시나리오형에서 사용).
- bgm 은 상품 분위기에 맞는 곡을 목록에서 고른다: {', '.join(bgm_list())}
- brightness 는 0(기본). 상품 정보나 미디어에서 확인되지 않는 사실(인증, 수치, 효능)은 지어내지 마라.
  상품 정보 텍스트가 없으면 미디어에서 보이는 것만으로 쓴다.
{reel_guide()}

[미디어]
{see}

[상품 정보]
{info.strip() or '(없음 - 미디어만 보고 판단)'}"""


# ---------- 3. TTS ----------
def tts(text, wav, voice):
    _, rate, pitch = VOICES.get(voice, VOICES["f2"])
    raw = Path(f"{wav}.raw.wav")
    write(f"{wav}.txt", text)
    run(["powershell", "-NoProfile", "-Command",
         "Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
         f"$s.SelectVoice('Microsoft Heami Desktop');$s.Rate={rate};$s.SetOutputToWaveFile('{raw}');"
         f"$s.Speak([IO.File]::ReadAllText('{wav}.txt'));$s.Dispose()"])
    with wave.open(str(raw)) as w:
        sr = w.getframerate()
    af = f"asetrate={round(sr * pitch)},aresample={sr},atempo={1 / pitch:.4f}" if pitch != 1 else "anull"
    run(["ffmpeg", "-y", "-i", str(raw), "-af", af, str(wav)])
    raw.unlink()
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


# ---------- 4. 렌더링 ----------
def motion_expr(m, n, amt):
    c = ("iw/2-iw/zoom/2", "ih/2-ih/zoom/2")
    return {"zoomin": (f"1+{amt}*on/{n}", *c), "zoomout": (f"{1 + amt}-{amt}*on/{n}", *c),
            "panleft": (f"{1 + amt * 0.8}", f"(iw-iw/zoom)*(1-on/{n})", c[1]),
            "panright": (f"{1 + amt * 0.8}", f"(iw-iw/zoom)*on/{n}", c[1]),
            "panup": (f"{1 + amt * 0.8}", c[0], f"(ih-ih/zoom)*(1-on/{n})"),
            "pandown": (f"{1 + amt * 0.8}", c[0], f"(ih-ih/zoom)*on/{n}")}[m]


def hexc(c, a=None):
    return "0x" + c.lstrip("#").upper() + (f"@{a}" if a is not None else "")


def drawtext(file, st, k, enable=None):
    p = [f"fontfile='{FONT_DIR}{FONTS.get(st['font'], 'malgunbd.ttf')}'", f"textfile='{file}'",
         f"fontsize={max(8, round(st['size'] * k))}", f"fontcolor={hexc(st['color'])}",
         f"line_spacing={round(st['line_spacing'] * k)}", f"text_align={st['align']}",
         "x=" + {"L": f"w*{st['x']}/100", "C": f"w*{st['x']}/100-text_w/2", "R": f"w*{st['x']}/100-text_w"}[st["align"]],
         f"y=h*{st['y']}/100"]
    if st["border_w"]:
        p += [f"borderw={max(1, round(st['border_w'] * k))}", f"bordercolor={hexc(st['border_color'])}"]
    if st["shadow"]:
        p += [f"shadowx={round(4 * k)}", f"shadowy={round(4 * k)}", "shadowcolor=black@0.6"]
    if st["bg_alpha"] > 0:
        p += ["box=1", f"boxcolor={hexc(st['bg_color'], st['bg_alpha'])}", f"boxborderw={round(22 * k)}"]
    if enable:
        p.append(f"enable='{enable}'")
    return "drawtext=" + ":".join(p)


def render_scene(i, n_sc, sc, plan, imgs, dur, vdur, d, opt, styles):
    W, H = map(int, opt["res"].split("x"))
    k, fps, tpl = W / 1080, int(opt["fps"]), opt["template"]
    nfr = round(vdur * fps)
    motion = sc["motion"] if opt["motion"] == "auto" else MOTIONS[(i * 7 + 3) % len(MOTIONS)] if opt["motion"] == "random" else opt["motion"]
    z, x, y = motion_expr(motion if motion in MOTIONS else "zoomin", nfr, TEMPO[opt["tempo"]][1])
    zp = lambda s: f"zoompan=z='{z}':x='{x}':y='{y}':d={nfr}:s={s}:fps={fps}"
    inputs, fc = [], []

    def add(*args):  # 입력 하나 추가 -> 스트림 번호
        inputs.append(list(args))
        return len(inputs) - 1

    def pick(j=0):
        return imgs[(sc["image"] + j) % len(imgs)] if imgs else None

    def img(j=0):  # 사진(단일 프레임 -> zoompan 으로 움직임)
        p = pick(j)
        i_ = add("-i", str(p)) if p else add("-f", "lavfi", "-i", f"color=c=0x333333:s={W}x{H}:r=1:d=1")
        return f"[{i_}:v]"

    def clip(j, w, h):  # 영상 클립: clip_start 부터 장면 길이만큼, 짧으면 반복. 원본 소리는 쓰지 않음
        start = float(sc.get("clip_start") or 0) if j == 0 else 0
        i_ = add("-stream_loop", "-1", "-ss", f"{start}", "-i", str(pick(j)))
        return (f"[{i_}:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
                f"trim=duration={vdur},setpts=PTS-STARTPTS")

    def still(j, w, h):  # 영상과 섞일 때 사진을 고정 영상으로
        p = pick(j)
        i_ = add("-loop", "1", "-framerate", str(fps), "-t", f"{vdur}", "-i", str(p)) if p else \
            add("-f", "lavfi", "-i", f"color=c=0x333333:s={w}x{h}:r={fps}:d={vdur}")
        return f"[{i_}:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"

    vid = imgs and is_video(pick())
    cap = dict(styles["caption"], size=sc.get("caption_size") or styles["caption"]["size"])
    write(d / f"cap{i}.txt", sc["caption"].replace("\\n", "\n"), cap["spacing"])
    on_image = opt["text_mode"] == "image" and tpl == "dynamic"  # 이미지 위 삽입: 글자가 이미지와 같이 움직임
    if tpl == "dynamic":
        if vid:
            fc.append(clip(0, W, H) + ("," + drawtext(f"cap{i}.txt", cap, k) if on_image else "") + "[b]")
        else:
            pre = f"{img()}scale={2 * W}:{2 * H}:force_original_aspect_ratio=increase,crop={2 * W}:{2 * H}"
            if on_image:
                pre += "," + drawtext(f"cap{i}.txt", cap, 2 * k)
            fc.append(f"{pre},{zp(f'{W}x{H}')}[b]")
    elif tpl == "black":
        src = clip(0, W, W) if vid else (f"{img()}scale={2 * W}:{2 * W}:force_original_aspect_ratio=increase,"
                                         f"crop={2 * W}:{2 * W},{zp(f'{W}x{W}')}")
        fc.append(f"{src},pad={W}:{H}:0:{round((H - W) / 2.6)}:black[b]")
    elif tpl == "collage":
        g = round(12 * k)
        lines = (f"drawbox=x=0:y=ih/2-{g}:w=iw:h={2 * g}:color=white:t=fill,"
                 f"drawbox=x=iw/2-{g}:y=0:w={2 * g}:h=ih:color=white:t=fill")
        if imgs and any(is_video(pick(j)) for j in range(4)):  # 영상이 섞이면 칸마다 재생
            for j in range(4):
                fc.append((clip(j, W // 2, H // 2) if is_video(pick(j)) else still(j, W // 2, H // 2)) + f"[c{j}]")
            fc.append(f"[c0][c1][c2][c3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0,{lines}[b]")
        else:
            cells = [img(j) for j in range(4)]
            for j, c in enumerate(cells):
                fc.append(f"{c}scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[c{j}]")
            fc.append(f"[c0][c1][c2][c3]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0,{lines},{zp(f'{W}x{H}')}[b]")
    else:  # search
        C, top, bar = round(920 * k), round(470 * k), round(120 * k)
        card = clip(0, C, C) if vid else None
        src = None if vid else img()
        base = f"[{add('-f', 'lavfi', '-i', f'color=c=white:s={W}x{H}:r={fps}:d={vdur}')}:v]"
        kw = plan.get("keyword") or plan.get("title", "")
        bx, by, bw, btn = round(70 * k), round(250 * k), W - round(140 * k), round(160 * k)
        kst = dict(styles["caption"], font="맑은 고딕 Bold", size=50, color="#222222", border_w=0, bg_alpha=0, shadow=False, spacing=0, align="L",
                   x=round((bx + 36 * k) / W * 100, 2), y=round((by + bar / 2 - 30 * k) / H * 100, 2))
        bst = dict(kst, color="#FFFFFF", x=round((bx + bw - btn / 2) / W * 100, 2), align="C")
        write(d / "btn.txt", "검색")
        parts = [f"drawbox=x={bx}:y={by}:w={bw}:h={bar}:color=0x03C75A:t={round(5 * k)}",
                 f"drawbox=x={bx + bw - btn}:y={by}:w={btn}:h={bar}:color=0x03C75A:t=fill", drawtext("btn.txt", bst, k)]
        if i == 0:  # 첫 장면은 검색어를 한 글자씩 입력
            for c in range(1, len(kw) + 1):
                write(d / f"kw{c}.txt", kw[:c])
                end = f"lt(t,{0.3 + c * 0.09:.2f})" if c < len(kw) else "1"
                parts.append(drawtext(f"kw{c}.txt", kst, k, f"gte(t,{0.3 + (c - 1) * 0.09:.2f})*{end}"))
        else:
            write(d / "kw.txt", kw)
            parts.append(drawtext("kw.txt", kst, k))
        fc.append((card or f"{src}scale={2 * C}:{2 * C}:force_original_aspect_ratio=increase,crop={2 * C}:{2 * C},{zp(f'{C}x{C}')}") + "[card]")
        fc.append(f"{base}[card]overlay=x={(W - C) // 2}:y={top}," + ",".join(parts) + "[b]")

    over = []
    if plan.get("brightness"):
        over.append(f"eq=brightness={float(plan['brightness']):.2f}")
    if not on_image:
        over.append(drawtext(f"cap{i}.txt", cap, k))
    if opt["subtitles"]:
        write(d / f"sub{i}.txt", sc["narration"], styles["subtitle"]["spacing"])
        over.append(drawtext(f"sub{i}.txt", styles["subtitle"], k))
    if opt["shop"]:
        write(d / "shop.txt", opt["shop"], styles["shop"]["spacing"])
        over.append(drawtext("shop.txt", styles["shop"], k))
    if opt["ai_mark"]:
        write(d / "ai.txt", "AI 제작")
        over.append(drawtext("ai.txt", dict(SHOP, size=30, color="#FFFFFF", bg_alpha=0.25, y=96.2), k))
    fc.append("[b]" + ",".join(over + ["format=yuv420p"]) + "[v]")

    afmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    fc.append(f"[{add('-i', f'tts{i}.wav')}:a]apad,atrim=0:{dur},{afmt}[t]")
    if opt["sfx"]:
        fc.append(f"[{add('-i', str(ASSETS / 'sfx.wav'))}:a]volume=0.7,{afmt}[s];[t][s]amix=inputs=2:duration=first:normalize=0[a]")
    else:
        fc.append("[t]anull[a]")
    run(["ffmpeg", "-y", *sum(inputs, []), "-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", "-t", f"{vdur}",
         "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", f"scene{i}.mp4"], cwd=d)


def render(proj, ver, plan, opt):
    ensure_assets()
    d = (proj / f"v{ver}").resolve()
    d.mkdir(exist_ok=True)
    write(d / "plan.json", json.dumps(plan, ensure_ascii=False, indent=2))
    write(d / "opts.json", json.dumps(opt, ensure_ascii=False, indent=2))
    imgs = media_files(proj)
    styles, scenes = styles_for(opt), plan["scenes"]
    T = 0 if opt["transition"] == "none" else 0.4
    durs = []
    for i, sc in enumerate(scenes):
        print(f"  장면 {i + 1}/{len(scenes)}: {sc['narration']}", flush=True)
        speech = tts(sc["narration"], d / f"tts{i}.wav", opt["voice"])
        dur = round(max(float(sc["seconds"]) * TEMPO[opt["tempo"]][0], speech + 0.3), 2)
        durs.append(dur)
        render_scene(i, len(scenes), sc, plan, imgs, dur, dur + (T if i < len(scenes) - 1 else 0), d, opt, styles)

    print("  합치는 중 (전환 효과, BGM)", flush=True)
    n, total = len(scenes), round(sum(durs), 2)
    ins = sum((["-i", f"scene{i}.mp4"] for i in range(n)), [])
    fc = []
    if T and n > 1:
        prev, off = "[0:v]", 0.0
        for i in range(1, n):
            off += durs[i - 1]
            tr = TRANSITIONS[(i * 3) % len(TRANSITIONS)] if opt["transition"] == "random" else opt["transition"]
            out = "[vx]" if i == n - 1 else f"[x{i}]"
            fc.append(f"{prev}[{i}:v]xfade=transition={tr}:duration={T}:offset={off:.2f}{out}")
            prev = out
    else:
        fc.append("".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vx]")
    fc.append("".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[ac]")
    bgm = plan.get("bgm") if opt["bgm"] == "auto" else None if opt["bgm"] == "none" else opt["bgm"]
    bgm = bgm if bgm in bgm_list() else (bgm_list() or [None])[0] if opt["bgm"] == "auto" else bgm if bgm in bgm_list() else None
    if bgm:
        ins += ["-stream_loop", "-1", "-i", str(BGM_DIR / bgm)]
        fc.append(f"[{n}:a]volume={float(opt['bgm_volume'])},atrim=0:{total},afade=t=out:st={max(total - 1.2, 0)}:d=1.2,"
                  f"aformat=sample_rates=44100:channel_layouts=stereo[bg];[ac][bg]amix=inputs=2:duration=first:normalize=0[m]")
    else:
        fc.append("[ac]anull[m]")
    fc.append("[m]loudnorm=I=-16:TP=-1.5,aresample=44100[a]")  # 쇼츠 표준 음량
    out = proj / f"{proj.name}_v{ver}.mp4"
    run(["ffmpeg", "-y", *ins, "-filter_complex", ";".join(fc), "-map", "[vx]", "-map", "[a]", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart",
         "-shortest", str(out.resolve())], cwd=d)
    for f in d.glob("scene*.mp4"):
        f.unlink()
    return out


def thumbnail(proj, ver):
    proj = proj.resolve()
    d = proj / f"v{ver}"
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    opt = merge_opts(json.loads((d / "opts.json").read_text(encoding="utf-8")) if (d / "opts.json").exists() else {})
    imgs, sc0 = media_files(proj), plan["scenes"][0]
    st = dict(styles_for(opt)["caption"], y=72)
    write(d / "thumb.txt", plan.get("title") or sc0["caption"].replace("\\n", "\n"), st["spacing"])
    p = imgs[sc0["image"] % len(imgs)] if imgs else None
    src = (["-ss", f"{float(sc0.get('clip_start') or 0) + 0.5}"] if p and is_video(p) else []) + \
        (["-i", str(p)] if p else ["-f", "lavfi", "-i", "color=c=0x333333:s=1000x1000:d=1"])
    out = proj / f"thumb_v{ver}.jpg"
    run(["ffmpeg", "-y", *src, "-vf", "scale=1000:1000:force_original_aspect_ratio=increase,crop=1000:1000,"
         + drawtext("thumb.txt", st, 1000 / 1080), "-frames:v", "1", "-q:v", "2", str(out.resolve())], cwd=d)
    return out


def versions(proj):
    return sorted(int(p.name[1:]) for p in proj.glob("v*") if p.is_dir() and (p / "plan.json").exists())


def load_version(proj, v):
    d = proj / f"v{v}"
    opts = json.loads((d / "opts.json").read_text(encoding="utf-8")) if (d / "opts.json").exists() else {}
    return json.loads((d / "plan.json").read_text(encoding="utf-8")), merge_opts(opts)


# ---------- CLI ----------
def main():
    ap = argparse.ArgumentParser(description="AI 쇼츠 자동 생성")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new")
    n.add_argument("url", nargs="?")
    n.add_argument("--info", help="상품정보 텍스트 파일(내 자료)")
    n.add_argument("--images", help="상품 이미지 폴더")
    n.add_argument("--opts", help="설정 JSON 파일")
    n.add_argument("--shop")
    n.add_argument("--template", choices=TEMPLATES)
    n.add_argument("--seconds", type=int)
    n.add_argument("--out", default=str(HERE / "shorts_out"))
    e = sub.add_parser("edit")
    e.add_argument("project")
    e.add_argument("request")
    e.add_argument("--from", dest="base", type=int)
    r = sub.add_parser("rerender")
    r.add_argument("project")
    r.add_argument("--plan", required=True)
    r.add_argument("--opts")
    s = sub.add_parser("restore")
    s.add_argument("project")
    s.add_argument("version", type=int)
    c = sub.add_parser("caption", help="인스타그램 캡션 작성 (ig-caption)")
    c.add_argument("project")
    c.add_argument("version", type=int, nargs="?")
    t = sub.add_parser("thumb")
    t.add_argument("project")
    t.add_argument("version", type=int, nargs="?")
    a = ap.parse_args()
    load = lambda f: json.loads(Path(f).read_text(encoding="utf-8")) if f else {}

    if a.cmd == "new":
        files = sorted(p for p in Path(a.images).iterdir() if p.suffix.lower() in IMG_EXT | VID_EXT) if a.images else []
        if not (a.url or a.info or files):
            ap.error("URL, --info, 사진/영상 중 하나는 필요합니다")
        opt = merge_opts(load(a.opts), {k: v for k, v in dict(shop=a.shop, template=a.template, seconds=a.seconds).items() if v})
        # Windows 경로 길이 제한(260자) 때문에 폴더명은 짧게: 날짜_상품 일부
        src = a.url.rstrip("/").split("/")[-1] if a.url else Path(a.info).read_text(encoding="utf-8").strip() if a.info else files[0].stem
        src = re.sub(r"^\s*상품명\s*[:：]\s*", "", src)
        proj = Path(a.out) / f"{time.strftime('%m%d_%H%M%S')}_{re.sub(r'\W+', '_', src)[:16].strip('_')}"
        (proj / "img").mkdir(parents=True, exist_ok=True)
        ensure_assets()
        try:
            info, n = scrape(a.url, proj / "img") if a.url else ("", [])
            n = len(n)
            if a.info:
                info += "\n" + Path(a.info).read_text(encoding="utf-8")
            if info.strip():
                write(proj / "info.txt", info.strip())  # 캡션 작성 때 다시 씀
            for p in files:
                shutil.copy(p, proj / "img" / f"{n:02d}{p.suffix.lower()}")
                n += 1
            media = prepare_media(proj)
            vids = sum("영상" in m for m in media)
            print(f"상품 정보 {len(info.strip())}자, 사진 {len(media) - vids}장, 영상 {vids}개 수집. "
                  f"{'GPT' if opt['model'] in GPT_MODELS else 'Claude'}({opt['model']}, {opt['effort']})가 미디어를 보고 기획 중...", flush=True)
            plan = ask_claude(plan_prompt(info, media, opt), opt["model"], opt["effort"], see_dir=proj.resolve() if media else None)
            for h in plan.get("hooks", []):
                print(f"  훅 후보 {'★' if h.get('chosen') else ' '} [{h['formula']}] {h['line']}", flush=True)
        except BaseException:
            shutil.rmtree(proj, ignore_errors=True)  # 수집/기획 실패 시 빈 프로젝트 폴더를 남기지 않음
            raise
        ver = 1
    else:
        proj = Path(a.project)
        vs = versions(proj)
        if a.cmd == "thumb":
            print(f"완료: {thumbnail(proj, a.version or vs[-1])}")
            return
        if a.cmd == "caption":
            print(f"완료: {make_caption(proj, a.version or vs[-1])}")
            return
        if a.cmd == "restore":
            new = vs[-1] + 1
            shutil.copytree(proj / f"v{a.version}", proj / f"v{new}")
            shutil.copy(proj / f"{proj.name}_v{a.version}.mp4", proj / f"{proj.name}_v{new}.mp4")
            print(f"v{a.version} 을 v{new} 로 복원\n완료: {proj / f'{proj.name}_v{new}.mp4'}")
            return
        base = a.base if a.cmd == "edit" and a.base else vs[-1]
        prev, opt = load_version(proj, base)
        if a.cmd == "rerender":
            plan, opt = load(a.plan), merge_opts(opt, load(a.opts))
            print(f"v{base} 설정 기준으로 다시 렌더링 (AI 사용 안 함)", flush=True)
        else:
            print(f"v{base} 기준으로 수정 중: {a.request}", flush=True)
            plan = ask_claude(
                f"아래 쇼츠 장면 JSON 을 요청대로 수정해서 같은 스키마로 돌려줘. 요청과 관계없는 부분은 그대로 둬라.\n"
                f"- 글씨 크기는 장면의 caption_size(현재 기본 {styles_for(opt)['caption']['size']}), 길이는 seconds,\n"
                f"- 배경 밝기는 brightness(-0.3 어둡게 ~ 0.3 밝게), 움직임은 motion({', '.join(MOTIONS)}),\n"
                f"- bgm 은 목록 중에서: {', '.join(bgm_list())}\n요청: {a.request}\n\n{json.dumps(prev, ensure_ascii=False)}",
                opt["model"], opt["effort"])
            plan.setdefault("hooks", prev.get("hooks", []))
        ver = vs[-1] + 1
    out = render(proj, ver, polish(plan), opt)
    print(f"완료: {out}")


if __name__ == "__main__":
    main()
