import types

import pytest

from promptfoo.src import storage as st


class FakeBlob:
    def __init__(self, store, name):
        self.store, self.name = store, name

    def download_blob(self):
        return types.SimpleNamespace(readall=lambda: self.store[self.name])

    def upload_blob(self, data, overwrite=False):
        self.store[self.name] = data.read() if hasattr(data, "read") else data


class FakeContainer:
    def __init__(self, blobs=None):
        self.blobs = dict(blobs or {})

    def list_blobs(self, name_starts_with=""):
        return [types.SimpleNamespace(name=n) for n in list(self.blobs) if n.startswith(name_starts_with)]

    def get_blob_client(self, name):
        return FakeBlob(self.blobs, name)


@pytest.fixture(autouse=True)
def no_azure_env(monkeypatch):
    for var in ("AZURE_STORAGE_CONNECTION_STRING", "AZURE_STORAGE_ACCOUNT_NAME", "AZURE_STORAGE_CONTAINER_NAME",
                "PROMPTFOO_DATA_CONTAINER_NAME", "PROMPTFOO_RESULTS_CONTAINER_NAME"):
        monkeypatch.delenv(var, raising=False)


def test_local_mode_without_env(tmp_path):
    store = st.PromptfooStorage(tmp_path / "data", tmp_path / "results")
    assert not store.enabled
    assert store.describe()["mode"] == "local"
    store.pull_data()
    store.push([tmp_path / "x.json"])  # no-op, no error


def test_promptfoo_uses_its_own_containers(tmp_path, monkeypatch):
    monkeypatch.setenv("AZURE_STORAGE_CONNECTION_STRING", "UseDevelopmentStorage=true")
    monkeypatch.setenv("AZURE_STORAGE_CONTAINER_NAME", "pyrit-results")  # PyRIT's setting must be ignored
    store = st.PromptfooStorage(tmp_path / "data", tmp_path / "results")
    assert store.enabled
    assert store.describe() == {"mode": "azure", "data_container": "promptfoo-data",
                                "results_container": "promptfoo-results"}

    monkeypatch.setenv("PROMPTFOO_DATA_CONTAINER_NAME", "pf-data-dev")
    monkeypatch.setenv("PROMPTFOO_RESULTS_CONTAINER_NAME", "pf-results-dev")
    store = st.PromptfooStorage(tmp_path / "data", tmp_path / "results")
    assert (store.data_container, store.results_container) == ("pf-data-dev", "pf-results-dev")


def test_pull_data_overwrites_local_copy(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "promptfoo_tests_cases.yaml").write_text("local")
    container = FakeContainer({"promptfoo_tests_cases.yaml": b"from-blob",
                               "../evil.yaml": b"x", "nested/file.yaml": b"x"})
    st.PromptfooStorage(data, tmp_path / "results", data_client=container, results_client=FakeContainer()).pull_data()
    assert (data / "promptfoo_tests_cases.yaml").read_text() == "from-blob"
    assert not (tmp_path / "evil.yaml").exists()
    assert not (data / "nested").exists()


def test_push_then_pull_results_round_trip(tmp_path):
    container = FakeContainer()
    results = tmp_path / "results"
    (results / "configs").mkdir(parents=True)
    (results / "eval_a.json").write_text("{}")
    (results / "configs" / "attack_a.yaml").write_text("{}")
    writer = st.PromptfooStorage(tmp_path / "d", results, results_client=container)
    writer.push([results / "eval_a.json", results / "configs" / "attack_a.yaml", tmp_path / "outside.json"])
    assert set(container.blobs) == {"eval_a.json", "configs/attack_a.yaml"}

    fresh = tmp_path / "fresh"
    st.PromptfooStorage(tmp_path / "d", fresh, results_client=container).pull_results(force=True)
    assert (fresh / "eval_a.json").read_text() == "{}"
    assert (fresh / "configs" / "attack_a.yaml").exists()


def test_azure_failure_falls_back_to_local(tmp_path):
    class Broken:
        def list_blobs(self, **_):
            raise RuntimeError("network down")

    data = tmp_path / "data"
    data.mkdir()
    (data / "t.yaml").write_text("local")
    store = st.PromptfooStorage(data, tmp_path / "r", data_client=Broken(), results_client=Broken())
    store.pull_data()
    store.pull_results(force=True)
    assert (data / "t.yaml").read_text() == "local"
