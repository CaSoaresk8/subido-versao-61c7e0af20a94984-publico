import asyncio
import json
import os
import uuid

from sqlalchemy import select, update

from app.database import SessionLocal
from app.models import ConexaoCentral, ProjetoVersao, TarefaCentral, VersaoComunidade
from app.servicos.central import codigo, cofre, provedores


def configuracao(projeto):
    dados = json.loads(projeto.configuracao)
    for chave, valor in list(dados.items()):
        if chave.endswith("_key"):
            dados[chave] = cofre.abrir(valor).get_secret_value()
    return dados


def guardar(db, projeto, dados):
    copia = dict(dados)
    for chave, valor in list(copia.items()):
        if chave.endswith("_key"):
            copia[chave] = cofre.cifrar(cofre.Credencial(token=valor))
    projeto.configuracao = json.dumps(copia)
    db.commit()


def conexao(db, autor_id, provedor):
    c = db.scalar(
        select(ConexaoCentral).where(
            ConexaoCentral.autor_id == autor_id, ConexaoCentral.provedor == provedor
        )
    )
    if not c:
        raise ValueError("Conecte sua conta " + provedor + " antes de continuar.")
    return c, cofre.abrir(c.token_cifrado)


def ocupada(db, pid):
    return (
        db.scalar(
            select(TarefaCentral.id).where(
                TarefaCentral.projeto_id == pid,
                TarefaCentral.estado.in_(["pendente", "executando"]),
            )
        )
        is not None
    )


def enfileirar(db, projeto, acao, dados=None):
    if ocupada(db, projeto.id):
        raise ValueError("Este projeto já tem uma tarefa em andamento.")
    t = TarefaCentral(
        id=uuid.uuid4().hex,
        projeto_id=projeto.id,
        autor_id=projeto.autor_id,
        acao=acao,
        dados=json.dumps(dados or {}),
        estado="pendente",
        mensagem="Aguardando execução",
    )
    db.add(t)
    db.commit()
    return t


def processar_um():
    with SessionLocal() as db:
        t = db.scalar(
            select(TarefaCentral)
            .where(TarefaCentral.estado == "pendente")
            .order_by(TarefaCentral.criado_em)
            .limit(1)
        )
        if not t:
            return False
        claim = db.execute(
            update(TarefaCentral)
            .where(TarefaCentral.id == t.id, TarefaCentral.estado == "pendente")
            .values(estado="executando", mensagem="Executando " + t.acao)
        )
        db.commit()
        if claim.rowcount != 1:
            return False
        projeto = db.get(ProjetoVersao, t.projeto_id)
        config = configuracao(projeto)
        dados = json.loads(t.dados)
        try:
            if t.acao == "criar":
                codigo.criar(projeto.id, dados.get("base_projeto"), dados.get("base_sha"))
                config["inicial_sha"] = codigo.git(projeto.id, "rev-parse", "HEAD")
                projeto.estado = "rascunho"
                t.mensagem = "Sua cópia foi criada com histórico próprio."
            elif t.acao == "conferir":
                config["conferido_sha"] = codigo.conferir(projeto.id)
                t.mensagem = "Arquivos e sintaxe conferidos. Abra uma prévia para testar a execução completa."
            elif t.acao in ("sincronizar", "previa", "publicar"):
                revisao = codigo.conferir(projeto.id)
                if t.acao == "publicar" and config.get("previa_sha") != revisao:
                    raise ValueError(
                        "Teste esta revisão na prévia antes de publicar na biblioteca."
                    )
                gh, token_gh = conexao(db, projeto.autor_id, "github")
                config = provedores.sincronizar(projeto.id, token_gh, gh.identidade, config)
                guardar(db, projeto, config)
                if t.acao in ("previa", "publicar"):
                    fly, token_fly = conexao(db, projeto.autor_id, "fly")
                    config = provedores.implantar(
                        projeto.id,
                        token_fly,
                        fly.identidade,
                        config,
                        previa=t.acao == "previa",
                        checkpoint=lambda: guardar(db, projeto, config),
                    )
                    if t.acao == "previa":
                        projeto.estado = "em_teste"
                        t.mensagem = "Prévia isolada publicada e respondendo."
                    else:
                        config = provedores.implantar(
                            projeto.id,
                            token_fly,
                            fly.identidade,
                            config,
                            vitrine=True,
                            checkpoint=lambda: guardar(db, projeto, config),
                        )
                        config = provedores.sincronizar(
                            projeto.id,
                            token_gh,
                            gh.identidade,
                            config,
                            publico=True,
                        )
                        guardar(db, projeto, config)
                        repo = config["github_publico_repo"]
                        provedores.github(token_gh, "PATCH", "/repos/" + repo, {"private": False})
                        tag = "v" + dados["numero"]
                        releases = provedores.github(
                            token_gh, "GET", "/repos/" + repo + "/releases?per_page=100"
                        )
                        if not any(r.get("tag_name") == tag for r in releases):
                            provedores.github(
                                token_gh,
                                "POST",
                                "/repos/" + repo + "/releases",
                                {
                                    "tag_name": tag,
                                    "target_commitish": revisao,
                                    "name": projeto.nome + " " + tag,
                                    "body": dados["novidades"],
                                },
                            )
                        v = (
                            db.get(VersaoComunidade, config.get("biblioteca_id"))
                            if config.get("biblioteca_id")
                            else None
                        )
                        if v is None:
                            v = VersaoComunidade(autor_id=projeto.autor_id, exemplo=False)
                            db.add(v)
                        for chave in (
                            "numero",
                            "resumo",
                            "novidades",
                            "categoria",
                            "autor_publico",
                        ):
                            setattr(v, chave, dados[chave])
                        v.nome = projeto.nome
                        v.repositorio = "https://github.com/" + repo
                        v.demonstracao = config["vitrine_url"]
                        db.flush()
                        config["biblioteca_id"] = v.id
                        config["publicado_sha"] = revisao
                        config["numero"] = dados["numero"]
                        projeto.estado = "publicado"
                        t.mensagem = (
                            "Publicação concluída na hospedagem, no GitHub e na biblioteca."
                        )
                else:
                    t.mensagem = "Código sincronizado com o seu repositório GitHub."
            elif t.acao == "propor":
                gh, token = conexao(db, projeto.autor_id, "github")
                config["proposta_url"] = provedores.propor(
                    projeto.id, token, gh.identidade, config, dados["titulo"], dados["descricao"]
                )
                t.mensagem = "Proposta criada como pull request em rascunho."
            elif t.acao in ("dominio", "verificar_dominio"):
                fly, token = conexao(db, projeto.autor_id, "fly")
                if not config.get("publicacao_app"):
                    raise ValueError("Publique a instalação antes de conectar o domínio.")
                config["dominio"] = dados["host"]
                config["dns"] = provedores.dominio(
                    token, config["publicacao_app"], dados["host"], criar=t.acao == "dominio"
                )
                t.mensagem = "Configuração consultada. Confira os registros DNS e o certificado."
            else:
                raise ValueError("Ação desconhecida")
            t.estado = "concluida"
        except ValueError as erro:
            t.estado = "falhou"
            t.mensagem = str(erro)[:500]
        except Exception:
            t.estado = "falhou"
            t.mensagem = "A tarefa falhou. Confira os recursos já criados e as conexões antes de tentar novamente."
        finally:
            if db.is_active:
                guardar(db, projeto, config)
            else:
                db.rollback()
                t = db.get(TarefaCentral, t.id)
                t.estado = "falhou"
                t.mensagem = "Falha de persistência. Confira os recursos antes de repetir."
            db.commit()
        return True


async def executar_fila():
    if os.environ.get("CENTRAL_ATIVA", "1") != "1":
        return
    with SessionLocal() as db:
        db.execute(
            update(TarefaCentral)
            .where(TarefaCentral.estado == "executando")
            .values(
                estado="interrompida",
                mensagem="O servidor reiniciou. Confira os recursos antes de repetir esta tarefa.",
            )
        )
        db.commit()
    while True:
        await asyncio.to_thread(processar_um)
        await asyncio.sleep(1)
