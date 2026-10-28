"""A API JSON, servida em /api/v1 ao lado das paginas Jinja.

As duas UIs convivem de proposito. A API nasce sozinha, com os testes dela, antes de existir uma
linha de React; assim o contrato e conferido enquanto a tela antiga ainda funciona e pode responder
a pergunta "e assim mesmo que devia ser?".

Nada de regra de negocio mora aqui dentro. Toda rota da API chama os mesmos servicos e
repositorios que as rotas de HTML chamam, pelo mesmo EscopoCla. Se a API tivesse a propria copia da
regra, as duas telas comecariam iguais e terminariam diferentes, e a diferenca so apareceria depois
que a antiga fosse apagada.
"""
