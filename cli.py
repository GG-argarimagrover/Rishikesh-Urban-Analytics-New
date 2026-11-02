"""Command-line interface:  rishikesh-urban run | serve | sample"""
from __future__ import annotations

import argparse
import sys
from dataclasses import MISSING, fields

from .config import Config


def _add_config_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="YAML/JSON file with settings (CLI flags override it)")
    for f in fields(Config):
        flag = "--" + f.name.replace("_", "-")
        default = f.default if f.default is not MISSING else None
        if f.type in ("bool", bool):
            p.add_argument(flag, action=argparse.BooleanOptionalAction, default=None, help=f"(default: {default})")
        else:
            p.add_argument(flag, default=None, help=f"(default: {default!r})")


def _cfg_from_args(a: argparse.Namespace) -> Config:
    base = Config.from_file(a.config).to_dict() if a.config else Config().to_dict()
    for f in fields(Config):
        v = getattr(a, f.name, None)
        if v is not None:
            base[f.name] = v
    return Config.from_dict(base)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rishikesh-urban", description="Rishikesh Urban Intelligence")
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="run the full analysis and write the dashboard + maps + tables")
    _add_config_args(run)
    run.add_argument("gpkg_pos", nargs="?", help="GeoPackage path (same as --gpkg)")

    srv = sub.add_parser("serve", help="start the web app (upload a GeoPackage in the browser)")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument("--debug", action="store_true")

    smp = sub.add_parser("sample", help="generate the synthetic demo GeoPackage")
    smp.add_argument("--out", default="data/sample/demo_city.gpkg")

    a = ap.parse_args(argv)
    if a.cmd == "run":
        if a.gpkg_pos and not a.gpkg:
            a.gpkg = a.gpkg_pos
        from .pipeline import run_pipeline
        res = run_pipeline(_cfg_from_args(a))
        print("\nOpen:", (res.out_dir / "Rishikesh_Dashboard.html").resolve())
        return 0
    if a.cmd == "serve":
        from .app import create_app
        create_app().run(host=a.host, port=a.port, debug=a.debug)
        return 0
    if a.cmd == "sample":
        from .sample import make_sample
        print("Wrote", make_sample(a.out))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
