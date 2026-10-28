from app.escopo import EscopoCla
from app.models import Log

# O feed do cla mostra o que e do cla: missoes, entregas, quem entrou, convites. Tarefa pessoal e
# privada (so o dono ve, inclusive na lixeira), e o titulo dela no feed era exatamente o vazamento
# que essa regra existe para impedir. O registro continua sendo gravado, so nao aparece para o cla.
# O filtro e no SQL, e nao depois, para o `limite` contar so linhas que de fato vao para a tela.
# Mentoria e acompanhamento entram pelo mesmo motivo: sao 1 para 1 entre a pessoa e o rastreador,
# e o saldo de consultorias de alguem nao e assunto do cla. A entrega continua publica: e a
# pontuacao do cla que muda quando o rastreador conclui uma.
# Diario e perfil pelo mesmo motivo: o cla ve no cartao o status e quem conversou, mas o texto da
# conversa e as dificuldades de alguem nao vao para o historico de todo mundo. Quem assumiu a
# semana continua aparecendo ("responsavel"): isso e do cla.
ENTIDADES_PRIVADAS = ("tarefa", "mentoria", "acompanhamento", "diario", "perfil")


def recentes(escopo: EscopoCla, limite: int = 100) -> list[Log]:
    stmt = (
        escopo.q(Log)
        .where(Log.entidade.not_in(ENTIDADES_PRIVADAS))
        .order_by(Log.criado_em.desc())
        .limit(limite)
    )
    return list(escopo.db.scalars(stmt))
