"""O escopo de um cla: a sessao do banco, o membro logado, e o cla em que ele esta agora.

Consulta de tabela com cla_id nasce aqui, nao no repositorio. `escopo.q(Missao)` ja vem com o
where(cla_id) aplicado, e `escopo.obter(Missao, id)` devolve None para id de outro cla em vez da
linha. Nao e preferencia de estilo: e para "esqueci o filtro" nao ser um caminho que existe.

Vale dizer o que isto NAO faz. Nada aqui impede alguem escrever um select() na mao dentro de
repositorios/ e esquecer o cla. Duas coisas cobrem esse buraco: as FKs compostas do banco
(app/models.py), que recusam a linha cruzada mesmo que a consulta a pedisse, e
tests/test_isolamento.py, que roda toda funcao publica de repositorio com dois clas no banco e
falha se uma unica linha do outro cla aparecer, inclusive para funcao que alguem acrescentar
depois sem avisar ninguem.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models import Cla, Membro

T = TypeVar("T")


@dataclass(frozen=True)
class EscopoCla:
    db: Session
    membro: Membro

    @property
    def cla(self) -> Cla:
        """O cla ativo. Carregado junto com o membro em deps.py, entao ler aqui nao vai ao banco."""
        return self.membro.cla

    @property
    def cla_id(self) -> int:
        return self.membro.cla_id

    @property
    def membro_id(self) -> int:
        return self.membro.id

    def q(self, modelo: type[T]) -> Select[tuple[T]]:
        """select(modelo) com o cla ja amarrado. O ponto de partida de toda consulta escopada."""
        return select(modelo).where(self._do_cla(modelo))

    def obter(self, modelo: type[T], ident: Any) -> T | None:
        """Uma linha por id, DENTRO do cla.

        Existe porque `db.get(Missao, id)` devolve a linha de qualquer cla, e devolver a linha e o
        comeco do vazamento: o router acha que achou, renderiza, e o cla ve dado alheio. Aqui id de
        outro cla e id que nao existe dao o mesmo resultado, None, e o router transforma os dois no
        mesmo 404. Um 403 diria "existe, mas nao e seu", que e justamente o que nao se quer contar.
        """
        if not ident:
            return None
        return self.db.scalar(self.q(modelo).where(modelo.id == ident))

    def contar(self, modelo: type[T]) -> int:
        return (
            self.db.scalar(select(func.count()).select_from(modelo).where(self._do_cla(modelo)))
            or 0
        )

    def _do_cla(self, modelo: type[T]):
        return modelo.cla_id == self.cla_id  # type: ignore[attr-defined]
