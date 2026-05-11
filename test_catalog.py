from catalog_service import listar_segmentos, listar_subgrupos_receita

print("Segmentos:")
for s in listar_segmentos():
    print(repr(s))

print("\nSubgrupos de receita:")
for s in listar_subgrupos_receita():
    print(repr(s))