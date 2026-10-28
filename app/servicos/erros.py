"""Erros de regra de negocio, sem nada de HTTP.

Servico que levanta HTTPException so pode ser chamado de dentro de uma requisicao, e a ideia de
separar as camadas era justamente poder chamar a regra de um teste sem servidor no ar. Quem
traduz isto para codigo de resposta e o app/main.py, num lugar so.
"""


class NaoEncontrado(Exception):
    """O recurso nao existe, ou existe e nao e de quem pediu.

    Os dois casos viram o MESMO erro de proposito, e viram 404 e nunca 403. Responder 403 para
    "existe mas nao e seu" confirma que o id existe, e ai da para varrer ids para descobrir o que
    os outros tem. Isso ja vale entre pessoas hoje e vai valer entre clas na fase 2.
    """


class DestinoInvalido(Exception):
    """Coluna que nao existe, ou que e de outra pessoa."""


class FaltaResposta(Exception):
    """Missao que exige resposta sendo concluida com o campo vazio.

    Carrega a missao porque as duas telas que tratam isto precisam dela: o HTML redesenha a pagina
    da missao com o campo em destaque, e a API devolve o id para o React saber para onde levar quem
    arrastou o cartao no quadro. Sem a missao junto, cada lado teria que buscar de novo o que quem
    levantou o erro ja tinha na mao.
    """

    def __init__(self, missao):
        super().__init__("Essa missão só é concluída com a resposta preenchida.")
        self.missao = missao


class ForaDeRegra(Exception):
    """O pedido chegou completo e mesmo assim nao pode: nome vazio, limite estourado, valor fora da lista.

    E o erro de formulario, o que vira 400 com a frase pronta para aparecer na tela. Diferente de
    `NaoEncontrado`, que fala sobre o que existe, este fala sobre o que foi pedido, e por isso a
    mensagem pode ser especifica sem contar nada a quem varre ids.
    """
