"""Acesso ao banco. E o unico lugar do app onde pode existir um select().

Fora daqui, router e servico pedem por nome ("missoes ativas", "colunas do membro") e nao montam
consulta. Isso deixa o custo de cada consulta visivel num lugar so, e e o que faz o filtro por cla
existir num lugar so: toda funcao daqui recebe um EscopoCla e comeca a consulta em `escopo.q()`,
que ja vem com o where(cla_id). Esquecer o filtro numa tela deixou de ser possivel porque nenhuma
tela monta consulta.

Duas regras de revisao:

1. `select(` fora de app/repositorios/ e bug.
2. Funcao aqui que nao recebe escopo e bug, com UMA excecao reunida em contas.py: o que roda antes
   de existir cla ativo (login, escolha do cla, convite). Cada funcao de la diz no docstring qual
   e o isolamento que vale no lugar do cla_id.

E `db.get(Modelo, id)` nao entra aqui: ele devolve linha de qualquer cla. O substituto e
`escopo.obter(Modelo, id)`, que devolve None para id de outro cla.
"""
