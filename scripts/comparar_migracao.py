"""Prova que a migracao nao mexeu em nada do que as pessoas fizeram.

Contagem de linha nao basta: uma migracao pode manter 7 entregas e trocar a coluna em que cada
cartao esta, a ordem dentro da coluna, ou o texto de uma resposta. O que as pessoas veem na tela e
exatamente isso, entao o que se compara aqui e VALOR A VALOR, celula por celula, nas colunas que
existiam antes.

As colunas novas (cla_id, usuario_id) nao entram na comparacao porque nao existiam do lado de la.
Tudo o mais tem que bater identico, e a comparacao inclui o campo `ordem` e o `coluna_id`, que sao
justamente a posicao do cartao no quadro.

Uso:
    python scripts/comparar_migracao.py ANTES.db DEPOIS.db
"""

from __future__ import annotations

import sqlite3
import sys

# Por tabela: as colunas que existiam ANTES da migracao e que precisam sair identicas do outro lado.
# `membro` e o caso especial: email e senha_hash sairam para `usuario`, entao a linha dele e
# conferida contra o JOIN das duas tabelas.
IGUAIS = {
    "missao": (
        "id, titulo, descricao, pontos, vencimento, criada_por_id, criada_em, exige_resposta, "
        "rotulo_resposta, excluida_em, excluida_por_id"
    ),
    "entrega": (
        "id, missao_id, membro_id, status, resposta, observacao, concluida_em, atualizada_em, "
        "coluna_id, ordem"
    ),
    "tarefa_pessoal": (
        "id, membro_id, titulo, descricao, status, prazo, criada_em, excluida_em, coluna_id, ordem"
    ),
    "coluna": "id, membro_id, nome, ordem, criada_em",
    "log": "id, membro_id, acao, entidade, entidade_id, detalhe, criado_em",
}

# O que a pessoa usa para entrar, e o nome e a ordem do quadro dela. Do lado novo isso vem de um
# JOIN, porque a credencial mudou de tabela sem mudar de valor.
MEMBRO_ANTES = "SELECT id, nome, LOWER(TRIM(email)), senha_hash, ordem_quadro, criado_em FROM membro ORDER BY id"
MEMBRO_DEPOIS = (
    "SELECT m.id, m.nome, u.email, u.senha_hash, m.ordem_quadro, m.entrou_em "
    "FROM membro m JOIN usuario u ON u.id = m.usuario_id ORDER BY m.id"
)

# O placar, pela mesma regra do app: concluido, fora de coluna privada, de missao fora da lixeira.
PONTOS = """
SELECT m.id, m.nome,
       COALESCE(SUM(CASE WHEN e.status = 'concluido' AND e.coluna_id IS NULL
                          AND ms.excluida_em IS NULL THEN ms.pontos ELSE 0 END), 0)
FROM membro m
LEFT JOIN entrega e ON e.membro_id = m.id
LEFT JOIN missao ms ON ms.id = e.missao_id
GROUP BY m.id, m.nome ORDER BY m.id
"""


def comparar(nome: str, antes: list, depois: list) -> bool:
    if antes == depois:
        print(f"  {nome}: {len(antes)} linhas identicas")
        return True
    print(f"  {nome}: DIFERENTE ({len(antes)} antes, {len(depois)} depois)")
    for a, d in zip(antes, depois):
        if a != d:
            print(f"    antes : {a}")
            print(f"    depois: {d}")
    for sobra in antes[len(depois) :]:
        print(f"    sumiu : {sobra}")
    for sobra in depois[len(antes) :]:
        print(f"    surgiu: {sobra}")
    return False


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("Uso: python scripts/comparar_migracao.py ANTES.db DEPOIS.db")
    antes = sqlite3.connect(sys.argv[1])
    depois = sqlite3.connect(sys.argv[2])

    print(f"antes : {sys.argv[1]}")
    print(f"depois: {sys.argv[2]}")
    tudo_igual = True

    print("quem entra no app (id, nome, email, hash da senha, ordem do quadro, entrada):")
    tudo_igual &= comparar(
        "membro", antes.execute(MEMBRO_ANTES).fetchall(), depois.execute(MEMBRO_DEPOIS).fetchall()
    )

    print("o que as pessoas criaram e onde cada cartao esta:")
    for tabela, colunas in IGUAIS.items():
        consulta = f"SELECT {colunas} FROM {tabela} ORDER BY id"
        tudo_igual &= comparar(
            tabela, antes.execute(consulta).fetchall(), depois.execute(consulta).fetchall()
        )

    print("placar por pessoa:")
    tudo_igual &= comparar(
        "pontos", antes.execute(PONTOS).fetchall(), depois.execute(PONTOS).fetchall()
    )

    if not tudo_igual:
        sys.exit("FALHOU: a migracao mudou alguma coisa. Nao suba isso.")
    print("TUDO IGUAL: a migracao nao mexeu em nada do que ja estava la.")


if __name__ == "__main__":
    main()
