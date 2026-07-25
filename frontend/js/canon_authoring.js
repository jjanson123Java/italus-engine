/*
Canon Workbook section editor.

This module renders project-local canon authoring status and a controlled
section editor inside the existing Canon Setup modal. It saves only author
canon draft data through the canon authoring API boundary.

It can request project-local Markdown rendering for completed canon sections.
It does not generate knowledge packs, call providers, call prompt construction,
write runtime memory, or unlock generation.
*/
(function () {
  const AUTHORING_ROUTE_SUFFIX = '/canon/authoring';
  const MARKDOWN_STATUS_ROUTE_SUFFIX = '/canon/markdown';
  const MARKDOWN_RENDER_ROUTE_SUFFIX = '/canon/markdown/render';
  const TARGET_STATE = new Map();

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function number(value) {
    const parsed = Number(value || 0);
    return Number.isFinite(parsed) ? parsed.toLocaleString() : '0';
  }

  function normalizeStatus(value) {
    return String(value || 'not_started').trim() || 'not_started';
  }

  function sectionStatusLabel(section) {
    return normalizeStatus(section && section.status).replaceAll('_', ' ').toUpperCase();
  }

  function sectionStatusClass(section) {
    const status = normalizeStatus(section && section.status);
    if (status === 'complete') return 'canon-file-detected';
    if (status === 'blocked') return 'canon-file-missing';
    if (status === 'draft' || status === 'in_progress') return 'setup-note';
    return 'setup-note';
  }

  function apiBase(projectId) {
    if (!projectId) {
      throw new Error('Project ID is required to use Canon Workbook authoring.');
    }
    return `/api/project/${encodeURIComponent(projectId)}`;
  }

  async function readJsonResponse(response, fallbackMessage) {
    const text = await response.text();
    let payload = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        throw new Error('Invalid Canon Workbook response.');
      }
    }

    if (!response.ok) {
      throw new Error(payload.detail || response.statusText || fallbackMessage || 'Canon Workbook request failed.');
    }

    return payload;
  }

  async function apiGet(projectId, suffix) {
    const response = await fetch(`${apiBase(projectId)}${suffix}`, {
      method: 'GET',
      headers: { Accept: 'application/json' }
    });
    return readJsonResponse(response, 'Canon Workbook request failed.');
  }

  async function apiPost(projectId, suffix, payload) {
    const options = {
      method: 'POST',
      headers: { Accept: 'application/json' }
    };

    if (payload !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(payload);
    }

    const response = await fetch(`${apiBase(projectId)}${suffix}`, options);
    return readJsonResponse(response, 'Canon Workbook update failed.');
  }

  function renderError(target, message) {
    target.innerHTML = `
      <article class="canon-group-card" data-status="ERROR">
        <header>
          <h3>Canon Workbook</h3>
          <span>LOCKED</span>
        </header>
        <p>${escapeHtml(message || 'Canon Workbook status could not be loaded.')}</p>
      </article>
    `;
  }

  function renderLoading(target) {
    target.innerHTML = `
      <article class="canon-group-card" data-status="LOADING">
        <header>
          <h3>Canon Workbook</h3>
          <span>AUTHORING</span>
        </header>
        <p class="setup-note">Loading project-local canon authoring status...</p>
      </article>
    `;
  }

  function renderMessage(message, tone) {
    if (!message) return '';
    const className = tone === 'error' ? 'canon-file-missing' : 'setup-note';
    return `<p class="${className}" data-canon-editor-message>${escapeHtml(message)}</p>`;
  }

  function renderSectionCard(section) {
    const missing = Array.isArray(section.missing_required_fields)
      ? section.missing_required_fields
      : [];
    const required = section.required ? 'Required' : 'Optional';
    const fieldCount = Number(section.field_count || 0);
    const recordCount = Number(section.record_count || section.record_group_count || 0);
    const label = section.label || section.section_id || 'Canon section';
    const status = sectionStatusLabel(section);
    const sectionId = section.section_id || '';

    return `
      <article class="canon-item-card" data-status="${escapeHtml(section.status || 'not_started')}" data-section-id="${escapeHtml(sectionId)}">
        <div>
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(required)} - ${escapeHtml(status)} - ${number(fieldCount)} fields - ${number(recordCount)} record groups</span>
        </div>
        <p class="${sectionStatusClass(section)}">
          ${missing.length
            ? `${number(missing.length)} required fields missing: ${missing.map(escapeHtml).join(', ')}`
            : 'No required field blockers reported.'}
        </p>
        <button type="button" class="secondary" data-canon-open-section="${escapeHtml(sectionId)}">Open Section</button>
      </article>
    `;
  }


  function markdownFileListHtml(files) {
    if (!Array.isArray(files) || !files.length) {
      return '<p class="setup-note">No rendered canon source files detected yet.</p>';
    }

    return `
      <ul class="canon-item-list">
        ${files.map((file) => `
          <li class="canon-item-card">
            <strong>${escapeHtml(file.filename || file.path || 'canon source')}</strong>
            <span>${escapeHtml(file.section_id || '')}</span>
            ${file.path ? `<small>${escapeHtml(file.path)}</small>` : ''}
          </li>
        `).join('')}
      </ul>
    `;
  }

  function renderMarkdownStatusPanel(markdownStatus) {
    const status = markdownStatus && typeof markdownStatus === 'object' ? markdownStatus : {};
    const renderedCount = Number(status.rendered_file_count || 0);
    const completedCount = Number(status.completed_section_count || 0);
    const files = Array.isArray(status.rendered_files) ? status.rendered_files : [];
    const sourceDir = status.canon_sources_dir || 'data/projects/<project_id>/canon/canon_sources';

    return `
      <article class="canon-group-card" data-canon-markdown-status data-status="${renderedCount ? 'READY' : 'LOCKED'}">
        <header>
          <h3>Canon Markdown Sources</h3>
          <span>${renderedCount ? 'SOURCES RENDERED' : 'READY TO RENDER'}</span>
        </header>
        <p class="setup-note">
          Completed canon sections can be rendered into project-local Markdown sources.
          This does not generate packets, call providers, or unlock generation.
        </p>
        <dl>
          <div><dt>Completed Sections</dt><dd>${number(completedCount)}</dd></div>
          <div><dt>Rendered Files</dt><dd>${number(renderedCount)}</dd></div>
          <div><dt>Output Directory</dt><dd>${escapeHtml(sourceDir)}</dd></div>
        </dl>
        <div class="wizard-actions">
          <button type="button" class="secondary" data-canon-render-all-markdown>
            Render Completed Sections
          </button>
        </div>
        ${markdownFileListHtml(files)}
      </article>
    `;
  }

  function renderAuthoringStatus(target, payload, selectedSectionHtml) {
    const state = TARGET_STATE.get(target.id || 'canon-workbook-shell') || {};
    const markdownStatus = state.lastMarkdownStatus || {};
    const sections = Array.isArray(payload.sections) ? payload.sections : [];
    const required = Number(payload.required_section_count || 0);
    const complete = Number(payload.completed_required_section_count || 0);
    const allComplete = Boolean(payload.all_required_sections_complete);

    target.innerHTML = `
      <article class="canon-group-card" data-status="${allComplete ? 'READY' : 'LOCKED'}">
        <header>
          <h3>Canon Workbook</h3>
          <span>${allComplete ? 'READY' : 'AUTHORING REQUIRED'}</span>
        </header>
        <p class="setup-note">
          Project-local canon authoring is active. This editor saves only section drafts and completion status.
          Generation remains locked until canon rendering, validation, draft review, and approved persistence boundaries exist.
        </p>
        <dl>
          <div><dt>Template</dt><dd>${escapeHtml(payload.template_id || '-')}</dd></div>
          <div><dt>Genre</dt><dd>${escapeHtml(payload.genre || '-')}</dd></div>
          <div><dt>Sections</dt><dd>${number(payload.section_count)} total</dd></div>
          <div><dt>Required Complete</dt><dd>${number(complete)} / ${number(required)}</dd></div>
        </dl>
      </article>
      ${renderMarkdownStatusPanel(markdownStatus)}
      <div class="canon-item-list" aria-label="Canon Workbook Sections">
        ${sections.length ? sections.map(renderSectionCard).join('') : '<p class="setup-note">No canon questionnaire sections were returned.</p>'}
      </div>
      <section class="canon-group-card" data-canon-section-editor aria-label="Canon Section Editor">
        ${selectedSectionHtml || '<p class="setup-note">Open a section to edit project-local author canon answers.</p>'}
      </section>
    `;
  }

  function fieldInputHtml(field, value) {
    const fieldId = field.field_id || '';
    const label = field.label || fieldId || 'Field';
    const type = field.field_type || 'long_text';
    const required = Boolean(field.required);
    const help = field.help_text ? `<p class="setup-note">${escapeHtml(field.help_text)}</p>` : '';
    const placeholder = field.placeholder || '';
    const name = `canon-field-${fieldId}`;

    if (type === 'boolean') {
      return `
        <label class="canon-field-row">
          <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
          <input type="checkbox" data-canon-field-id="${escapeHtml(fieldId)}" ${value ? 'checked' : ''}>
        </label>
        ${help}
      `;
    }

    if (type === 'select') {
      const options = Array.isArray(field.options) ? field.options : [];
      return `
        <label class="canon-field-row">
          <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
          <select name="${escapeHtml(name)}" data-canon-field-id="${escapeHtml(fieldId)}">
            <option value="">Select...</option>
            ${options.map((option) => `
              <option value="${escapeHtml(option)}" ${String(value || '') === String(option) ? 'selected' : ''}>${escapeHtml(option)}</option>
            `).join('')}
          </select>
        </label>
        ${help}
      `;
    }

    if (type === 'multi_select') {
      const selected = Array.isArray(value) ? value.map(String) : [];
      const options = Array.isArray(field.options) ? field.options : [];
      return `
        <label class="canon-field-row">
          <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
          <select name="${escapeHtml(name)}" data-canon-field-id="${escapeHtml(fieldId)}" multiple>
            ${options.map((option) => `
              <option value="${escapeHtml(option)}" ${selected.includes(String(option)) ? 'selected' : ''}>${escapeHtml(option)}</option>
            `).join('')}
          </select>
        </label>
        ${help}
      `;
    }

    if (type === 'short_text') {
      return `
        <label class="canon-field-row">
          <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
          <input type="text" name="${escapeHtml(name)}" data-canon-field-id="${escapeHtml(fieldId)}" value="${escapeHtml(value || '')}" placeholder="${escapeHtml(placeholder)}">
        </label>
        ${help}
      `;
    }

    return `
      <label class="canon-field-row">
        <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
        <textarea name="${escapeHtml(name)}" data-canon-field-id="${escapeHtml(fieldId)}" rows="${type === 'rich_text' ? '8' : '4'}" placeholder="${escapeHtml(placeholder)}">${escapeHtml(value || '')}</textarea>
      </label>
      ${help}
    `;
  }

  function recordFieldInputHtml(recordId, index, field, value) {
    const fieldId = field.field_id || '';
    const label = field.label || fieldId || 'Record field';
    const type = field.field_type || 'long_text';
    const required = Boolean(field.required);
    const dataAttrs = `data-canon-record-field-id="${escapeHtml(fieldId)}" data-canon-record-id="${escapeHtml(recordId)}" data-canon-record-index="${escapeHtml(index)}"`;

    if (type === 'boolean') {
      return `
        <label class="canon-field-row">
          <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
          <input type="checkbox" ${dataAttrs} ${value ? 'checked' : ''}>
        </label>
      `;
    }

    if (type === 'short_text' || type === 'select') {
      return `
        <label class="canon-field-row">
          <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
          <input type="text" ${dataAttrs} value="${escapeHtml(value || '')}">
        </label>
      `;
    }

    return `
      <label class="canon-field-row">
        <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
        <textarea ${dataAttrs} rows="${type === 'rich_text' ? '6' : '3'}">${escapeHtml(value || '')}</textarea>
      </label>
    `;
  }

  function renderRecordGroup(record, storedItems) {
    const recordId = record.record_id || '';
    const items = Array.isArray(storedItems) && storedItems.length ? storedItems : [{}];
    const fields = Array.isArray(record.fields) ? record.fields : [];
    const minItems = Number(record.min_items || 0);
    const help = record.help_text ? `<p class="setup-note">${escapeHtml(record.help_text)}</p>` : '';

    return `
      <fieldset class="canon-record-group" data-canon-record-id="${escapeHtml(recordId)}">
        <legend>${escapeHtml(record.label || recordId || 'Record group')}${record.required ? ' *' : ''}</legend>
        ${help}
        <p class="setup-note">Minimum entries: ${number(minItems)}</p>
        <div data-canon-record-items="${escapeHtml(recordId)}">
          ${items.map((item, index) => `
            <article class="canon-item-card" data-canon-record-item="${escapeHtml(recordId)}" data-canon-record-index="${escapeHtml(index)}">
              <header>
                <strong>${escapeHtml(record.label || 'Record')} ${number(index + 1)}</strong>
                <button type="button" class="secondary" data-canon-remove-record="${escapeHtml(recordId)}" data-canon-record-index="${escapeHtml(index)}">Remove</button>
              </header>
              ${fields.map((field) => recordFieldInputHtml(recordId, index, field, item ? item[field.field_id] : '')).join('')}
            </article>
          `).join('')}
        </div>
        <button type="button" class="secondary" data-canon-add-record="${escapeHtml(recordId)}">Add ${escapeHtml(record.label || 'Record')}</button>
      </fieldset>
    `;
  }

  function renderSectionEditor(payload, message, tone) {
    const section = payload.section || {};
    const schema = section.schema || {};
    const data = section.data || {};
    const completion = section.completion || {};
    const answers = data.answers && typeof data.answers === 'object' ? data.answers : {};
    const records = data.records && typeof data.records === 'object' ? data.records : {};
    const fields = Array.isArray(schema.fields) ? schema.fields : [];
    const recordGroups = Array.isArray(schema.records) ? schema.records : [];
    const missing = Array.isArray(completion.missing_required_fields) ? completion.missing_required_fields : [];
    const status = normalizeStatus(completion.status || data.status);

    return `
      <header>
        <div>
          <h3>${escapeHtml(schema.label || schema.section_id || 'Canon Section')}</h3>
          <p class="setup-note">${escapeHtml(schema.purpose || schema.author_guidance || 'Edit project-local author canon answers.')}</p>
        </div>
        <span>${escapeHtml(status.replaceAll('_', ' ').toUpperCase())}</span>
      </header>
      ${schema.author_guidance ? `<p class="setup-note">${escapeHtml(schema.author_guidance)}</p>` : ''}
      ${renderMessage(message, tone)}
      ${missing.length ? `<p class="canon-file-missing">Missing required fields: ${missing.map(escapeHtml).join(', ')}</p>` : ''}
      <form data-canon-section-form="${escapeHtml(schema.section_id || '')}">
        <input type="hidden" data-canon-current-section value="${escapeHtml(schema.section_id || '')}">
        ${fields.map((field) => fieldInputHtml(field, answers[field.field_id])).join('')}
        ${recordGroups.map((record) => renderRecordGroup(record, records[record.record_id])).join('')}
        <div class="wizard-actions">
          <button type="submit" data-canon-save-section="${escapeHtml(schema.section_id || '')}">Save Draft</button>
          ${status === 'complete'
            ? `<button type="button" class="secondary" data-canon-reopen-section="${escapeHtml(schema.section_id || '')}">Reopen Section</button>
               <button type="button" class="secondary" data-canon-render-section-markdown="${escapeHtml(schema.section_id || '')}">Render Section Markdown</button>`
            : `<button type="button" class="secondary" data-canon-complete-section="${escapeHtml(schema.section_id || '')}">Mark Complete</button>`}
        </div>
      </form>
    `;
  }

  async function loadCanonAuthoringStatus(projectId) {
    return apiGet(projectId, AUTHORING_ROUTE_SUFFIX);
  }

  async function loadCanonMarkdownStatus(projectId) {
    return apiGet(projectId, MARKDOWN_STATUS_ROUTE_SUFFIX);
  }

  async function renderCompletedCanonSources(projectId) {
    return apiPost(projectId, MARKDOWN_RENDER_ROUTE_SUFFIX);
  }

  async function renderCanonSectionMarkdown(projectId, sectionId) {
    return apiPost(projectId, `/canon/markdown/section/${encodeURIComponent(sectionId)}`);
  }

  async function loadCanonSection(projectId, sectionId) {
    return apiGet(projectId, `/canon/section/${encodeURIComponent(sectionId)}`);
  }

  async function saveCanonSectionDraft(projectId, sectionId, payload) {
    return apiPost(projectId, `/canon/section/${encodeURIComponent(sectionId)}`, payload);
  }

  async function completeCanonSection(projectId, sectionId) {
    return apiPost(projectId, `/canon/section/${encodeURIComponent(sectionId)}/complete`);
  }

  async function reopenCanonSection(projectId, sectionId) {
    return apiPost(projectId, `/canon/section/${encodeURIComponent(sectionId)}/reopen`);
  }

  function ensureTargetState(target, config) {
    const targetId = target.id || 'canon-workbook-shell';
    const current = TARGET_STATE.get(targetId) || {};
    const next = Object.assign({}, current, config || {}, { targetId });
    TARGET_STATE.set(targetId, next);
    return next;
  }

  function collectFormPayload(form) {
    const answers = {};
    const records = {};

    form.querySelectorAll('[data-canon-field-id]').forEach((field) => {
      const fieldId = field.getAttribute('data-canon-field-id');
      if (!fieldId) return;
      if (field instanceof HTMLInputElement && field.type === 'checkbox') {
        answers[fieldId] = field.checked;
      } else if (field instanceof HTMLSelectElement && field.multiple) {
        answers[fieldId] = Array.from(field.selectedOptions).map((option) => option.value);
      } else {
        answers[fieldId] = field.value || '';
      }
    });

    form.querySelectorAll('[data-canon-record-field-id]').forEach((field) => {
      const recordId = field.getAttribute('data-canon-record-id');
      const fieldId = field.getAttribute('data-canon-record-field-id');
      const index = Number(field.getAttribute('data-canon-record-index') || 0);
      if (!recordId || !fieldId || !Number.isFinite(index)) return;

      if (!records[recordId]) records[recordId] = [];
      if (!records[recordId][index]) records[recordId][index] = {};

      if (field instanceof HTMLInputElement && field.type === 'checkbox') {
        records[recordId][index][fieldId] = field.checked;
      } else {
        records[recordId][index][fieldId] = field.value || '';
      }
    });

    Object.keys(records).forEach((recordId) => {
      records[recordId] = records[recordId].filter((item) => item && Object.keys(item).length);
    });

    return { answers, records };
  }

  function cloneRecordItem(recordGroup) {
    const itemsContainer = recordGroup.querySelector('[data-canon-record-items]');
    const firstItem = recordGroup.querySelector('[data-canon-record-item]');
    if (!itemsContainer || !firstItem) return;

    const recordId = recordGroup.getAttribute('data-canon-record-id') || '';
    const nextIndex = itemsContainer.querySelectorAll('[data-canon-record-item]').length;
    const clone = firstItem.cloneNode(true);

    clone.setAttribute('data-canon-record-index', String(nextIndex));
    clone.querySelectorAll('[data-canon-record-index]').forEach((node) => {
      node.setAttribute('data-canon-record-index', String(nextIndex));
    });
    clone.querySelectorAll('input, textarea, select').forEach((field) => {
      if (field instanceof HTMLInputElement && field.type === 'checkbox') {
        field.checked = false;
      } else {
        field.value = '';
      }
    });
    const heading = clone.querySelector('strong');
    if (heading) {
      heading.textContent = `${recordId || 'Record'} ${nextIndex + 1}`;
    }

    itemsContainer.appendChild(clone);
  }

  function removeRecordItem(button) {
    const item = button.closest('[data-canon-record-item]');
    const group = button.closest('[data-canon-record-group]');
    if (!item || !group) return;
    const items = group.querySelectorAll('[data-canon-record-item]');
    if (items.length <= 1) {
      item.querySelectorAll('input, textarea, select').forEach((field) => {
        if (field instanceof HTMLInputElement && field.type === 'checkbox') {
          field.checked = false;
        } else {
          field.value = '';
        }
      });
      return;
    }
    item.remove();
  }

  async function refreshWorkbook(target, state, selectedSectionId, selectedHtml) {
    const status = await loadCanonAuthoringStatus(state.projectId);
    state.lastStatus = status;
    try {
      state.lastMarkdownStatus = await loadCanonMarkdownStatus(state.projectId);
    } catch (error) {
      state.lastMarkdownStatus = {
        status: 'unavailable',
        rendered_file_count: 0,
        completed_section_count: 0,
        rendered_files: [],
        message: error && error.message ? error.message : 'Markdown status unavailable.'
      };
    }
    state.selectedSectionId = selectedSectionId || state.selectedSectionId || null;
    renderAuthoringStatus(target, status, selectedHtml);
  }

  async function openSection(target, state, sectionId, message, tone) {
    if (!sectionId) return;
    const payload = await loadCanonSection(state.projectId, sectionId);
    state.lastSection = payload;
    const editorHtml = renderSectionEditor(payload, message, tone);
    await refreshWorkbook(target, state, sectionId, editorHtml);
  }

  function bindWorkbookEvents(target) {
    if (target.dataset.canonAuthoringBound === 'true') return;
    target.dataset.canonAuthoringBound = 'true';

    target.addEventListener('click', async (event) => {
      const openButton = event.target.closest('[data-canon-open-section]');
      const completeButton = event.target.closest('[data-canon-complete-section]');
      const reopenButton = event.target.closest('[data-canon-reopen-section]');
      const renderAllButton = event.target.closest('[data-canon-render-all-markdown]');
      const renderSectionButton = event.target.closest('[data-canon-render-section-markdown]');
      const addButton = event.target.closest('[data-canon-add-record]');
      const removeButton = event.target.closest('[data-canon-remove-record]');
      const state = TARGET_STATE.get(target.id || 'canon-workbook-shell') || {};

      try {
        if (openButton) {
          await openSection(target, state, openButton.getAttribute('data-canon-open-section'));
          return;
        }

        if (completeButton) {
          const sectionId = completeButton.getAttribute('data-canon-complete-section');
          const result = await completeCanonSection(state.projectId, sectionId);
          const blocked = result.status === 'blocked';
          await openSection(
            target,
            state,
            sectionId,
            blocked ? (result.message || 'Section has missing required fields.') : 'Section marked complete.',
            blocked ? 'error' : 'ok'
          );
          return;
        }

        if (reopenButton) {
          const sectionId = reopenButton.getAttribute('data-canon-reopen-section');
          await reopenCanonSection(state.projectId, sectionId);
          await openSection(target, state, sectionId, 'Section reopened for editing.', 'ok');
          return;
        }

        if (renderAllButton) {
          const result = await renderCompletedCanonSources(state.projectId);
          state.lastMarkdownStatus = await loadCanonMarkdownStatus(state.projectId);
          await refreshWorkbook(
            target,
            state,
            state.selectedSectionId,
            state.lastSection ? renderSectionEditor(state.lastSection, `Rendered ${number(result.rendered_file_count)} completed section(s).`, 'ok') : null
          );
          return;
        }

        if (renderSectionButton) {
          const sectionId = renderSectionButton.getAttribute('data-canon-render-section-markdown');
          const result = await renderCanonSectionMarkdown(state.projectId, sectionId);
          await openSection(target, state, sectionId, `Rendered section Markdown: ${result.filename || result.path || sectionId}`, 'ok');
          return;
        }

        if (addButton) {
          const group = addButton.closest('[data-canon-record-id]');
          if (group) cloneRecordItem(group);
          return;
        }

        if (removeButton) {
          removeRecordItem(removeButton);
        }
      } catch (error) {
        renderError(target, error && error.message ? error.message : 'Canon Workbook action failed.');
      }
    });

    target.addEventListener('submit', async (event) => {
      const form = event.target.closest('[data-canon-section-form]');
      if (!form || !target.contains(form)) return;
      event.preventDefault();

      const state = TARGET_STATE.get(target.id || 'canon-workbook-shell') || {};
      const sectionId = form.getAttribute('data-canon-section-form') || '';
      const payload = collectFormPayload(form);

      try {
        await saveCanonSectionDraft(state.projectId, sectionId, payload);
        await openSection(target, state, sectionId, 'Draft saved to project-local author canon storage.', 'ok');
      } catch (error) {
        renderError(target, error && error.message ? error.message : 'Canon Workbook draft save failed.');
      }
    });
  }

  async function renderCanonWorkbookShell(options) {
    const config = options || {};
    const targetId = config.targetId || 'canon-workbook-shell';
    const target = document.getElementById(targetId);
    if (!target) return;

    const state = ensureTargetState(target, config);
    bindWorkbookEvents(target);
    renderLoading(target);

    try {
      const payload = await loadCanonAuthoringStatus(state.projectId);
      state.lastStatus = payload;
      try {
        state.lastMarkdownStatus = await loadCanonMarkdownStatus(state.projectId);
      } catch (markdownError) {
        state.lastMarkdownStatus = {
          status: 'unavailable',
          rendered_file_count: 0,
          completed_section_count: 0,
          rendered_files: [],
          message: markdownError && markdownError.message ? markdownError.message : 'Markdown status unavailable.'
        };
      }
      renderAuthoringStatus(target, payload || {});
    } catch (error) {
      renderError(target, error && error.message ? error.message : 'Canon Workbook status could not be loaded.');
    }
  }

  window.ItalusCanonAuthoring = {
    renderCanonWorkbookShell,
    loadCanonAuthoringStatus,
    loadCanonMarkdownStatus,
    renderCompletedCanonSources,
    renderCanonSectionMarkdown,
    loadCanonSection,
    saveCanonSectionDraft,
    completeCanonSection,
    reopenCanonSection
  };
})();
