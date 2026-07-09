(function () {
  "use strict";

  const cards = document.querySelectorAll("[data-tilt]");
  const maxTilt = 7;

  function setTilt(card, event) {
    const rect = card.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const px = x / rect.width;
    const py = y / rect.height;
    const rotateY = (px - 0.5) * maxTilt * 2;
    const rotateX = (0.5 - py) * maxTilt * 2;

    card.style.setProperty("--rx", rotateX.toFixed(2) + "deg");
    card.style.setProperty("--ry", rotateY.toFixed(2) + "deg");
    card.style.setProperty("--mx", (px * 100).toFixed(1) + "%");
    card.style.setProperty("--my", (py * 100).toFixed(1) + "%");
  }

  function resetTilt(card) {
    card.style.setProperty("--rx", "0deg");
    card.style.setProperty("--ry", "0deg");
    card.style.setProperty("--mx", "50%");
    card.style.setProperty("--my", "0%");
  }

  cards.forEach((card) => {
    card.addEventListener("pointermove", (event) => setTilt(card, event));
    card.addEventListener("pointerleave", () => resetTilt(card));
    card.addEventListener("blur", () => resetTilt(card));
  });
})();
