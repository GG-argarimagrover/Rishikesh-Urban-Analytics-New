import pytest

from rishikesh_urban.config import Config


def test_defaults_valid_without_gpkg():
    Config().validate()


def test_from_dict_casts_types():
    c = Config.from_dict({"walk_radius-m": "750", "use_osm": "false", "built_min_share": "0.1"} | {"hot_percentile": 80})
    assert c.walk_radius_m == 750 and c.use_osm is False and c.built_min_share == 0.1


def test_unknown_key_rejected():
    with pytest.raises(KeyError):
        Config.from_dict({"nope": 1})


def test_bad_values():
    with pytest.raises(ValueError):
        Config(language="French").validate()
    with pytest.raises(ValueError):
        Config(use_osm=False).validate()          # no gpkg + no OSM = nothing to analyse
    with pytest.raises(FileNotFoundError):
        Config(gpkg="missing.gpkg").validate()


def test_yaml_roundtrip(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("language: English\nwalk_radius_m: 800\nuse_osm: false\n")
    c = Config.from_file(p)
    assert (c.language, c.walk_radius_m, c.use_osm) == ("English", 800, False)
