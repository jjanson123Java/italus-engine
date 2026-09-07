(function () {
  'use strict';

  const ENDPOINT = '/api/application/author-profile';
  const MODAL_ID = 'author-profile-modal';
  const LAYER_ID = 'studio-modal-layer';

  const PROFILE_FIELDS = Object.freeze([
    'professional_name',
    'profession_niche',
    'featured_work',
    'genre_mission',
    'standard_bio',
    'short_bio',
    'credentials_achievements',
    'expertise_background',
    'humanizing_detail',
    'location',
    'professional_email',
    'website',
    'newsletter_url',
    'cta',
    'x_url',
    'instagram_url',
    'tiktok_url',
    'linkedin_url'
  ]);

  let baseline = '';
  let dirty = false;
  let saveInFlight = false;
  let loadSequence = 0;

  function getModal() {
    return document.getElementById(MODAL_ID);
  }

  function getLayer() {
    return document.getElementById(LAYER_ID);
  }

  function getForm() {
    return document.getElementById('author-profile-form');
  }

  function getStatus() {
    return document.getElementById('author-profile-status');
  }

  function getUnsavedPanel() {
    return document.getElementById('author-profile-unsaved');
  }

  function emptyProfile() {
    const profile = {};
    PROFILE_FIELDS.forEach((fieldName) => {
      profile[fieldName] = '';
    });
    return profile;
  }

  function normalizeProfile(raw) {
    const source = raw && typeof raw === 'object' ? raw : {};
    const profile = emptyProfile();
    PROFILE_FIELDS.forEach((fieldName) => {
      profile[fieldName] = typeof source[fieldName] === 'string'
        ? source[fieldName]
        : '';
    });
    return profile;
  }

  function setStatus(message, kind) {
    const status = getStatus();
    if (!status) return;

    status.textContent = message || '';
    status.dataset.kind = kind || 'neutral';
  }

  function setFormEnabled(enabled) {
    const form = getForm();
    if (!form) return;

    form.querySelectorAll('input, textarea').forEach((field) => {
      field.disabled = !enabled;
    });

    const saveButton = form.querySelector('[data-author-profile-save]');
    if (saveButton) {
      saveButton.disabled = !enabled || saveInFlight;
    }
  }

  function populateForm(profile) {
    const form = getForm();
    if (!form) return;

    const normalized = normalizeProfile(profile);
    PROFILE_FIELDS.forEach((fieldName) => {
      const field = form.elements.namedItem(fieldName);
      if (field) {
        field.value = normalized[fieldName];
      }
    });
  }

  function collectForm() {
    const form = getForm();
    const profile = emptyProfile();
    if (!form) return profile;

    PROFILE_FIELDS.forEach((fieldName) => {
      const field = form.elements.namedItem(fieldName);
      profile[fieldName] = field ? String(field.value || '') : '';
    });
    return profile;
  }

  function fingerprint(profile) {
    const normalized = normalizeProfile(profile);
    return JSON.stringify(normalized);
  }

  function syncDirtyState() {
    dirty = fingerprint(collectForm()) !== baseline;
    const modal = getModal();
    if (modal) {
      modal.dataset.dirty = dirty ? 'true' : 'false';
    }

    if (!dirty) {
      hideUnsavedPanel();
    }
  }

  function hideUnsavedPanel() {
    const panel = getUnsavedPanel();
    if (panel) panel.hidden = true;
  }

  function showUnsavedPanel() {
    const panel = getUnsavedPanel();
    if (!panel) return;

    panel.hidden = false;
    const keepEditing = panel.querySelector('[data-author-profile-keep-editing]');
    if (keepEditing) keepEditing.focus();
  }

  function closeModalNow() {
    dirty = false;
    hideUnsavedPanel();

    if (
      window.ItalusProjectLifecycle
      && typeof window.ItalusProjectLifecycle.closeAllModals === 'function'
    ) {
      window.ItalusProjectLifecycle.closeAllModals();
      return;
    }

    const layer = getLayer();
    const modal = getModal();
    if (modal) modal.hidden = true;
    if (layer) layer.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('modal-open');
  }

  function requestExplicitClose() {
    if (saveInFlight) return;

    if (dirty) {
      showUnsavedPanel();
      return;
    }
    closeModalNow();
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
        // Preserve the HTTP status when the backend response is not JSON.
      }
      throw new Error(detail);
    }

    return response.json();
  }

  async function loadProfile() {
    const sequence = ++loadSequence;
    setFormEnabled(false);
    setStatus('Loading author profile...', 'neutral');

    try {
      const response = await apiFetch(ENDPOINT, { method: 'GET' });
      if (sequence !== loadSequence) return;

      const profile = normalizeProfile(response.profile);
      populateForm(profile);
      baseline = fingerprint(profile);
      dirty = false;

      const modal = getModal();
      if (modal) modal.dataset.dirty = 'false';

      setStatus('Profile loaded. Changes are saved only when you choose Save Profile.', 'success');
      setFormEnabled(true);

      const firstField = getForm()
        ? getForm().querySelector('input, textarea')
        : null;
      if (firstField) firstField.focus();
    } catch (error) {
      if (sequence !== loadSequence) return;

      baseline = '';
      dirty = false;
      setStatus(
        `Author profile could not be loaded. No changes can be saved until the profile is available. ${error.message}`,
        'error'
      );
      setFormEnabled(false);
    }
  }

  async function saveProfile(event) {
    event.preventDefault();
    if (saveInFlight) return;

    const form = getForm();
    const saveButton = form
      ? form.querySelector('[data-author-profile-save]')
      : null;

    saveInFlight = true;
    if (saveButton) saveButton.disabled = true;
    hideUnsavedPanel();
    setStatus('Saving author profile...', 'neutral');

    try {
      const response = await apiFetch(ENDPOINT, {
        method: 'PUT',
        body: JSON.stringify(collectForm())
      });
      const profile = normalizeProfile(response.profile);
      populateForm(profile);
      baseline = fingerprint(profile);
      dirty = false;

      const modal = getModal();
      if (modal) modal.dataset.dirty = 'false';

      setStatus('Author profile saved.', 'success');
      closeModalNow();
    } catch (error) {
      setStatus(`Author profile could not be saved. ${error.message}`, 'error');
      setFormEnabled(true);
    } finally {
      saveInFlight = false;
      if (saveButton && !saveButton.disabled) {
        saveButton.disabled = false;
      } else if (saveButton) {
        saveButton.disabled = false;
      }
    }
  }

  function openModalShell() {
    const layer = getLayer();
    const modal = getModal();
    if (!layer || !modal) return false;

    if (
      window.ItalusProjectLifecycle
      && typeof window.ItalusProjectLifecycle.closeAllModals === 'function'
    ) {
      window.ItalusProjectLifecycle.closeAllModals();
    } else {
      layer.querySelectorAll('.studio-modal').forEach((item) => {
        item.hidden = true;
      });
    }

    layer.setAttribute('aria-hidden', 'false');
    modal.hidden = false;
    document.body.classList.add('modal-open');
    hideUnsavedPanel();
    return true;
  }

  function openAuthorProfile() {
    if (!openModalShell()) return;
    loadProfile();
  }

  function bindOpenControl() {
    document.addEventListener('click', (event) => {
      const control = event.target.closest('[data-author-profile-open]');
      if (!control) return;

      event.preventDefault();
      event.stopPropagation();
      openAuthorProfile();
    });
  }

  function bindForm() {
    const form = getForm();
    const modal = getModal();
    if (!form || !modal) return;

    form.addEventListener('input', syncDirtyState);
    form.addEventListener('submit', saveProfile);

    modal.querySelectorAll('[data-author-profile-close]').forEach((control) => {
      control.addEventListener('click', requestExplicitClose);
    });

    const discard = modal.querySelector('[data-author-profile-discard]');
    if (discard) {
      discard.addEventListener('click', () => {
        dirty = false;
        closeModalNow();
      });
    }

    const keepEditing = modal.querySelector('[data-author-profile-keep-editing]');
    if (keepEditing) {
      keepEditing.addEventListener('click', () => {
        hideUnsavedPanel();
        const firstField = form.querySelector('input, textarea');
        if (firstField) firstField.focus();
      });
    }

    modal.addEventListener('italus:modal-close-request', (event) => {
      const reason = event.detail && event.detail.reason;
      if (reason !== 'escape') return;

      if (saveInFlight || dirty) {
        event.preventDefault();
        if (dirty) showUnsavedPanel();
      }
    });
  }

  function init() {
    bindOpenControl();
    bindForm();
  }

  window.ItalusAuthorProfile = {
    endpoint: ENDPOINT,
    open: openAuthorProfile,
    reload: loadProfile
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
