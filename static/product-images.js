(() => {
  const showUnavailable = (image) => {
    const media = image.closest('.product-media');
    if (!media) return;
    image.hidden = true;
    media.classList.add('is-unavailable');
    media.querySelector('.product-image-fallback').hidden = false;
  };

  document.querySelectorAll('img[data-product-image]').forEach((image) => {
    image.addEventListener('error', () => showUnavailable(image), {
      once: true
    });
    // A cached failure can finish before this deferred script attaches listeners.
    if (image.complete && image.naturalWidth === 0) showUnavailable(image);
  });

  document.querySelectorAll('[data-product-gallery]').forEach((gallery) => {
    const controls = gallery.querySelector('.detail-gallery-controls');
    if (!controls) return;

    const slides = gallery.querySelectorAll('.detail-slide');
    const counter = controls.querySelector('[data-gallery-counter]');
    let current = 0;

    const move = (step) => {
      slides[current].hidden = true;
      current = (current + step + slides.length) % slides.length;
      slides[current].hidden = false;
      counter.textContent = `Ảnh ${current + 1} / ${slides.length}`;
    };

    controls.querySelectorAll('[data-gallery-step]').forEach((button) => {
      button.addEventListener('click', () => move(Number(button.dataset.galleryStep)));
    });
    gallery.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        move(event.key === 'ArrowLeft' ? -1 : 1);
      }
    });
    controls.hidden = false;
  });
})();
