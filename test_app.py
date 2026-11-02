import io
import time

import pytest

from rishikesh_urban.app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(str(tmp_path / "jobs"))
    app.config["TESTING"] = True
    return app.test_client()


def wait_done(client, job_id, timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = client.get(f"/jobs/{job_id}/status").get_json()
        if st["state"] in ("done", "error"):
            return st
        time.sleep(0.5)
    raise TimeoutError


def test_pages(client):
    assert client.get("/healthz").get_json() == {"ok": True}
    r = client.get("/")
    assert r.status_code == 200 and b"Run analysis" in r.data


def test_bad_job_ids(client):
    assert client.get("/jobs/../etc").status_code == 404
    assert client.get("/jobs/abcdefabcdef/status").status_code == 404
    assert client.get("/jobs/abcdefabcdef/files/x").status_code == 404


def test_rejects_wrong_extension(client):
    r = client.post("/run", data={"gpkg": (io.BytesIO(b"x"), "evil.exe")}, content_type="multipart/form-data")
    assert r.status_code == 400 and b".gpkg" in r.data


def test_demo_job_end_to_end(client):
    r = client.post("/run", data={"use_demo": "1", "language": "English"}, content_type="multipart/form-data")
    assert r.status_code == 302
    job_id = r.headers["Location"].rsplit("/", 1)[1]
    st = wait_done(client, job_id)
    assert st["state"] == "done", st
    assert "Rishikesh_Dashboard.html" in st["files"]
    d = client.get(f"/jobs/{job_id}/dashboard")
    assert d.status_code == 200 and b"Rishikesh Urban Intelligence Dashboard" in d.data
    assert client.get(f"/jobs/{job_id}/files/rishikesh_results.csv?download=1").status_code == 200
    assert client.get(f"/jobs/{job_id}/files/../status.json").status_code in (400, 404)


def test_upload_job(client, demo_gpkg):
    data = {"gpkg": (open(demo_gpkg, "rb"), "city.gpkg"), "heat_column": "heat_c", "language": "English"}
    # OSM + NDVI boxes left unticked → fully offline
    r = client.post("/run", data=data, content_type="multipart/form-data")
    job_id = r.headers["Location"].rsplit("/", 1)[1]
    assert wait_done(client, job_id)["state"] == "done"


def test_basic_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("RUI_USER", "u")
    monkeypatch.setenv("RUI_PASSWORD", "p")
    c = create_app(str(tmp_path / "j")).test_client()
    assert c.get("/").status_code == 401
    assert c.get("/healthz").status_code == 200
    import base64
    ok = {"Authorization": "Basic " + base64.b64encode(b"u:p").decode()}
    assert c.get("/", headers=ok).status_code == 200
