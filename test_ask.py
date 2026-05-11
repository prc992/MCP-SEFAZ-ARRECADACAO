from ask_service import (
    interpretar_pergunta,
    extrair_ultimos_meses,
    extrair_subgrupo,
)

pergunta = "quero ver a arrecadação nos últimos 12 meses para o subgrupo ICMS"

print("Pergunta:", pergunta)
print("months_back:", extrair_ultimos_meses(pergunta))
print("subgrupo:", extrair_subgrupo(pergunta))

spec = interpretar_pergunta(pergunta)

print("\nQuerySpec:")
print(spec.model_dump())