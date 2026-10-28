(() => {
  const painel = document.querySelector('[data-tarefas]');
  if (!painel || painel.dataset.ocupada !== '1') return;
  let tentativas = 0;
  async function atualizar() {
    try {
      const r = await fetch('/versoes/projetos/' + painel.dataset.tarefas + '/estado', {credentials:'same-origin'});
      if (!r.ok) throw new Error();
      const dados = await r.json();
      const destino = document.getElementById('central-atividade');
      destino.replaceChildren(...dados.tarefas.slice(0,4).map(t => {
        const p = document.createElement('p'); p.textContent = t.estado + ': ' + t.mensagem; return p;
      }));
      tentativas = 0;
      if (!dados.ocupada) { location.reload(); return; }
    } catch (erro) {
      tentativas++;
      if (tentativas >= 5) {
        document.getElementById('central-atividade').textContent = 'Não foi possível atualizar o estado. Recarregue a página para consultar a tarefa; ela não foi reenviada.';
        return;
      }
    }
    setTimeout(atualizar, 2500);
  }
  setTimeout(atualizar, 1000);
})();
