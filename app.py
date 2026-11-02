"""Flask web app: upload a GeoPackage (or use the demo data), run the analysis in the background,
then open the interactive dashboard / maps / downloads.

Run locally :  rishikesh-urban serve
Production  :  gunicorn "rishikesh_urban.app:get_app()" --workers 1 --threads 8 --timeout 120
"""
from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields
from pathlib import Path

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, send_from_directory, url_for

from .config import Config
from .pipeline import run_pipeline

JOB_ID = re.compile(r"^[0-9a-f]{12}$")
_lock = threading.Lock()


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def create_app(data_dir: str | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "webtemplates"))
    app.config["MAX_CONTENT_LENGTH"] = int(os.environ.get("RUI_MAX_UPLOAD_MB", "300")) * 1024 * 1024
    jobs_root = Path(data_dir or os.environ.get("RUI_DATA_DIR", "jobs")).resolve()
    jobs_root.mkdir(parents=True, exist_ok=True)
    ttl = float(os.environ.get("RUI_JOB_TTL_HOURS", "24")) * 3600
    pool = ThreadPoolExecutor(max_workers=int(os.environ.get("RUI_MAX_CONCURRENT_JOBS", "1")))
    user, password = os.environ.get("RUI_USER"), os.environ.get("RUI_PASSWORD")

    # ------------------------------------------------------------ optional HTTP basic auth
    @app.before_request
    def _auth():
        if not (user and password) or request.path == "/healthz":
            return None
        a = request.authorization
        if a and secrets.compare_digest(a.username or "", user) and secrets.compare_digest(a.password or "", password):
            return None
        return Response("Login required", 401, {"WWW-Authenticate": 'Basic realm="Rishikesh Urban Intelligence"'})

    def job_dir(job_id: str) -> Path:
        if not JOB_ID.match(job_id):
            abort(404)
        d = jobs_root / job_id
        if not d.is_dir():
            abort(404)
        return d

    def cleanup() -> None:
        now = time.time()
        for d in jobs_root.iterdir():
            try:
                if d.is_dir() and JOB_ID.match(d.name) and now - d.stat().st_mtime > ttl:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass

    # ------------------------------------------------------------ background job
    def run_job(job_id: str, cfg: Config) -> None:
        d = jobs_root / job_id
        status_path, log_path = d / "status.json", d / "log.txt"
        st = _read_json(status_path) or {}

        def save(**kw):
            st.update(kw)
            _write_json(status_path, st)

        def log(msg: str) -> None:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(str(msg) + "\n")

        save(state="running", pct=1, msg="Starting")
        try:
            res = run_pipeline(cfg, log=log, progress=lambda p, m: save(pct=p, msg=m))
            save(state="done", pct=100, msg="Done", files=res.files, summary=res.summary)
        except Exception as e:  # noqa: BLE001
            log(traceback.format_exc())
            save(state="error", msg=str(e)[:500], error=str(e)[:500])

    # ------------------------------------------------------------ routes
    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True)

    @app.get("/")
    def index():
        return render_template("index.html", defaults=Config().to_dict(), max_mb=app.config["MAX_CONTENT_LENGTH"] // 2**20)

    @app.post("/run")
    def run():
        cleanup()
        job_id = uuid.uuid4().hex[:12]
        d = jobs_root / job_id
        d.mkdir(parents=True)
        form = request.form
        overrides: dict = {}
        for f in fields(Config):
            if f.name in ("gpkg", "out_dir", "utm", "centre_lon", "centre_lat", "fallback_radius_km", "osm_tries"):
                continue                                 # never settable from the browser
            if f.name in form and form[f.name].strip() != "":
                overrides[f.name] = form[f.name].strip()
        for flag in ("use_osm", "use_ndvi"):
            overrides[flag] = flag in form
        use_demo = "use_demo" in form
        up = request.files.get("gpkg")

        try:
            if use_demo:
                from .sample import make_sample
                gpkg = make_sample(str(d / "input.gpkg"))
                overrides.update(heat_column="heat_c", use_osm=False, use_ndvi=False)
            elif up and up.filename:
                if not up.filename.lower().endswith(".gpkg"):
                    raise ValueError("Please upload a .gpkg (GeoPackage) file.")
                gpkg = str(d / "input.gpkg")
                up.save(gpkg)
            else:
                gpkg = ""                                 # OSM-only mode (circle around Rishikesh)
            cfg = Config.from_dict({**overrides, "gpkg": gpkg, "out_dir": str(d / "out")}).validate()
        except Exception as e:  # noqa: BLE001
            shutil.rmtree(d, ignore_errors=True)
            return render_template("index.html", defaults={**Config().to_dict(), **overrides}, error=str(e),
                                   max_mb=app.config["MAX_CONTENT_LENGTH"] // 2**20), 400

        _write_json(d / "status.json", dict(state="queued", pct=0, msg="Queued", created=time.time()))
        pool.submit(run_job, job_id, cfg)
        return redirect(url_for("job", job_id=job_id))

    @app.get("/jobs/<job_id>")
    def job(job_id):
        job_dir(job_id)
        return render_template("job.html", job_id=job_id)

    @app.get("/jobs/<job_id>/status")
    def status(job_id):
        d = job_dir(job_id)
        st = _read_json(d / "status.json") or dict(state="queued", pct=0, msg="Queued")
        try:
            lines = (d / "log.txt").read_text(encoding="utf-8").splitlines()[-40:]
        except OSError:
            lines = []
        out = {k: st.get(k) for k in ("state", "pct", "msg", "error", "files")}
        out["log"] = lines
        return jsonify(out)

    @app.get("/jobs/<job_id>/dashboard")
    def dashboard(job_id):
        d = job_dir(job_id) / "out"
        if not (d / "Rishikesh_Dashboard.html").is_file():
            abort(404)
        return send_from_directory(d, "Rishikesh_Dashboard.html")

    @app.get("/jobs/<job_id>/files/<path:name>")
    def files(job_id, name):
        d = job_dir(job_id) / "out"
        dl = request.args.get("download") == "1"
        return send_from_directory(d, name, as_attachment=dl)

    return app


app = None


def get_app() -> Flask:               # gunicorn "rishikesh_urban.app:get_app()"
    global app
    if app is None:
        app = create_app()
    return app
