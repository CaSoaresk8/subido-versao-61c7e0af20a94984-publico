"""Regra da tarefa pessoal: a que so o dono ve.

Como em `servicos/missoes.py`, nada aqui da commit: quem chamou decide se a operacao inteira vale.
"""

from __future__ import annotations

from datetime import date

from app.escopo import EscopoCla
from app.models import A_FAZER, TarefaPessoal, agora
from app.repositorios import tarefas as repo_tarefas
from app.servicos.auditoria import registrar
from app.servicos.erros import ForaDeRegra, NaoEncontrado

MAXIMO_TITULO = 200


def data_ou_nada(texto: str | None) -> date | None:
    """O campo chega do navegador, mas um POST na mao manda qualquer coisa: data torta vira sem prazo.

    Engolir a data invalida em vez de recusar e escolha, e ela cabe aqui porque a tarefa e de uma
    pessoa so: no pior caso ela ve o proprio cartao sem prazo e corrige. O vencimento de missao, que
    e do cla inteiro, e tratado ao contrario de proposito em `servicos/missoes.py:data_da_missao`.
    """
    try:
        return date.fromisoformat((texto or "").strip())
    except ValueError:
        return None


def minha_tarefa(escopo: EscopoCla, tarefa_id: int) -> TarefaPessoal:
    """A tarefa do membro logado, ou NaoEncontrado.

    Nao existir, ser de outra pessoa e estar na lixeira dao o MESMO erro. Diferenciar diria a quem
    varre ids quais tarefas os outros tem. Tarefa de outro cla nao chega nem a ser comparada: o
    repositorio ja devolveu None, pelo mesmo motivo e com o mesmo resultado.
    """
    tarefa = repo_tarefas.por_id(escopo, tarefa_id)
    if tarefa is None or tarefa.membro_id != escopo.membro_id or tarefa.excluida_em is not None:
        raise NaoEncontrado("Tarefa não encontrada")
    return tarefa


def criar(
    escopo: EscopoCla,
    titulo: str,
    descricao: str = "",
    prazo: date | None = None,
    coluna_id: int | None = None,
    status: str = A_FAZER,
) -> TarefaPessoal:
    titulo = titulo.strip()[:MAXIMO_TITULO]
    if not titulo:
        raise ForaDeRegra("Escreva um título para a tarefa.")
    tarefa = TarefaPessoal(
        cla_id=escopo.cla_id,
        membro_id=escopo.membro_id,
        titulo=titulo,
        descricao=descricao.strip(),
        prazo=prazo,
        coluna_id=coluna_id,
        status=status,
    )
    escopo.db.add(tarefa)
    escopo.db.flush()
    registrar(escopo, "criou", "tarefa", tarefa.id, titulo)
    return tarefa


def editar(
    escopo: EscopoCla, tarefa: TarefaPessoal, titulo: str, prazo: date | None = None
) -> TarefaPessoal:
    titulo = titulo.strip()[:MAXIMO_TITULO]
    if not titulo:
        raise ForaDeRegra("Escreva um título para a tarefa.")
    tarefa.titulo = titulo
    tarefa.prazo = prazo
    registrar(escopo, "atualizou", "tarefa", tarefa.id, titulo)
    return tarefa


def excluir(escopo: EscopoCla, tarefa: TarefaPessoal) -> None:
    tarefa.excluida_em = agora()
    registrar(escopo, "excluiu", "tarefa", tarefa.id, tarefa.titulo)


def restaurar(escopo: EscopoCla, tarefa_id: int) -> TarefaPessoal:
    """Tira da lixeira. Tarefa de outra pessoa da o mesmo 404 de tarefa que nao existe.

    Nao reaproveita `minha_tarefa` porque a condicao e o inverso da dela: aqui a tarefa TEM que
    estar na lixeira, e la ela tem que estar fora.
    """
    tarefa = repo_tarefas.por_id(escopo, tarefa_id)
    if tarefa is None or tarefa.membro_id != escopo.membro_id or tarefa.excluida_em is None:
        raise NaoEncontrado("Tarefa não encontrada na lixeira")
    tarefa.excluida_em = None
    registrar(escopo, "restaurou", "tarefa", tarefa.id, tarefa.titulo)
    return tarefa
