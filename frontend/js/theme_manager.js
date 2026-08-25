(function () {
  'use strict';

  const STORAGE_KEY = 'italus.theme';
  const DEFAULT_THEME = 'original';
  const PICKER_VERSION_KEY = 'italus.theme.pickerVersion';
  const PICKER_VERSION = 'v1.9-fantasy';
  const THEMES = Object.freeze({
    original: { id: 'original', label: 'Original', description: 'The classic Italus library and leather-desk studio.', isDefault: true },
    'sci-fi': { id: 'sci-fi', label: 'Sci-Fi', description: 'A neon blue and violet futuristic studio overlooking a night city and deep space.', isDefault: false },
    mystery: { id: 'mystery', label: 'Mystery', description: 'A dark, atmospheric writing skin inspired by detective fiction, lamplit desks, and literary suspense.', isDefault: false },
    fantasy: { id: 'fantasy', label: 'Fantasy', description: 'An enchanted author studio of deep indigo, arcane purple, luminous blue, emerald, and moonlit silver.', isDefault: false }
  });

  function normalizeTheme(value) {
    const key = String(value || '').trim().toLowerCase();
    return Object.prototype.hasOwnProperty.call(THEMES, key) ? key : DEFAULT_THEME;
  }

  function storedTheme() {
    try {
      return normalizeTheme(window.localStorage.getItem(STORAGE_KEY));
    } catch (_) {
      return DEFAULT_THEME;
    }
  }

  function currentTheme() {
    return normalizeTheme(document.documentElement.dataset.theme || storedTheme());
  }

  function persistTheme(themeId) {
    try {
      window.localStorage.setItem(STORAGE_KEY, themeId);
      window.localStorage.setItem(PICKER_VERSION_KEY, PICKER_VERSION);
    } catch (_) {
      // Preference persistence is best-effort. The live theme still applies.
    }
  }

  function syncControls(themeId) {
    const active = normalizeTheme(themeId);

    document.querySelectorAll('[data-theme-option]').forEach((control) => {
      const selected = normalizeTheme(control.dataset.themeOption) === active;
      control.classList.toggle('theme-option-card--selected', selected);
      control.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });

    document.querySelectorAll('[data-theme-current-label]').forEach((node) => {
      node.textContent = THEMES[active].label;
    });

    document.querySelectorAll('[data-theme-current-description]').forEach((node) => {
      node.textContent = THEMES[active].description;
    });

    document.querySelectorAll('[data-theme-selection-status]').forEach((node) => {
      node.textContent = active === DEFAULT_THEME
        ? 'Original is active. This is the default skin. Changes apply immediately.'
        : `${THEMES[active].label} is active. This preference is remembered in this browser. Original remains the default skin.`;
    });
  }

  function applyTheme(themeId, options) {
    const active = normalizeTheme(themeId);
    document.documentElement.dataset.theme = active;
    if (document.body) document.body.dataset.theme = active;
    if (!options || options.persist !== false) persistTheme(active);
    syncControls(active);

    document.dispatchEvent(new CustomEvent('italus:themechange', {
      detail: { theme: active, label: THEMES[active].label }
    }));
    return active;
  }

  function openLandingThemeSettings() {
    const layer = document.getElementById('studio-modal-layer');
    const modal = document.getElementById('theme-settings-modal');
    if (!layer || !modal) return;

    if (window.ItalusProjectLifecycle && typeof window.ItalusProjectLifecycle.closeAllModals === 'function') {
      window.ItalusProjectLifecycle.closeAllModals();
    } else {
      layer.querySelectorAll('.studio-modal').forEach((item) => { item.hidden = true; });
    }

    layer.setAttribute('aria-hidden', 'false');
    modal.hidden = false;
    document.body.classList.add('modal-open');
    syncControls(currentTheme());

    const selected = modal.querySelector('.theme-option-card--selected') || modal.querySelector('[data-theme-option]');
    if (selected) selected.focus();
  }

  function bindDelegatedControls() {
    document.addEventListener('click', (event) => {
      const openControl = event.target.closest('[data-theme-settings-open]');
      if (openControl) {
        event.preventDefault();
        openLandingThemeSettings();
        return;
      }

      const themeControl = event.target.closest('[data-theme-option]');
      if (!themeControl) return;

      event.preventDefault();
      applyTheme(themeControl.dataset.themeOption);
    });
  }

  function init() {
    applyTheme(currentTheme(), { persist: false });
    bindDelegatedControls();
  }

  window.addEventListener('storage', (event) => {
    if (event.key === STORAGE_KEY) {
      applyTheme(event.newValue, { persist: false });
    }
  });

  window.ItalusTheme = {
    STORAGE_KEY,
    THEMES,
    DEFAULT_THEME,
    PICKER_VERSION_KEY,
    PICKER_VERSION,
    getTheme: currentTheme,
    setTheme: applyTheme,
    syncControls,
    openSettings: openLandingThemeSettings
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
