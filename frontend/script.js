(function () {
  const tiles = document.querySelectorAll('.project-tile');

  tiles.forEach((tile, index) => {
    tile.style.animationDelay = `${index * 0.35}s`;
    const img = tile.querySelector('img');
    if (img) img.style.animationDelay = `${index * 0.35}s`;

    tile.addEventListener('mousemove', (event) => {
      const rect = tile.getBoundingClientRect();
      const x = (event.clientX - rect.left) / rect.width - 0.5;
      const y = (event.clientY - rect.top) / rect.height - 0.5;

      tile.style.setProperty('--rx', `${(-y * 5).toFixed(2)}deg`);
      tile.style.setProperty('--ry', `${(x * 5).toFixed(2)}deg`);
    });

    tile.addEventListener('mouseleave', () => {
      tile.style.setProperty('--rx', '0deg');
      tile.style.setProperty('--ry', '0deg');
    });
  });

  // Intentionally no wheel/keyboard zoom interception.
})();
