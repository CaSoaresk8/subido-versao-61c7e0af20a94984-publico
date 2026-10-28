(function () {
  const quadro = document.querySelector("[data-quadro]");

  document.querySelectorAll("select[data-mover]").forEach(function (select) {
    select.addEventListener("change", function () {
      select.form.submit();
    });
    const botao = select.form.querySelector("button[type=submit]");
    if (botao) botao.hidden = true;
  });

  if (!quadro) return;

  let arrastando = null;
  let colunaArrastando = null;

  function posicaoAlvo(corpo, y) {
    const cartoes = corpo.querySelectorAll(".cartao:not(.arrastando)");
    for (const cartao of cartoes) {
      const caixa = cartao.getBoundingClientRect();
      if (y < caixa.top + caixa.height / 2) return cartao;
    }
    return null;
  }

  function recontar() {
    quadro.querySelectorAll(".coluna").forEach(function (coluna) {
      const total = coluna.querySelectorAll(".cartao").length;
      const conta = coluna.querySelector(".conta");
      if (conta) conta.textContent = total;
      const vazia = coluna.querySelector(".coluna-vazia");
      if (vazia) vazia.hidden = total > 0;
    });
  }

  function sincronizarSelects() {
    quadro.querySelectorAll(".coluna-corpo").forEach(function (corpo) {
      const destino = corpo.dataset.coluna;
      corpo.querySelectorAll("select[data-mover]").forEach(function (select) {
        select.value = destino;
      });
    });
  }

  function salvar(corpo) {
    const destino = corpo.dataset.coluna;
    const itens = Array.from(corpo.querySelectorAll(".cartao")).map(function (cartao) {
      return cartao.dataset.card;
    });
    recontar();
    sincronizarSelects();

    fetch("/minhas/mover", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ destino: destino, itens: itens }),
    })
      .then(function (resposta) {
        if (resposta.status === 409) {
          return resposta.json().then(function (dados) {
            window.alert(dados.mensagem);
            window.location.href = dados.url;
            throw new Error("resposta obrigatoria");
          });
        }
        if (!resposta.ok) throw new Error(resposta.status);
        return resposta.json();
      })
      .then(function (dados) {
        const alvo = document.querySelector("[data-meus-pontos]");
        if (alvo) alvo.textContent = dados.pontos;
      })
      .catch(function (erro) {
        if (erro && erro.message === "resposta obrigatoria") return;
        window.location.reload();
      });
  }

  function salvarColunas() {
    const chaves = Array.from(quadro.querySelectorAll(".coluna")).map(function (coluna) {
      return coluna.dataset.chave;
    });
    fetch("/minhas/colunas/ordenar", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ colunas: chaves }),
    })
      .then(function (resposta) {
        if (!resposta.ok) throw new Error(resposta.status);
      })
      .catch(function () {
        window.location.reload();
      });
  }

  // Sem isso, comecar o clique num select ou botao vira arrasto. Link e summary ficam de fora:
  // o titulo cobre o cartao inteiro, e bloquear ali mataria o arrasto do cartao.
  quadro.addEventListener("pointerdown", function (ev) {
    const controle = ev.target.closest("select, button, input, textarea");
    const cartao = ev.target.closest(".cartao");
    if (cartao) cartao.draggable = !controle;
    const coluna = ev.target.closest(".coluna");
    const interativo = controle || ev.target.closest("a, summary");
    if (coluna) coluna.draggable = !interativo && !cartao && !!ev.target.closest("[data-pega]");
  });

  // Alternativa ao arrasto para quem esta no celular, onde drag nativo nao existe.
  quadro.addEventListener("click", function (ev) {
    const botao = ev.target.closest("[data-passo]");
    if (!botao) return;
    const coluna = botao.closest(".coluna");
    const vizinho =
      botao.dataset.passo === "1" ? coluna.nextElementSibling : coluna.previousElementSibling;
    if (!vizinho) return;
    if (botao.dataset.passo === "1") quadro.insertBefore(vizinho, coluna);
    else quadro.insertBefore(coluna, vizinho);
    coluna.scrollIntoView({ block: "nearest", inline: "nearest" });
    salvarColunas();
  });

  quadro.addEventListener("dragstart", function (ev) {
    const cartao = ev.target.closest(".cartao");
    if (cartao && cartao.draggable) {
      arrastando = cartao;
      ev.dataTransfer.effectAllowed = "move";
      ev.dataTransfer.setData("text/plain", cartao.dataset.card);
      requestAnimationFrame(function () {
        cartao.classList.add("arrastando");
      });
      return;
    }
    const coluna = ev.target.closest(".coluna");
    if (!coluna || !coluna.draggable) return;
    colunaArrastando = coluna;
    ev.dataTransfer.effectAllowed = "move";
    ev.dataTransfer.setData("text/plain", coluna.dataset.chave);
    requestAnimationFrame(function () {
      coluna.classList.add("arrastando");
    });
  });

  quadro.addEventListener("dragend", function () {
    if (arrastando) arrastando.classList.remove("arrastando");
    arrastando = null;
    quadro.querySelectorAll(".coluna-corpo").forEach(function (corpo) {
      corpo.classList.remove("alvo");
    });
    if (colunaArrastando) {
      colunaArrastando.classList.remove("arrastando");
      colunaArrastando.draggable = false;
      colunaArrastando = null;
      salvarColunas();
    }
  });

  quadro.addEventListener("dragover", function (ev) {
    if (colunaArrastando) {
      const alvo = ev.target.closest(".coluna");
      ev.preventDefault();
      ev.dataTransfer.dropEffect = "move";
      if (!alvo || alvo === colunaArrastando) return;
      const caixa = alvo.getBoundingClientRect();
      const depois = ev.clientX > caixa.left + caixa.width / 2;
      quadro.insertBefore(colunaArrastando, depois ? alvo.nextSibling : alvo);
      return;
    }
    if (!arrastando) return;
    const corpo = ev.target.closest(".coluna-corpo");
    if (!corpo) return;
    ev.preventDefault();
    ev.dataTransfer.dropEffect = "move";
    corpo.classList.add("alvo");
    const vizinho = posicaoAlvo(corpo, ev.clientY);
    if (vizinho) corpo.insertBefore(arrastando, vizinho);
    else corpo.appendChild(arrastando);
  });

  quadro.addEventListener("dragleave", function (ev) {
    const corpo = ev.target.closest(".coluna-corpo");
    if (corpo && !corpo.contains(ev.relatedTarget)) corpo.classList.remove("alvo");
  });

  quadro.addEventListener("drop", function (ev) {
    if (colunaArrastando) {
      ev.preventDefault();
      return;
    }
    if (!arrastando) return;
    const corpo = ev.target.closest(".coluna-corpo");
    if (!corpo) return;
    ev.preventDefault();
    corpo.classList.remove("alvo");
    arrastando.classList.remove("arrastando");
    salvar(corpo);
  });

  recontar();
})();
