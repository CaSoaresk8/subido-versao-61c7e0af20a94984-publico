"""A agenda do cla pela API. Mesmas regras de `servicos/agenda.py` que a tela chama.

Conectar a conta Google fica so na tela (`routers/agenda.py`): e um vai-e-volta de navegador
inteiro pelo Google, que nao se faz por fetch. Aqui da para ver qual conta manda os convites e, para
o dono da plataforma, desconectar.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api import saida
from app.api.deps import escopo_api, exige_origem_propria
from app.config import GOOGLE_CONFIGURADO
from app.escopo import EscopoCla
from app.models import Evento
from app.repositorios import eventos as repo_eventos
from app.repositorios import plataforma as repo_plataforma
from app.servicos import agenda as servico_agenda


def _agenda_ligada() -> None:
    from app import config

    if not config.AGENDA_ATIVA:
        raise HTTPException(status_code=404, detail="Não encontrado")


router = APIRouter(tags=["agenda"], dependencies=[Depends(_agenda_ligada)])


class EventoEnviado(BaseModel):
    titulo: str
    inicio: datetime
    tipo: str = "reuniao"
    duracao_min: int = 60
    descricao: str = ""
    local: str = ""
    conduzido_por_id: int | None = None


def evento_ativo(escopo: EscopoCla, evento_id: int) -> Evento:
    evento = repo_eventos.por_id(escopo, evento_id)
    if evento is None or not evento.ativo:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    return evento


def _campos(pedido: EventoEnviado) -> dict:
    return {
        "titulo": pedido.titulo,
        # Mesma limpeza da tela: sem segundos e sem fuso, hora de parede de Brasilia.
        "inicio": servico_agenda.ler_inicio(pedido.inicio.isoformat()),
        "tipo": pedido.tipo,
        "duracao_min": pedido.duracao_min,
        "descricao": pedido.descricao,
        "local": pedido.local,
        "conduzido_por_id": pedido.conduzido_por_id,
    }


@router.get("/agenda")
def listar(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    return {
        "eventos": [saida.evento(e) for e in repo_eventos.ativos(escopo)],
        "google": {
            "configurado": GOOGLE_CONFIGURADO,
            # O email de quem envia so sai para o dono da plataforma, como na tela.
            "conta": saida.integracao_google(
                repo_plataforma.integracao_google(escopo.db),
                com_email=servico_agenda.e_dono_da_plataforma(escopo.membro.usuario),
            ),
        },
    }


@router.post("/agenda", status_code=201, dependencies=[Depends(exige_origem_propria)])
def criar(pedido: EventoEnviado, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    evento = servico_agenda.criar(escopo, **_campos(pedido))
    escopo.db.commit()
    return saida.evento(evento)


@router.get("/agenda/{evento_id}")
def detalhe(evento_id: int, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    evento = evento_ativo(escopo, evento_id)
    return {**saida.evento(evento), "link_google": servico_agenda.link_google_agenda(evento)}


@router.put("/agenda/{evento_id}", dependencies=[Depends(exige_origem_propria)])
def editar(evento_id: int, pedido: EventoEnviado, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    evento = evento_ativo(escopo, evento_id)
    servico_agenda.editar(escopo, evento, **_campos(pedido))
    escopo.db.commit()
    return saida.evento(evento)


@router.delete("/agenda/{evento_id}", dependencies=[Depends(exige_origem_propria)])
def excluir(evento_id: int, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    evento = evento_ativo(escopo, evento_id)
    servico_agenda.excluir(escopo, evento)
    escopo.db.commit()
    return saida.evento(evento)


@router.post("/agenda/{evento_id}/reenviar", dependencies=[Depends(exige_origem_propria)])
def reenviar(evento_id: int, escopo: EscopoCla = Depends(escopo_api)) -> dict:
    evento = evento_ativo(escopo, evento_id)
    servico_agenda.sincronizar(escopo, evento)
    escopo.db.commit()
    return saida.evento(evento)


@router.delete("/agenda-google", dependencies=[Depends(exige_origem_propria)])
def desconectar(escopo: EscopoCla = Depends(escopo_api)) -> dict:
    """So o dono da plataforma. Para os outros a rota nao existe (404), como na tela."""
    if not servico_agenda.e_dono_da_plataforma(escopo.membro.usuario):
        raise HTTPException(status_code=404, detail="Não encontrado")
    servico_agenda.desconectar(escopo.db)
    escopo.db.commit()
    return {"conta": None}
