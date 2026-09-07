(function () {
  'use strict';

  const ENDPOINT = '/api/application/settings/view';
  const DEFAULTS = Object.freeze({
    show_tiles: true,
    show_learn_more: true
  });

  let state = { ...DEFAULTS };
  let saveInFlight = false;

  function normalizeView(raw) {
    const source = raw && typeof raw === 'object' ? raw : {};
    return {
      show_tiles: typeof source.show_tiles === 'boolean'
        ? source.show_tiles
        : DEFAULTS.show_tiles,
      show_learn_more: typeof source.show_learn_more === 'boolean'
        ? source.show_learn_more
        : DEFAULTS.show_learn_more
    };
  }

  function applyView(nextState) {
    state = normalizeView(nextState);

    document.documentElement.dataset.viewTiles =
      state.show_tiles ? 'visible' : 'hidden';
    document.documentElement.dataset.viewLearnMore =
      state.show_learn_more ? 'visible' : 'hidden';

    document.querySelectorAll('[data-application-view-setting]').forEach((control) => {
      const key = control.dataset.applicationViewSetting;
      if (!Object.prototype.hasOwnProperty.call(state, key)) return;

      const checked = Boolean(state[key]);
      control.setAttribute('aria-checked', checked ? 'true' : 'false');

      const check = control.querySelector('[data-application-view-check]');
      if (check) {
        check.textContent = checked ? '\u2713' : '';
      }
    });

    document.dispatchEvent(new CustomEvent('italus:applicationviewchange', {
      detail: { ...state }
    }));
  }

  async function apiFetch(url, options) {
    const response = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options
    });

    if (!response.ok) {
      let detail = `HTTP ${response.status}`;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch (_) {
        // Keep the HTTP status when the backend response is not JSON.
      }
      throw new Error(detail);
    }

    return response.json();
  }

  async function loadViewSettings() {
    try {
      const response = await apiFetch(ENDPOINT, { method: 'GET' });
      applyView(response.view);
    } catch (error) {
      applyView(DEFAULTS);
      console.error('Application view settings could not be loaded.', error);
    }
  }

  async function toggleSetting(key, control) {
    if (saveInFlight || !Object.prototype.hasOwnProperty.call(state, key)) return;

    const previous = { ...state };
    const next = { ...state, [key]: !state[key] };

    saveInFlight = true;
    if (control) control.disabled = true;
    applyView(next);

    try {
      const response = await apiFetch(ENDPOINT, {
        method: 'PUT',
        body: JSON.stringify({ [key]: next[key] })
      });
      applyView(response.view);
    } catch (error) {
      applyView(previous);
      console.error('Application view settings could not be saved.', error);
      window.alert(`Application Settings could not be saved. ${error.message}`);
    } finally {
      saveInFlight = false;
      if (control) control.disabled = false;
    }
  }

  function bindControls() {
    document.addEventListener('click', (event) => {
      const control = event.target.closest('[data-application-view-setting]');
      if (!control) return;

      event.preventDefault();
      event.stopPropagation();
      toggleSetting(control.dataset.applicationViewSetting, control);
    });
  }

  function init() {
    applyView(DEFAULTS);
    bindControls();
    loadViewSettings();
  }

  window.ItalusApplicationSettings = {
    endpoint: ENDPOINT,
    getView: () => ({ ...state }),
    reload: loadViewSettings
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
