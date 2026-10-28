"""Regra de negocio: o que o app calcula e decide.

Nada aqui monta consulta (isso e de app/repositorios/) e nada aqui sabe o que e uma requisicao
HTTP (isso e de app/routers/). O que esta aqui pode ser chamado de um teste sem servidor no ar,
que e o ponto: pontuacao, relatorio e regra de quadro sao o que mais quebra em silencio.
"""
