"""As tabelas. Tudo que pertence a um cla carrega cla_id, e a FK garante que ele nao mente.

Duas ideias moram aqui e vale dizer por que:

1. `Usuario` e a credencial, `Membro` e a participacao num cla. Eram a mesma tabela, e por isso
   `email` era unico no banco inteiro: a mesma pessoa nao conseguia entrar num segundo cla sem
   inventar outro email. A senha passou a viver numa linha so, entao trocar a senha vale em todos
   os clas da pessoa.

2. As FKs para `membro`, `missao` e `coluna` sao COMPOSTAS: levam `cla_id` junto. Uma entrega do
   cla A apontando para um membro do cla B nao e recusada pela aplicacao, e recusada pelo banco,
   que nao acha o par (cla_id, id) no alvo. O filtro por cla na aplicacao (app/escopo.py) e a
   primeira camada; esta e a segunda, e ela continua valendo no dia em que alguem escrever uma
   consulta e esquecer o where.
"""

from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

A_FAZER = "a_fazer"
FAZENDO = "fazendo"
CONCLUIDO = "concluido"

STATUS_LABEL = {A_FAZER: "A fazer", FAZENDO: "Fazendo", CONCLUIDO: "Concluído"}
STATUS_VALIDOS = tuple(STATUS_LABEL)


def agora() -> datetime:
    """UTC, sem tzinfo. O "sem tzinfo" e a parte que importa, e nao e descuido.

    Todas as colunas de data aqui sao `DateTime` sem timezone, entao o que o banco guarda e hora de
    parede em UTC e o que ele devolve na leitura e datetime ingenuo. Enquanto `agora()` devolvia um
    datetime com timezone, a diferenca era invisivel: na ESCRITA o driver do SQLite descarta o
    tzinfo em silencio, e todo uso no app era escrita.

    A primeira leitura comparada com agora() (a validade do convite) estourou com "can't compare
    offset-naive and offset-aware datetimes". Podar o tzinfo so naquela comparacao esconderia o
    problema e deixaria a proxima leitura cair no mesmo buraco, entao o corte e aqui: uma unica
    nocao de "agora" no app, do mesmo tipo que sai do banco.

    Guardar UTC e escolha deliberada: o app mostra data em horario de Brasilia, mas o que fica
    gravado nao muda de significado quando o fuso do servidor mudar.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _alvo_membro(nome: str, coluna: str) -> ForeignKeyConstraint:
    """FK composta para membro: o par (cla_id, membro_id) tem que existir no mesmo cla.

    Quando `coluna` e anulavel (quem excluiu, quem agiu no log), o SQLite nao cobra a FK com NULL
    dentro, que e o comportamento desejado: 'ninguem' e uma resposta valida ali.
    """
    return ForeignKeyConstraint(
        ["cla_id", coluna], ["membro.cla_id", "membro.id"], name=nome, ondelete="RESTRICT"
    )


class Usuario(Base):
    """A credencial, uma por pessoa, valida em qualquer cla.

    O email e unico aqui, e so aqui. Em `membro` ele nao podia ser unico sem impedir a pessoa de
    participar de um segundo cla, que e exatamente o que se quer permitir.
    """

    __tablename__ = "usuario"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    senha_hash: Mapped[str] = mapped_column(String(255))
    # Guardado so com os digitos, DDD na frente e sem o 55 do pais: "11976012274". A pessoa digita
    # do jeito que quiser (com parenteses, tracos, espacos) e quem normaliza e o
    # `servicos/contas.py`. Formato unico e o que permite comparar e montar link depois; se cada
    # conta guardasse o telefone com a pontuacao que a pessoa usou, dois cadastros do mesmo numero
    # seriam duas strings diferentes.
    #
    # Anulavel no banco e obrigatorio no formulario, e os dois ao mesmo tempo de proposito: as contas
    # que ja existem nasceram antes deste campo e nao tem como preenche-lo retroativamente. NOT NULL
    # com default "" faria "nao informou" e "informou vazio" virarem a mesma coisa, e so um dos dois
    # e verdade sobre as 17 pessoas que ja estao dentro.
    #
    # E dado pessoal: nao entra em log, nem em mensagem de erro, nem na lista de membros do cla. Quem
    # ve o telefone de alguem e o dono do numero e mais ninguem (ver `api/saida.py`).
    telefone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Cla(Base):
    """O cla. Era a variavel de ambiente CLA_NOME; virou linha de tabela.

    Nao tem campo de papel nem de dono com poder: o app foi pedido sem lider, com o poder dividido
    em todo mundo. `criado_por_id` serve para saber quem abriu, nao para dar permissao a mais.
    """

    __tablename__ = "cla"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    # Nome do arquivo dentro de DATA_DIR/logos, nunca o caminho e nunca a URL: o endereco publico e
    # decisao de rota (app/main.py monta /logos) e mudaria junto com ela. None e "usa o icone do
    # app", que e o estado de todo cla que nao mandou logo, inclusive o que ja esta em producao.
    logo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    criado_por_id: Mapped[int | None] = mapped_column(ForeignKey("usuario.id"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Membro(Base):
    """A participacao de um usuario num cla: e a pessoa vista de dentro do cla.

    `nome` fica aqui e nao so em usuario porque e o nome que aparece no ranking daquele cla.

    Os dois UNIQUE fazem trabalhos diferentes: (cla_id, usuario_id) impede a mesma pessoa entrar
    duas vezes no mesmo cla, e (cla_id, id) e o alvo das FKs compostas das outras tabelas. O
    segundo parece redundante porque id ja e unico sozinho, mas sem ele o SQLite recusa declarar
    FK composta apontando para ca.
    """

    __tablename__ = "membro"
    __table_args__ = (
        UniqueConstraint("cla_id", "usuario_id", name="uq_membro_cla_usuario"),
        UniqueConstraint("cla_id", "id", name="uq_membro_cla_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), index=True)
    nome: Mapped[str] = mapped_column(String(120))
    entrou_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    # Ordem das colunas do quadro, separada por virgula. Ex: "a_fazer,c3,fazendo,concluido".
    ordem_quadro: Mapped[str] = mapped_column(Text, default="")

    usuario: Mapped[Usuario] = relationship()
    cla: Mapped[Cla] = relationship()


class Convite(Base):
    """O unico jeito de entrar num cla: link gerado por quem ja esta dentro.

    Qualquer membro gera, porque o cla nao tem hierarquia. O token e aleatorio de 32 bytes, tem
    validade, limite de usos e revogacao, e quem gerou e quem usou fica no log.
    """

    __tablename__ = "convite"
    __table_args__ = (_alvo_membro("fk_convite_criado_por", "criado_por_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    criado_por_id: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    expira_em: Mapped[datetime] = mapped_column(DateTime)
    # None e "sem limite de usos". Zero seria ambiguo com "esgotado".
    max_usos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usos: Mapped[int] = mapped_column(Integer, default=0)
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    criado_por: Mapped[Membro] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(
            Convite.cla_id == Membro.cla_id, Convite.criado_por_id == Membro.id
        ),
    )


class Coluna(Base):
    """Coluna extra que o membro cria no proprio quadro. Nao e vista por mais ninguem."""

    __tablename__ = "coluna"
    __table_args__ = (
        UniqueConstraint("cla_id", "id", name="uq_coluna_cla_id"),
        _alvo_membro("fk_coluna_membro", "membro_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    membro_id: Mapped[int] = mapped_column(Integer, index=True)
    nome: Mapped[str] = mapped_column(String(60))
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class Missao(Base):
    __tablename__ = "missao"
    __table_args__ = (
        UniqueConstraint("cla_id", "id", name="uq_missao_cla_id"),
        _alvo_membro("fk_missao_criada_por", "criada_por_id"),
        _alvo_membro("fk_missao_excluida_por", "excluida_por_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    descricao: Mapped[str] = mapped_column(Text, default="")
    pontos: Mapped[int] = mapped_column(Integer, default=0)
    vencimento: Mapped[date | None] = mapped_column(Date, nullable=True)
    criada_por_id: Mapped[int] = mapped_column(Integer)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    exige_resposta: Mapped[bool] = mapped_column(Boolean, default=False)
    rotulo_resposta: Mapped[str] = mapped_column(String(200), default="")
    excluida_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    excluida_por_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Todas viewonly, e as tres com primaryjoin escrito na mao: cla_id participa de mais de uma FK
    # composta, entao o SQLAlchemy nao tem como adivinhar qual delas cada relacionamento usa. Nada
    # no app escreve por relacionamento (sempre por id), entao so leitura nao perde nada.
    criada_por: Mapped[Membro] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(Missao.cla_id == Membro.cla_id, Missao.criada_por_id == Membro.id),
    )
    excluida_por: Mapped[Membro | None] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(
            Missao.cla_id == Membro.cla_id, Missao.excluida_por_id == Membro.id
        ),
    )
    entregas: Mapped[list["Entrega"]] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(Missao.cla_id == Entrega.cla_id, Missao.id == Entrega.missao_id),
    )

    @property
    def ativa(self) -> bool:
        return self.excluida_em is None


class Entrega(Base):
    __tablename__ = "entrega"
    __table_args__ = (
        UniqueConstraint("cla_id", "missao_id", "membro_id", name="uq_entrega_cla_missao_membro"),
        ForeignKeyConstraint(
            ["cla_id", "missao_id"], ["missao.cla_id", "missao.id"], name="fk_entrega_missao"
        ),
        ForeignKeyConstraint(
            ["cla_id", "coluna_id"], ["coluna.cla_id", "coluna.id"], name="fk_entrega_coluna"
        ),
        _alvo_membro("fk_entrega_membro", "membro_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    missao_id: Mapped[int] = mapped_column(Integer)
    membro_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=A_FAZER)
    resposta: Mapped[str] = mapped_column(Text, default="")
    observacao: Mapped[str] = mapped_column(Text, default="")
    concluida_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    atualizada_em: Mapped[datetime] = mapped_column(DateTime, default=agora, onupdate=agora)
    coluna_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0)

    missao: Mapped[Missao] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(Entrega.cla_id == Missao.cla_id, Entrega.missao_id == Missao.id),
    )
    membro: Mapped[Membro] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(Entrega.cla_id == Membro.cla_id, Entrega.membro_id == Membro.id),
    )


class TarefaPessoal(Base):
    __tablename__ = "tarefa_pessoal"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cla_id", "coluna_id"], ["coluna.cla_id", "coluna.id"], name="fk_tarefa_coluna"
        ),
        _alvo_membro("fk_tarefa_membro", "membro_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    membro_id: Mapped[int] = mapped_column(Integer)
    titulo: Mapped[str] = mapped_column(String(200))
    descricao: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=A_FAZER)
    prazo: Mapped[date | None] = mapped_column(Date, nullable=True)
    criada_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    excluida_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    coluna_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ordem: Mapped[int] = mapped_column(Integer, default=0)
    # Quem da mentoria criou esta tarefa, quando nao foi a propria pessoa. E o que separa as duas
    # coisas: tarefa pessoal e privada e ninguem mais ve; tarefa da mentoria e combinada com o
    # rastreador, e ele ve. Sem esta coluna, dar tarefa para alguem obrigaria o rastreador a ver
    # tambem o que a pessoa anota so para ela.
    # Integer puro, sem ForeignKey, e a escolha e sobre a MIGRACAO: no SQLite, acrescentar uma FK
    # obriga a recriar a tabela inteira (batch_alter_table), copiando linha por linha. Esta tabela
    # tem dado de gente usando o app agora; um ADD COLUMN simples nao encosta em nenhuma linha.
    # A integridade fica na aplicacao, que so escreve aqui o id de um rastreador que ela acabou de
    # carregar.
    criada_por_rastreador_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    membro: Mapped[Membro] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(
            TarefaPessoal.cla_id == Membro.cla_id, TarefaPessoal.membro_id == Membro.id
        ),
    )


class Log(Base):
    __tablename__ = "log"
    __table_args__ = (_alvo_membro("fk_log_membro", "membro_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    membro_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acao: Mapped[str] = mapped_column(String(40))
    entidade: Mapped[str] = mapped_column(String(40))
    entidade_id: Mapped[int] = mapped_column(Integer)
    detalhe: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    # Quem agiu, quando quem agiu foi a mentoria e nao um membro. O Caio pediu transparencia com
    # NOME: a pessoa precisa saber que foi o rastreador Fulano que concluiu a entrega dela, senao
    # ela ve um ponto que nao lancou e acha que o app errou.
    # Integer puro pelo mesmo motivo da coluna em `tarefa_pessoal`: o log e a tabela com mais
    # linhas do app, e recria-la para ganhar uma FK seria o passo mais arriscado da migracao.
    rastreador_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    membro: Mapped[Membro | None] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(Log.cla_id == Membro.cla_id, Log.membro_id == Membro.id),
    )


TIPOS_DE_EVENTO = {"reuniao": "Reunião", "workshop": "Workshop", "outro": "Outro"}

# Situacao do convite no Google Agenda. Vazio e "nunca tentou" (o cla nao conectou conta nenhuma).
CONVITE_ENVIADO = "enviado"
CONVITE_ERRO = "erro"


class Evento(Base):
    """Reuniao, workshop ou qualquer encontro do cla, com convite pelo Google Agenda.

    `inicio` e hora de PAREDE em Brasilia (`config.FUSO`), sem tzinfo, e nao UTC como os carimbos
    `*_em` do resto do banco. A diferenca e de natureza: `criado_em` e um instante que o app
    registrou; `inicio` e o que a pessoa digitou no formulario ("quinta, 20h"), e e esse texto que
    tem que voltar para a tela e ir para o Google junto com o nome do fuso. Converter para UTC na
    ida e de volta na vinda seria trocar uma informacao exata por duas contas.
    """

    __tablename__ = "evento"
    __table_args__ = (
        _alvo_membro("fk_evento_criado_por", "criado_por_id"),
        _alvo_membro("fk_evento_conduzido_por", "conduzido_por_id"),
        _alvo_membro("fk_evento_excluido_por", "excluido_por_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    tipo: Mapped[str] = mapped_column(String(20), default="reuniao")
    descricao: Mapped[str] = mapped_column(Text, default="")
    inicio: Mapped[datetime] = mapped_column(DateTime, index=True)
    duracao_min: Mapped[int] = mapped_column(Integer, default=60)
    # Link da chamada (Meet, Zoom) ou endereco. Texto livre: o cla usa mais de uma ferramenta.
    local: Mapped[str] = mapped_column(String(500), default="")
    # Quem vai dar o workshop, ou conduzir a reuniao. Anulavel: nem todo encontro tem um.
    conduzido_por_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criado_por_id: Mapped[int] = mapped_column(Integer)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    excluido_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    excluido_por_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # O espelho no Google. O id e o que permite editar e cancelar o MESMO convite em vez de mandar
    # outro; o status e o erro sao o que a tela mostra quando o envio falhou, para ninguem achar que
    # o cla foi convidado sem ter sido.
    google_evento_id: Mapped[str] = mapped_column(String(200), default="")
    google_status: Mapped[str] = mapped_column(String(20), default="")
    google_erro: Mapped[str] = mapped_column(Text, default="")

    criado_por: Mapped[Membro] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(Evento.cla_id == Membro.cla_id, Evento.criado_por_id == Membro.id),
    )
    conduzido_por: Mapped[Membro | None] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(
            Evento.cla_id == Membro.cla_id, Evento.conduzido_por_id == Membro.id
        ),
    )
    excluido_por: Mapped[Membro | None] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(
            Evento.cla_id == Membro.cla_id, Evento.excluido_por_id == Membro.id
        ),
    )

    @property
    def ativo(self) -> bool:
        return self.excluido_em is None


class IntegracaoGoogle(Base):
    """A conta Google que manda os convites de TODOS os clas. Uma linha so na plataforma.

    Nao tem cla_id de proposito: a conta e da plataforma, e nao de um cla. O que separa os clas e
    a lista de convidados, montada a partir dos membros do cla dono do evento
    (`repositorios/eventos.py:emails_dos_membros`), e a agenda do app, que continua escopada. A
    unica coisa compartilhada e a agenda do Google desta conta, que so quem tem a senha dela ve.

    Quem conecta e troca e o dono da plataforma (`config.DONOS_DA_PLATAFORMA`), e nao um membro de
    cla: a conta serve a todos, entao nenhum cla pode troca-la pelos outros. Por isso a FK aponta
    para `usuario`, a credencial, e nao para `membro`.

    O refresh token fica cifrado com uma chave derivada da SECRET_KEY (ver
    `servicos/google_agenda.py`): o banco sozinho, copiado num backup, nao abre a agenda de ninguem.
    """

    __tablename__ = "integracao_google"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255))
    token_cifrado: Mapped[str] = mapped_column(Text)
    conectado_por_usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    conectado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    conectado_por: Mapped[Usuario] = relationship()


class Rastreador(Base):
    """Quem acompanha as pessoas pela mentoria, atravessando o isolamento entre clas.

    E o primeiro papel do app que ve alem do proprio cla, e por isso ele nao mora em `membro`: um
    rastreador pode nao participar de cla nenhum. Ele e uma CONTA com um papel de plataforma, igual
    ao dono da plataforma, e nao um membro com botoes a mais.

    Quais clas ele acompanha fica em `rastreador_cla`, escolhido por ele mesmo. Nada disso e
    silencioso: entrar num cla vira linha no log daquele cla, com o nome dele.
    """

    __tablename__ = "rastreador"

    id: Mapped[int] = mapped_column(primary_key=True)
    usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), unique=True, index=True)
    criado_por_usuario_id: Mapped[int | None] = mapped_column(
        ForeignKey("usuario.id"), nullable=True
    )
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    # Desligar sem apagar: o historico das acoes dele continua fazendo sentido depois que ele sai.
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)

    usuario: Mapped[Usuario] = relationship(foreign_keys=[usuario_id])


class RastreadorCla(Base):
    """Um cla que um rastreador acompanha. Ele mesmo escolhe, e o cla fica sabendo."""

    __tablename__ = "rastreador_cla"
    __table_args__ = (UniqueConstraint("rastreador_id", "cla_id", name="uq_rastreador_cla"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    rastreador_id: Mapped[int] = mapped_column(ForeignKey("rastreador.id"), index=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    desde: Mapped[datetime] = mapped_column(DateTime, default=agora)

    rastreador: Mapped[Rastreador] = relationship()
    cla: Mapped[Cla] = relationship()


class ConviteRastreador(Base):
    """O link que transforma uma conta em rastreador. So o dono da plataforma gera.

    Tabela propria, e nao um campo em `convite`: aquele leva para DENTRO de um cla e qualquer
    membro gera; este da um papel que atravessa clas e so o dono cria. Misturar os dois faria a
    tela de convites de qualquer cla ter, por descuido, o poder de fabricar rastreador.
    """

    __tablename__ = "convite_rastreador"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    criado_por_usuario_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"))
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    expira_em: Mapped[datetime] = mapped_column(DateTime)
    max_usos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usos: Mapped[int] = mapped_column(Integer, default=0)
    revogado_em: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    criado_por: Mapped[Usuario] = relationship()


# Mentoria: os dois tipos que o Caio definiu. Cada pessoa tem 12 mensais (uma por mes de consultoria)
# e 6 livres (sobre o tema que ela escolher). Os dois acumulam, mas cada um no proprio contador.
TIPOS_DE_MENTORIA = {"mensal": "Consultoria mensal", "livre": "Consultoria livre"}
SALDO_INICIAL = {"mensal": 12, "livre": 6}

MARCADA = "marcada"
REALIZADA = "realizada"
FALTOU = "faltou"
CANCELADA = "cancelada"
SITUACOES_DE_MENTORIA = {
    MARCADA: "Marcada",
    REALIZADA: "Realizada",
    FALTOU: "Faltou",
    CANCELADA: "Cancelada",
}
# O que gasta saldo. Falta gasta: o horario foi reservado e a pessoa nao veio. Cancelamento nao:
# foi desmarcado antes. Excecao a qualquer das duas regras e ajuste manual do saldo, que fica no log.
CONSOME_SALDO = (MARCADA, REALIZADA, FALTOU)


class Acompanhamento(Base):
    """O que a mentoria guarda sobre UMA pessoa: o saldo de consultorias e a anotacao do rastreador.

    Nasce quando o rastreador abre a ficha da pessoa pela primeira vez, com 12 mensais e 6 livres.
    O saldo guardado aqui e o TOTAL concedido; quanto sobra e a conta com as mentorias
    (`servicos/mentoria.saldo`). Guardar o que sobra obrigaria a acertar dois numeros a cada
    mentoria marcada, e eles desandariam no primeiro cancelamento.

    `anotacao` e do rastreador e so dele: a pessoa ve o saldo e as mentorias, nao o que foi escrito
    sobre ela.
    """

    __tablename__ = "acompanhamento"
    __table_args__ = (
        UniqueConstraint("cla_id", "membro_id", name="uq_acompanhamento_membro"),
        _alvo_membro("fk_acompanhamento_membro", "membro_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    membro_id: Mapped[int] = mapped_column(Integer)
    mensais_total: Mapped[int] = mapped_column(Integer, default=SALDO_INICIAL["mensal"])
    livres_total: Mapped[int] = mapped_column(Integer, default=SALDO_INICIAL["livre"])
    anotacao: Mapped[str] = mapped_column(Text, default="")
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, onupdate=agora)


class Mentoria(Base):
    """Uma consultoria entre o rastreador e uma pessoa. E 1 para 1, entao nao aparece para o cla.

    `inicio` e hora de parede em Brasilia, como `Evento.inicio`, pelo mesmo motivo: e o que foi
    combinado ("quinta, 20h"), e nao um instante que o app registrou.
    """

    __tablename__ = "mentoria"
    __table_args__ = (_alvo_membro("fk_mentoria_membro", "membro_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    membro_id: Mapped[int] = mapped_column(Integer, index=True)
    rastreador_id: Mapped[int] = mapped_column(ForeignKey("rastreador.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))
    inicio: Mapped[datetime] = mapped_column(DateTime)
    duracao_min: Mapped[int] = mapped_column(Integer, default=60)
    local: Mapped[str] = mapped_column(String(500), default="")
    situacao: Mapped[str] = mapped_column(String(20), default=MARCADA)
    # O que foi tratado nesta consultoria. Do rastreador, como a anotacao do acompanhamento.
    anotacao: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)

    rastreador: Mapped[Rastreador] = relationship()
    membro: Mapped[Membro] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(Mentoria.cla_id == Membro.cla_id, Mentoria.membro_id == Membro.id),
    )


# Acompanhamento semanal: o diario de cada pessoa do cla. Sem lider e sem rodizio: a cada semana
# alguem clica em "Eu assumo essa semana" e passa a ser quem conversa com cada um. Pode transferir.
STATUS_DO_DIARIO = {
    "conversou": "Conversa registrada",
    "em_dia": "Em dia",
    "atencao": "Precisa de atenção",
    "travado": "Travado",
    "sem_resposta": "Não respondeu",
}


class PerfilMembro(Base):
    """O que se sabe de uma pessoa do cla para acompanha-la: contexto, metas e dificuldades.

    Uma linha por pessoa por cla. A propria pessoa edita, e quem esta responsavel na semana tambem
    (e quem conversa e quem descobre que a meta mudou). Le: a pessoa, o responsavel da semana e o
    rastreador. O resto do cla nao, porque dificuldade de alguem nao e vitrine.
    """

    __tablename__ = "perfil_membro"
    __table_args__ = (
        UniqueConstraint("cla_id", "membro_id", name="uq_perfil_membro"),
        _alvo_membro("fk_perfil_membro", "membro_id"),
        _alvo_membro("fk_perfil_atualizado_por", "atualizado_por_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    membro_id: Mapped[int] = mapped_column(Integer)
    sobre: Mapped[str] = mapped_column(Text, default="")
    metas: Mapped[str] = mapped_column(Text, default="")
    dificuldades: Mapped[str] = mapped_column(Text, default="")
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, onupdate=agora)
    atualizado_por_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    atualizado_por: Mapped[Membro | None] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(
            PerfilMembro.cla_id == Membro.cla_id, PerfilMembro.atualizado_por_id == Membro.id
        ),
    )


class ResponsavelSemana(Base):
    """Quem assumiu conversar com o cla numa semana. Uma por cla por semana (segunda-feira).

    Linha criada no clique em "Eu assumo essa semana", e trocada quando o responsavel transfere.
    Semana sem linha e semana sem ninguem: o botao aparece para todo mundo.
    """

    __tablename__ = "responsavel_semana"
    __table_args__ = (
        UniqueConstraint("cla_id", "semana", name="uq_responsavel_semana"),
        _alvo_membro("fk_responsavel_membro", "membro_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    semana: Mapped[date] = mapped_column(Date)
    membro_id: Mapped[int] = mapped_column(Integer)
    desde: Mapped[datetime] = mapped_column(DateTime, default=agora)

    membro: Mapped[Membro] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(
            ResponsavelSemana.cla_id == Membro.cla_id, ResponsavelSemana.membro_id == Membro.id
        ),
    )


class DiarioEntrada(Base):
    """A conversa da semana com uma pessoa: como ela esta, o que foi combinado, e quem conversou.

    Uma por pessoa por semana; quem registra pode corrigir durante a semana. O cla ve o status,
    quem conversou e quando; o texto (como esta indo, combinados) so a pessoa, o responsavel da
    semana e o rastreador.
    """

    __tablename__ = "diario_entrada"
    __table_args__ = (
        UniqueConstraint("cla_id", "membro_id", "semana", name="uq_diario_semana"),
        _alvo_membro("fk_diario_membro", "membro_id"),
        _alvo_membro("fk_diario_autor", "autor_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cla_id: Mapped[int] = mapped_column(ForeignKey("cla.id"), index=True)
    membro_id: Mapped[int] = mapped_column(Integer, index=True)
    semana: Mapped[date] = mapped_column(Date, index=True)
    autor_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    como_esta: Mapped[str] = mapped_column(Text, default="")
    # As tarefas da semana combinadas na conversa. Texto livre, uma por linha: e o que a proxima
    # conversa confere.
    combinados: Mapped[str] = mapped_column(Text, default="")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(DateTime, default=agora, onupdate=agora)

    autor: Mapped[Membro] = relationship(
        viewonly=True,
        primaryjoin=lambda: and_(
            DiarioEntrada.cla_id == Membro.cla_id, DiarioEntrada.autor_id == Membro.id
        ),
    )


class VersaoComunidade(Base):
    __tablename__ = "versao_comunidade"

    id: Mapped[int] = mapped_column(primary_key=True)
    autor_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), index=True)
    autor_publico: Mapped[str] = mapped_column(String(80))
    nome: Mapped[str] = mapped_column(String(100))
    numero: Mapped[str] = mapped_column(String(40))
    resumo: Mapped[str] = mapped_column(String(240))
    novidades: Mapped[str] = mapped_column(Text, default="")
    categoria: Mapped[str] = mapped_column(String(30))
    repositorio: Mapped[str] = mapped_column(String(500), default="")
    demonstracao: Mapped[str] = mapped_column(String(500), default="")
    exemplo: Mapped[bool] = mapped_column(default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class ProjetoVersao(Base):
    __tablename__ = "projeto_versao"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    autor_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), index=True)
    nome: Mapped[str] = mapped_column(String(100))
    estado: Mapped[str] = mapped_column(String(30), default="rascunho")
    base_id: Mapped[int | None] = mapped_column(ForeignKey("versao_comunidade.id"), nullable=True)
    configuracao: Mapped[str] = mapped_column(Text, default="{}")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)


class ConexaoCentral(Base):
    __tablename__ = "conexao_central"
    __table_args__ = (UniqueConstraint("autor_id", "provedor", name="uq_conexao_central"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    autor_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), index=True)
    provedor: Mapped[str] = mapped_column(String(20))
    token_cifrado: Mapped[str] = mapped_column(Text)
    identidade: Mapped[str] = mapped_column(String(150))


class TarefaCentral(Base):
    __tablename__ = "tarefa_central"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    projeto_id: Mapped[str] = mapped_column(ForeignKey("projeto_versao.id"), index=True)
    autor_id: Mapped[int] = mapped_column(ForeignKey("usuario.id"), index=True)
    acao: Mapped[str] = mapped_column(String(30))
    estado: Mapped[str] = mapped_column(String(30), default="pendente", index=True)
    dados: Mapped[str] = mapped_column(Text, default="{}")
    mensagem: Mapped[str] = mapped_column(Text, default="Aguardando execução")
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
