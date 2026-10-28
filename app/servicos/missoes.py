"""Regra da missao e da entrega: o criterio de "isso vale ponto" e as escritas do ciclo de vida.

As funcoes de criterio (`conta_como_concluida`, `falta_resposta`) nao vao ao banco: recebem o
objeto ja carregado e respondem sim ou nao. As de escrita (`criar`, `editar`, `excluir`,
`restaurar`, `salvar_entrega`) escrevem e anotam no log, mas **nao dao commit**: quem chamou e quem
sabe se a operacao inteira vale, e o mesmo servico e chamado de uma rota que responde HTML e de uma
que responde JSON.

As de escrita moravam dentro de `routers/missoes.py`. Sairam de la quando a API apareceu, e o
motivo e o que aconteceria se nao tivessem saido: a rota de HTML e a de JSON comecariam com o mesmo
comportamento e terminariam com dois, porque ninguem lembra de mudar as duas. Um exemplo do que se
perderia: o `coluna_id = None` de `salvar_entrega` existe por causa de um defeito real, e ele estava
escrito em um lugar so.
"""

from datetime import date

from app.escopo import EscopoCla
from app.models import CONCLUIDO, STATUS_VALIDOS, Entrega, Missao, agora
from app.repositorios import entregas as repo_entregas
from app.servicos.auditoria import registrar
from app.servicos.erros import FaltaResposta, ForaDeRegra, NaoEncontrado

MINIMO_TITULO = 3


def conta_como_concluida(entrega: Entrega | None) -> bool:
    """O criterio unico de "isso vale ponto", e o unico lugar onde ele fica escrito.

    Concluido dentro de coluna que o membro criou nao vale: a coluna e privada, ninguem mais ve o
    cartao ali, e o que pontua e a etapa Concluido do quadro compartilhado.

    Existia em duas versoes antes. `relatorio` e o ponto do quadro checavam coluna_id; os numeros
    do cla, o grafico e a barra de progresso nao. Com o cartao numa coluna privada e concluido, o
    dashboard mostrava 100 pontos gerados e ao mesmo tempo todo mundo com 0 no ranking, e o grafico
    dizia que a pessoa fez a missao que a propria linha dela dizia que nao.

    A versao em SQL vive em repositorios/entregas.py:pontuacao_concluida, e um teste compara as
    duas contra o mesmo banco para elas nao desandarem separadas.
    """
    return entrega is not None and entrega.status == CONCLUIDO and entrega.coluna_id is None


def falta_resposta(missao: Missao, entrega: Entrega | None) -> bool:
    """Missao que pede resposta so pode ser concluida com o campo preenchido."""
    if not missao.exige_resposta:
        return False
    return not (entrega and entrega.resposta.strip())


def rotulo_da_resposta(missao: Missao) -> str:
    return missao.rotulo_resposta.strip() or "Link ou texto da entrega"


def frase_de_falta_de_resposta(missao: Missao) -> str:
    """A explicacao que a pessoa le quando a missao barra a conclusao, escrita uma vez so.

    Tres lugares dizem isto: o arrastar do kanban em HTML, o mesmo arrastar pela API e a entrega
    salva pela tela da missao. A frase cita o rotulo que quem criou a missao escolheu, entao ela
    depende da regra e mora junto dela. Copiada em tres lugares, viraria tres frases no dia em que
    alguem melhorasse uma.
    """
    return (
        f'"{missao.titulo}" só entra em Concluído depois que você preencher: '
        f"{rotulo_da_resposta(missao)}."
    )


def marcar_excluido(objeto) -> None:
    """Exclusao e sempre marcacao, nunca DELETE: e o que permite restaurar pelo historico."""
    objeto.excluida_em = agora()


def data_da_missao(texto: str | None) -> date | None:
    """O vencimento digitado, ou nada. Texto torto vira ValueError, e o router responde 400.

    Diferente do prazo da tarefa pessoal, que engole data invalida: aqui a missao e do cla inteiro e
    um vencimento que sumiu em silencio e um prazo que 17 pessoas deixam de ver.
    """
    texto = (texto or "").strip()
    return date.fromisoformat(texto) if texto else None


def validar_titulo(titulo: str) -> str | None:
    if len(titulo.strip()) < MINIMO_TITULO:
        return "Escreva um título para a missão."
    return None


def criar(
    escopo: EscopoCla,
    titulo: str,
    descricao: str = "",
    pontos: int = 0,
    vencimento: date | None = None,
    exige_resposta: bool = False,
    rotulo_resposta: str = "",
) -> Missao:
    """Cria a missao do cla ativo e anota no log. Nao da commit."""
    problema = validar_titulo(titulo)
    if problema:
        raise ForaDeRegra(problema)
    missao = Missao(
        cla_id=escopo.cla_id,
        titulo=titulo.strip(),
        descricao=descricao.strip(),
        # Ponto negativo tiraria pontos de quem concluiu, que nao e uma ideia que alguem teve: e o
        # que sai de um campo `type=number` com um sinal de menos digitado na frente.
        pontos=max(0, pontos),
        vencimento=vencimento,
        criada_por_id=escopo.membro_id,
        exige_resposta=exige_resposta,
        rotulo_resposta=rotulo_resposta.strip(),
    )
    escopo.db.add(missao)
    escopo.db.flush()
    registrar(escopo, "criou", "missao", missao.id, missao.titulo)
    return missao


def editar(
    escopo: EscopoCla,
    missao: Missao,
    titulo: str,
    descricao: str = "",
    pontos: int = 0,
    vencimento: date | None = None,
    exige_resposta: bool = False,
    rotulo_resposta: str = "",
) -> Missao:
    """Titulo vazio mantem o que estava, em vez de apagar o nome da missao do cla inteiro."""
    missao.titulo = titulo.strip() or missao.titulo
    missao.descricao = descricao.strip()
    missao.pontos = max(0, pontos)
    missao.vencimento = vencimento
    missao.exige_resposta = exige_resposta
    missao.rotulo_resposta = rotulo_resposta.strip()
    registrar(escopo, "editou", "missao", missao.id, missao.titulo)
    return missao


def excluir(escopo: EscopoCla, missao: Missao) -> None:
    marcar_excluido(missao)
    missao.excluida_por_id = escopo.membro_id
    registrar(escopo, "excluiu", "missao", missao.id, missao.titulo)


def restaurar(escopo: EscopoCla, missao: Missao) -> None:
    if missao.ativa:
        raise NaoEncontrado("Missão não encontrada na lixeira")
    missao.excluida_em = None
    missao.excluida_por_id = None
    registrar(escopo, "restaurou", "missao", missao.id, missao.titulo)


def salvar_entrega(
    escopo: EscopoCla,
    missao: Missao,
    status: str,
    resposta: str = "",
    observacao: str = "",
) -> Entrega:
    """A entrega de quem esta logado nesta missao. Levanta FaltaResposta quando o campo e exigido.

    O `coluna_id = None` no fim nao e detalhe: escolher a etapa por aqui tira o cartao da coluna
    privada, se ele estava numa. Sem isso o cartao ficava guardado na gaveta com status concluido,
    que e um lugar que o quadro nao sabe desenhar, porque coluna_id manda no desenho e status manda
    no ponto, e os dois discordavam.

    Quem levanta FaltaResposta ja escreveu na entrega, entao o rollback e obrigatorio e fica com
    quem chamou: as duas rotas que chamam isto precisam desfazer, e uma delas ainda redesenha a
    pagina inteira com a mensagem.
    """
    if status not in STATUS_VALIDOS:
        raise ForaDeRegra("Status inválido")

    entrega = repo_entregas.obter_ou_criar(escopo, missao.id, escopo.membro_id)
    entrega.status = status
    entrega.resposta = resposta.strip()
    entrega.observacao = observacao.strip()

    if status == CONCLUIDO and falta_resposta(missao, entrega):
        raise FaltaResposta(missao)

    entrega.concluida_em = agora() if status == CONCLUIDO else None
    entrega.coluna_id = None
    registrar(escopo, "atualizou", "entrega", entrega.id, f"{missao.titulo}: {status}")
    return entrega
