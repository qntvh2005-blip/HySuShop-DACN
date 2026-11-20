(() => {
  const preview = document.querySelector('[data-return-evidence-preview]');
  const image = preview.querySelector('img');
  const input = preview.closest('form').elements.namedItem('evidence');
  let imageUrl;

  const updatePreview = async () => {
    preview.hidden = true;
    input.classList.remove('has-evidence-preview');
    image.removeAttribute('src');
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    imageUrl = undefined;

    const file = input.files[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    imageUrl = url;
    image.src = url;
    try {
      await image.decode();
      if (url !== imageUrl) return;
      preview.hidden = false;
      input.classList.add('has-evidence-preview');
    } catch {
      if (url !== imageUrl) return;
      URL.revokeObjectURL(url);
      imageUrl = undefined;
      image.removeAttribute('src');
    }
  };

  input.addEventListener('change', updatePreview);
})();
