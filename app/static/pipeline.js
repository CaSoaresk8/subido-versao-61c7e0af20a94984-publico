(() => {
  document.querySelectorAll('[data-pipeline]').forEach(rail => {
    let drag = null;
    rail.addEventListener('pointerdown', e => {
      if (e.pointerType !== 'mouse' || e.button !== 0) return;
      drag = { id: e.pointerId, x: e.clientX, scroll: rail.scrollLeft };
      rail.setPointerCapture(e.pointerId);
    });
    rail.addEventListener('pointermove', e => {
      if (!drag || drag.id !== e.pointerId) return;
      if (Math.abs(e.clientX - drag.x) < 4) return;
      e.preventDefault();
      rail.classList.add('arrastando');
      rail.scrollLeft = drag.scroll - (e.clientX - drag.x);
    });
    const end = e => {
      if (!drag || drag.id !== e.pointerId) return;
      const id = drag.id;
      drag = null;
      rail.classList.remove('arrastando');
      if (rail.hasPointerCapture(id)) rail.releasePointerCapture(id);
    };
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(type => rail.addEventListener(type, end));
    rail.addEventListener('dragstart', e => e.preventDefault());
    rail.addEventListener('keydown', e => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) return;
      e.preventDefault();
      if (e.key === 'Home') rail.scrollLeft = 0;
      else if (e.key === 'End') rail.scrollLeft = rail.scrollWidth;
      else rail.scrollLeft += (e.key === 'ArrowRight' ? 1 : -1) * Math.min(320, rail.clientWidth * .85);
    });
  });
})();
