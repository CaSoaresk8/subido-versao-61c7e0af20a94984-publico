"""Regra do acompanhamento semanal: quem assume a semana, a conversa com cada pessoa e o perfil.

Como pediu o Caio: sem rodizio. Cada semana comeca sem ninguem, e quem clicar em "Eu assumo essa
semana" vira o responsavel de conversar com cada pessoa do cla. O responsavel pode passar a vez
para outra pessoa. Nada aqui da commit.

Quem le o que, num lugar so (`pode_ver_detalhes`):
  - o cla inteiro ve o status de cada um, quem conversou e em que semana;
  - o TEXTO (como esta indo, combinados) e o perfil (metas, dificuldades) so a propria pessoa, o
    responsavel da semana atual e o rastreador. Dificuldade de alguem nao e vitrine do cla.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.escopo import EscopoCla
from app.models import STATUS_DO_DIARIO, DiarioEntrada, Membro, PerfilMembro, ResponsavelSemana
from app.repositorios import diario as repo
from app.servicos.agenda import agora_local
from app.servicos.auditoria import registrar
from app.servicos.erros import ForaDeRegra, NaoEncontrado

MAXIMO_TEXTO = 5000


def semana_atual() -> date:
    """A segunda-feira da semana corrente, no horario de Brasilia."""
    hoje = agora_local().date()
    return hoje - timedelta(days=hoje.weekday())


def fim_da_semana(semana: date) -> date:
    return semana + timedelta(days=6)


def responsavel(escopo: EscopoCla, semana: date | None = None) -> Membro | None:
    registro = repo.responsavel_da_semana(escopo, semana or semana_atual())
    return registro.membro if registro else None


def sou_responsavel(escopo: EscopoCla) -> bool:
    atual = responsavel(escopo)
    return atual is not None and atual.id == escopo.membro_id


def pode_ver_detalhes(escopo: EscopoCla, pessoa_id: int) -> bool:
    return pessoa_id == escopo.membro_id or sou_responsavel(escopo)


def assumir(escopo: EscopoCla) -> ResponsavelSemana:
    """Eu assumo essa semana. Semana que ja tem alguem nao se toma: quem esta passa a vez."""
    semana = semana_atual()
    registro = repo.responsavel_da_semana(escopo, semana)
    if registro is not None:
        if registro.membro_id == escopo.membro_id:
            return registro
        raise ForaDeRegra(
            f"{registro.membro.nome} já assumiu esta semana. Peça para transferir para você."
        )
    registro = ResponsavelSemana(cla_id=escopo.cla_id, semana=semana, membro_id=escopo.membro_id)
    escopo.db.add(registro)
    escopo.db.flush()
    registrar(
        escopo,
        "assumiu",
        "responsavel",
        registro.id,
        f"{escopo.membro.nome} assumiu o acompanhamento da semana de {semana:%d/%m}",
    )
    return registro


def transferir(escopo: EscopoCla, para_membro_id: int) -> ResponsavelSemana:
    """Passa a semana para outra pessoa do cla. So quem esta responsavel passa."""
    registro = repo.responsavel_da_semana(escopo, semana_atual())
    if registro is None or registro.membro_id != escopo.membro_id:
        raise ForaDeRegra("Só quem assumiu a semana pode transferir.")
    destino = escopo.obter(Membro, para_membro_id)
    if destino is None:
        raise ForaDeRegra("Escolha alguém do clã.")
    if destino.id == escopo.membro_id:
        return registro
    registro.membro_id = destino.id
    escopo.db.flush()
    registrar(
        escopo,
        "transferiu",
        "responsavel",
        registro.id,
        f"{escopo.membro.nome} passou o acompanhamento da semana para {destino.nome}",
    )
    return registro


def registrar_conversa(
    escopo: EscopoCla, pessoa: Membro, status: str, como_esta: str = "", combinados: str = ""
) -> DiarioEntrada:
    """A conversa da semana com uma pessoa. So o responsavel registra, e nao sobre si mesmo."""
    if not sou_responsavel(escopo):
        raise ForaDeRegra("Só quem assumiu a semana registra as conversas.")
    if pessoa.id == escopo.membro_id:
        raise ForaDeRegra("A sua conversa da semana é com outra pessoa do clã.")
    if status not in STATUS_DO_DIARIO:
        raise ForaDeRegra("Escolha como a pessoa está.")
    if len(como_esta) > MAXIMO_TEXTO or len(combinados) > MAXIMO_TEXTO:
        raise ForaDeRegra("O texto ficou comprido demais.")
    semana = semana_atual()
    entrada = repo.entradas_da_semana(escopo, semana).get(pessoa.id)
    if entrada is None:
        entrada = DiarioEntrada(
            cla_id=escopo.cla_id, membro_id=pessoa.id, semana=semana, autor_id=escopo.membro_id
        )
        escopo.db.add(entrada)
    entrada.autor_id = escopo.membro_id
    entrada.status = status
    entrada.como_esta = como_esta.strip()
    entrada.combinados = combinados.strip()
    escopo.db.flush()
    registrar(
        escopo,
        "registrou",
        "diario",
        entrada.id,
        f"{escopo.membro.nome} conversou com {pessoa.nome}: {STATUS_DO_DIARIO[status]}",
    )
    return entrada


def salvar_perfil(
    escopo: EscopoCla, pessoa: Membro, sobre: str = "", metas: str = "", dificuldades: str = ""
) -> PerfilMembro:
    """A propria pessoa edita, e o responsavel da semana tambem."""
    if not pode_ver_detalhes(escopo, pessoa.id):
        raise NaoEncontrado("Perfil não encontrado")
    if max(len(sobre), len(metas), len(dificuldades)) > MAXIMO_TEXTO:
        raise ForaDeRegra("O texto ficou comprido demais.")
    registro = repo.perfil(escopo, pessoa.id)
    if registro is None:
        registro = PerfilMembro(cla_id=escopo.cla_id, membro_id=pessoa.id)
        escopo.db.add(registro)
    registro.sobre = sobre.strip()
    registro.metas = metas.strip()
    registro.dificuldades = dificuldades.strip()
    registro.atualizado_por_id = escopo.membro_id
    escopo.db.flush()
    registrar(
        escopo,
        "atualizou",
        "perfil",
        registro.id,
        f"{escopo.membro.nome} atualizou o perfil de {pessoa.nome}",
    )
    return registro


def resumo_da_semana(escopo: EscopoCla) -> dict:
    """O que a tela e o aviso do painel precisam: quem e o responsavel e quantas conversas faltam."""
    from app.repositorios import membros as repo_membros

    semana = semana_atual()
    dono = responsavel(escopo, semana)
    feitas = repo.entradas_da_semana(escopo, semana)
    pessoas = [m for m in repo_membros.todos(escopo) if not dono or m.id != dono.id]
    return {
        "semana": semana,
        "fim": fim_da_semana(semana),
        "responsavel": dono,
        "sou_responsavel": dono is not None and dono.id == escopo.membro_id,
        "feitas": len([p for p in pessoas if p.id in feitas]),
        "total": len(pessoas),
        "entradas": feitas,
    }
