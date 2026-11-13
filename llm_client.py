"""Configuração centralizada dos provedores de LLM do Faro."""
import os
from functools import lru_cache
import httpx
from dotenv import load_dotenv
from openai import OpenAI, AzureOpenAI

load_dotenv()


def model_name(planner=False):
    provider = os.getenv('LLM_PROVIDER', 'openai').strip().lower()
    if provider == 'azure':
        return (os.getenv('AZURE_OPENAI_PLANNER_DEPLOYMENT') if planner else None) or os.environ['AZURE_OPENAI_DEPLOYMENT']
    if provider == 'openai':
        return (os.getenv('ANALYSIS_PLANNER_MODEL') if planner else None) or os.getenv('OPENAI_MODEL', 'gpt-4.1-mini')
    raise ValueError('LLM_PROVIDER deve ser azure ou openai')


@lru_cache(maxsize=1)
def get_client():
    provider = os.getenv('LLM_PROVIDER', 'openai').strip().lower()
    transport = httpx.Client(trust_env=False, timeout=30.0)
    if provider == 'azure':
        return AzureOpenAI(
            azure_endpoint=os.environ['AZURE_OPENAI_ENDPOINT'],
            api_key=os.environ['AZURE_OPENAI_API_KEY'],
            api_version=os.environ['AZURE_OPENAI_API_VERSION'],
            http_client=transport, timeout=30.0, max_retries=1,
        )
    if provider == 'openai':
        return OpenAI(api_key=os.environ['OPENAI_API_KEY'], http_client=transport,
                      timeout=25.0, max_retries=1)
    transport.close()
    raise ValueError('LLM_PROVIDER deve ser azure ou openai')
