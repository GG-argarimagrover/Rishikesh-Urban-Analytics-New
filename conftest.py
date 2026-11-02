import pytest

from rishikesh_urban.sample import make_sample


@pytest.fixture(scope="session")
def demo_gpkg(tmp_path_factory):
    return make_sample(str(tmp_path_factory.mktemp("sample") / "demo.gpkg"))
