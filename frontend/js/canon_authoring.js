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
  const TEMPLATE_MIGRATION_ROUTE_SUFFIX = '/canon/template-migration';
  const MARKDOWN_STATUS_ROUTE_SUFFIX = '/canon/markdown';
  const MARKDOWN_RENDER_ROUTE_SUFFIX = '/canon/markdown/render';
  const VALIDATION_STATUS_ROUTE_SUFFIX = '/canon/validation';
  const VALIDATION_RUN_ROUTE_SUFFIX = '/canon/validation/run';
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


  function markdownFileGuidance(file) {
    const renderStatus = file.render_status || 'verification_required';
    const sectionLabel = file.section_label || file.section_id || 'this canon section';

    if (renderStatus === 'current' && file.freshness_verified === true) {
      return {
        statusLabel: 'CURRENT',
        message: `The backend verified that this Markdown source matches the latest saved ${sectionLabel} content. No action is required.`,
      };
    }

    if (renderStatus === 'review_in_progress') {
      return {
        statusLabel: 'REVIEW IN PROGRESS',
        message: `The stored Markdown still matches the saved ${sectionLabel} content, but the section remains a draft. Open ${sectionLabel}, finish the review, and click Mark Complete. Re-render only if the canon content changes.`,
      };
    }

    if (renderStatus === 'ready_to_render') {
      return {
        statusLabel: 'READY TO RENDER',
        message: `The ${sectionLabel} is complete, but the backend verified that its Markdown source does not match the latest saved canon. Open the section and click Render Section Markdown. The existing file will be replaced, not appended.`,
      };
    }

    if (renderStatus === 'update_required') {
      return {
        statusLabel: 'UPDATE REQUIRED',
        message: `This Markdown source does not match the current ${sectionLabel} draft. Open the section, review or finish the canon, and click Mark Complete. After completion, click Render Section Markdown. The previous file remains preserved until replacement.`,
      };
    }

    return {
      statusLabel: 'VERIFICATION REQUIRED',
      message: `The backend could not verify this Markdown source against ${sectionLabel}. Open the section and render it again after confirming the canon.`,
    };
  }

  function markdownFileListHtml(files) {
    if (!Array.isArray(files) || !files.length) {
      return '<p class="setup-note">No rendered canon source files detected yet.</p>';
    }

    return `
      <ul class="canon-item-list">
        ${files.map((file) => {
          const guidance = markdownFileGuidance(file);
          const sectionId = file.section_id || '';
          return `
            <li class="canon-item-card" data-status="${escapeHtml(guidance.statusLabel)}">
              <strong>${escapeHtml(file.filename || file.path || 'canon source')}</strong>
              <span>${escapeHtml(file.section_label || file.section_id || '')} — ${escapeHtml(guidance.statusLabel)}</span>
              <small>${escapeHtml(guidance.message)}</small>
              ${file.path ? `<small>${escapeHtml(file.path)}</small>` : ''}
              ${sectionId && file.action_required === true
                ? `<button type="button" class="secondary" data-canon-open-section="${escapeHtml(sectionId)}">Open ${escapeHtml(file.section_label || sectionId)}</button>`
                : ''}
            </li>
          `;
        }).join('')}
      </ul>
    `;
  }

  function renderMarkdownStatusPanel(markdownStatus) {
    const status = markdownStatus && typeof markdownStatus === 'object' ? markdownStatus : {};
    const renderedCount = Number(status.rendered_file_count || 0);
    const currentCount = Number(status.current_rendered_file_count || 0);
    const staleCount = Number(status.stale_rendered_file_count || 0);
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
          Markdown freshness is verified by the backend against the latest saved canon content. Use Render Section Markdown only when a source card requests action. Rendering replaces the section file and never appends duplicate content.
        </p>
        <dl>
          <div><dt>Completed Sections</dt><dd>${number(completedCount)}</dd></div>
          <div><dt>Current Sources</dt><dd>${number(currentCount)}</dd></div>
          <div><dt>Needs Re-render</dt><dd>${number(staleCount)}</dd></div>
          <div><dt>Stored Files</dt><dd>${number(renderedCount)}</dd></div>
          <div><dt>Output Directory</dt><dd>${escapeHtml(sourceDir)}</dd></div>
        </dl>
        ${markdownFileListHtml(files)}
      </article>
    `;
  }

  function validationIssueListHtml(items, emptyMessage) {
    if (!Array.isArray(items) || !items.length) {
      return `<p class="setup-note">${escapeHtml(emptyMessage)}</p>`;
    }

    return `
      <ul class="canon-item-list">
        ${items.map((item) => `
          <li class="canon-item-card">
            <strong>${escapeHtml(item.code || item.severity || 'validation finding')}</strong>
            <span>${escapeHtml(item.message || 'Canon validation finding')}</span>
            ${item.section_id ? `<small>Section: ${escapeHtml(item.section_id)}</small>` : ''}
          </li>
        `).join('')}
      </ul>
    `;
  }

  function projectValidationSummaryHtml(validationStatus, payload) {
    const status = validationStatus || {};
    const issues = Array.isArray(status.issues) ? status.issues : [];
    const warnings = Array.isArray(status.warnings) ? status.warnings : [];
    const expectedAuthoringCodes = new Set([
      'required_section_not_complete',
      'missing_required_section'
    ]);
    const unexpectedIssues = issues.filter((item) => !expectedAuthoringCodes.has(item && item.code));
    const reportWritten = Boolean(status.report_written);
    const required = number(status.required_sections_total || payload.required_section_count);
    const complete = number(status.required_sections_complete || payload.completed_required_section_count);
    const incomplete = Math.max(0, required - complete);

    const missingRenderedSources = Array.isArray(status.missing_rendered_sources)
      ? status.missing_rendered_sources
      : [];

    return `
      <dl>
        <div><dt>Author-facing Canon Sections</dt><dd>${number(payload.section_count)} total</dd></div>
        <div><dt>Required Sections Complete</dt><dd>${complete} / ${required}</dd></div>
        <div><dt>Current Rendered Sources</dt><dd>${number(status.rendered_sources_total)}</dd></div>
        <div><dt>Blocking Issues</dt><dd>${number(unexpectedIssues.length)}</dd></div>
        <div><dt>Warnings</dt><dd>${number(warnings.length)}</dd></div>
        <div><dt>Validation Report</dt><dd>${reportWritten ? 'WRITTEN' : 'STATUS ONLY'}</dd></div>
      </dl>
      <p class="setup-note">
        ${incomplete
          ? `${incomplete} required canon section${incomplete === 1 ? '' : 's'} remain incomplete.`
          : 'All required canon sections are complete.'}
      </p>
      <p class="setup-note">
        ${missingRenderedSources.length
          ? `${missingRenderedSources.length} completed-section Markdown source${missingRenderedSources.length === 1 ? ' is' : 's are'} missing or outdated.`
          : 'No completed-section Markdown sources are missing.'}
      </p>
    `;
  }

  function updateProjectValidationSummary(validationStatus, payload) {
    const target = document.getElementById('project-canon-progress');
    if (!target) return;
    target.innerHTML = projectValidationSummaryHtml(validationStatus || {}, payload || {});
  }

  function renderTemplateMigrationPanel(migration) {
    if (!migration || typeof migration !== 'object') return '';

    const currentVersion = migration.current_template_version || 'unknown';
    const activeVersion = migration.active_template_version || 'unknown';
    const reconciliation = Array.isArray(migration.reconciliation_required)
      ? migration.reconciliation_required
      : [];
    const reconciliationCount = reconciliation.reduce(
      (total, item) => total + Number(item && item.missing_count ? item.missing_count : 0),
      0
    );

    if (migration.template_conflict) {
      return `
        <article class="canon-group-card" data-status="BLOCKED" data-canon-template-migration-panel>
          <header>
            <div>
              <h3>Canon Template Upgrade</h3>
              <p class="setup-note">The project snapshot template does not match the active project template.</p>
            </div>
            <span>BLOCKED</span>
          </header>
          <p class="canon-file-missing">Template migration is blocked until the template conflict is reconciled.</p>
        </article>
      `;
    }

    if (migration.persistence_conflict) {
      const persistence = migration.persistence || {};
      return `
        <article class="canon-group-card" data-status="BLOCKED" data-canon-template-migration-panel>
          <header>
            <div>
              <h3>Canon Template Persistence Error</h3>
              <p class="canon-file-missing">The template version appears current, but required Patch 15 migration artifacts are missing or invalid.</p>
            </div>
            <span>BLOCKED</span>
          </header>
          <p class="setup-note">
            Persistence verification failed. Do not continue Canon editing or begin the next migration patch.
          </p>
          <p class="setup-note">
            Snapshot: ${persistence.snapshot_verified ? 'verified' : 'missing / invalid'} ·
            Migration report: ${persistence.template_report_verified ? 'verified' : 'missing / invalid'} ·
            Reference report: ${persistence.reference_report_verified ? 'verified' : 'missing / invalid'}
          </p>
        </article>
      `;
    }

    if (migration.migration_required) {
      return `
        <article class="canon-group-card" data-status="UPDATE_REQUIRED" data-canon-template-migration-panel>
          <header>
            <div>
              <h3>Canon Template Upgrade</h3>
              <p class="setup-note">Upgrade the project-local questionnaire before continuing Canon Workbook editing.</p>
            </div>
            <span>UPDATE REQUIRED</span>
          </header>
          <p class="setup-note">
            ${escapeHtml(currentVersion)} → ${escapeHtml(activeVersion)}.
            The upgrade preserves author-owned story meaning, converts only exact deterministic relationships
            to stable Canon references, and reports anything that cannot be resolved safely.
          </p>
          <button type="button" data-canon-migrate-template>Upgrade Canon Template</button>
        </article>
      `;
    }

    if (reconciliationCount > 0) {
      return `
        <article class="canon-group-card" data-status="CURRENT" data-canon-template-migration-panel>
          <header>
            <div>
              <h3>Canon Template</h3>
              <p class="setup-note">Project-local template is current and persisted migration state is verified.</p>
            </div>
            <span>CURRENT</span>
          </header>
          <p class="setup-note">
            ${number(reconciliationCount)} author-owned value${reconciliationCount === 1 ? '' : 's'}
            remain available for reconciliation. Italus did not infer them.
          </p>
        </article>
      `;
    }

    return '';
  }

  function renderAuthoringStatus(target, payload, selectedSectionHtml) {
    const state = TARGET_STATE.get(target.id || 'canon-workbook-shell') || {};
    const markdownStatus = state.lastMarkdownStatus || {};
    const validationStatus = state.lastValidationStatus || {};
    const sections = Array.isArray(payload.sections) ? payload.sections : [];
    const required = Number(payload.required_section_count || 0);
    const complete = Number(payload.completed_required_section_count || 0);

    updateProjectValidationSummary(validationStatus, payload);

    target.innerHTML = `
      ${renderMarkdownStatusPanel(markdownStatus)}
      ${state.flashMessage
        ? `<p class="setup-message ${escapeHtml(state.flashTone || 'success')}" data-canon-workbook-message>${escapeHtml(state.flashMessage)}</p>`
        : ''}
      ${renderTemplateMigrationPanel(payload.template_migration)}
      <div class="canon-item-list" aria-label="Canon Workbook Sections" data-canon-section-list>
        ${sections.length ? sections.map(renderSectionCard).join('') : '<p class="setup-note">No canon questionnaire sections were returned.</p>'}
      </div>
      <section class="canon-group-card" data-canon-section-editor aria-label="Canon Section Editor" tabindex="-1">
        ${selectedSectionHtml || '<p class="setup-note">Open a section to edit project-local author canon answers.</p>'}
      </section>
    `;
  }

  function fieldLabelHtml(field) {
    const fieldId = field.field_id || '';
    const label = field.label || fieldId || 'Field';
    const required = Boolean(field.required);
    const planningOptional = Boolean(field.planning_field) && !required;
    const helpText = field.help_text || '';

    return `
      ${escapeHtml(label)}${required ? ' *' : ''}${planningOptional ? ' (Optional)' : ''}
      ${planningOptional
        ? `<span class="canon-info-tip" title="${escapeHtml(helpText)}" aria-label="${escapeHtml(helpText || `${label} is optional`)}" tabindex="0">ⓘ</span>`
        : ''}
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
          <span>${fieldLabelHtml(field)}</span>
          <input type="checkbox" data-canon-field-id="${escapeHtml(fieldId)}" ${value ? 'checked' : ''}>
        </label>
        ${help}
      `;
    }

    if (type === 'select') {
      const options = Array.isArray(field.options) ? field.options : [];
      return `
        <label class="canon-field-row">
          <span>${fieldLabelHtml(field)}</span>
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
          <span>${fieldLabelHtml(field)}</span>
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
          <span>${fieldLabelHtml(field)}</span>
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

  function referenceOptionsForField(field, referenceCatalog) {
    const targets = Array.isArray(field.reference_targets) ? field.reference_targets : [];
    const catalog = referenceCatalog && typeof referenceCatalog === 'object' ? referenceCatalog : {};
    const seen = new Set();
    const options = [];

    targets.forEach((target) => {
      const rows = Array.isArray(catalog[target]) ? catalog[target] : [];
      rows.forEach((row) => {
        const recordId = String((row && row.record_id) || '').trim();
        if (!recordId || seen.has(recordId)) return;
        seen.add(recordId);
        options.push({
          record_id: recordId,
          label: String((row && row.label) || 'Canon record')
        });
      });
    });

    return options;
  }

  function legacyReferenceWarningHtml(values) {
    const legacy = (Array.isArray(values) ? values : [values])
      .map((value) => String(value || '').trim())
      .filter(Boolean);
    if (!legacy.length) return '';
    return `
      <p class="canon-file-missing">
        Unresolved legacy relationship: ${legacy.map(escapeHtml).join(', ')}.
        Select the intended Canon record when you are ready to reconcile it.
      </p>
    `;
  }

  function recordFieldInputHtml(recordId, index, field, value, referenceCatalog) {
    const fieldId = field.field_id || '';
    const type = field.field_type || 'long_text';
    const help = field.help_text ? `<p class="setup-note">${escapeHtml(field.help_text)}</p>` : '';
    const dataAttrs = `data-canon-record-field-id="${escapeHtml(fieldId)}" data-canon-record-id="${escapeHtml(recordId)}" data-canon-record-index="${escapeHtml(index)}"`;

    if (field.author_hidden) {
      return `<input type="hidden" ${dataAttrs} value="${escapeHtml(value || '')}">`;
    }

    if (type === 'record_ref') {
      const options = referenceOptionsForField(field, referenceCatalog);
      const current = String(value || '').trim();
      const knownIds = new Set(options.map((option) => option.record_id));
      const legacyValues = current && !knownIds.has(current) ? [current] : [];

      return `
        <label class="canon-field-row">
          <span>${fieldLabelHtml(field)}</span>
          <select ${dataAttrs} data-canon-reference-selector>
            <option value="">Select Canon record...</option>
            ${legacyValues.map((legacy) => `
              <option value="${escapeHtml(legacy)}" selected>Unresolved legacy: ${escapeHtml(legacy)}</option>
            `).join('')}
            ${options.map((option) => `
              <option value="${escapeHtml(option.record_id)}" ${current === option.record_id ? 'selected' : ''}>${escapeHtml(option.label)}</option>
            `).join('')}
          </select>
        </label>
        ${legacyReferenceWarningHtml(legacyValues)}
        ${help}
      `;
    }

    if (type === 'record_ref_list') {
      const options = referenceOptionsForField(field, referenceCatalog);
      const selected = (Array.isArray(value) ? value : (value ? [value] : []))
        .map((item) => String(item || '').trim())
        .filter(Boolean);
      const knownIds = new Set(options.map((option) => option.record_id));
      const legacyValues = selected.filter((item) => !knownIds.has(item));
      const size = Math.max(3, Math.min(8, options.length + legacyValues.length || 3));

      return `
        <label class="canon-field-row">
          <span>${fieldLabelHtml(field)}</span>
          <select ${dataAttrs} data-canon-reference-selector multiple size="${size}">
            ${legacyValues.map((legacy) => `
              <option value="${escapeHtml(legacy)}" selected>Unresolved legacy: ${escapeHtml(legacy)}</option>
            `).join('')}
            ${options.map((option) => `
              <option value="${escapeHtml(option.record_id)}" ${selected.includes(option.record_id) ? 'selected' : ''}>${escapeHtml(option.label)}</option>
            `).join('')}
          </select>
        </label>
        ${legacyReferenceWarningHtml(legacyValues)}
        ${help}
      `;
    }

    if (type === 'boolean') {
      return `
        <label class="canon-field-row">
          <span>${fieldLabelHtml(field)}</span>
          <input type="checkbox" ${dataAttrs} ${value ? 'checked' : ''}>
        </label>
        ${help}
      `;
    }

    if (type === 'select') {
      const options = Array.isArray(field.options) ? field.options : [];
      return `
        <label class="canon-field-row">
          <span>${fieldLabelHtml(field)}</span>
          <select ${dataAttrs}>
            <option value="">Select...</option>
            ${options.map((option) => `
              <option value="${escapeHtml(option)}" ${String(value || '') === String(option) ? 'selected' : ''}>${escapeHtml(option)}</option>
            `).join('')}
          </select>
        </label>
        ${help}
      `;
    }

    if (type === 'short_text') {
      return `
        <label class="canon-field-row">
          <span>${fieldLabelHtml(field)}</span>
          <input type="text" ${dataAttrs} value="${escapeHtml(value || '')}" placeholder="${escapeHtml(field.placeholder || '')}">
        </label>
        ${help}
      `;
    }

    return `
      <label class="canon-field-row">
        <span>${fieldLabelHtml(field)}</span>
        <textarea ${dataAttrs} rows="${type === 'rich_text' ? '6' : '3'}" placeholder="${escapeHtml(field.placeholder || '')}">${escapeHtml(value || '')}</textarea>
      </label>
      ${help}
    `;
  }

  function renderRecordGroup(record, storedItems, referenceCatalog) {
    const recordId = record.record_id || '';
    const items = Array.isArray(storedItems) && storedItems.length ? storedItems : [{}];
    const fields = Array.isArray(record.fields) ? record.fields : [];
    const hiddenFields = fields.filter((field) => Boolean(field.author_hidden));
    const standardFields = fields.filter((field) => !field.author_hidden && !field.planning_field);
    const planningFields = fields.filter((field) => !field.author_hidden && field.planning_field);
    const minItems = Number(record.min_items || 0);
    const help = record.help_text ? `<p class="setup-note">${escapeHtml(record.help_text)}</p>` : '';

    return `
      <fieldset class="canon-record-group" data-canon-record-id="${escapeHtml(recordId)}">
        <legend>${escapeHtml(record.label || recordId || 'Record group')}${record.required ? ' *' : ''}</legend>
        ${help}
        <p class="setup-note">Minimum entries: ${number(minItems)}</p>
        <div data-canon-record-items="${escapeHtml(recordId)}">
          ${items.map((item, index) => `
            <article class="canon-item-card" data-canon-record-item="${escapeHtml(recordId)}" data-canon-record-index="${escapeHtml(index)}" data-canon-record-internal-id="${escapeHtml(item && item.internal_id ? item.internal_id : '')}">
              <header>
                <strong>${escapeHtml(record.label || 'Record')} ${number(index + 1)}</strong>
                <button type="button" class="secondary" data-canon-remove-record="${escapeHtml(recordId)}" data-canon-record-index="${escapeHtml(index)}">Remove</button>
              </header>
              ${hiddenFields.map((field) => recordFieldInputHtml(recordId, index, field, item ? item[field.field_id] : '', referenceCatalog)).join('')}
              ${standardFields.map((field) => recordFieldInputHtml(recordId, index, field, item ? item[field.field_id] : '', referenceCatalog)).join('')}
              ${planningFields.length
                ? `<details class="canon-planning-fields">
                    <summary>Advanced / Planning</summary>
                    <p class="canon-planning-instructions">Use the fields below to guide when and how this canon item can enter your story planning. Complete only the fields that apply to this item. Leave any field blank until you are ready to make that planning decision.</p>
                    ${planningFields.map((field) => `
                      <div class="canon-planning-field-block">
                        ${recordFieldInputHtml(recordId, index, field, item ? item[field.field_id] : '', referenceCatalog)}
                      </div>
                    `).join('')}
                  </details>`
                : ''}
            </article>
          `).join('')}
        </div>
        <button type="button" class="secondary" data-canon-add-record="${escapeHtml(recordId)}">Add ${escapeHtml(record.label || 'Record')}</button>
      </fieldset>
    `;
  }

  function singularRecordLabel(label, recordId) {
    const source = String(label || recordId || 'Record').trim();
    if (/ies$/i.test(source)) return source.replace(/ies$/i, 'y');
    if (/sses$/i.test(source)) return source.replace(/es$/i, '');
    if (/s$/i.test(source) && !/ss$/i.test(source)) return source.slice(0, -1);
    return source;
  }

  function quickAddButtonsHtml(recordGroups, status) {
    if (status === 'complete') return '';
    return recordGroups.map((record) => {
      const recordId = record.record_id || '';
      const label = singularRecordLabel(record.label, recordId);
      return `<button type="button" class="secondary canon-quick-add-button" data-canon-add-record="${escapeHtml(recordId)}">Add ${escapeHtml(label)}</button>`;
    }).join('');
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
    const referenceCatalog = payload.reference_catalog && typeof payload.reference_catalog === 'object'
      ? payload.reference_catalog
      : {};
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
        ${recordGroups.map((record) => renderRecordGroup(record, records[record.record_id], referenceCatalog)).join('')}
        <p class="setup-note canon-section-workflow-note">
          Save Draft keeps the section editable. Mark Complete approves it. Render Section Markdown creates the derived validation source.
        </p>
        <div class="wizard-actions canon-section-actions">
          ${quickAddButtonsHtml(recordGroups, status)}
          <button type="submit" data-canon-save-section="${escapeHtml(schema.section_id || '')}">Save Draft</button>
          ${status === 'complete'
            ? `<button type="button" class="secondary" data-canon-reopen-section="${escapeHtml(schema.section_id || '')}">Edit Section</button>
               <button type="button" class="secondary" data-canon-render-section-markdown="${escapeHtml(schema.section_id || '')}">Render Section Markdown</button>`
            : `<button type="button" class="secondary" data-canon-complete-section="${escapeHtml(schema.section_id || '')}">Mark Complete</button>`}
          <button type="button" class="secondary" data-canon-close-section>Close Section</button>
        </div>
      </form>
    `;
  }

  async function loadCanonAuthoringStatus(projectId) {
    return apiGet(projectId, AUTHORING_ROUTE_SUFFIX);
  }

  async function migrateCanonTemplate(projectId) {
    return apiPost(projectId, TEMPLATE_MIGRATION_ROUTE_SUFFIX);
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

  async function loadCanonValidationStatus(projectId) {
    return apiGet(projectId, VALIDATION_STATUS_ROUTE_SUFFIX);
  }

  async function runCanonValidation(projectId) {
    return apiPost(projectId, VALIDATION_RUN_ROUTE_SUFFIX);
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

    form.querySelectorAll('[data-canon-record-item]').forEach((item) => {
      const recordId = item.getAttribute('data-canon-record-item');
      const index = Number(item.getAttribute('data-canon-record-index') || 0);
      const internalId = item.getAttribute('data-canon-record-internal-id') || '';
      if (!recordId || !Number.isFinite(index) || !internalId) return;

      if (!records[recordId]) records[recordId] = [];
      if (!records[recordId][index]) records[recordId][index] = {};
      records[recordId][index].internal_id = internalId;
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
      } else if (field instanceof HTMLSelectElement && field.multiple) {
        records[recordId][index][fieldId] = Array.from(field.selectedOptions).map((option) => option.value);
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
    clone.setAttribute('data-canon-record-internal-id', '');
    clone.querySelectorAll('[data-canon-record-index]').forEach((node) => {
      node.setAttribute('data-canon-record-index', String(nextIndex));
    });
    clone.querySelectorAll('input, textarea, select').forEach((field) => {
      if (field instanceof HTMLInputElement && field.type === 'checkbox') {
        field.checked = false;
      } else if (field instanceof HTMLSelectElement && field.multiple) {
        Array.from(field.options).forEach((option) => {
          option.selected = false;
        });
      } else {
        field.value = '';
      }
    });
    const heading = clone.querySelector('strong');
    if (heading) {
      heading.textContent = `${recordId || 'Record'} ${nextIndex + 1}`;
    }

    itemsContainer.appendChild(clone);
    window.requestAnimationFrame(() => {
      clone.scrollIntoView({ behavior: 'smooth', block: 'start' });
      const firstEditable = clone.querySelector('input:not([type="hidden"]), textarea, select');
      if (firstEditable) firstEditable.focus({ preventScroll: true });
    });
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
    try {
      state.lastValidationStatus = await loadCanonValidationStatus(state.projectId);
    } catch (error) {
      state.lastValidationStatus = {
        status: 'unavailable',
        ready_for_packet_generation: false,
        issues: [],
        warnings: [],
        message: error && error.message ? error.message : 'Validation status unavailable.'
      };
    }
    state.selectedSectionId = selectedSectionId || state.selectedSectionId || null;
    renderAuthoringStatus(target, status, selectedHtml);
  }

  function revealSectionList(target) {
    const sectionList = target.querySelector('[data-canon-section-list]');
    if (!sectionList) return;

    window.requestAnimationFrame(() => {
      sectionList.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  function revealSectionEditor(target) {
    const editor = target.querySelector('[data-canon-section-editor]');
    if (!editor) return;

    window.requestAnimationFrame(() => {
      editor.scrollIntoView({ behavior: 'smooth', block: 'start' });
      editor.focus({ preventScroll: true });
    });
  }

  async function openSection(target, state, sectionId, message, tone) {
    if (!sectionId) return;
    const payload = await loadCanonSection(state.projectId, sectionId);
    state.lastSection = payload;
    const editorHtml = renderSectionEditor(payload, message, tone);
    await refreshWorkbook(target, state, sectionId, editorHtml);
    revealSectionEditor(target);
  }

  function bindWorkbookEvents(target) {
    if (target.dataset.canonAuthoringBound === 'true') return;
    target.dataset.canonAuthoringBound = 'true';

    target.addEventListener('click', async (event) => {
      const migrationButton = event.target.closest('[data-canon-migrate-template]');
      const openButton = event.target.closest('[data-canon-open-section]');
      const completeButton = event.target.closest('[data-canon-complete-section]');
      const reopenButton = event.target.closest('[data-canon-reopen-section]');
      const closeButton = event.target.closest('[data-canon-close-section]');
      const renderSectionButton = event.target.closest('[data-canon-render-section-markdown]');
      const addButton = event.target.closest('[data-canon-add-record]');
      const removeButton = event.target.closest('[data-canon-remove-record]');
      const state = TARGET_STATE.get(target.id || 'canon-workbook-shell') || {};

      try {
        if (migrationButton) {
          const result = await migrateCanonTemplate(state.projectId);
          const migration = result.migration || {};
          if (migration.persistence_verified !== true) {
            throw new Error('Canon template migration did not verify persisted project state.');
          }
          const reconciliationCount = Number(migration.reconciliation_required_count || 0);
          state.selectedSectionId = null;
          state.lastSection = null;
          state.flashMessage = reconciliationCount
            ? `Canon template upgraded. ${reconciliationCount} optional author-owned planning value${reconciliationCount === 1 ? '' : 's'} were left blank for reconciliation.`
            : 'Canon template upgraded. Existing author canon values were preserved.';
          state.flashTone = 'success';
          await refreshWorkbook(target, state, null, null);
          revealSectionList(target);
          return;
        }

        if (openButton) {
          if (state.lastStatus
              && state.lastStatus.template_migration
              && state.lastStatus.template_migration.migration_required) {
            state.flashMessage = 'Upgrade the project-local Canon Template before editing sections.';
            state.flashTone = 'error';
            await refreshWorkbook(target, state, null, null);
            return;
          }
          await openSection(target, state, openButton.getAttribute('data-canon-open-section'));
          return;
        }

        if (closeButton) {
          state.selectedSectionId = null;
          state.lastSection = null;
          await refreshWorkbook(target, state, null, null);
          revealSectionList(target);
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
          await openSection(target, state, sectionId, 'Section is now editable. Save changes as a draft, then mark it complete again.', 'ok');
          return;
        }

        if (renderSectionButton) {
          const sectionId = renderSectionButton.getAttribute('data-canon-render-section-markdown');
          const result = await renderCanonSectionMarkdown(state.projectId, sectionId);
          await openSection(target, state, sectionId, `Rendered section Markdown: ${result.filename || result.path || sectionId}`, 'ok');
          return;
        }

        if (addButton) {
          const recordId = addButton.getAttribute('data-canon-add-record') || '';
          const form = addButton.closest('[data-canon-section-form]');
          const group = form
            ? Array.from(form.querySelectorAll('[data-canon-record-id]')).find(
                (candidate) => candidate.getAttribute('data-canon-record-id') === recordId
              )
            : null;
          if (!group) {
            throw new Error(`Record editor not found for ${recordId || 'requested item'}.`);
          }
          cloneRecordItem(group);
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
        state.selectedSectionId = null;
        state.lastSection = null;
        state.flashMessage = 'Draft saved to project-local author canon storage.';
        state.flashTone = 'success';
        await refreshWorkbook(target, state, null, null);
        revealSectionList(target);
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
      try {
        state.lastValidationStatus = await loadCanonValidationStatus(state.projectId);
      } catch (validationError) {
        state.lastValidationStatus = {
          status: 'unavailable',
          ready_for_packet_generation: false,
          issues: [],
          warnings: [],
          message: validationError && validationError.message ? validationError.message : 'Validation status unavailable.'
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
    loadCanonValidationStatus,
    runCanonValidation,
    loadCanonSection,
    saveCanonSectionDraft,
    completeCanonSection,
    reopenCanonSection
  };
})();
