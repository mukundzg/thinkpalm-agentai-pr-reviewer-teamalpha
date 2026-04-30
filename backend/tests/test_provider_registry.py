from backend.integrations import register_default_providers
from backend.integrations.registry import provider_registry


def test_provider_registry_has_default_providers():
    register_default_providers()
    available = provider_registry.available()
    assert "github" in available["scm"]
    assert "gitlab" in available["scm"]
    assert "bitbucket" in available["scm"]
    assert "jira" in available["tracker"]
    assert "linear" in available["tracker"]
    assert "github_issues" in available["tracker"]
