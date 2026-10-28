"""Conta e participacao: criar um `Usuario`, e por esse usuario dentro de um `Cla`.

Sao duas coisas separadas de proposito, e e a separacao que faz o multi-cla existir: a conta e
global (um email, uma senha, uma pessoa) e a participacao e por cla. Criar conta nao poe ninguem
em cla nenhum, e entrar num cla nao cria conta nova.

Quem junta os dois passos e quem tem a porta na mao, e existem exatamente duas portas: criar um
cla (a conta nasce junto com o cla que ela abriu) e usar um convite (a conta entra no cla que o
token aponta). As duas dizem em qual cla a pessoa vai cair. A terceira porta, o /criar-conta que
punha todo mundo no unico cla que existia, foi fechada: com mais de um cla ela teria que adivinhar
o destino, e adivinhar errado e por alguem dentro do cla de outra gente.
"""

import re

from sqlalchemy.orm import Session

from app.escopo import EscopoCla
from app.models import Cla, Membro, Usuario
from app.repositorios import contas as repo_contas
from app.security import hash_senha
from app.servicos.auditoria import registrar

MINIMO_SENHA = 8
MINIMO_NOME_CLA = 3
# O nome cabe no cabecalho e no seletor de cla. A coluna aceita 120, e deixar passar 120 faria o
# topo da tela quebrar em celular por causa do nome que alguem colou de um documento.
MAXIMO_NOME_CLA = 40


def normalizar_telefone(bruto: str) -> str | None:
    """So os digitos, DDD na frente e sem o 55. None quando o que veio nao e um telefone daqui.

    A pessoa digita "(11) 97601-2274", "11 97601 2274" ou "+55 11 976012274", e as tres sao o mesmo
    numero. Guardar do jeito que cada uma digitou faria o mesmo telefone virar tres strings
    diferentes, e ai comparar dois cadastros deixaria de funcionar sem ninguem ter digitado errado.

    O 55 sai porque ele e constante para todo mundo aqui: guardar o pais em alguns cadastros e nao
    em outros e o mesmo problema da pontuacao, com outro nome. Quem precisa do numero internacional
    (o link do wa.me) poe o 55 na hora de montar.

    O 9 exigido no celular de 11 digitos nao e preciosismo: numero movel no Brasil comeca com 9
    depois do DDD desde 2016, entao um 11 digitos que nao comeca com 9 e um digito a mais em algum
    lugar, e recusar agora e melhor do que descobrir na hora de mandar mensagem.
    """
    digitos = re.sub(r"\D", "", bruto)
    if len(digitos) in (12, 13) and digitos.startswith("55"):
        digitos = digitos[2:]
    if len(digitos) not in (10, 11):
        return None
    # DDD nao comeca com 0 nem com 1: os validos vao de 11 a 99.
    if digitos[0] == "0" or digitos[1] == "0":
        return None
    if len(digitos) == 11 and digitos[2] != "9":
        return None
    return digitos


def validar(db: Session, nome: str, email: str, senha: str, telefone: str) -> str | None:
    """A mensagem do primeiro problema, ou None quando esta tudo certo.

    Devolve texto em vez de levantar erro porque quem chama e um formulario: ele redesenha a
    propria tela com a mensagem e os campos preenchidos, e nao uma pagina de erro.

    Nenhuma mensagem daqui repete o que a pessoa digitou. E de proposito no telefone: mensagem de
    erro e a primeira coisa que vai parar num log ou num print de tela mandado para outra pessoa, e
    dado pessoal nao pode viajar de carona numa reclamacao de formulario.
    """
    if len(nome) < 2:
        return "Coloque seu nome completo."
    if "@" not in email or "." not in email.split("@")[-1]:
        return "Email inválido."
    if len(senha) < MINIMO_SENHA:
        return f"A senha precisa de pelo menos {MINIMO_SENHA} caracteres."
    if normalizar_telefone(telefone) is None:
        return "Telefone inválido. Escreva com DDD, como em (11) 91234-5678."
    if repo_contas.usuario_por_email(db, email):
        return "Já existe uma conta com esse email."
    return None


def criar_usuario(db: Session, nome: str, email: str, senha: str, telefone: str) -> Usuario:
    """A credencial, sem cla nenhum. Nao da commit: quem chamou decide se a operacao inteira vale.

    O email e guardado em minusculas porque e por ele que o login procura, e ninguem digita o
    proprio email do mesmo jeito duas vezes. O telefone entra normalizado pelo mesmo motivo.

    `telefone` e obrigatorio no argumento e pode acabar nulo na coluna: quem chama aqui e sempre uma
    porta nova, onde o campo e exigido, mas a coluna guarda tambem as contas que nasceram antes de
    ele existir. Passar algo que `normalizar_telefone` recusa grava None em vez de gravar sujeira, e
    quem devia ter barrado isso e o `validar` logo acima.
    """
    usuario = Usuario(
        nome=nome.strip(),
        email=email.strip().lower(),
        senha_hash=hash_senha(senha),
        telefone=normalizar_telefone(telefone),
    )
    db.add(usuario)
    db.flush()
    return usuario


def entrar_no_cla(db: Session, usuario: Usuario, cla: Cla) -> Membro:
    """Poe a conta dentro do cla e anota no log do cla.

    Se a conta ja participa, devolve a participacao que existe em vez de tentar criar outra. O
    banco recusaria a segunda pela UNIQUE(cla_id, usuario_id), e um link de convite reaberto por
    quem ja esta dentro nao e erro de ninguem: e so entrar de novo no lugar onde ja esta.
    """
    existente = repo_contas.membro_do_usuario_no_cla(db, usuario.id, cla.id)
    if existente is not None:
        return existente

    membro = Membro(cla_id=cla.id, usuario_id=usuario.id, nome=usuario.nome)
    db.add(membro)
    db.flush()
    # O escopo nasce aqui: o membro acabou de existir, e e ele que diz em qual cla o log entra.
    escopo = EscopoCla(db=db, membro=membro)
    registrar(escopo, "criou", "membro", membro.id, f"Entrou no clã: {cla.nome}")
    # Importado aqui dentro porque a agenda depende de contas indiretamente (membros, escopo), e o
    # import no topo fecharia o ciclo. Quem entra passa a estar nos convites do que vai acontecer.
    from app.servicos.agenda import convidar_quem_entrou

    convidar_quem_entrou(escopo)
    return membro


def validar_nome_de_cla(nome: str) -> str | None:
    limpo = nome.strip()
    if len(limpo) < MINIMO_NOME_CLA:
        return f"O nome do clã precisa de pelo menos {MINIMO_NOME_CLA} caracteres."
    if len(limpo) > MAXIMO_NOME_CLA:
        return f"O nome do clã não pode passar de {MAXIMO_NOME_CLA} caracteres."
    return None


def criar_cla(db: Session, usuario: Usuario, nome: str) -> Membro:
    """Abre um cla novo e poe quem abriu dentro dele. Devolve a participacao, nao o cla.

    Devolve o Membro porque e ele que a sessao guarda e que o escopo exige: quem acabou de criar
    um cla sai daqui ja podendo olhar para dentro dele.

    Nome repetido e aceito de proposito. Dois grupos diferentes podem se chamar a mesma coisa, o
    nome nao e endereco de nada (o escopo vem da sessao, nao da URL) e recusar obrigaria a pessoa a
    inventar um sufixo que ninguem pediu.

    Sobram duas linhas no log do cla novo, e as duas sao verdade: o cla foi criado, e a primeira
    pessoa entrou nele. O historico de quem entrou quando comeca do primeiro membro, sem excecao
    para quem abriu.
    """
    cla = Cla(nome=nome.strip(), criado_por_id=usuario.id)
    db.add(cla)
    db.flush()
    membro = entrar_no_cla(db, usuario, cla)
    registrar(EscopoCla(db=db, membro=membro), "criou", "cla", cla.id, f"Criou o clã {cla.nome}")
    return membro
