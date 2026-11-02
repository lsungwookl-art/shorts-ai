"""AI 쇼츠 자동 생성기 브라우저 화면. 실행: python app.py -> http://127.0.0.1:8766
영상 생성/수정은 shorts.py 를 그대로 실행한다."""
import json, os, re, shutil, subprocess, sys, threading, uuid, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

import shorts

HERE = shorts.HERE
OUT = HERE / "shorts_out"
PORT = int(os.environ.get("PORT", 8766))
jobs = {}  # ponytail: 메모리 보관, 서버 재시작 시 진행 로그만 사라짐(영상은 디스크에 남음)
MIME = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
        ".ogg": "audio/ogg", ".img": "image/jpeg", ".webm": "video/webm", ".mov": "video/quicktime"}


def start_job(args):
    jid = uuid.uuid4().hex[:8]
    job = jobs[jid] = {"log": [], "done": False, "ok": False, "project": None, "version": None}

    def work():
        p = subprocess.Popen([sys.executable, "-u", str(HERE / "shorts.py"), *args], cwd=HERE,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env={**os.environ, "PYTHON_COLORS": "0"},
                             text=True, encoding="utf-8", errors="replace")
        for line in p.stdout:
            job["log"].append(line.rstrip())
            if m := re.match(r"완료: (.+)_v(\d+)\.mp4", line.strip()):
                job["project"], job["version"] = Path(m.group(1)).parent.name, int(m.group(2))
        job["ok"] = p.wait() == 0
        job["done"] = True

    threading.Thread(target=work, daemon=True).start()
    return jid


def tmp_json(data):
    p = OUT / "_tmp" / f"{uuid.uuid4().hex[:8]}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def project_dir(name):
    p = (OUT / Path(str(name)).name).resolve()
    return p if p.is_dir() and p.parent == OUT.resolve() and not p.name.startswith("_") else None


def projects():
    res = []
    for d in sorted((d for d in OUT.glob("*") if d.is_dir() and not d.name.startswith("_")) if OUT.exists() else [],
                    key=lambda d: d.stat().st_mtime, reverse=True):
        vs = [v for v in shorts.versions(d) if (d / f"{d.name}_v{v}.mp4").exists()]
        if vs:
            res.append({"name": d.name, "versions": vs,
                        "thumbs": [v for v in vs if (d / f"thumb_v{v}.jpg").exists()]})
    return res


def claude_status():
    exe = shutil.which("claude")
    if not exe:
        return {"installed": False, "loggedIn": False}
    try:
        r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=20)
        return {"installed": True, "loggedIn": bool(json.loads(r.stdout).get("loggedIn"))}
    except Exception:
        return {"installed": True, "loggedIn": False}


def meta():
    shorts.ensure_assets()
    return {"templates": {k: {"label": t[0], "desc": t[1], "styles": t[2]} for k, t in shorts.TEMPLATES.items()},
            "voices": {k: v[0] for k, v in shorts.VOICES.items()}, "fonts": list(shorts.FONTS),
            "bgms": shorts.bgm_list(), "defaults": shorts.DEFAULT_OPTS, "motions": shorts.MOTIONS,
            "transitions": shorts.TRANSITIONS, "downloads": str(Path.home() / "Downloads")}


def safe_name(name, exts):
    name = re.sub(r'[\\/:*?"<>|]+', "_", Path(unquote(name)).name)
    return name if Path(name).suffix.lower() in exts else None


class H(BaseHTTPRequestHandler):
    def send(self, body, ctype="application/json; charset=utf-8", code=200):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def file(self, f, root):
        f = f.resolve()
        if f.is_file() and root.resolve() in f.parents:  # 지정 폴더 밖 파일 차단
            return self.send(f.read_bytes(), MIME.get(f.suffix.lower(), "application/octet-stream"))
        self.send({"error": "not found"}, code=404)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == "/":
            return self.send((HERE / "app.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/meta":
            return self.send(meta())
        if path == "/api/projects":
            return self.send(projects())
        if path == "/api/claude":
            return self.send(claude_status())
        if m := re.fullmatch(r"/api/job/(\w+)", path):
            return self.send(jobs.get(m.group(1)) or {"done": True, "ok": False, "log": ["작업 없음"]})
        if m := re.fullmatch(r"/api/version/([^/]+)/(\d+)", path):
            if p := project_dir(m.group(1)):
                plan, opts = shorts.load_version(p, int(m.group(2)))
                if not (p / "vision").exists():
                    shorts.prepare_media(p)
                return self.send({"plan": plan, "opts": opts, "styles": shorts.styles_for(opts),
                                  "media": [{"video": shorts.is_video(m), "dur": round(shorts.duration(m), 1) if shorts.is_video(m) else 0}
                                            for m in shorts.media_files(p)]})
        if m := re.fullmatch(r"/media/([^/]+)/([^/]+)", path):
            if p := project_dir(m.group(1)):
                return self.file(p / m.group(2), p)
        if m := re.fullmatch(r"/vision/([^/]+)/(\d+)\.jpg", path):
            if p := project_dir(m.group(1)):
                return self.file(p / "vision" / f"{int(m.group(2)):02d}.jpg", p / "vision")
        if m := re.fullmatch(r"/bgm/([^/]+)", path):
            return self.file(shorts.BGM_DIR / m.group(1), shorts.BGM_DIR)
        if m := re.fullmatch(r"/voice/(\w+)", path):
            if m.group(1) in shorts.VOICES:
                f = OUT / "_voices" / f"{m.group(1)}.wav"
                if not f.exists():
                    f.parent.mkdir(parents=True, exist_ok=True)
                    shorts.tts("안녕하세요. 오늘 소개할 상품은 정말 특별해요.", f, m.group(1))
                return self.file(f, OUT)
        self.send({"error": "not found"}, code=404)

    def do_POST(self):
        url = urlparse(self.path)
        size = int(self.headers.get("Content-Length", 0))
        if url.path == "/api/upload":  # 이미지/BGM 업로드 (본문 = 파일 그대로)
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            if size > 500_000_000:
                return self.send({"error": "파일이 너무 큽니다(500MB 초과)"}, code=400)
            if q.get("kind") == "bgm":
                name, root = safe_name(q.get("name", ""), {".mp3", ".wav", ".m4a", ".ogg"}), shorts.BGM_DIR
            else:
                name = safe_name(q.get("name", ""), (shorts.IMG_EXT | shorts.VID_EXT) - {".img"})
                root = OUT / "_uploads" / re.sub(r"\W", "", q.get("batch", "x"))[:16]
            if not name:
                return self.send({"error": "지원하지 않는 파일 형식"}, code=400)
            root.mkdir(parents=True, exist_ok=True)
            with open(root / name, "wb") as f:  # 큰 영상도 메모리에 다 올리지 않고 나눠 저장
                left = size
                while left > 0:
                    chunk = self.rfile.read(min(left, 1 << 20))
                    if not chunk:
                        break
                    f.write(chunk)
                    left -= len(chunk)
            return self.send({"ok": True, "name": name, "bgms": shorts.bgm_list()})

        body = json.loads(self.rfile.read(size) or b"{}")
        proj = project_dir(body.get("project", ""))
        if url.path == "/api/new":
            args = ["new"]
            if body.get("url", "").strip():
                args.append(body["url"].strip())
            if body.get("info", "").strip():
                info = OUT / "_tmp" / f"{uuid.uuid4().hex[:8]}.txt"
                info.parent.mkdir(parents=True, exist_ok=True)
                info.write_text(body["info"], encoding="utf-8")
                args += ["--info", str(info)]
            if body.get("batch"):
                args += ["--images", str(OUT / "_uploads" / re.sub(r"\W", "", body["batch"])[:16])]
            if len(args) == 1:
                return self.send({"error": "상품 URL, 내 자료, 사진/영상 중 하나는 넣어 주세요"}, code=400)
            return self.send({"job": start_job(args + ["--opts", tmp_json(body.get("opts") or {})])})
        if not proj:
            return self.send({"error": "영상을 먼저 선택하세요"}, code=400)
        v = str(int(body.get("v") or shorts.versions(proj)[-1]))
        if url.path == "/api/edit":
            if not body.get("request", "").strip():
                return self.send({"error": "수정 요청을 입력하세요"}, code=400)
            return self.send({"job": start_job(["edit", str(proj), body["request"].strip(), "--from", v])})
        if url.path == "/api/rerender":
            return self.send({"job": start_job(["rerender", str(proj), "--plan", tmp_json(body["plan"]),
                                                "--opts", tmp_json(body.get("opts") or {})])})
        if url.path == "/api/restore":
            return self.send({"job": start_job(["restore", str(proj), v])})
        if url.path == "/api/thumb":
            return self.send({"job": start_job(["thumb", str(proj), v])})
        if url.path == "/api/save":
            dest = Path(body.get("dest") or Path.home() / "Downloads")
            if not dest.is_dir():
                return self.send({"error": f"폴더가 없습니다: {dest}"}, code=400)
            f = shutil.copy(proj / f"{proj.name}_v{v}.mp4", dest)
            return self.send({"saved": str(f)})
        self.send({"error": "not found"}, code=404)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    print(f"AI 쇼츠 생성기: {url}  (종료: Ctrl+C)")
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    ThreadingHTTPServer.allow_reuse_address = False  # Windows 에서 같은 포트에 서버가 겹쳐 뜨는 것 방지
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError:
        sys.exit(f"포트 {PORT} 를 이미 쓰고 있습니다. 이미 켜 둔 생성기 창이 있으면 그 창에서 Ctrl+C 로 끈 뒤 다시 실행하세요.")
    server.serve_forever()
