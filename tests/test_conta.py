"""Regras de cadastro e de entrada.

Nenhum teste aqui pode criar uma conta que sobreviva DENTRO DO CLA DA ANA: ele precisa ficar com
exatamente Ana e Bruno para as contagens do ranking e do grafico baterem. Os casos de recusa
devolvem 400 e nao gravam ninguem.

A validacao de conta e a mesma nas duas portas (criar cla e aceitar convite) porque as duas chamam
`servicos/contas.py:validar`. Os testes abaixo batem em /criar-cla, que e a porta que nao precisa
de token para ser exercitada.
"""

from __future__ import annotations

import re


def test_quem_cria_um_cla_ja_entra_nele(criacao_ana):
    _, resposta = criacao_ana
    assert "Dashboard do clã" in resposta.text


def test_criar_conta_solto_nao_existe_mais(visitante):
    # A porta que punha a pessoa no unico cla que existia foi fechada na fase 3: com mais de um
    # cla ela teria que adivinhar o destino.
    assert visitante.post("/criar-conta", data={"nome": "X"}).status_code == 404


def test_email_duplicado_e_recusado(visitante):
    # Maiuscula nao cria conta nova: o email e comparado em minusculo.
    resposta = visitante.post(
        "/criar-cla",
        data={
            "nome_cla": "Cla Duplicado",
            "nome": "Outra",
            "email": "ANA@cla.com",
            "telefone": "11955550001",
            "senha": "senhaforte1",
        },
    )
    assert resposta.status_code == 400
    assert "Já existe" in resposta.text


def test_senha_curta_e_recusada(visitante):
    resposta = visitante.post(
        "/criar-cla",
        data={
            "nome_cla": "Cla da Senha Curta",
            "nome": "Curta",
            "email": "curta@cla.com",
            "telefone": "11955550002",
            "senha": "1234",
        },
    )
    assert resposta.status_code == 400


def test_nome_de_cla_curto_e_recusado(visitante):
    resposta = visitante.post(
        "/criar-cla",
        data={
            "nome_cla": "ab",
            "nome": "Bre",
            "email": "bre@cla.com",
            "telefone": "11955550003",
            "senha": "senhaforte1",
        },
    )
    assert resposta.status_code == 400


def test_telefone_chega_de_qualquer_jeito_e_e_guardado_de_um_jeito_so():
    """Quatro formas de escrever o mesmo telefone, e o banco tem que guardar uma.

    A pessoa digita como esta acostumada: com parenteses, com traco, com espaco, com o +55 que o
    proprio celular copia junto. Guardado como veio, o mesmo telefone vira quatro registros
    diferentes, e procurar alguem por numero deixa de funcionar sem nunca dar erro.
    """
    from app.servicos.contas import normalizar_telefone

    for escrito in ("(11) 97601-2274", "+55 11 976012274", "11 9760 12274", "11976012274"):
        assert normalizar_telefone(escrito) == "11976012274", f"{escrito!r} virou outra coisa"

    # Fixo de 10 digitos continua valendo: nem todo mundo cadastra celular.
    assert normalizar_telefone("(11) 3255-1000") == "1132551000"


def test_telefone_que_nao_existe_e_recusado():
    """As recusas, que sao o motivo de a normalizacao nao ser so um `re.sub`.

    Tirar a pontuacao de qualquer coisa sempre da certo: "abc" vira "" e "" e um telefone tao bom
    quanto outro para quem so limpa. Cada caso abaixo e um numero que seria aceito por engano e so
    apareceria no dia em que alguem tentasse ligar.
    """
    from app.servicos.contas import normalizar_telefone

    for escrito in (
        "",  # campo em branco que passou pelo required do HTML
        "97601227",  # sem DDD
        "119760122740",  # um digito a mais
        "11876012274",  # celular de 11 digitos que nao comeca com 9 no terceiro
        "01976012274",  # DDD comecando com zero
        "10976012274",  # DDD com zero no segundo digito
        "nao tenho",
    ):
        assert normalizar_telefone(escrito) is None, f"{escrito!r} passou por telefone valido"


def test_conta_guarda_o_telefone_limpo_e_nao_o_que_foi_digitado(ana):  # noqa: ARG001
    """A ponta do fluxo: a Ana se cadastrou com "(11) 98765-0001" e o banco tem so digitos.

    Depende da fixture `ana` porque e ela que passa pela porta de verdade, com pontuacao. Conferir
    a funcao isolada nao prova que a rota chama a funcao.
    """
    from app.database import SessionLocal
    from app.models import Usuario

    db = SessionLocal()
    try:
        guardado = db.query(Usuario).filter(Usuario.email == "ana@cla.com").one().telefone
    finally:
        db.close()
    assert guardado == "11987650001", f"o telefone foi guardado como {guardado!r}"


def test_telefone_invalido_recusa_a_conta_sem_repetir_o_numero(visitante):
    """400, e a mensagem de erro nao pode conter o que foi digitado.

    Telefone e dado pessoal. Mensagem de erro e a primeira coisa que vai parar num log, num print
    de tela mandado por quem esta com problema, ou num relatorio de erro de terceiro. Repetir o
    numero na recusa parece gentileza e e o jeito mais facil de um telefone vazar de um app que
    nunca mostra telefone em lugar nenhum.

    O valor digitado volta para o CAMPO, que e onde ele precisa estar: a pessoa reconhece o que
    escreveu e corrige. Ele volta como foi digitado, e nao normalizado, porque um numero que a
    pessoa nao reconhece e pior do que um campo vazio.
    """
    resposta = visitante.post(
        "/criar-cla",
        data={
            "nome_cla": "Cla do Telefone Torto",
            "nome": "Torto",
            "email": "torto@cla.com",
            "telefone": "9760-1227",
            "senha": "senhaforte1",
        },
    )
    assert resposta.status_code == 400
    assert "Telefone inválido" in resposta.text
    assert 'value="9760-1227"' in resposta.text, (
        "o campo voltou vazio e a pessoa digita tudo de novo"
    )

    erro = re.search(r'<div class="alerta alerta-erro">(.*?)</div>', resposta.text, re.S)
    assert erro is not None, "a tela nao mostrou o erro"
    assert "9760" not in erro.group(1), "a mensagem de recusa repetiu o telefone digitado"


def test_conta_sem_telefone_nao_e_criada(visitante):
    # O `required` do HTML nao vale nada: qualquer POST direto passa por cima dele. A porta que
    # decide e o servidor, e o formulario manda string vazia quando o campo nao veio.
    resposta = visitante.post(
        "/criar-cla",
        data={
            "nome_cla": "Cla Sem Telefone",
            "nome": "Sem Tel",
            "email": "semtel@cla.com",
            "senha": "senhaforte1",
        },
    )
    assert resposta.status_code == 400
    assert "Telefone inválido" in resposta.text


EMAIL_DA_ANTIGA = "velhaguarda@cla.com"
SENHA_DA_ANTIGA = "senhaforte1"
CLA_DA_ANTIGA = "Cla da Velha Guarda"
OUTRO_DA_ANTIGA = "Segundo Cla da Velha Guarda"


def test_conta_anterior_ao_campo_continua_inteira_sem_telefone(
    app_web, carla, cliente_de_api, gerar_convite
):
    """As 17 contas que ja estao em producao nao tem telefone, e nada muda para elas.

    Esta e a assercao que responde por gente de verdade. A coluna nasceu nula porque esses cadastros
    sao anteriores a ela, e o formulario so exige o campo de quem se cadastra daqui em diante. O
    risco nao e o banco: e alguma porta do app tropecar num `None` que nunca existiu enquanto o
    campo era escrito. Entao a conta montada aqui e uma conta antiga de verdade, com `telefone`
    nulo na linha, e ela e levada por todos os caminhos que uma pessoa dessas percorre.

    O que mais importa sao os dois ultimos: entrar num cla novo e abrir um cla novo sao os unicos
    lugares onde alguem ja cadastrado encosta na regra de cadastro. Nos dois o codigo pega a conta
    da sessao e nao passa pelo `validar`, entao o telefone nunca e cobrado de quem ja esta dentro.
    Se um refactor juntar os dois ramos, e aqui que o estrago aparece: a pessoa levaria um
    "Telefone invalido" ao tentar entrar num cla, sem ter digitado nada.

    Tudo que este teste cria e apagado na saida, na ordem das FKs.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import delete, select

    from app.database import SessionLocal
    from app.models import Cla, Convite, Log, Membro, Usuario
    from app.servicos.contas import criar_cla, hash_senha

    db = SessionLocal()
    try:
        # A conta e escrita no banco direto, e nao pela porta do app, porque a porta EXIGE telefone
        # desde ontem. A unica forma de ter uma conta antiga de verdade e fabricar a linha como a
        # migracao a deixou: com a coluna nula. Passar pela porta daria uma conta COM telefone, que
        # e o oposto do que se quer provar.
        antiga = Usuario(
            nome="Velha Guarda",
            email=EMAIL_DA_ANTIGA,
            senha_hash=hash_senha(SENHA_DA_ANTIGA),
            telefone=None,
        )
        db.add(antiga)
        db.flush()
        # O cla dela passa pelo servico de verdade: e so a linha do usuario que precisa ser
        # fabricada, e quanto menos coisa for montada por baixo, menos o teste inventa.
        criar_cla(db, antiga, CLA_DA_ANTIGA)
        db.commit()
        usuario_id = antiga.id
    finally:
        db.close()

    convite_id, token = gerar_convite(carla, dias=7, max_usos="")

    try:
        # 1. Entra. O login nao encosta no telefone, mas e a primeira porta: se ela encostasse,
        #    derrubaria as 17 de uma vez.
        cliente = TestClient(app_web)
        entrada = cliente.post(
            "/login",
            data={"email": EMAIL_DA_ANTIGA, "senha": SENHA_DA_ANTIGA},
            follow_redirects=True,
        )
        assert "Dashboard do clã" in entrada.text, "conta antiga nao consegue mais entrar"

        # 2. As telas que desenham o cabecalho, que e onde o botao novo do WhatsApp mora.
        for endereco in ("/", "/missoes", "/minhas", "/cla"):
            assert cliente.get(endereco).status_code == 200, f"{endereco} quebrou para conta antiga"

        # 3. A API devolve a ausencia como ausencia. String vazia aqui diria que a pessoa informou
        #    um telefone em branco, e "nao informou" e "informou vazio" nao sao a mesma coisa.
        api = cliente_de_api()
        login_api = api.post(
            "/api/v1/sessao", json={"email": EMAIL_DA_ANTIGA, "senha": SENHA_DA_ANTIGA}
        )
        assert login_api.status_code == 200, login_api.text
        assert api.get("/api/v1/sessao").json()["usuario"]["telefone"] is None, (
            "a API inventou um telefone para quem nunca informou um"
        )

        # 4. Entra num cla novo por convite, JA LOGADA. E um dos dois lugares onde alguem que ja
        #    tem conta encosta na regra de cadastro, e o formulario nao vai junto: o POST vai vazio,
        #    como a tela manda quando ja existe sessao.
        aceite = cliente.post(f"/convite/{token}", data={}, follow_redirects=True)
        assert "Telefone inválido" not in aceite.text, (
            "o app cobrou telefone de quem ja tinha conta, so por ela aceitar um convite"
        )
        assert "Dashboard do clã" in aceite.text, "conta antiga nao consegue mais entrar em cla"

        # 5. Abre um segundo cla, JA LOGADA: o outro ramo. Se um refactor juntar os dois caminhos
        #    de `/criar-cla` num so, e aqui que aparece, e a pessoa levaria um "Telefone invalido"
        #    sem ter digitado nada.
        criacao = cliente.post(
            "/criar-cla", data={"nome_cla": OUTRO_DA_ANTIGA}, follow_redirects=True
        )
        assert "Telefone inválido" not in criacao.text, (
            "o app cobrou telefone de quem ja tinha conta, so por ela abrir um cla"
        )
        assert "Dashboard do clã" in criacao.text, "conta antiga nao consegue mais abrir cla"

        db = SessionLocal()
        try:
            # Os tres clas: o dela do comeco, o da Carla pelo convite, e o que ela acabou de abrir.
            # Sem esta contagem os dois passos acima passariam com uma tela bonita e nenhuma
            # participacao criada, que e o jeito silencioso de o convite deixar de funcionar.
            quantos = (
                db.execute(select(Membro).where(Membro.usuario_id == usuario_id)).scalars().all()
            )
            assert len(quantos) == 3, f"a conta antiga ficou em {len(quantos)} clas, e nao em 3"
            # E, depois de tudo, o telefone continua nulo: nenhuma dessas portas inventou um valor
            # para a coluna so porque ela agora e pedida no cadastro.
            assert db.get(Usuario, usuario_id).telefone is None, (
                "alguma porta gravou telefone numa conta que nunca informou um"
            )
        finally:
            db.close()
    finally:
        db = SessionLocal()
        try:
            meus_clas = (
                db.execute(select(Cla.id).where(Cla.nome.in_((CLA_DA_ANTIGA, OUTRO_DA_ANTIGA))))
                .scalars()
                .all()
            )
            meus_membros = (
                db.execute(select(Membro.id).where(Membro.usuario_id == usuario_id)).scalars().all()
            )
            # O log sai primeiro, e pelos ids de MEMBRO e nao so pelos de cla: a entrada no cla da
            # Carla deixou uma linha de log LA, apontando para o membro daqui pela FK composta
            # (cla_id, membro_id). Apagar so por cla deixaria essa linha para tras e o banco
            # recusaria a remocao do membro, com o teste ja verde e a sujeira no lugar.
            db.execute(delete(Log).where(Log.membro_id.in_(meus_membros)))
            db.execute(delete(Log).where(Log.cla_id.in_(meus_clas)))
            db.execute(delete(Convite).where(Convite.id == convite_id))
            db.execute(delete(Membro).where(Membro.usuario_id == usuario_id))
            db.execute(delete(Cla).where(Cla.id.in_(meus_clas)))
            db.execute(delete(Usuario).where(Usuario.id == usuario_id))
            db.commit()
        finally:
            db.close()


def test_senha_errada_e_recusada(ana):
    assert ana.post("/login", data={"email": "ana@cla.com", "senha": "errada"}).status_code == 401


def test_conta_sem_cla_nao_entra(visitante):
    """Senha certa e conta sem participacao nenhuma nao da sessao: nao ha cla para abrir.

    Nao existe no fluxo normal (as duas portas criam a participacao junto com a conta), mas existe
    no banco: basta alguem ser removido do unico cla em que estava. A resposta tem que ser recusa
    com instrucao, e nao dashboard vazio nem erro de servidor.
    """
    from sqlalchemy import delete

    from app.database import SessionLocal
    from app.models import Membro, Usuario
    from app.servicos.contas import criar_usuario

    db = SessionLocal()
    try:
        usuario = criar_usuario(db, "Sem Cla", "semcla@cla.com", "senhaforte1", "11955550004")
        db.commit()
        usuario_id = usuario.id
    finally:
        db.close()

    resposta = visitante.post("/login", data={"email": "semcla@cla.com", "senha": "senhaforte1"})
    assert resposta.status_code == 401
    assert "não está em nenhum clã" in resposta.text

    # Limpa na saida: um usuario sobrando nao muda contagem de cla nenhum, mas o email ficaria
    # ocupado para qualquer teste futuro que usasse o mesmo.
    db = SessionLocal()
    try:
        db.execute(delete(Membro).where(Membro.usuario_id == usuario_id))
        db.execute(delete(Usuario).where(Usuario.id == usuario_id))
        db.commit()
    finally:
        db.close()
