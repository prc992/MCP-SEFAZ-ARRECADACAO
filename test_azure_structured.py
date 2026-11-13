"""Teste independente de Responses API + Pydantic, sem Redshift."""
from dotenv import load_dotenv
load_dotenv('.env', override=True)
from pydantic import BaseModel, ConfigDict
from llm_client import get_client, model_name

class TestResult(BaseModel):
    model_config = ConfigDict(extra='forbid')
    status: str
    number: int

try:
    response = get_client().responses.parse(
        model=model_name(),
        input=[{'role': 'system', 'content': 'Responda usando apenas o esquema fornecido.'},
               {'role': 'user', 'content': 'Informe status OK e number 42.'}],
        text_format=TestResult,
        store=False,
    )
    print('RESULTADO:', response.output_parsed)
    if response.output_parsed is None or response.output_parsed.status != 'OK' or response.output_parsed.number != 42:
        raise RuntimeError('Resposta estruturada inesperada')
    print('TESTE ESTRUTURADO APROVADO')
except Exception as exc:
    print('FALHA:', type(exc).__name__, str(exc))
    raise
