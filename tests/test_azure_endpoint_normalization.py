from aifa_pyrit.config import normalize_azure_openai_endpoint


def test_azure_endpoint_normalization_strips_openai_v1_suffix():
    base = "https://css-ai-dev-openai-east.openai.azure.com/openai/v1"
    normalized = normalize_azure_openai_endpoint(base)

    assert normalized == "https://css-ai-dev-openai-east.openai.azure.com"


def test_azure_endpoint_normalization_keeps_base_resource_url():
    base = "https://css-ai-dev-openai-east.openai.azure.com"
    normalized = normalize_azure_openai_endpoint(base)

    assert normalized == "https://css-ai-dev-openai-east.openai.azure.com"
