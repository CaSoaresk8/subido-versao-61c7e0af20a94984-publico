(() => {
  document.querySelectorAll('.cal-evento-detalhes').forEach(evento => {
    let mouse = false;
    evento.addEventListener('pointerenter', e => {
      if (e.pointerType !== 'mouse') return;
      mouse = true;
      evento.open = true;
    });
    evento.addEventListener('pointerleave', e => {
      if (e.pointerType !== 'mouse') return;
      mouse = false;
      if (!evento.contains(document.activeElement)) evento.open = false;
    });
    evento.querySelector('summary').addEventListener('click', e => {
      if (!e.target.closest('a') && mouse && e.detail > 0) { e.preventDefault(); evento.open = true; }
    });
    evento.addEventListener('focusout', () => {
      setTimeout(() => {
        if (!mouse && !evento.contains(document.activeElement)) evento.open = false;
      }, 0);
    });
    evento.addEventListener('keydown', e => {
      if (e.key === 'Escape') { evento.open = false; evento.querySelector('summary').focus(); }
    });
  });
})();
