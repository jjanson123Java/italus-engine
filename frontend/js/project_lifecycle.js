/*
Landing-page project lifecycle controller.

This module owns frontend project setup mode. New projects are created with
POST /api/project/new. Existing projects are loaded with GET /api/project/{id}
and saved in place with PATCH /api/project/{id}.
*/
(function () {
  const modalLayerId = 'studio-modal-layer';
  const modalByAction = {
    new: 'new-project-modal',
    existing: 'existing-project-modal',
    archived: 'archived-project-modal',
    learnMore: 'learn-more-modal',
    canon: 'canon-setup-modal'
  };

  const state = {
    activeProjectId: null,
    isEditMode: false,
    loadedProject: null
  };

  const lifecycleLabels = {
    DRAFT_SETUP: 'Draft Setup',
    CANON_IN_PROGRESS: 'Canon Setup in Progress',
    READY_FOR_WORKSPACE: 'Ready for Workspace',
    ACTIVE: 'Active',
    ARCHIVED: 'Archived'
  };

  function humanizeIdentifier(value, labels = {}) {
    const raw = String(value || '').trim();
    if (!raw) return '—';
    if (labels[raw]) return labels[raw];
    return raw
      .replace(/[_-]+/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .replace(/\b\w/g, (character) => character.toUpperCase());
  }

  function getModalLayer() {
    return document.getElementById(modalLayerId);
  }

  function getNewProjectForm() {
    return document.getElementById('new-project-form');
  }

  function getBudgetPreview() {
    return document.getElementById('budget-preview');
  }

  function closeAllModals() {
    const layer = getModalLayer();
    if (!layer) return;

    layer.setAttribute('aria-hidden', 'true');
    layer.querySelectorAll('.studio-modal').forEach((modal) => {
      modal.hidden = true;
    });
    document.body.classList.remove('modal-open');
  }

  function openModal(action) {
    const layer = getModalLayer();
    const modalId = modalByAction[action];
    const modal = modalId ? document.getElementById(modalId) : null;

    if (!layer || !modal) return;

    closeAllModals();
    layer.setAttribute('aria-hidden', 'false');
    modal.hidden = false;
    document.body.classList.add('modal-open');

    if (action === 'new') {
      startNewProjectMode();
    } else if (action === 'existing') {
      loadProjectList('active');
    } else if (action === 'archived') {
      loadProjectList('archived');
    }

    const firstField = modal.querySelector('input, select, button');
    if (firstField) firstField.focus();
  }

  function showModal(action) {
    const layer = getModalLayer();
    const modalId = modalByAction[action];
    const modal = modalId ? document.getElementById(modalId) : null;
    if (!layer || !modal) return;

    closeAllModals();
    layer.setAttribute('aria-hidden', 'false');
    modal.hidden = false;
    document.body.classList.add('modal-open');

    const firstField = modal.querySelector('input, select, button');
    if (firstField) firstField.focus();
  }

  function bindProjectActions() {
    document.querySelectorAll('[data-project-action]').forEach((element) => {
      element.addEventListener('click', (event) => {
        event.preventDefault();
        openModal(element.dataset.projectAction);
      });
    });
  }

  function bindModalClose() {
    document.querySelectorAll('[data-modal-close]').forEach((element) => {
      element.addEventListener('click', closeAllModals);
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeAllModals();
      }
    });
  }

  function bindNewProjectForm() {
    const form = getNewProjectForm();
    const preview = getBudgetPreview();
    const saveDraftButton = document.getElementById('save-project-draft');

    if (!form || !window.ItalusProjectWizard) return;

    const updatePreview = async () => {
      const basics = window.ItalusProjectWizard.collectProjectBasics(form);
      const localEstimate = window.ItalusProjectWizard.estimateBudget(basics);
      window.ItalusProjectWizard.renderBudgetPreview(preview, localEstimate);

      try {
        const response = await apiFetch('/api/project/estimate-budget', {
          method: 'POST',
          body: JSON.stringify(basics)
        });
        window.ItalusProjectWizard.renderBudgetPreview(preview, response.budget_plan);
      } catch (error) {
        appendMessage(preview, `Backend budget estimate unavailable. Using local estimate. ${error.message}`, 'warning');
      }
    };

    form.addEventListener('input', debounce(updatePreview, 250));
    form.addEventListener('change', updatePreview);

    if (saveDraftButton) {
      saveDraftButton.addEventListener('click', () => {
        saveProject({ continueToCanon: false });
      });
    }

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      saveProject({ continueToCanon: true });
    });

    updatePreview();
  }

  async function saveProject(options) {
    const form = getNewProjectForm();
    const preview = getBudgetPreview();
    if (!form || !window.ItalusProjectWizard) return;

    const payload = window.ItalusProjectWizard.buildProjectPayload(form, options);

    if (!payload.project_name) {
      appendMessage(preview, 'Project name is required before saving.', 'error');
      return;
    }

    const isUpdate = Boolean(state.activeProjectId && state.isEditMode);
    const endpoint = isUpdate
      ? `/api/project/${encodeURIComponent(state.activeProjectId)}`
      : '/api/project/new';
    const method = isUpdate ? 'PATCH' : 'POST';

    setSavingState(true);
    try {
      const result = await apiFetch(endpoint, {
        method,
        body: JSON.stringify(payload)
      });

      enterEditMode(result);
      renderSaveResult(preview, result, isUpdate ? 'Project changes saved.' : 'Project draft saved.');

      if (options && options.continueToCanon) {
        await initializeAndOpenCanonSetup(result.project_id || (result.manifest || {}).project_id);
      }

      await loadProjectList('active', { silent: true });
    } catch (error) {
      appendMessage(preview, `Save failed: ${error.message}`, 'error');
    } finally {
      setSavingState(false);
    }
  }

  async function loadProjectList(kind, options) {
    const isArchived = kind === 'archived';
    const target = document.getElementById(isArchived ? 'archived-project-state' : 'existing-project-state');
    if (!target) return;

    if (!options || !options.silent) {
      target.innerHTML = '<p class="setup-note">Loading projects…</p>';
    }

    try {
      const endpoint = isArchived ? '/api/projects?state=archived' : '/api/projects?state=active';
      const response = await apiFetch(endpoint);
      const projects = Array.isArray(response.projects) ? response.projects : [];
      renderProjectList(target, projects, { archived: isArchived });
    } catch (error) {
      target.innerHTML = `<p class="setup-error">Project list failed to load: ${escapeHtml(error.message)}</p>`;
    }
  }

  function renderProjectList(target, projects, options) {
    const archived = Boolean(options && options.archived);
    const visibleProjects = archived
      ? projects
      : projects.filter((project) => (project.manifest || {}).lifecycle_state !== 'ARCHIVED');

    if (!visibleProjects.length) {
      target.innerHTML = `<p class="setup-note">${archived ? 'No archived projects found.' : 'No existing projects found.'}</p>`;
      return;
    }

    target.innerHTML = `
      <div class="project-card-list">
        ${visibleProjects.map((project) => renderProjectCard(project, { archived })).join('')}
      </div>
    `;

    target.querySelectorAll('[data-resume-project-id]').forEach((button) => {
      button.addEventListener('click', () => resumeProject(button.dataset.resumeProjectId));
    });

    target.querySelectorAll('[data-restore-project-id]').forEach((button) => {
      button.addEventListener('click', () => restoreArchivedProject(button.dataset.restoreProjectId));
    });

    target.querySelectorAll('[data-delete-project-id]').forEach((button) => {
      button.addEventListener('click', () => deleteIncompleteProject(
        button.dataset.deleteProjectId,
        button.dataset.deleteProjectName
      ));
    });
  }

  function renderProjectCard(project, options) {
    const manifest = project.manifest || {};
    const resume = project.resume || {};
    const budget = project.budget_plan || {};
    const projectId = manifest.project_id || project.project_id || '';
    const lifecycle = manifest.lifecycle_state || 'UNKNOWN';
    const archived = Boolean(options && options.archived);
    const opensWorkspace = lifecycle === 'READY_FOR_WORKSPACE' || lifecycle === 'ACTIVE';
    const opensCanon = lifecycle === 'CANON_IN_PROGRESS';
    const buttonText = archived
      ? 'Restore Project'
      : opensWorkspace
        ? 'Open Workspace'
        : opensCanon
          ? 'Open Canon Setup'
          : 'Resume Setup';
    const actionAttr = archived ? 'data-restore-project-id' : 'data-resume-project-id';
    const deletable = !archived && (lifecycle === 'DRAFT_SETUP' || lifecycle === 'CANON_IN_PROGRESS');
    const projectName = manifest.project_name || 'Untitled Project';

    return `
      <article class="project-card">
        <h3>${escapeHtml(projectName)}</h3>
        <dl>
          <div><dt>Project ID</dt><dd>${escapeHtml(projectId)}</dd></div>
          <div><dt>Lifecycle</dt><dd class="human-readable-value">${escapeHtml(humanizeIdentifier(lifecycle, lifecycleLabels))}</dd></div>
          <div><dt>Genre</dt><dd class="human-readable-value">${escapeHtml(humanizeIdentifier(manifest.genre))}</dd></div>
          <div><dt>Budget</dt><dd>${escapeHtml(budget.token_budget_status || '—')}</dd></div>
        </dl>
        <p class="setup-note">Resume: ${escapeHtml(humanizeIdentifier(resume.resume_target || 'project_metadata'))}</p>
        <button type="button" class="primary-button project-card-action" ${actionAttr}="${escapeHtml(projectId)}">
          ${escapeHtml(buttonText)}
        </button>
        ${deletable
          ? `<button
               type="button"
               class="secondary-button project-card-action"
               data-delete-project-id="${escapeHtml(projectId)}"
               data-delete-project-name="${escapeHtml(projectName)}"
             >
               Delete Project
             </button>`
          : ''}
      </article>
    `;
  }

  async function resumeProject(projectId) {
    if (!projectId) return;

    try {
      const project = await apiFetch(`/api/project/${encodeURIComponent(projectId)}`);
      const manifest = project.manifest || {};
      const lifecycle = manifest.lifecycle_state;

      if (lifecycle === 'READY_FOR_WORKSPACE' || lifecycle === 'ACTIVE') {
        const migration = await apiFetch(
          `/api/project/${encodeURIComponent(projectId)}/canon/template-migration`
        );
        if (migration.migration_required || migration.persistence_conflict) {
          enterEditMode(project);
          await openCanonSetup(projectId);
          return;
        }

        window.location.href = `/workspace?project_id=${encodeURIComponent(projectId)}`;
        return;
      }

      if (lifecycle === 'ARCHIVED') {
        renderPickerMessage('existing-project-state', 'Archived projects must be restored before editing.', 'warning');
        return;
      }

      if (lifecycle === 'CANON_IN_PROGRESS') {
        enterEditMode(project);
        await openCanonSetup(projectId);
        return;
      }

      enterEditMode(project);
      showModal('new');
      renderEditModeNotice(project);
    } catch (error) {
      renderPickerMessage('existing-project-state', `Project failed to load: ${error.message}`, 'error');
    }
  }

  async function restoreArchivedProject(projectId) {
    if (!projectId) return;

    const target = document.getElementById('archived-project-state');
    try {
      const project = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/restore`, {
        method: 'POST'
      });
      renderPickerMessage('archived-project-state', `Restored ${projectId}. It is now available under Existing Projects.`, 'success');
      await loadProjectList('archived', { silent: true });
    } catch (error) {
      if (target) appendMessage(target, `Restore failed: ${error.message}`, 'error');
    }
  }


  async function deleteIncompleteProject(projectId, projectName) {
    if (!projectId) return;

    const displayName = String(projectName || projectId);
    const confirmed = window.confirm(
      `Delete "${displayName}"?\n\n`
      + 'This permanently removes this unfinished project and all project-local setup, Canon, planning, and runtime files.\n\n'
      + 'This cannot be undone.'
    );

    if (!confirmed) return;

    const target = document.getElementById('existing-project-state');
    try {
      const result = await apiFetch(`/api/project/${encodeURIComponent(projectId)}`, {
        method: 'DELETE'
      });

      if (state.activeProjectId === projectId) {
        state.activeProjectId = null;
        state.isEditMode = false;
        state.loadedProject = null;
      }

      await loadProjectList('active', { silent: true });
      renderPickerMessage(
        'existing-project-state',
        `Deleted unfinished project: ${result.project_name || displayName}.`,
        'success'
      );
    } catch (error) {
      if (target) appendMessage(target, `Delete failed: ${error.message}`, 'error');
    }
  }


  async function initializeAndOpenCanonSetup(projectId) {
    if (!projectId) return;

    try {
      await apiFetch(`/api/project/${encodeURIComponent(projectId)}/canon/initialize`, {
        method: 'POST'
      });
      await openCanonSetup(projectId);
    } catch (error) {
      appendMessage(getBudgetPreview(), `Canon setup failed to initialize: ${error.message}`, 'error');
    }
  }

  async function openCanonSetup(projectId) {
    if (!projectId) return;

    const target = document.getElementById('canon-setup-state');
    showModal('canon');

    if (target) {
      target.innerHTML = '<p class="setup-note">Loading canon architecture…</p>';
    }

    try {
      const setup = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/canon/setup`);
      renderCanonSetup(setup);
      bindCanonSetupActions(setup.project_id);
    } catch (error) {
      if (target) {
        target.innerHTML = `<p class="setup-error">Canon setup failed to load: ${escapeHtml(error.message)}</p>`;
      }
    }
  }

  function bindCanonSetupActions(projectId) {
    const confirmButton = document.getElementById('accept-genre-template');
    const backButton = document.getElementById('canon-back-to-project');

    if (confirmButton) {
      confirmButton.onclick = async () => {
        try {
          confirmButton.disabled = true;
          const setup = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/canon/confirm-template`, {
            method: 'POST'
          });
          renderCanonSetup(setup);
          bindCanonSetupActions(projectId);
        } catch (error) {
          const target = document.getElementById('canon-setup-state');
          appendMessage(target, `Template confirmation failed: ${error.message}`, 'error');
          confirmButton.disabled = false;
        }
      };
    }

    if (backButton) {
      backButton.onclick = () => {
        if (state.loadedProject) {
          showModal('new');
          renderEditModeNotice(state.loadedProject);
        } else {
          openModal('new');
        }
      };
    }

    document.querySelectorAll('[data-canon-action="complete-setup"]').forEach((button) => {
      button.onclick = async () => {
        await runCanonAction(
          projectId,
          `/api/project/${encodeURIComponent(projectId)}/canon/complete`,
          'Canon setup completion failed'
        );
      };
    });
  }

  async function runCanonAction(projectId, url, failurePrefix) {
    const target = document.getElementById('canon-setup-state');
    try {
      const setup = await apiFetch(url, { method: 'POST' });
      renderCanonSetup(setup);
      bindCanonSetupActions(projectId);
      if (setup.message) {
        appendMessage(target, setup.message, 'success');
      }
    } catch (error) {
      appendMessage(target, `${failurePrefix}: ${error.message}`, 'error');
    }
  }

  function renderCanonSetup(setup) {
    const target = document.getElementById('canon-setup-state');
    const confirmButton = document.getElementById('accept-genre-template');
    if (!target) return;

    const manifest = setup.manifest || {};
    const template = setup.template || {};
    const summary = setup.summary || {};
    const wizardState = setup.wizard_state || {};
    const hiddenLegacyGroupIds = new Set([
      'editable_canon',
      'locked_rules',
      'system_support_files',
      'structured_indexes',
      'runtime_knowledge_packs'
    ]);
    const groups = Array.isArray(setup.canon_groups)
      ? setup.canon_groups.filter(
          (group) => group && !hiddenLegacyGroupIds.has(group.group_id)
        )
      : [];
    const resumeTarget = (wizardState.resume_target || summary.resume_target || 'genre_template');

    target.innerHTML = `
      <section class="canon-template-summary">
        <dl>
          <div><dt>Project</dt><dd>${escapeHtml(manifest.project_name || setup.project_id)}</dd></div>
          <div><dt>Template</dt><dd>${escapeHtml(template.label || template.template_id || '—')}</dd></div>
          <div><dt>Seed Mode</dt><dd>${escapeHtml(template.seed_mode || '—')}</dd></div>
          <div><dt>Storage</dt><dd>${escapeHtml(template.project_storage_mode || '—')}</dd></div>
          <div><dt>Resume Target</dt><dd>${escapeHtml(resumeTarget)}</dd></div>
        </dl>
        <p class="setup-note">${escapeHtml(template.description || '')}</p>
        <p class="setup-note">
          Author-facing canon sections: ${Number(summary.author_section_count || 0)} total.
          Required: ${Number(summary.required_author_section_count || 0)}.
          Needing attention: ${Number(summary.attention_required_section_count || 0)}.
        </p>
        ${Array.isArray(summary.attention_required_sections) && summary.attention_required_sections.length
          ? `<p class="setup-note attention-required-list">Attention required: ${summary.attention_required_sections
              .map((section, index) => {
                const label = escapeHtml(
                  section.label || section.section_id || 'Canon section'
                );
                const colorClass = index % 2 === 0
                  ? 'attention-section-label--light'
                  : 'attention-section-label--gold';
                return `<span class="attention-section-label ${colorClass}">${label}</span>`;
              })
              .join('<span class="attention-section-separator">, </span>')}.</p>`
          : '<p class="setup-note">All canon sections are complete with verified current Markdown sources.</p>'}
      </section>
      <section class="canon-action-toolbar" aria-label="Canon setup actions">
        <button type="button" class="primary-button" data-canon-action="complete-setup" ${setup.read_only ? 'disabled' : ''}>Complete Canon Setup</button>
      </section>
      <div class="canon-group-list">
        ${groups.map(renderCanonGroup).join('')}
      </div>
      <section class="canon-workbook-shell" id="canon-workbook-shell" aria-label="Canon Workbook">
        <p class="setup-note">Canon Workbook status will load after template requirements.</p>
      </section>
    `;

    if (confirmButton) {
      confirmButton.disabled = resumeTarget !== 'genre_template' || Boolean(setup.read_only);
      confirmButton.textContent = resumeTarget === 'genre_template'
        ? 'Confirm Genre Template'
        : 'Template Confirmed';
    }

    if (window.ItalusCanonAuthoring && typeof window.ItalusCanonAuthoring.renderCanonWorkbookShell === 'function') {
      window.ItalusCanonAuthoring.renderCanonWorkbookShell({
        projectId: state.activeProjectId || setup.project_id,
        targetId: 'canon-workbook-shell'
      });
    }
  }

  function renderCanonGroup(group) {
    const items = Array.isArray(group.items) ? group.items : [];
    return `
      <article class="canon-group-card" data-status="${escapeHtml(group.status || 'UNKNOWN')}">
        <header>
          <h3>${escapeHtml(group.label || group.group_id)}</h3>
          <span>${escapeHtml(group.status || 'UNKNOWN')}</span>
        </header>
        <p>${escapeHtml(group.description || '')}</p>
        <div class="canon-item-list">
          ${items.map(renderCanonItem).join('')}
        </div>
      </article>
    `;
  }

  function renderCanonItem(item) {
    const files = Array.isArray(item.source_files) ? item.source_files : [];
    return `
      <section class="canon-item-card" data-status="${escapeHtml(item.status || 'UNKNOWN')}" data-wizard-status="${escapeHtml(item.wizard_status || item.status || '')}">
        <div>
          <strong>${escapeHtml(item.label || item.canon_id)}</strong>
          <span>${escapeHtml(item.role || '')} · ${item.editable ? 'editable' : 'locked'} · ${escapeHtml(item.source_strategy || '')} · ${escapeHtml(item.wizard_status || item.status || '')}</span>
        </div>
        <ul>
          ${files.map((file) => `
            <li class="${file.exists ? 'canon-file-detected' : 'canon-file-missing'}">
              ${file.exists ? '✓' : '•'} ${escapeHtml(file.display_path || file.relative_path || '')}
              <em>${escapeHtml(file.storage_scope || '')}</em>
            </li>
          `).join('')}
        </ul>
      </section>
    `;
  }

  function startNewProjectMode() {
    const form = getNewProjectForm();
    const preview = getBudgetPreview();

    state.activeProjectId = null;
    state.isEditMode = false;
    state.loadedProject = null;

    if (window.ItalusProjectWizard && form) {
      window.ItalusProjectWizard.resetProjectForm(form);
    }

    updateModalTitle('Create New Project', 'Define the project shell before entering the workspace. Canon setup follows after this stage.');
    updateSaveButtonText('Save Draft');
    removeEditNotice();

    if (form && preview) {
      const basics = window.ItalusProjectWizard.collectProjectBasics(form);
      window.ItalusProjectWizard.renderBudgetPreview(preview, window.ItalusProjectWizard.estimateBudget(basics));
    }
  }

  function enterEditMode(project) {
    const form = getNewProjectForm();

    state.activeProjectId = project.project_id || (project.manifest || {}).project_id || null;
    state.isEditMode = Boolean(state.activeProjectId);
    state.loadedProject = project;

    if (window.ItalusProjectWizard && form) {
      window.ItalusProjectWizard.hydrateProjectForm(form, project);
    }

    updateModalTitle('Edit Existing Project', 'Save changes back to the same project. No duplicate project will be created.');
    updateSaveButtonText('Save Changes');
  }

  function renderEditModeNotice(project) {
    const preview = getBudgetPreview();
    const budgetPlan = project.budget_plan || {};
    const resume = project.resume || {};
    if (!preview) return;

    window.ItalusProjectWizard.renderBudgetPreview(preview, budgetPlan);
    appendMessage(
      preview,
      `Editing existing project: ${state.activeProjectId}. Resume target: ${resume.resume_target || 'project_metadata'}.`,
      'success'
    );
  }

  function renderSaveResult(target, project, message) {
    if (!target) return;

    const manifest = project.manifest || {};
    const budgetPlan = project.budget_plan || {};
    const resume = project.resume || {};

    window.ItalusProjectWizard.renderBudgetPreview(target, budgetPlan);
    appendMessage(
      target,
      `${message} Project ID: ${manifest.project_id}. Lifecycle: ${manifest.lifecycle_state}. Resume: ${resume.resume_target || 'project_metadata'}.`,
      'success'
    );
  }

  function updateModalTitle(title, description) {
    const titleNode = document.getElementById('new-project-title');
    const header = titleNode ? titleNode.closest('.studio-modal-header') : null;
    const descriptionNode = header ? header.querySelector('p:last-child') : null;

    if (titleNode) titleNode.textContent = title;
    if (descriptionNode) descriptionNode.textContent = description;
  }

  function updateSaveButtonText(text) {
    const button = document.getElementById('save-project-draft');
    if (button) button.textContent = text;
  }

  function removeEditNotice() {
    document.querySelectorAll('.edit-mode-notice').forEach((node) => node.remove());
  }

  function setSavingState(isSaving) {
    const form = getNewProjectForm();
    if (!form) return;
    form.querySelectorAll('button').forEach((button) => {
      button.disabled = isSaving;
    });
  }

  async function apiFetch(url, options) {
    const requestOptions = Object.assign(
      {
        method: 'GET',
        headers: {
          Accept: 'application/json'
        }
      },
      options || {}
    );

    if (requestOptions.body) {
      requestOptions.headers = Object.assign({}, requestOptions.headers, {
        'Content-Type': 'application/json'
      });
    }

    const response = await fetch(url, requestOptions);
    const text = await response.text();
    let payload = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        throw new Error(`Invalid JSON response from ${url}`);
      }
    }

    if (!response.ok) {
      const detail = payload.detail || response.statusText || 'Request failed';
      throw new Error(detail);
    }

    return payload;
  }

  function appendMessage(target, message, kind) {
    if (!target) return;

    const className = kind === 'error'
      ? 'setup-error'
      : kind === 'warning'
        ? 'setup-warning'
        : 'setup-success';

    const messageNode = document.createElement('p');
    messageNode.className = className;
    messageNode.textContent = message;
    target.appendChild(messageNode);
  }

  function renderPickerMessage(targetId, message, kind) {
    const target = document.getElementById(targetId);
    if (!target) return;
    appendMessage(target, message, kind);
  }

  function debounce(callback, delay) {
    let timerId = null;
    return function debouncedCallback() {
      window.clearTimeout(timerId);
      timerId = window.setTimeout(callback, delay);
    };
  }

  function escapeHtml(value) {
    if (window.ItalusProjectWizard && window.ItalusProjectWizard.escapeHtml) {
      return window.ItalusProjectWizard.escapeHtml(value);
    }
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function init() {
    bindProjectActions();
    bindModalClose();
    bindNewProjectForm();
  }

  document.addEventListener('DOMContentLoaded', init);

  window.ItalusProjectLifecycle = {
    openModal,
    closeAllModals,
    openCanonSetup,
    state
  };
})();
