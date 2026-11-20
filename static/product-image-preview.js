(() => {
  const form = document.querySelector('[data-product-image-upload]');
  if (!form) return;

  const input = form.elements.namedItem('file');
  const preview = form.querySelector('.product-upload-preview');
  const supportedTypes = ['image/jpeg', 'image/png', 'image/webp'];
  let currentUrl;

  input.addEventListener('change', async () => {
    preview.hidden = true;
    preview.removeAttribute('src');
    if (currentUrl) URL.revokeObjectURL(currentUrl);
    currentUrl = undefined;

    const file = input.files[0];
    if (!file || file.size > 5 * 1024 * 1024) return;
    if (file.type && !supportedTypes.includes(file.type)) return;

    const url = URL.createObjectURL(file);
    currentUrl = url;
    preview.src = url;
    try {
      await preview.decode();
      if (currentUrl === url) preview.hidden = false;
    } catch {
      if (currentUrl !== url) return;
      preview.removeAttribute('src');
      URL.revokeObjectURL(url);
      currentUrl = undefined;
    }
  });
})();
