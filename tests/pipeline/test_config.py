import httpx
import pytest

from timeglobe_pipeline import config
from timeglobe_pipeline.http import DisallowedURL, PoliteClient


def test_load_env_reads_values_and_skips_comments_and_blanks(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('# comment\n\nTIMEGLOBE_CONTACT="a@b.test"\nDATABASE_URL=\n')
    monkeypatch.delenv("TIMEGLOBE_CONTACT", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config.load_env(env)
    assert config.os.environ["TIMEGLOBE_CONTACT"] == "a@b.test"
    assert "DATABASE_URL" not in config.os.environ


def test_load_env_does_not_override_existing(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("TIMEGLOBE_CONTACT=file@b.test\n")
    monkeypatch.setenv("TIMEGLOBE_CONTACT", "shell@b.test")
    config.load_env(env)
    assert config.os.environ["TIMEGLOBE_CONTACT"] == "shell@b.test"


def test_load_env_missing_file_is_noop(tmp_path):
    config.load_env(tmp_path / "nope.env")


def test_user_agent_names_project_and_contact(monkeypatch):
    monkeypatch.setenv("TIMEGLOBE_CONTACT", "a@b.test")
    ua = config.user_agent()
    assert ua.startswith("TimeGlobe/") and "time.anzarahmad.me" in ua and "a@b.test" in ua


def test_user_agent_requires_contact(monkeypatch):
    monkeypatch.delenv("TIMEGLOBE_CONTACT", raising=False)
    with pytest.raises(RuntimeError):
        config.user_agent()


def test_only_published_circular_t_is_allowed_under_ftp():
    ftp = [p for p in config.ALLOWED_PREFIXES if "/ftp/" in p]
    assert ftp == ["https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/"]


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/cirt.465", True),
        ("https://webtai.bipm.org/ftp/pub/tai/data/some-lab/clock.dat", False),
        ("https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/../../data/clock.dat", False),
        ("https://webtai.bipm.org/ftp/pub/tai/Circular-T/cirt/%2e%2e/%2e%2e/data/x", False),
        ("https://webtai.bipm.org/ftp/pub/tai/other-products/notes/x.pdf", False),
    ],
)
def test_real_config_url_decisions(url, ok):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"ok"))
    client = PoliteClient(
        "t", config.ALLOWED_PREFIXES, forbidden_prefixes=config.FORBIDDEN_PREFIXES,
        transport=transport,
    )
    if ok:
        assert client.get(url) == b"ok"
    else:
        with pytest.raises(DisallowedURL):
            client.get(url)


def test_env_value_prefers_the_environment_and_reads_a_file_without_loading_the_rest(
    tmp_path, monkeypatch
):
    env = tmp_path / ".env"
    env.write_text("ONLY_THIS=from-file\nOTHER_SECRET=do-not-load\n")
    monkeypatch.delenv("ONLY_THIS", raising=False)
    monkeypatch.delenv("OTHER_SECRET", raising=False)
    assert config.env_value("ONLY_THIS", env) == "from-file"
    assert "OTHER_SECRET" not in config.os.environ and "ONLY_THIS" not in config.os.environ
    monkeypatch.setenv("ONLY_THIS", "from-env")
    assert config.env_value("ONLY_THIS", env) == "from-env"
    assert config.env_value("MISSING", env) == ""
