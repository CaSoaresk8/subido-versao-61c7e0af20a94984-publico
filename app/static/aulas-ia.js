const cards = [...document.querySelectorAll('.aula-card')];
const covers = new Map(cards.map(card => [card, card.querySelector('.aula-player').innerHTML]));
function resetLesson(card) {
  card.classList.remove('aula-expandida');
  card.querySelector('.aula-player').innerHTML = covers.get(card);
  card.querySelector('[data-fechar-aula]')?.remove();
}
document.addEventListener('click', event => {
  const close = event.target.closest('[data-fechar-aula]');
  if (close) {
    const card = close.closest('.aula-card');
    resetLesson(card);
    card.querySelector('[data-aula]').focus();
    return;
  }
  const button = event.target.closest('[data-aula]');
  if (!button) return;
  const id = button.dataset.aula;
  if (!/^[a-zA-Z0-9_-]{11}$/.test(id)) return;
  const card = button.closest('.aula-card');
  cards.forEach(resetLesson);
  const frame = document.createElement('iframe');
  frame.src = 'https://www.youtube-nocookie.com/embed/' + id + '?autoplay=1&rel=0';
  frame.title = button.dataset.titulo;
  frame.allow = 'autoplay; encrypted-media; picture-in-picture; fullscreen';
  frame.allowFullscreen = true;
  frame.referrerPolicy = 'strict-origin-when-cross-origin';
  card.classList.add('aula-expandida');
  card.querySelector('.aula-player').replaceChildren(frame);
  const back = document.createElement('button');
  back.type = 'button';
  back.className = 'btn btn-mini';
  back.dataset.fecharAula = '';
  back.textContent = 'Voltar às aulas';
  card.querySelector('.aula-corpo').append(back);
  card.scrollIntoView({behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block:'start'});
  frame.focus({preventScroll:true});
});
