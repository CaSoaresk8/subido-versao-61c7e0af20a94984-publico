"""O fluxo do cla de ponta a ponta: missao, entrega, pontos, quadro, coluna e lixeira.

Este arquivo e uma narrativa, e a ordem dos testes importa: um cria a missao que o proximo
entrega, e os pontos sobem e descem conforme o cartao anda. Foi escrito assim de proposito, porque
o que se quer provar e justamente que o placar acompanha o quadro; quebrar isso em testes
independentes exigiria montar o mesmo estado varias vezes e deixaria de exercitar a sequencia.

Os ids que um passo cria e o seguinte usa ficam na fixture `mundo`.

O banco inteiro e um arquivo temporario criado na entrada da sessao e apagado na saida (ver
conftest.py), entao nada aqui sobrevive para a proxima rodada.
"""

from __future__ import annotations

import re

MISSAO = "Resumo do Curso Subido de Trafego"
COBRADA = "Missao zqx9 que cobra entrega"


def colunas_na_tela(cliente) -> list[str]:
    return re.findall(r'data-chave="([^"]+)"', cliente.get("/minhas").text)


def relatorio_de(cliente, nome: str) -> str:
    """Pedaco do dashboard que fica dentro do acordeao daquela pessoa."""
    linhas = cliente.get("/").text.split('<details class="rank-linha')
    alvo = [bloco for bloco in linhas[1:] if nome in bloco]
    return alvo[0] if alvo else ""


def pontos_na_tela(cliente, quantos: int) -> bool:
    return f">{quantos}<" in cliente.get("/").text.replace(" ", "")


def test_qualquer_membro_sobe_missao(ana, mundo):
    resposta = ana.post(
        "/missoes/nova",
        data={
            "titulo": MISSAO,
            "descricao": "Entregar resumo escrito",
            "pontos": "500",
            "vencimento": "2026-09-30",
        },
        follow_redirects=True,
    )
    assert MISSAO in resposta.text
    mundo["missao"] = int(resposta.url.path.rsplit("/", 1)[-1])


def test_missao_aparece_para_os_outros_membros(bruno):
    assert "Resumo do Curso" in bruno.get("/missoes").text


def test_missao_sem_exigencia_conclui_sem_nada_anexado(ana, bruno, mundo):
    bruno.post(
        f"/missoes/{mundo['missao']}/entrega",
        data={"status": "concluido", "resposta": "", "observacao": "sem link mesmo"},
    )
    assert pontos_na_tela(ana, 500)


def test_dashboard_mostra_os_membros(ana):
    assert "Membros no clã" in ana.get("/").text


def test_missao_pode_exigir_resposta(ana, mundo):
    resposta = ana.post(
        "/missoes/nova",
        data={
            "titulo": COBRADA,
            "descricao": "Precisa do link",
            "pontos": "100",
            "vencimento": "",
            "exige_resposta": "1",
            "rotulo_resposta": "Link do resumo ou o resumo escrito aqui",
        },
        follow_redirects=True,
    )
    mundo["cobrada"] = int(resposta.url.path.rsplit("/", 1)[-1])
    assert "Link do resumo" in resposta.text


def test_concluir_sem_a_resposta_exigida_e_recusado(ana, bruno, mundo):
    resposta = bruno.post(
        f"/missoes/{mundo['cobrada']}/entrega",
        data={"status": "concluido", "resposta": "   ", "observacao": ""},
    )
    assert resposta.status_code == 400
    # Missao barrada nao pontua: o placar continua so com os 500 da outra.
    assert pontos_na_tela(ana, 500)


def test_arrastar_para_concluido_sem_resposta_e_recusado(bruno, mundo):
    resposta = bruno.post(
        "/minhas/mover",
        json={"destino": "concluido", "itens": [f"missao-{mundo['cobrada']}"]},
    )
    assert resposta.status_code == 409
    # A recusa precisa dizer o que falta, senao o cartao volta sozinho e ninguem entende por que.
    assert "Link do resumo" in resposta.text


def test_com_a_resposta_preenchida_a_missao_pontua(ana, bruno, mundo):
    bruno.post(
        f"/missoes/{mundo['cobrada']}/entrega",
        data={"status": "concluido", "resposta": "https://docs.google.com/zqx9", "observacao": ""},
    )
    assert pontos_na_tela(ana, 600)
    assert "https://docs.google.com/zqx9" in bruno.get(f"/missoes/{mundo['cobrada']}").text


def test_resposta_em_texto_tambem_e_aceita(bruno, mundo):
    bruno.post(
        f"/missoes/{mundo['cobrada']}/entrega",
        data={
            "status": "concluido",
            "resposta": "Resumo escrito zqx9 aqui mesmo",
            "observacao": "",
        },
    )
    assert "Resumo escrito zqx9 aqui mesmo" in bruno.get(f"/missoes/{mundo['cobrada']}").text


def test_limpar_a_missao_cobrada(ana, mundo):
    """Tira a missao de 100 pontos de cena para os testes seguintes contarem so a de 500."""
    ana.post(f"/missoes/{mundo['cobrada']}/excluir")
    assert COBRADA not in ana.get("/missoes").text


def test_visao_padrao_e_o_kanban(ana):
    assert 'class="kanban"' in ana.get("/minhas").text


def test_calendario_carrega_com_a_agenda_do_mes(ana):
    """O mes vai explicito na URL porque o vencimento das missoes daqui e uma data fixa.

    Sem `ano` e `mes` a rota abre no mes de hoje, e este teste passava so por coincidencia de
    calendario: em outubro de 2026 ele viraria vermelho sem ninguem ter mexido em nada. Teste que
    depende da data em que roda nao esta medindo o app, esta medindo o relogio.
    """
    texto = ana.get("/minhas?visao=calendario&ano=2026&mes=9").text
    assert "setembro" in texto.lower()
    assert 'class="agenda-item"' in texto and "30/09" in texto


def test_tarefa_pessoal_aparece_na_lista(ana, mundo):
    ana.post(
        "/minhas/tarefas", data={"titulo": "Tarefa privada zqx9 da Ana", "prazo": "2026-09-25"}
    )
    assert "Tarefa privada zqx9 da Ana" in ana.get("/minhas?visao=lista").text
    mundo["tarefa_ana"] = int(ana.get("/minhas").text.split('data-card="pessoal-')[1].split('"')[0])


def test_tarefa_pessoal_nao_vaza_para_outro_membro(bruno):
    assert "Tarefa privada zqx9 da Ana" not in bruno.get("/minhas?visao=lista").text


def test_cartao_aberto_troca_titulo_e_prazo(ana, mundo):
    resposta = ana.post(
        f"/minhas/tarefas/{mundo['tarefa_ana']}/editar",
        data={"titulo": "Tarefa privada zqx9 renomeada", "prazo": "2026-09-28", "visao": "lista"},
        follow_redirects=True,
    )
    assert "Tarefa privada zqx9 renomeada" in resposta.text and "28/09" in resposta.text


def test_da_para_tirar_o_prazo_da_tarefa(ana, mundo):
    resposta = ana.post(
        f"/minhas/tarefas/{mundo['tarefa_ana']}/editar",
        data={"titulo": "Tarefa privada zqx9 renomeada", "prazo": ""},
        follow_redirects=True,
    )
    assert "sem prazo" in resposta.text


def test_data_impossivel_nao_derruba_a_pagina(ana, mundo):
    resposta = ana.post(
        f"/minhas/tarefas/{mundo['tarefa_ana']}/editar",
        data={"titulo": "Tarefa privada zqx9 renomeada", "prazo": "30/02/2026"},
        follow_redirects=False,
    )
    assert resposta.status_code == 303


def test_membro_nao_edita_tarefa_de_outro(bruno, mundo):
    # 404 e nao 403: 403 confirmaria que a tarefa existe.
    resposta = bruno.post(
        f"/minhas/tarefas/{mundo['tarefa_ana']}/editar", data={"titulo": "invadida"}
    )
    assert resposta.status_code == 404


def test_cartoes_do_quadro_abrem_pelo_proprio_cartao(ana, mundo):
    texto = ana.get("/minhas").text
    assert ">Abrir<" not in texto and f'href="/missoes/{mundo["missao"]}"' in texto
    assert '<summary class="cartao-inteiro">' in texto
    assert "simbolo-topo" in texto


def test_so_concluido_tem_etiqueta_de_ponto(ana):
    texto = ana.get("/minhas").text
    concluido = texto.split('data-chave="concluido"')[1].split("coluna-corpo")[0]
    assert "Vale ponto" in concluido
    assert texto.count("Vale ponto") == 1
    assert "todos veem" not in texto


def test_membro_cria_coluna_propria(ana, mundo):
    resposta = ana.post(
        "/minhas/colunas", data={"nome": "Coluna zqx9 da Ana"}, follow_redirects=True
    )
    assert "Coluna zqx9 da Ana" in resposta.text
    mundo["coluna_ana"] = int(resposta.text.split("/minhas/colunas/")[1].split("/")[0])


def test_coluna_de_um_nao_aparece_para_o_outro(bruno):
    assert "Coluna zqx9 da Ana" not in bruno.get("/minhas").text


def test_membro_nao_move_cartao_para_coluna_alheia(bruno, mundo):
    resposta = bruno.post(
        "/minhas/mover",
        json={"destino": f"c{mundo['coluna_ana']}", "itens": [f"missao-{mundo['missao']}"]},
    )
    assert resposta.status_code == 400


def test_tirar_do_concluido_zera_os_pontos(ana, bruno, mundo):
    bruno.post("/minhas/mover", json={"destino": "fazendo", "itens": [f"missao-{mundo['missao']}"]})
    assert not pontos_na_tela(ana, 500)


def test_voltar_para_concluido_devolve_os_pontos(ana, bruno, mundo):
    bruno.post(
        "/minhas/mover", json={"destino": "concluido", "itens": [f"missao-{mundo['missao']}"]}
    )
    assert pontos_na_tela(ana, 500)


def test_cartao_arrastado_fica_na_coluna_criada(ana, mundo):
    ana.post("/minhas/tarefas", data={"titulo": "Tarefa na coluna nova"})
    tarefa = int(ana.get("/minhas").text.split('data-card="pessoal-')[-1].split('"')[0])
    ana.post(
        "/minhas/mover",
        json={"destino": f"c{mundo['coluna_ana']}", "itens": [f"pessoal-{tarefa}"]},
    )
    bloco = (
        ana.get("/minhas")
        .text.split(f'data-coluna="c{mundo["coluna_ana"]}"')[1]
        .split("data-coluna=")[0]
    )
    assert f'data-card="pessoal-{tarefa}"' in bloco


def test_tarefa_criada_pelo_botao_da_coluna_nasce_ali(ana, mundo):
    ana.post(
        "/minhas/tarefas",
        data={"titulo": "Direto na coluna zqx9", "destino": f"c{mundo['coluna_ana']}"},
    )
    bloco = (
        ana.get("/minhas")
        .text.split(f'data-coluna="c{mundo["coluna_ana"]}"')[1]
        .split("data-coluna=")[0]
    )
    assert "Direto na coluna zqx9" in bloco


def test_membro_salva_a_ordem_das_colunas(ana, bruno, mundo):
    ordem = [f"c{mundo['coluna_ana']}", "concluido", "a_fazer", "fazendo"]
    mundo["ordem"] = ordem
    assert ana.post("/minhas/colunas/ordenar", json={"colunas": ordem}).status_code == 200
    assert colunas_na_tela(ana) == ordem
    # A ordem e de quem salvou: o quadro do outro nao se mexe.
    assert colunas_na_tela(bruno)[0] == "a_fazer"


def test_ordem_sem_todas_as_colunas_e_recusada(ana, mundo):
    resposta = ana.post("/minhas/colunas/ordenar", json={"colunas": ["a_fazer"]})
    assert resposta.status_code == 400
    assert colunas_na_tela(ana) == mundo["ordem"]


def test_excluir_coluna_devolve_o_cartao(ana, mundo):
    ana.post(f"/minhas/colunas/{mundo['coluna_ana']}/excluir")
    texto = ana.get("/minhas").text
    assert "Coluna zqx9 da Ana" not in texto and "Tarefa na coluna nova" in texto
    assert colunas_na_tela(ana) == ["concluido", "a_fazer", "fazendo"]


def test_missao_excluida_some_da_lista_e_vai_para_o_historico(ana, mundo):
    ana.post(f"/missoes/{mundo['missao']}/excluir")
    assert "Resumo do Curso" not in ana.get("/missoes").text
    assert "Resumo do Curso" in ana.get("/historico").text


def test_missao_restaurada_volta_com_os_pontos(ana, mundo):
    ana.post(f"/historico/missoes/{mundo['missao']}/restaurar")
    assert "Resumo do Curso" in ana.get("/missoes").text
    assert pontos_na_tela(ana, 500)


def test_ranking_abre_o_relatorio_na_propria_linha(ana):
    texto = ana.get("/").text
    # Acordeao na linha, sem trocar de pagina: nao existe rota /membros/<id>.
    assert texto.count('<details class="rank-linha') == 2
    assert "/membros/" not in texto


def test_grafico_traz_uma_barra_por_missao(ana):
    grafico = ana.get("/").text.split("Quem fez cada missão")[1]
    assert grafico.count('class="grafico-linha"') == 1 and "1 de 2" in grafico
    assert "Bruno Tester" in grafico and "Ana Tester" not in grafico


def test_relatorio_separa_concluida_fazendo_e_nao_comecou(ana):
    bloco = relatorio_de(ana, "Bruno Tester")
    assert "Concluídas (1)" in bloco and "Fazendo (0)" in bloco and "Não começou (0)" in bloco
    assert "Resumo do Curso" in bloco


def test_relatorio_mostra_a_missao_que_a_pessoa_nao_comecou(bruno):
    assert "Não começou (1)" in relatorio_de(bruno, "Ana Tester")


def test_tarefa_pessoal_nao_entra_em_relatorio_nenhum(bruno):
    texto = bruno.get("/").text
    assert "Tarefa privada zqx9 renomeada" not in texto and "Tarefa na coluna nova" not in texto


def test_missao_em_coluna_privada_conta_como_nao_comecada(ana, bruno, mundo):
    resposta = bruno.post(
        "/minhas/colunas", data={"nome": "Gaveta zqx9 do Bruno"}, follow_redirects=True
    )
    mundo["coluna_bruno"] = int(resposta.text.split("/minhas/colunas/")[1].split("/")[0])
    bruno.post(
        "/minhas/mover",
        json={"destino": f"c{mundo['coluna_bruno']}", "itens": [f"missao-{mundo['missao']}"]},
    )
    assert "Não começou (1)" in relatorio_de(ana, "Bruno Tester")
    assert "Gaveta zqx9 do Bruno" not in ana.get("/").text
    assert not pontos_na_tela(ana, 500)


def test_voltar_da_coluna_privada_devolve_os_pontos(ana, bruno, mundo):
    bruno.post(
        "/minhas/mover", json={"destino": "concluido", "itens": [f"missao-{mundo['missao']}"]}
    )
    assert pontos_na_tela(ana, 500)


def test_mover_form_funciona_sem_javascript(ana, bruno, mundo):
    """O quadro arrasta por fetch, mas /minhas/mover-form e o caminho de quem esta sem JS.

    Ate aqui essa rota nao tinha teste nenhum: dava para apagar o arquivo inteiro e a suite
    continuava verde. Vai e volta na mesma funcao para nao deixar o cartao fora de lugar.
    """
    alvo = {"chave": f"missao-{mundo['missao']}"}
    bruno.post("/minhas/mover-form", data={**alvo, "destino": "fazendo"})
    assert not pontos_na_tela(ana, 500)
    bruno.post("/minhas/mover-form", data={**alvo, "destino": "concluido"})
    assert pontos_na_tela(ana, 500)


def test_mover_form_para_coluna_alheia_e_recusado(ana, mundo):
    resposta = ana.post(
        "/minhas/mover-form",
        data={"chave": f"missao-{mundo['missao']}", "destino": f"c{mundo['coluna_bruno']}"},
    )
    assert resposta.status_code == 400


def test_membro_nao_exclui_coluna_de_outro(ana, bruno, mundo):
    # 404 e nao 403, pelo mesmo motivo da tarefa: 403 confirmaria que a coluna existe.
    assert ana.post(f"/minhas/colunas/{mundo['coluna_bruno']}/excluir").status_code == 404
    assert "Gaveta zqx9 do Bruno" in bruno.get("/minhas").text


def test_tarefa_excluida_vai_para_o_historico_e_volta(ana, mundo):
    nome = "Tarefa privada zqx9 renomeada"
    ana.post(f"/minhas/tarefas/{mundo['tarefa_ana']}/excluir")
    assert nome not in ana.get("/minhas?visao=lista").text
    assert nome in ana.get("/historico").text
    ana.post(f"/historico/tarefas/{mundo['tarefa_ana']}/restaurar")
    assert nome in ana.get("/minhas?visao=lista").text
