(function () {
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get('project_id');
  const legacyMode = params.get('mode') || 'workspace';

  const state = {
    bootstrap: null,
    activeSection: 'dashboard',
    projectRuntimeContext: null,
    projectRuntimeContextLoading: false,
    projectRuntimeContextApprovalLoading: false,
    bookPlan: null,
    bookPlanLoading: false,
    bookPlanSaving: false,
    bookPlanApprovalLoading: false,
    bookRuntimeContext: null,
    bookRuntimeContextLoading: false
  };

  const workspaceJsVersion = 'workspace-ux-stabilization-20260816';
  console.info(`[ITALUS] ${workspaceJsVersion} loaded`);
  const gatePanelNavigationVersion = 'workspace-gate-panel-navigation-v2-20260708';
  console.info(`[ITALUS] ${gatePanelNavigationVersion} loaded`);
  const providerStatusVersion = 'workspace-provider-author-view-cleanup-20260708';
  console.info(`[ITALUS] ${providerStatusVersion} loaded`);
  const runtimeStoragePreviewVersion = 'workspace-runtime-storage-preview-20260708';
  console.info(`[ITALUS] ${runtimeStoragePreviewVersion} loaded`);

  const modeLabel = document.getElementById('workspace-mode');
  const runtimeLog = document.getElementById('runtime-log');
  const mainPanel = document.getElementById('workspace-main-panel');
  const heading = document.getElementById('workspace-heading');

  const modeNames = {
    new: 'New Project',
    open: 'Existing Project',
    archive: 'Archived Project',
    workspace: 'Workspace'
  };

  document.addEventListener('DOMContentLoaded', init);

  async function init() {
    bindSidebar();
    bindTopMenu();
    bindRuntimeGateNavigation();

    if (!projectId) {
      renderNoProject();
      return;
    }

    await loadWorkspace(projectId);
  }

  async function loadWorkspace(id) {
    setLog(`Loading workspace bootstrap for ${id}…`);
    try {
      const bootstrap = await apiFetch(`/api/project/${encodeURIComponent(id)}/workspace/bootstrap`);
      state.bootstrap = bootstrap;
      state.activeSection = 'dashboard';

      renderInspector(bootstrap);
      applyMenuState(bootstrap);
      renderSection('dashboard');
      setLog(`Workspace bootstrap loaded for ${id}. Generation runtime disabled.`);
    } catch (error) {
      renderError(`Workspace bootstrap failed: ${error.message}`);
      setLog(`Workspace bootstrap failed for ${id}: ${error.message}`);
    }
  }

  function bindSidebar() {
    const explorer = document.querySelector('.project-explorer');
    if (!explorer) return;

    explorer.querySelectorAll('[data-workspace-section]').forEach((button) => {
      // Do not rely on the native disabled property here.
      // Some browsers/extensions can expose it as read-only on mixed elements,
      // and a disabled button will not fire click events needed for explanations.
      button.removeAttribute('disabled');
      button.dataset.workspaceEnabled = button.dataset.workspaceEnabled || 'true';
      button.setAttribute('aria-disabled', button.dataset.workspaceEnabled === 'false' ? 'true' : 'false');
    });

    explorer.addEventListener('click', (event) => {
      const button = event.target.closest('[data-workspace-section]');
      if (!button || !explorer.contains(button)) return;

      event.preventDefault();

      const sectionId = button.dataset.workspaceSection || 'dashboard';
      const enabled = button.dataset.workspaceEnabled !== 'false';

      if (!enabled) {
        const reason = button.dataset.disabledReason || 'This workspace function is not enabled yet.';
        setLog(reason);
        renderDisabled(button.textContent.trim() || labelFor(sectionId), reason);
        return;
      }

      renderSection(sectionId);
      setLog(`Opened ${button.textContent.trim() || labelFor(sectionId)}.`);
    });
  }

  function bindTopMenu() {
    document.querySelectorAll('[data-top-menu]').forEach((link) => {
      link.addEventListener('click', (event) => {
        const menu = link.dataset.topMenu;
        if (link.classList.contains('disabled-link')) {
          event.preventDefault();
          setLog(`${labelFor(menu)} is visible but disabled until project-scoped runtime migration is complete.`);
          return;
        }

        if (menu !== 'file') {
          event.preventDefault();
        }

        if (menu === 'project') renderSection('dashboard');
        if (menu === 'engine') renderSection('settings');
        if (menu === 'settings') renderSection('settings');
        if (menu === 'view') setLog('View controls are preserved. Explorer, inspector, and runtime console remain visible.');
      });
    });
  }

  function bindRuntimeGateNavigation() {
    if (!mainPanel) return;

    mainPanel.addEventListener('click', (event) => {
      const trigger = event.target.closest('[data-runtime-gate-section]');
      if (!trigger || !mainPanel.contains(trigger)) return;

      event.preventDefault();

      const targetSection = trigger.dataset.runtimeGateSection || 'dashboard';
      const gateLabel = trigger.dataset.runtimeGateLabel || 'Runtime Gate';
      const targetLabel = trigger.dataset.runtimeGateTargetLabel || labelFor(targetSection);

      renderSection(targetSection);
      setLog(`${gateLabel}: opened ${targetLabel} as a read-only migration panel. No runtime action was executed.`);
    });
  }


  function applyMenuState(bootstrap) {
    const items = flattenMenu(bootstrap.workspace_menu || []);

    document.querySelectorAll('[data-workspace-section]').forEach((button) => {
      const item = items[button.dataset.workspaceSection];
      if (!item) return;

      const enabled = item.enabled !== false;
      button.dataset.workspaceEnabled = enabled ? 'true' : 'false';
      button.classList.toggle('workspace-disabled', !enabled);
      button.setAttribute('aria-disabled', enabled ? 'false' : 'true');

      // Keep disabled items clickable so the Runtime Console can explain why.
      // Avoid assigning to button.disabled; the reported browser error was:
      // "TypeError: Cannot assign to read only property" from workspace.js.
      button.removeAttribute('disabled');

      if (item.disabled_reason) {
        button.dataset.disabledReason = item.disabled_reason;
        button.title = item.disabled_reason;
      } else {
        delete button.dataset.disabledReason;
        button.removeAttribute('title');
      }
    });
  }

  function renderSection(sectionId) {
    const bootstrap = state.bootstrap;
    if (!bootstrap) {
      renderNoProject();
      return;
    }

    state.activeSection = sectionId || 'dashboard';

    document.querySelectorAll('[data-workspace-section]').forEach((button) => {
      button.classList.toggle('active', button.dataset.workspaceSection === state.activeSection);
    });

    const manifest = bootstrap.manifest || {};
    const budget = bootstrap.budget_plan || {};
    const wizard = bootstrap.wizard_state || {};
    const context = bootstrap.project_context || {};
    const summary = bootstrap.summary || {};

    const viewMap = {
      dashboard: () => renderDashboard(manifest, budget, wizard, bootstrap),
      manuscript_plan: () => renderManuscriptPlan(manifest, budget, wizard, summary),
      budget_plan: () => renderBudgetPlan(budget, manifest),
      books: () => renderLibraryDetail('Books', manifest, bootstrap, {
        key: 'books',
        status: 'Planned',
        source: 'books_manifest',
        detail: `Books planned: ${number(manifest.book_count)}. This is a read-only planning view until project-scoped book records are wired.`,
        next: 'Load approved book manifest into project-local workspace browsing.'
      }),
      chapters: () => renderLibraryDetail('Chapters', manifest, bootstrap, {
        key: 'chapters',
        status: 'Planned',
        source: 'project manifest',
        detail: `${number(manifest.book_count)} book(s) × ${number(manifest.chapters_per_book)} chapters are planned.`,
        next: 'Wire chapter browsing after project-local manuscript storage is defined.'
      }),
      events: () => renderLibraryDetail('Events', manifest, bootstrap, {
        key: 'events',
        status: 'Reference only',
        source: 'events_manifest',
        detail: 'Events remain approved reference data. Runtime event selection is not active.',
        next: 'Expose event index read-only before runtime event routing.'
      }),
      scenes: () => renderLibraryDetail('Scenes', manifest, bootstrap, {
        key: 'scenes',
        status: 'Locked',
        source: 'project runtime',
        detail: 'Scene records are not project-scoped yet. Generation and scene saving remain disabled.',
        next: 'Migrate scene persistence behind a project-context-aware service.'
      }),
      characters: () => renderLibraryDetail('Characters', manifest, bootstrap, {
        key: 'characters',
        status: 'Reference only',
        source: 'character canon',
        detail: 'Character canon is approved as a reference. Editable character workspace is not enabled.',
        next: 'Add read-only character browsing from approved canon.'
      }),
      author_canon: () => renderAuthorCanon(bootstrap),
      project_runtime_context: () => renderProjectRuntimeContext(bootstrap),
      book_plan: () => renderBookPlan(bootstrap),
      book_runtime_context: () => renderBookRuntimeContext(bootstrap),
      settings: () => renderSettings(manifest, context, bootstrap),
      provider_status: () => renderProviderStatusPanel(manifest, bootstrap),
      runtime_storage_preview: () => renderRuntimeStoragePreview(manifest, context, bootstrap),
      archive: () => renderArchiveView(manifest, wizard),
      memory_continuity: () => renderDisabled('Memory / Continuity', 'Continuity memory is not yet project-scoped.'),
      validation: () => renderValidationReadinessPanel(manifest, context, bootstrap),
      output: () => renderExportReadinessPanel(manifest, context, bootstrap)
    };

    const renderer = viewMap[state.activeSection] || viewMap.dashboard;
    renderer();
  }

    function renderDashboard(manifest, budget, wizard, bootstrap) {
    setHeading('Project Dashboard');
    const summary = bootstrap.summary || {};
    const runtimeContext = bootstrap.runtime_context || {};
    const projectContext = runtimeContext.project || {};
    const bookPlan = runtimeContext.book_plan || {};
    const bookContext = runtimeContext.books || {};
    const gates = [
      ['Workspace Access', bootstrap.can_enter_workspace ? 'PASS' : 'BLOCKED', lifecycleLabel(manifest.lifecycle_state)],
      [
        'Author Canon',
        summary.attention_required_section_count ? 'ATTENTION' : 'PASS',
        `${number(summary.completed_required_author_section_count)} / ${number(summary.required_author_section_count)} required complete`
      ],
      [
        'Canon Markdown',
        summary.attention_required_section_count ? 'ATTENTION' : 'PASS',
        `${number(summary.current_markdown_source_count)} current sources`
      ],
      ['Project Runtime Context', String(projectContext.status || 'not_generated').toUpperCase(), projectContext.message || 'Not generated'],
      ['Book Plan', String(bookPlan.status || 'not_available').toUpperCase(), bookPlan.message || 'Not available'],
      ['Book Runtime Context', String(bookContext.status || 'blocked').toUpperCase(), bookContext.message || 'Blocked'],
      ['Generation', bootstrap.generation_enabled ? 'ENABLED' : 'DISABLED', 'Protected until runtime migration'],
      ['Validation', bootstrap.validation_enabled ? 'ENABLED' : 'DISABLED', 'Validation runtime is not wired'],
      ['Exports', bootstrap.exports_enabled ? 'ENABLED' : 'DISABLED', 'Output pipeline is not enabled']
    ];

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-navigation-detail-20260707">
        <p class="placeholder">The workspace is available. Author canon is project-local; runtime context and generation remain locked.</p>

        <section class="workspace-panel">
          <h3>Project Readiness</h3>
          <div class="workspace-stat-grid">
            ${statCard('Project', manifest.project_name || 'Untitled Project')}
            ${statCard('Lifecycle', lifecycleLabel(manifest.lifecycle_state), { humanReadable: true })}
            ${statCard('Resume Target', labelFor(wizard.resume_target || 'workspace'), { humanReadable: true })}
            ${statCard('Author Canon', `${number(summary.completed_required_author_section_count)} / ${number(summary.required_author_section_count)} complete`)}
            ${statCard('Needs Attention', number(summary.attention_required_section_count))}
            ${statCard('Current Markdown', number(summary.current_markdown_source_count))}
            ${statCard('Project Runtime Context', String(projectContext.status || 'not_generated').replace(/_/g, ' '))}
            ${statCard('Budget Status', budget.token_budget_status || '—')}
            ${statCard('Generation', bootstrap.generation_enabled ? 'Enabled' : 'Disabled')}
          </div>
        </section>

        <section class="workspace-panel">
          <h3>Readiness Gates</h3>
          <div class="workspace-gate-list">
            ${gates.map(([label, status, detail]) => readinessGate(label, status, detail)).join('')}
          </div>
        </section>

        ${runtimeLockPanel(bootstrap)}
      </div>
    `;
  }

  function renderManuscriptPlan(manifest, budget, wizard, summary) {
    setHeading('Manuscript Plan');
    mainPanel.innerHTML = `
      <div class="workspace-content">
        <p class="placeholder">Read-only manuscript plan from the project manifest and budget plan.</p>
        <dl class="workspace-definition-list">
          ${definition('Books', number(manifest.book_count))}
          ${definition('Chapters per Book', number(manifest.chapters_per_book))}
          ${definition('Target Words per Chapter', number(manifest.target_words_per_chapter))}
          ${definition('Target Words per Book', number(manifest.target_words_per_book))}
          ${definition('Target Total Words', number(manifest.target_total_words))}
          ${definition('Estimated Tokens Total', number(budget.estimated_tokens_total))}
          ${definition('Estimated Generation Passes', number(budget.estimated_generation_passes_required))}
          ${definition('Workspace Gate', wizard && wizard.can_enter_workspace ? 'Open' : 'Blocked')}
          ${definition('Author Canon', summary ? `${number(summary.completed_required_author_section_count)} / ${number(summary.required_author_section_count)} required complete` : '—')}
        </dl>
        <div class="workspace-disabled-note">This is planning metadata only. Manuscript generation remains locked.</div>
      </div>
    `;
  }

  function renderBudgetPlan(budget, manifest) {
    setHeading('Budget Plan');
    mainPanel.innerHTML = `
      <div class="workspace-content">
        <p class="placeholder">Budget planning is read-only in workspace bootstrap.</p>
        <dl class="workspace-definition-list">
          ${definition('Token Budget Total', number(budget.token_budget_total))}
          ${definition('Token Budget per Generation', number(budget.token_budget_per_generation))}
          ${definition('Token Multiplier', budget.token_multiplier || '—')}
          ${definition('Estimated Tokens per Chapter', number(budget.estimated_tokens_per_chapter))}
          ${definition('Estimated Tokens Total', number(budget.estimated_tokens_total))}
          ${definition('Budget Status', budget.token_budget_status || '—')}
          ${definition('Project Target Words', number(manifest && manifest.target_total_words))}
        </dl>
        <div class="workspace-disabled-note">Budget information is read-only. It does not trigger provider calls.</div>
      </div>
    `;
  }

  function renderLibraryDetail(title, manifest, bootstrap, detail) {
    setHeading(title);
    const summary = bootstrap.summary || {};
    const readOnlyData = bootstrap.read_only_data || {};
    const dataset = readOnlyData[detail.key] || {};
    const sample = Array.isArray(dataset.sample) ? dataset.sample : [];
    const sourceMode = readOnlyData.source_mode || 'not available';
    const runtimeMigration = readOnlyData.runtime_migration_status || 'not migrated';

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-navigation-detail-20260707 workspace-readonly-data-20260707">
        <p class="placeholder">${escapeHtml(detail.detail)}</p>
        <section class="workspace-panel">
          <h3>${escapeHtml(title)} Read-Only Data</h3>
          <dl class="workspace-definition-list">
            ${definition('Status', detail.status)}
            ${definition('Source', detail.source)}
            ${definition('Source Mode', sourceMode)}
            ${definition('Runtime Migration', runtimeMigration)}
            ${definition('Visible Records', number(dataset.count))}
            ${definition('Project', manifest.project_name || 'Untitled Project')}
            ${definition('Lifecycle', lifecycleLabel(manifest.lifecycle_state), { humanReadable: true })}
            ${definition('Author Canon', summary.attention_required_section_count ? 'Attention required' : 'Current')}
            ${definition('Next Safe Step', detail.next)}
          </dl>
        </section>
        ${readOnlySampleTable(title, sample)}
        <div class="workspace-disabled-note">
          Read-only data is loaded for inspection only. Creation, mutation, generation, validation, and output remain blocked.
        </div>
      </div>
    `;
  }

  function renderAuthorCanon(bootstrap) {
    setHeading('Author Canon');
    const status = bootstrap.author_canon_status || {};
    const markdownStatus = bootstrap.canon_markdown_status || {};
    const summary = bootstrap.summary || {};
    const markdownBySection = Object.fromEntries(
      (markdownStatus.rendered_files || [])
        .filter((item) => item && item.section_id)
        .map((item) => [item.section_id, item])
    );
    const rows = (status.sections || []).map((section) => {
      const markdown = markdownBySection[section.section_id] || {};
      const complete = section.status === 'complete'
        && !(section.missing_required_fields || []).length;
      const markdownState = markdown.render_status || 'not_rendered';
      return `
        <tr>
          <td>${escapeHtml(section.label || section.section_id || 'Canon section')}</td>
          <td>${statusBadge(complete ? 'COMPLETE' : String(section.status || 'NOT_STARTED').toUpperCase())}</td>
          <td>${statusBadge(String(markdownState).toUpperCase())}</td>
          <td>${number((section.missing_required_fields || []).length)}</td>
        </tr>
      `;
    }).join('');

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-navigation-detail-20260707">
        <p class="placeholder">
          Project-local author canon is the workspace source of truth. Editing remains on the Project page.
        </p>
        <div class="workspace-stat-grid">
          ${statCard('Author Sections', number(summary.author_section_count))}
          ${statCard('Required Complete', `${number(summary.completed_required_author_section_count)} / ${number(summary.required_author_section_count)}`)}
          ${statCard('Current Markdown', number(summary.current_markdown_source_count))}
          ${statCard('Needs Attention', number(summary.attention_required_section_count))}
        </div>
        ${table(['Section', 'Author State', 'Markdown State', 'Missing Required Fields'], rows)}
        <div class="workspace-disabled-note">
          This workspace view is read-only. It does not mutate canon, render Markdown, or route prompts.
        </div>
      </div>
    `;
  }

  function renderProjectRuntimeContext(bootstrap) {
    setHeading('Project Runtime Context');

    const bootstrapContext = (bootstrap.runtime_context || {}).project || {};
    const projectContext = state.projectRuntimeContext || bootstrapContext;
    const validation = projectContext.validation || {};
    const targets = projectContext.targets || projectContext.generated_packets || [];
    const locks = projectContext.execution_locks || {};
    const validationReady = projectContext.validation_ready === true;
    const artifactCurrent = projectContext.artifact_current === true;
    const approvalStatus = String(projectContext.approval_status || 'not_ready');
    const approvalFresh = projectContext.approval_fresh === true;
    const loading = state.projectRuntimeContextLoading === true
      || state.projectRuntimeContextApprovalLoading === true;
    const readOnly = bootstrap.read_only === true;
    const generateEnabled = validationReady && !loading && !readOnly;
    const approveEnabled = artifactCurrent && !approvalFresh && !loading && !readOnly;
    const revokeEnabled = ['approved', 'outdated'].includes(approvalStatus)
      && !loading && !readOnly;
    const targetRows = targets.map((target) => `
      <tr>
        <td>${escapeHtml(target.label || 'Project Runtime Context')}</td>
        <td>${statusBadge(String(target.status || (target.exists ? 'generated' : 'missing')).toUpperCase())}</td>
        <td><code>${escapeHtml(target.project_relative_path || target.relative_path || '—')}</code></td>
        <td>${target.sha256 ? `<code>${escapeHtml(String(target.sha256).slice(0, 16))}…</code>` : '—'}</td>
        <td>${target.source_set_sha256 ? `<code>${escapeHtml(String(target.source_set_sha256).slice(0, 16))}…</code>` : '—'}</td>
      </tr>
    `).join('');

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-project-runtime-approval-v1">
        <p class="placeholder">
          Review the project-level runtime context boundary. Approval is bound
          to the current artifact and current source-set SHA-256. Canon changes
          make the artifact and approval outdated.
        </p>
        <div class="workspace-stat-grid">
          ${statCard('Status', String(projectContext.status || 'not_generated').replace(/_/g, ' '))}
          ${statCard('Validation', validationReady ? 'Ready' : 'Blocked')}
          ${statCard('Artifact', artifactCurrent ? 'Current' : (projectContext.generated_count ? 'Outdated' : 'Missing'))}
          ${statCard('Approval', approvalStatus.replace(/_/g, ' '))}
          ${statCard('Freshness', approvalFresh ? 'current' : (approvalStatus === 'outdated' ? 'outdated' : 'not approved'))}
        </div>
        <section class="workspace-detail-card">
          <h3>Canon readiness</h3>
          <dl class="workspace-definition-grid workspace-definition-grid--compact">
            ${definition('Required sections', `${number(validation.required_sections_complete)} / ${number(validation.required_sections_total)}`)}
            ${definition('Rendered Markdown sources', number(validation.rendered_sources_total))}
          </dl>
          <details class="workspace-technical-details">
            <summary>Technical details</summary>
            <dl class="workspace-definition-grid workspace-definition-grid--compact">
              ${definition('Source-set SHA-256', projectContext.source_set_sha256 ? `${String(projectContext.source_set_sha256).slice(0, 20)}…` : '—')}
              ${definition('Approved artifact SHA-256', projectContext.approved_artifact_sha256 ? `${String(projectContext.approved_artifact_sha256).slice(0, 20)}…` : '—')}
              ${definition('Approved source-set SHA-256', projectContext.approved_source_set_sha256 ? `${String(projectContext.approved_source_set_sha256).slice(0, 20)}…` : '—')}
              ${definition('Approved at', projectContext.approved_at || '—')}
            </dl>
          </details>
        </section>
        <section class="workspace-detail-card">
          <h3>Project-local artifact</h3>
          ${table(['Artifact', 'State', 'Project path', 'SHA-256', 'Source-set SHA-256'], targetRows)}
        </section>
        <section class="workspace-detail-card">
          <h3>Execution boundary</h3>
          <div class="workspace-lock-grid">
            ${lockCard('Approval', approvalFresh ? 'Current' : 'Blocked')}
            ${lockCard('Prompt Builder', locks.prompt_builder_called ? 'Called' : 'Not called')}
            ${lockCard('Provider', locks.provider_called ? 'Called' : 'Blocked')}
            ${lockCard('Runtime Writes', locks.runtime_written ? 'Written' : 'Blocked')}
            ${lockCard('Draft Persistence', locks.draft_persisted ? 'Written' : 'Blocked')}
            ${lockCard('Generation Unlock', locks.generation_unlocked ? 'Unlocked' : 'Locked')}
          </div>
        </section>
        <div class="workspace-action-row">
          <button type="button" id="project-runtime-context-refresh" class="secondary-action" ${loading ? 'disabled' : ''}>${loading ? 'Working…' : 'Refresh Status'}</button>
          <button type="button" id="project-runtime-context-generate" class="primary-action" ${generateEnabled ? '' : 'disabled'}>Generate Project Runtime Context</button>
          <button type="button" id="project-runtime-context-approve" class="primary-action" ${approveEnabled ? '' : 'disabled'}>Approve Current Context</button>
          <button type="button" id="project-runtime-context-revoke" class="secondary-action" ${revokeEnabled ? '' : 'disabled'}>Revoke Approval</button>
        </div>
        <div class="workspace-disabled-note">${escapeHtml(projectContext.message || 'Project Runtime Context status is unavailable.')}</div>
      </div>
    `;
    document.getElementById('project-runtime-context-refresh')?.addEventListener('click', () => void loadProjectRuntimeContextStatus());
    document.getElementById('project-runtime-context-generate')?.addEventListener('click', () => void generateProjectRuntimeContext());
    document.getElementById('project-runtime-context-approve')?.addEventListener('click', () => void approveProjectRuntimeContext());
    document.getElementById('project-runtime-context-revoke')?.addEventListener('click', () => void revokeProjectRuntimeContextApproval());
    if (!state.projectRuntimeContext && !state.projectRuntimeContextLoading) void loadProjectRuntimeContextStatus();
  }

  async function loadProjectRuntimeContextStatus() {
    if (!projectId || state.projectRuntimeContextLoading) return;

    state.projectRuntimeContextLoading = true;
    if (state.activeSection === 'project_runtime_context') {
      renderProjectRuntimeContext(state.bootstrap);
    }

    try {
      const status = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/project/status`
      );
      state.projectRuntimeContext = status;
      setLog(`Project Runtime Context status: ${status.status || 'unknown'}.`);
    } catch (error) {
      state.projectRuntimeContext = {
        status: 'error',
        validation_ready: false,
        message: `Unable to load Project Runtime Context status: ${error.message}`,
        execution_locks: {
          prompt_builder_called: false,
          provider_called: false,
          runtime_written: false,
          draft_persisted: false,
          generation_unlocked: false
        }
      };
      setLog(state.projectRuntimeContext.message);
    } finally {
      state.projectRuntimeContextLoading = false;
      if (state.activeSection === 'project_runtime_context') {
        renderProjectRuntimeContext(state.bootstrap);
      }
      renderInspector(state.bootstrap);
    }
  }

  async function generateProjectRuntimeContext() {
    const status = state.projectRuntimeContext
      || ((state.bootstrap.runtime_context || {}).project || {});

    if (status.validation_ready !== true || state.projectRuntimeContextLoading) {
      setLog('Project Runtime Context generation remains blocked by canon readiness.');
      return;
    }

    state.projectRuntimeContextLoading = true;
    renderProjectRuntimeContext(state.bootstrap);
    setLog('Generating project-level Runtime Context…');

    try {
      const result = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/project/generate`,
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json'
          }
        }
      );
      state.projectRuntimeContext = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/project/status`
      );
      setLog('Project Runtime Context generated for author review and now requires approval. Generation remains locked.');
    } catch (error) {
      state.projectRuntimeContext = {
        ...status,
        status: 'error',
        message: `Project Runtime Context generation failed: ${error.message}`
      };
      setLog(state.projectRuntimeContext.message);
    } finally {
      state.projectRuntimeContextLoading = false;
      renderProjectRuntimeContext(state.bootstrap);
      renderInspector(state.bootstrap);
    }
  }

  async function approveProjectRuntimeContext() {
    if (!projectId || state.projectRuntimeContextApprovalLoading) return;
    state.projectRuntimeContextApprovalLoading = true;
    renderProjectRuntimeContext(state.bootstrap);
    try {
      state.projectRuntimeContext = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/project/approve`,
        { method: 'POST', headers: { Accept: 'application/json' } }
      );
      setLog('Project Runtime Context approved against current artifact and source hashes.');
    } catch (error) {
      setLog(`Project Runtime Context approval failed: ${error.message}`);
    } finally {
      state.projectRuntimeContextApprovalLoading = false;
      renderProjectRuntimeContext(state.bootstrap);
      renderInspector(state.bootstrap);
    }
  }

  async function revokeProjectRuntimeContextApproval() {
    if (!projectId || state.projectRuntimeContextApprovalLoading) return;
    state.projectRuntimeContextApprovalLoading = true;
    renderProjectRuntimeContext(state.bootstrap);
    try {
      state.projectRuntimeContext = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/project/revoke`,
        { method: 'POST', headers: { Accept: 'application/json' } }
      );
      setLog('Project Runtime Context approval revoked.');
    } catch (error) {
      setLog(`Project Runtime Context approval revocation failed: ${error.message}`);
    } finally {
      state.projectRuntimeContextApprovalLoading = false;
      renderProjectRuntimeContext(state.bootstrap);
      renderInspector(state.bootstrap);
    }
  }

  function renderBookPlan(bootstrap) {
    setHeading('Book Plan');

    const bootstrapPlan = (bootstrap.runtime_context || {}).book_plan || {};
    const response = state.bookPlan;
    const plan = response && response.plan
      ? response.plan
      : {
          status: bootstrapPlan.status || 'not_started',
          revision: bootstrapPlan.revision || 0,
          content_hash: bootstrapPlan.content_hash || '',
          book_count: bootstrapPlan.expected_book_count
            || bootstrapPlan.planned_book_count
            || (bootstrap.manifest || {}).book_count
            || 0,
          books: []
        };
    const validation = plan.validation || {
      valid: bootstrapPlan.valid === true,
      complete_book_count: bootstrapPlan.complete_book_count || 0,
      expected_book_count: bootstrapPlan.expected_book_count || plan.book_count || 0,
      issues: bootstrapPlan.issues || []
    };
    const loading = state.bookPlanLoading === true;
    const saving = state.bookPlanSaving === true;
    const approvalLoading = state.bookPlanApprovalLoading === true;
    const approvalStatus = String(
      plan.approval_status
      || bootstrapPlan.approval_status
      || 'not_ready'
    );
    const approvalFresh = plan.approval_fresh === true
      || bootstrapPlan.approval_fresh === true;
    const canApprove = validation.valid === true
      && !readOnly
      && !loading
      && !saving
      && !approvalLoading
      && approvalStatus !== 'approved';
    const canRevoke = !readOnly
      && !loading
      && !saving
      && !approvalLoading
      && (approvalStatus === 'approved' || approvalStatus === 'outdated');
    const readOnly = bootstrap.read_only === true
      || bootstrapPlan.authoring_enabled === false;
    const expectedBookCount = Number(
      validation.expected_book_count
      || plan.book_count
      || (bootstrap.manifest || {}).book_count
      || 0
    );
    const books = normalizeBookPlanBooks(plan.books || [], expectedBookCount);
    const issueRows = (validation.issues || []).map((issue) => `
      <tr>
        <td>${escapeHtml(issue.book_number ? `Book ${issue.book_number}` : 'Plan')}</td>
        <td>${escapeHtml(issue.code || 'validation_issue')}</td>
        <td>${escapeHtml(issue.message || 'Book Plan validation issue.')}</td>
      </tr>
    `).join('');

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-book-plan-authoring-v1">
        <p class="placeholder">
          Define project-local boundaries for each book. Saving changes only
          <code>book_plan.json</code>. Approval, book-pack compilation, prompt
          routing, provider execution, runtime memory, and generation remain locked.
        </p>

        <div class="workspace-stat-grid">
          ${statCard('Status', String(plan.status || 'not_started').replace(/_/g, ' '))}
          ${statCard('Complete Books', `${number(validation.complete_book_count)} / ${number(expectedBookCount)}`)}
          ${statCard('Revision', number(plan.revision))}
          ${statCard('Approval', approvalStatus.replace(/_/g, ' '))}
          ${statCard('Freshness', approvalFresh ? 'current' : (
            approvalStatus === 'outdated' ? 'outdated' : 'not approved'
          ))}
        </div>

        <section class="workspace-detail-card">
          <h3>Plan identity</h3>
          <dl class="workspace-definition-grid">
            ${definition('Project path', (response && response.project_relative_path) || bootstrapPlan.project_relative_path || 'book_plan.json')}
            ${definition('Schema', plan.schema_version || bootstrapPlan.schema_version || 'project_book_plan_v1')}
            ${definition('Content hash', plan.content_hash ? `${String(plan.content_hash).slice(0, 20)}…` : 'Not saved')}
            ${definition('Authoring', readOnly ? 'Read-only' : 'Enabled')}
            ${definition('Approved revision', number(plan.approved_revision || 0))}
            ${definition('Approved hash', plan.approved_content_hash
              ? `${String(plan.approved_content_hash).slice(0, 20)}…`
              : 'Not approved')}
            ${definition('Approved at', plan.approved_at || 'Not approved')}
          </dl>
        </section>

        <form id="book-plan-form" class="book-plan-form">
          ${books.map((book) => renderBookPlanCard(book, expectedBookCount, readOnly)).join('')}
        </form>

        <section class="workspace-detail-card">
          <h3>Validation</h3>
          ${validation.valid
            ? '<div class="workspace-success-note">All required Book Plan fields are complete.</div>'
            : table(['Scope', 'Code', 'Issue'], issueRows)}
        </section>

        <section class="workspace-detail-card">
          <h3>Execution boundary</h3>
          <div class="workspace-lock-grid">
            ${lockCard('Approval', approvalStatus.replace(/_/g, ' '))}
            ${lockCard('Book Pack Compilation', 'Blocked')}
            ${lockCard('Prompt Builder', 'Not called')}
            ${lockCard('Provider Calls', 'Blocked')}
            ${lockCard('Runtime Writes', 'Blocked')}
            ${lockCard('Generation Unlock', 'Locked')}
          </div>
        </section>

        <div class="workspace-action-row">
          <button type="button" id="book-plan-refresh" class="secondary-action"
            ${loading || saving ? 'disabled' : ''}>
            ${loading ? 'Loading…' : 'Reload Plan'}
          </button>
          <button type="button" id="book-plan-save" class="primary-action"
            ${readOnly || loading || saving || approvalLoading ? 'disabled' : ''}
            aria-disabled="${readOnly || loading || saving || approvalLoading ? 'true' : 'false'}">
            ${saving ? 'Saving…' : 'Save Book Plan Draft'}
          </button>
          <button type="button" id="book-plan-approve" class="primary-action"
            ${canApprove ? '' : 'disabled'}
            aria-disabled="${canApprove ? 'false' : 'true'}">
            ${approvalLoading ? 'Updating…' : 'Approve Current Plan'}
          </button>
          <button type="button" id="book-plan-revoke" class="secondary-action"
            ${canRevoke ? '' : 'disabled'}
            aria-disabled="${canRevoke ? 'false' : 'true'}">
            Revoke Approval
          </button>
        </div>

        <div class="workspace-disabled-note">
          ${escapeHtml(
            bootstrapPlan.message
            || (readOnly
              ? 'This Book Plan is read-only.'
              : 'Complete plans can be approved. Editing approved content makes approval outdated.')
          )}
        </div>
      </div>
    `;

    const refreshButton = document.getElementById('book-plan-refresh');
    if (refreshButton) {
      refreshButton.addEventListener('click', () => void loadBookPlan());
    }

    const saveButton = document.getElementById('book-plan-save');
    if (saveButton) {
      saveButton.addEventListener('click', () => void saveBookPlanDraft());
    }

    const approveButton = document.getElementById('book-plan-approve');
    if (approveButton) {
      approveButton.addEventListener('click', () => void approveBookPlan());
    }

    const revokeButton = document.getElementById('book-plan-revoke');
    if (revokeButton) {
      revokeButton.addEventListener('click', () => void revokeBookPlanApproval());
    }

    if (!state.bookPlan && !state.bookPlanLoading) {
      void loadBookPlan();
    }
  }

  function renderBookPlanCard(book, expectedBookCount, readOnly) {
    const bookNumber = Number(book.book_number || 0);
    const isFinalBook = bookNumber === expectedBookCount;
    const readonlyAttribute = readOnly ? 'readonly' : '';
    const disabledAttribute = readOnly ? 'disabled' : '';

    return `
      <article class="book-plan-card" data-book-card="${bookNumber}">
        <header>
          <div>
            <span class="eyebrow">Book ${bookNumber}</span>
            <h3>${escapeHtml(book.title || `Book ${bookNumber}`)}</h3>
          </div>
          ${statusBadge(bookPlanBookComplete(book, isFinalBook) ? 'COMPLETE' : 'DRAFT')}
        </header>

        <div class="book-plan-field-grid">
          ${bookPlanInput(bookNumber, 'title', 'Title', book.title, true, readonlyAttribute)}
          ${bookPlanInput(bookNumber, 'time_span', 'Time span', book.time_span, true, readonlyAttribute)}
        </div>

        ${bookPlanTextarea(bookNumber, 'primary_arc', 'Primary arc', book.primary_arc, true, readonlyAttribute)}
        ${bookPlanTextarea(bookNumber, 'ending_state', 'Ending state', book.ending_state, true, readonlyAttribute)}
        ${bookPlanTextarea(
          bookNumber,
          'handoff_to_next_book',
          isFinalBook ? 'Series closing handoff (optional)' : 'Handoff to next book',
          book.handoff_to_next_book,
          !isFinalBook,
          readonlyAttribute
        )}

        <div class="book-plan-field-grid">
          ${bookPlanListField(bookNumber, 'major_events', 'Major events', book.major_events, disabledAttribute)}
          ${bookPlanListField(bookNumber, 'required_characters', 'Required characters', book.required_characters, disabledAttribute)}
          ${bookPlanListField(bookNumber, 'required_locations', 'Required locations', book.required_locations, disabledAttribute)}
          ${bookPlanListField(bookNumber, 'allowed_reveals', 'Allowed reveals', book.allowed_reveals, disabledAttribute)}
          ${bookPlanListField(bookNumber, 'forbidden_future_knowledge', 'Forbidden future knowledge', book.forbidden_future_knowledge, disabledAttribute)}
        </div>

        ${bookPlanTextarea(bookNumber, 'notes', 'Author notes', book.notes, false, readonlyAttribute)}
      </article>
    `;
  }

  function bookPlanInput(bookNumber, field, label, value, required, readonlyAttribute) {
    return `
      <label class="book-plan-field">
        <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
        <input type="text"
          data-book-plan-field="${escapeHtml(field)}"
          data-book-number="${bookNumber}"
          value="${escapeHtml(value || '')}"
          ${required ? 'required' : ''}
          ${readonlyAttribute} />
      </label>
    `;
  }

  function bookPlanTextarea(bookNumber, field, label, value, required, readonlyAttribute) {
    return `
      <label class="book-plan-field">
        <span>${escapeHtml(label)}${required ? ' *' : ''}</span>
        <textarea rows="3"
          data-book-plan-field="${escapeHtml(field)}"
          data-book-number="${bookNumber}"
          ${required ? 'required' : ''}
          ${readonlyAttribute}>${escapeHtml(value || '')}</textarea>
      </label>
    `;
  }

  function bookPlanListField(bookNumber, field, label, values, disabledAttribute) {
    return `
      <label class="book-plan-field">
        <span>${escapeHtml(label)}</span>
        <textarea rows="4"
          data-book-plan-list-field="${escapeHtml(field)}"
          data-book-number="${bookNumber}"
          placeholder="One item per line"
          ${disabledAttribute}>${escapeHtml((values || []).join('\n'))}</textarea>
      </label>
    `;
  }

  function normalizeBookPlanBooks(books, expectedBookCount) {
    const byNumber = new Map(
      (books || []).map((book) => [Number(book.book_number), book])
    );
    const normalized = [];
    for (let bookNumber = 1; bookNumber <= expectedBookCount; bookNumber += 1) {
      normalized.push({
        book_number: bookNumber,
        title: '',
        time_span: '',
        primary_arc: '',
        major_events: [],
        required_characters: [],
        required_locations: [],
        ending_state: '',
        handoff_to_next_book: '',
        allowed_reveals: [],
        forbidden_future_knowledge: [],
        notes: '',
        ...(byNumber.get(bookNumber) || {})
      });
    }
    return normalized;
  }

  function bookPlanBookComplete(book, isFinalBook) {
    return Boolean(
      String(book.title || '').trim()
      && String(book.time_span || '').trim()
      && String(book.primary_arc || '').trim()
      && String(book.ending_state || '').trim()
      && (isFinalBook || String(book.handoff_to_next_book || '').trim())
    );
  }

  function collectBookPlanPayload() {
    const form = document.getElementById('book-plan-form');
    if (!form) throw new Error('Book Plan form is not available.');

    const bookNumbers = Array.from(
      form.querySelectorAll('[data-book-number]')
    )
      .map((node) => Number(node.dataset.bookNumber))
      .filter((value) => Number.isInteger(value) && value > 0);
    const uniqueBookNumbers = Array.from(new Set(bookNumbers)).sort(
      (left, right) => left - right
    );

    return {
      books: uniqueBookNumbers.map((bookNumber) => {
        const book = { book_number: bookNumber };

        form.querySelectorAll(
          `[data-book-plan-field][data-book-number="${bookNumber}"]`
        ).forEach((node) => {
          book[node.dataset.bookPlanField] = String(node.value || '').trim();
        });

        form.querySelectorAll(
          `[data-book-plan-list-field][data-book-number="${bookNumber}"]`
        ).forEach((node) => {
          book[node.dataset.bookPlanListField] = String(node.value || '')
            .split(/\r?\n/)
            .map((item) => item.trim())
            .filter(Boolean);
        });

        return book;
      })
    };
  }

  async function loadBookPlan() {
    if (!projectId || state.bookPlanLoading || state.bookPlanSaving) return;

    state.bookPlanLoading = true;
    if (state.activeSection === 'book_plan') {
      renderBookPlan(state.bootstrap);
    }

    try {
      state.bookPlan = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-plan`
      );
      setLog(
        `Book Plan loaded: ${state.bookPlan.plan.status || 'unknown'}, revision ${state.bookPlan.plan.revision || 0}.`
      );
    } catch (error) {
      state.bookPlan = {
        plan: {
          status: 'error',
          revision: 0,
          books: [],
          validation: {
            valid: false,
            issues: [{ code: 'load_failed', message: error.message }]
          }
        }
      };
      setLog(`Book Plan load failed: ${error.message}`);
    } finally {
      state.bookPlanLoading = false;
      if (state.activeSection === 'book_plan') {
        renderBookPlan(state.bootstrap);
      }
    }
  }

  async function saveBookPlanDraft() {
    const bootstrapPlan = (state.bootstrap.runtime_context || {}).book_plan || {};
    if (
      state.bootstrap.read_only === true
      || bootstrapPlan.authoring_enabled === false
      || state.bookPlanSaving
      || state.bookPlanLoading
    ) {
      setLog('Book Plan saving is not available in the current project state.');
      return;
    }

    let payload;
    try {
      payload = collectBookPlanPayload();
    } catch (error) {
      setLog(`Book Plan save blocked: ${error.message}`);
      return;
    }

    state.bookPlanSaving = true;
    renderBookPlan(state.bootstrap);
    setLog('Saving project-local Book Plan draft…');

    try {
      state.bookPlan = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-plan`,
        {
          method: 'PUT',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload)
        }
      );
      setLog(
        `Book Plan saved at revision ${state.bookPlan.plan.revision}. Approval and book-pack compilation remain locked.`
      );
    } catch (error) {
      setLog(`Book Plan save failed: ${error.message}`);
    } finally {
      state.bookPlanSaving = false;
      renderBookPlan(state.bootstrap);
      renderInspector(state.bootstrap);
    }
  }


  async function approveBookPlan() {
    if (
      !projectId
      || state.bookPlanApprovalLoading
      || state.bookPlanLoading
      || state.bookPlanSaving
    ) return;

    state.bookPlanApprovalLoading = true;
    renderBookPlan(state.bootstrap);
    setLog('Approving the current Book Plan content hash…');

    try {
      state.bookPlan = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-plan/approve`,
        {
          method: 'POST',
          headers: { Accept: 'application/json' }
        }
      );
      setLog(
        `Book Plan approved at revision ${state.bookPlan.plan.approved_revision}. Downstream generation remains locked.`
      );
    } catch (error) {
      setLog(`Book Plan approval failed: ${error.message}`);
    } finally {
      state.bookPlanApprovalLoading = false;
      renderBookPlan(state.bootstrap);
      renderInspector(state.bootstrap);
    }
  }

  async function revokeBookPlanApproval() {
    if (
      !projectId
      || state.bookPlanApprovalLoading
      || state.bookPlanLoading
      || state.bookPlanSaving
    ) return;

    state.bookPlanApprovalLoading = true;
    renderBookPlan(state.bootstrap);
    setLog('Revoking Book Plan approval…');

    try {
      state.bookPlan = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-plan/revoke`,
        {
          method: 'POST',
          headers: { Accept: 'application/json' }
        }
      );
      setLog('Book Plan approval revoked. Downstream generation remains locked.');
    } catch (error) {
      setLog(`Book Plan approval revocation failed: ${error.message}`);
    } finally {
      state.bookPlanApprovalLoading = false;
      renderBookPlan(state.bootstrap);
      renderInspector(state.bootstrap);
    }
  }

  function renderBookRuntimeContext(bootstrap) {
    setHeading('Book Runtime Context');

    const bootstrapContext = (bootstrap.runtime_context || {}).books || {};
    const bookContext = state.bookRuntimeContext || bootstrapContext;
    const plan = bookContext.book_plan || {};
    const projectContext = bookContext.project_runtime_context || {};
    const targets = bookContext.targets || [];
    const blockers = bookContext.blockers || [];
    const locks = bookContext.execution_locks || {};
    const loading = state.bookRuntimeContextLoading === true;
    const readOnly = bootstrap.read_only === true;
    const compilerReady = bookContext.compiler_ready === true;
    const compileEnabled = compilerReady && !readOnly && !loading;

    const targetRows = targets.map((target) => `
      <tr>
        <td>${escapeHtml(target.label || `Book ${target.book_number || '—'} Runtime Context`)}</td>
        <td>${statusBadge(String(target.status || (target.exists ? 'current' : 'missing')).toUpperCase())}</td>
        <td><code>${escapeHtml(target.project_relative_path || '—')}</code></td>
        <td>${target.sha256
          ? `<code>${escapeHtml(String(target.sha256).slice(0, 16))}…</code>`
          : '—'}</td>
        <td>${escapeHtml(String(target.source_book_plan_revision || '—'))}</td>
      </tr>
    `).join('');

    const blockerRows = blockers.map((blocker) => `
      <tr>
        <td>${escapeHtml(blocker.code || 'blocked')}</td>
        <td>${escapeHtml(blocker.message || 'Compilation is blocked.')}</td>
      </tr>
    `).join('');

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-book-runtime-context-review-v1">
        <p class="placeholder">
          Review one project-local runtime-context artifact per approved book.
          Compilation is derived from the current approved Book Plan and the
          current Project Runtime Context. Prompt, provider, runtime-memory,
          draft, export, and generation boundaries remain locked.
        </p>

        <div class="workspace-stat-grid">
          ${statCard('Status', String(bookContext.status || 'blocked').replace(/_/g, ' '))}
          ${statCard('Compiler', compilerReady ? 'Ready' : 'Blocked')}
          ${statCard('Current', `${number(bookContext.current_count)} / ${number(bookContext.target_count)}`)}
          ${statCard('Missing', number(bookContext.missing_count))}
          ${statCard('Outdated', number(bookContext.outdated_count))}
        </div>

        <section class="workspace-detail-card">
          <h3>Source readiness</h3>
          <dl class="workspace-definition-grid workspace-definition-grid--compact">
            ${definition('Book Plan status', labelFor(plan.status || 'not_started'))}
            ${definition('Book Plan approval', labelFor(plan.approval_status || 'not_ready'))}
            ${definition('Book Plan freshness', plan.approval_fresh === true ? 'Current' : 'Not Current')}
            ${definition('Book Plan revision', number(plan.revision))}
            ${definition('Project Runtime Context', projectContext.exists ? 'Present' : 'Missing')}
          </dl>
          <details class="workspace-technical-details">
            <summary>Technical details</summary>
            <dl class="workspace-definition-grid workspace-definition-grid--compact">
              ${definition('Project Runtime Context SHA-256', projectContext.sha256
                ? `${String(projectContext.sha256).slice(0, 20)}…`
                : '—')}
            </dl>
          </details>
        </section>

        <section class="workspace-detail-card">
          <h3>Book artifacts</h3>
          ${table(
            ['Artifact', 'State', 'Project path', 'SHA-256', 'Plan revision'],
            targetRows
          )}
        </section>

        <section class="workspace-detail-card">
          <h3>Compilation blockers</h3>
          ${blockers.length
            ? table(['Code', 'Reason'], blockerRows)
            : '<div class="workspace-success-note">No compilation blockers.</div>'}
        </section>

        <section class="workspace-detail-card">
          <h3>Execution boundary</h3>
          <div class="workspace-lock-grid">
            ${lockCard('Compilation', compilerReady ? 'Ready' : 'Blocked')}
            ${lockCard('Prompt Builder', locks.prompt_builder_called ? 'Called' : 'Not called')}
            ${lockCard('Provider', locks.provider_called ? 'Called' : 'Blocked')}
            ${lockCard('Registry Writes', locks.registry_written ? 'Written' : 'Blocked')}
            ${lockCard('Runtime Writes', locks.runtime_written ? 'Written' : 'Blocked')}
            ${lockCard('Draft Persistence', locks.draft_persisted ? 'Written' : 'Blocked')}
            ${lockCard('Generation Unlock', locks.generation_unlocked ? 'Unlocked' : 'Locked')}
          </div>
        </section>

        <div class="workspace-action-row">
          <button
            type="button"
            id="book-runtime-context-refresh"
            class="secondary-action"
            ${loading ? 'disabled' : ''}
          >${loading ? 'Refreshing…' : 'Refresh Status'}</button>
          <button
            type="button"
            id="book-runtime-context-generate"
            class="primary-action"
            ${compileEnabled ? '' : 'disabled'}
            aria-disabled="${compileEnabled ? 'false' : 'true'}"
          >${loading ? 'Working…' : 'Compile Book Runtime Context'}</button>
        </div>

        <div class="workspace-disabled-note">
          ${escapeHtml(
            bookContext.message
            || 'Book Runtime Context status is unavailable.'
          )}
          ${readOnly ? ' Archived projects are read-only.' : ''}
        </div>
      </div>
    `;

    const refreshButton = document.getElementById(
      'book-runtime-context-refresh'
    );
    if (refreshButton) {
      refreshButton.addEventListener('click', () => {
        void loadBookRuntimeContextStatus();
      });
    }

    const generateButton = document.getElementById(
      'book-runtime-context-generate'
    );
    if (generateButton) {
      generateButton.addEventListener('click', () => {
        void generateBookRuntimeContext();
      });
    }

    if (!state.bookRuntimeContext && !state.bookRuntimeContextLoading) {
      void loadBookRuntimeContextStatus();
    }
  }

  async function loadBookRuntimeContextStatus() {
    if (!projectId || state.bookRuntimeContextLoading) return;

    state.bookRuntimeContextLoading = true;
    if (state.activeSection === 'book_runtime_context') {
      renderBookRuntimeContext(state.bootstrap);
    }

    try {
      const status = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/books/status`
      );
      state.bookRuntimeContext = status;
      setLog(`Book Runtime Context status: ${status.status || 'unknown'}.`);
    } catch (error) {
      state.bookRuntimeContext = {
        status: 'error',
        compiler_ready: false,
        target_count: 0,
        current_count: 0,
        missing_count: 0,
        outdated_count: 0,
        targets: [],
        blockers: [{
          code: 'status_load_failed',
          message: error.message
        }],
        message: `Unable to load Book Runtime Context status: ${error.message}`,
        execution_locks: {
          book_runtime_context_compilation_enabled: false,
          prompt_builder_called: false,
          provider_called: false,
          registry_written: false,
          runtime_written: false,
          draft_persisted: false,
          generation_unlocked: false
        }
      };
      setLog(state.bookRuntimeContext.message);
    } finally {
      state.bookRuntimeContextLoading = false;
      if (state.activeSection === 'book_runtime_context') {
        renderBookRuntimeContext(state.bootstrap);
      }
      renderInspector(state.bootstrap);
    }
  }

  async function generateBookRuntimeContext() {
    const status = state.bookRuntimeContext
      || ((state.bootstrap.runtime_context || {}).books || {});

    if (
      status.compiler_ready !== true
      || state.bootstrap.read_only === true
      || state.bookRuntimeContextLoading
    ) {
      setLog(
        'Book Runtime Context compilation remains blocked by source readiness.'
      );
      return;
    }

    state.bookRuntimeContextLoading = true;
    renderBookRuntimeContext(state.bootstrap);
    setLog('Compiling one Book Runtime Context artifact per approved book…');

    try {
      const result = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/books/generate`,
        {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            'Content-Type': 'application/json'
          }
        }
      );
      setLog(
        `Compiled ${result.generated_count || 0} Book Runtime Context artifacts. Downstream generation remains locked.`
      );
      state.bookRuntimeContext = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/books/status`
      );
    } catch (error) {
      state.bookRuntimeContext = {
        ...status,
        status: 'error',
        compiler_ready: false,
        message: `Book Runtime Context compilation failed: ${error.message}`
      };
      setLog(state.bookRuntimeContext.message);
    } finally {
      state.bookRuntimeContextLoading = false;
      renderBookRuntimeContext(state.bootstrap);
      renderInspector(state.bootstrap);
    }
  }

  function renderSettings(manifest, context, bootstrap) {
    setHeading('Settings');
    mainPanel.innerHTML = `
      <div class="workspace-content">
        <p class="placeholder">Settings are read-only until project setup editing rules are defined for workspace-ready projects.</p>
        <dl class="workspace-definition-list">
          ${definition('Project ID', manifest.project_id)}
          ${definition('Template', manifest.template_id)}
          ${definition('Genre', labelFor(manifest.genre), { humanReadable: true })}
          ${definition('Engine', manifest.engine_id)}
          ${definition('AI Provider', manifest.ai_provider)}
          ${definition('Project Code', context.project_code)}
          ${definition('Storage Mode', context.storage_mode)}
          ${definition('Seed Mode', context.seed_mode)}
          ${definition('Runtime Ready', bootstrap && bootstrap.runtime_ready ? 'true' : 'false')}
          ${definition('Generation Enabled', bootstrap && bootstrap.generation_enabled ? 'true' : 'false')}
          ${definition('Validation Enabled', bootstrap && bootstrap.validation_enabled ? 'true' : 'false')}
          ${definition('Exports Enabled', bootstrap && bootstrap.exports_enabled ? 'true' : 'false')}
        </dl>
      </div>
    `;
  }


  function renderRuntimeStoragePreview(manifest, context, bootstrap) {
    setHeading('Project Writing Memory Preview');

    const projectIdValue = (manifest && manifest.project_id) || projectId || '<project_id>';
    const projectNameValue = (manifest && manifest.project_name) || projectIdValue;
    const runtimeStorage = (bootstrap && bootstrap.runtime_storage) || {};
    const storageRoot = runtimeStorage.runtime_root || (context && context.runtime_data_dir) || `data/projects/${projectIdValue}/runtime/`;
    const runtimeStatus = runtimeStorage.status || 'not_initialized';
    const runtimeFiles = Array.isArray(runtimeStorage.files) && runtimeStorage.files.length
      ? runtimeStorage.files
      : [
          {
            label: 'Books',
            role: 'author_facing',
            relative_path: `${storageRoot}books.json`,
            description: 'Project-local generated book-level manuscript records.',
            status: 'not_created'
          },
          {
            label: 'Chapters',
            role: 'author_facing',
            relative_path: `${storageRoot}chapters.json`,
            description: 'Project-local generated chapter records.',
            status: 'not_created'
          },
          {
            label: 'Scenes',
            role: 'author_facing',
            relative_path: `${storageRoot}scenes.json`,
            description: 'Project-local generated scene text and scene metadata.',
            status: 'not_created'
          },
          {
            label: 'Writing Session',
            role: 'author_facing',
            relative_path: `${storageRoot}session_state.json`,
            description: 'Project-local resumable writing session state.',
            status: 'not_created'
          },
          {
            label: 'Continuity Coverage',
            role: 'author_facing',
            relative_path: `${storageRoot}coverage_map.json`,
            description: 'Project-local continuity and coverage tracking.',
            status: 'not_created'
          },
          {
            label: 'Book State',
            role: 'internal_continuity',
            relative_path: `${storageRoot}book_state.json`,
            description: 'Internal project-local book generation state.',
            status: 'not_created'
          },
          {
            label: 'Chapter Continuity Digests',
            role: 'internal_continuity',
            relative_path: `${storageRoot}chapter_continuity_digests.json`,
            description: 'Internal project-local continuity digests used by later runtime migration stages.',
            status: 'not_created'
          }
        ];

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-runtime-storage-preview-20260708 workspace-runtime-storage-author-ux-20260708 workspace-project-runtime-storage-service-20260708 workspace-runtime-storage-auto-init-20260708">
        <p class="placeholder">
          This page shows the project’s backend-owned Writing Memory containers. They are prepared automatically by the project lifecycle and remain locked for generation until later runtime gates pass.
        </p>

        <section class="workspace-panel workspace-runtime-memory-summary">
          <h3>Writing Memory Status</h3>
          <dl class="workspace-definition-list">
            ${definition('Project', projectNameValue)}
            ${definition('Writing Memory', runtimeStatus === 'initialized' ? 'Initialized' : 'Not initialized yet')}
            ${definition('Backend Storage Status', runtimeStatus)}
            ${definition('Current Source', 'Read-only seed/reference data')}
            ${definition('Generation', bootstrap && bootstrap.generation_enabled ? 'Enabled' : 'Locked')}
          </dl>
          <div class="workspace-disabled-note">
            Technical storage target: Project-local runtime storage. The backend lifecycle prepares empty runtime files automatically and never copies legacy data.
          </div>
        </section>

        <section class="workspace-panel">
          <h3>What Will Be Saved Later</h3>
          <div class="workspace-runtime-storage-grid">
            ${runtimeStorageFolderCard(storageRoot, runtimeStorage).map(runtimeStorageStatusCard).concat(runtimeFiles.map(runtimeStorageStatusCard)).join('')}
          </div>
        </section>

        <section class="workspace-panel">
          <h3>Technical Storage Details</h3>
          <dl class="workspace-definition-list">
            ${definition('Project ID', projectIdValue)}
            ${definition('Runtime Folder', storageRoot)}
            ${definition('Runtime Folder Exists', runtimeStorage.runtime_root_exists ? 'Yes' : 'No')}
            ${definition('Runtime File Contract', runtimeStorage.file_contract_version || 'stage9_seven_file_contract')}
            ${definition('Required Runtime Files', runtimeStorage.required_file_count || runtimeFiles.length)}
            ${definition('Current Storage Mode', context && context.storage_mode ? context.storage_mode : 'legacy root data')}
            ${definition('Runtime Storage', runtimeStatus === 'initialized' ? 'Prepared automatically' : 'Not prepared')}
          </dl>
          <div class="workspace-disabled-note">
            Legacy read-only data remains the current source for browsing. Runtime storage is prepared as empty project-local containers for later generation migration.
          </div>
        </section>

        <section class="workspace-panel">
          <h3>What Is Still Locked</h3>
          <p class="placeholder">
            These actions stay locked after storage preparation. Runtime containers exist, but generation cannot write until prompt routing, provider execution, validation, and export gates are approved.
          </p>
          <div class="workspace-lock-grid">
            ${lockCard('Runtime Containers', runtimeStatus === 'initialized' ? 'Prepared' : 'Not prepared')}
            ${lockCard('Copy Legacy Data', 'Blocked')}
            ${lockCard('Save Generated Scenes', 'Blocked')}
            ${lockCard('Enable Generation', 'Blocked')}
          </div>
          <div class="workspace-disabled-note">
            The backend storage service is installed in status-only mode. It reports the seven-file runtime contract without enabling generation.
          </div>
        </section>
      </div>
    `;
  }

  function runtimeStorageFolderCard(storageRoot, runtimeStorage) {
    return [
      {
        label: 'Runtime Folder',
        role: 'runtime_root',
        relative_path: storageRoot,
        description: 'Project-local home for generated writing state once runtime storage is initialized.',
        status: runtimeStorage && runtimeStorage.runtime_root_exists ? 'present' : 'not_created'
      }
    ];
  }

  function runtimeStorageStatusCard(item) {
    const roleLabel = item.role === 'internal_continuity' ? 'Internal continuity state' : 'Author-facing writing memory';
    const path = item.relative_path || item.path || item.file_name || '';
    return `
      <article class="workspace-runtime-storage-card">
        <header>
          <strong>${escapeHtml(item.label || item.file_name || 'Runtime File')}</strong>
          <span>${escapeHtml(item.status || 'not_created')}</span>
        </header>
        <p>${escapeHtml(item.description || 'Project-local runtime file.')}</p>
        <div class="workspace-runtime-author-value">${escapeHtml(roleLabel)}</div>
        <code>Technical file: ${escapeHtml(path)}</code>
      </article>
    `;
  }


  function renderValidationReadinessPanel(manifest, context, bootstrap) {
    setHeading('Validation Readiness');

    const projectIdValue = (manifest && manifest.project_id) || projectId || '<project_id>';
    const validationChecks = [
      {
        label: 'Project Context',
        status: 'Pending',
        detail: 'Validation must read from project-local runtime storage after migration.'
      },
      {
        label: 'Canon Continuity',
        status: 'Pending',
        detail: 'Approved canon remains available as reference context but validation is not wired.'
      },
      {
        label: 'Scene Coverage',
        status: 'Pending',
        detail: 'Scene coverage checks wait for project-scoped scene records.'
      },
      {
        label: 'Runtime Results',
        status: 'Pending',
        detail: 'Validation result storage is not connected to this workspace.'
      }
    ];

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-validation-export-readiness-20260708 workspace-validation-export-contrast-fix-20260708">
        <p class="placeholder">
          Read-only validation readiness panel. This page shows what must be connected before validation can run.
        </p>

        <section class="workspace-panel">
          <h3>Validation Runtime Status</h3>
          <dl class="workspace-definition-list">
            ${definition('Project ID', projectIdValue)}
            ${definition('Validation', bootstrap && bootstrap.validation_enabled ? 'Enabled' : 'Locked')}
            ${definition('Runtime Ready', bootstrap && bootstrap.runtime_ready ? 'Ready' : 'Not ready')}
            ${definition('Generation', bootstrap && bootstrap.generation_enabled ? 'Enabled' : 'Locked')}
          </dl>
          <div class="workspace-disabled-note">
            No validation is run from this workspace.
          </div>
        </section>

        <section class="workspace-panel">
          <h3>Validation Readiness Gates</h3>
          <div class="workspace-readiness-grid">
            ${validationChecks.map(readinessCard).join('')}
          </div>
        </section>

        <section class="workspace-panel">
          <h3>Validation Boundary</h3>
          <div class="workspace-lock-grid">
            ${lockCard('Read Runtime Manuscript', 'Blocked')}
            ${lockCard('Run Continuity Checks', 'Blocked')}
            ${lockCard('Save Validation Results', 'Blocked')}
            ${lockCard('Unlock Generation', 'Blocked')}
          </div>
          <div class="workspace-disabled-note">
            Validation remains locked until runtime storage, prompt routing, and result persistence are migrated.
          </div>
        </section>
      </div>
    `;
  }

  function renderExportReadinessPanel(manifest, context, bootstrap) {
    setHeading('Export Readiness');

    const projectIdValue = (manifest && manifest.project_id) || projectId || '<project_id>';
    const exportRoot = `data/projects/${projectIdValue}/exports/`;
    const exportChecks = [
      {
        label: 'Manuscript Export',
        status: 'Pending',
        detail: 'Full manuscript export waits for project-local generated content.'
      },
      {
        label: 'Chapter Export',
        status: 'Pending',
        detail: 'Chapter export waits for project-scoped chapter and scene records.'
      },
      {
        label: 'Metadata Export',
        status: 'Pending',
        detail: 'Project metadata export is not wired to the workspace yet.'
      },
      {
        label: 'Export Storage',
        status: 'Pending',
        detail: `Future export output location: ${exportRoot}`
      }
    ];

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-validation-export-readiness-20260708 workspace-validation-export-contrast-fix-20260708">
        <p class="placeholder">
          Read-only export readiness panel. This page shows what must be connected before project exports can be produced.
        </p>

        <section class="workspace-panel">
          <h3>Export Pipeline Status</h3>
          <dl class="workspace-definition-list">
            ${definition('Project ID', projectIdValue)}
            ${definition('Exports', bootstrap && bootstrap.exports_enabled ? 'Enabled' : 'Locked')}
            ${definition('Runtime Ready', bootstrap && bootstrap.runtime_ready ? 'Ready' : 'Not ready')}
            ${definition('Generation', bootstrap && bootstrap.generation_enabled ? 'Enabled' : 'Locked')}
          </dl>
          <div class="workspace-disabled-note">
            No files are exported from this workspace.
          </div>
        </section>

        <section class="workspace-panel">
          <h3>Export Readiness Gates</h3>
          <div class="workspace-readiness-grid">
            ${exportChecks.map(readinessCard).join('')}
          </div>
        </section>

        <section class="workspace-panel">
          <h3>Export Boundary</h3>
          <div class="workspace-lock-grid">
            ${lockCard('Build Manuscript Files', 'Blocked')}
            ${lockCard('Write Export Files', 'Blocked')}
            ${lockCard('Download Package', 'Blocked')}
            ${lockCard('Publish Output', 'Blocked')}
          </div>
          <div class="workspace-disabled-note">
            Export remains locked until generated content, validation results, and output storage are migrated.
          </div>
        </section>
      </div>
    `;
  }

  function readinessCard(item) {
    return `
      <article class="workspace-readiness-card">
        <header>
          <strong>${escapeHtml(item.label)}</strong>
          <span>${escapeHtml(item.status)}</span>
        </header>
        <p>${escapeHtml(item.detail)}</p>
      </article>
    `;
  }


  function renderProviderStatusPanel(manifest, bootstrap) {
    setHeading('Provider Configuration Status');

    const selectedProvider = String((manifest && manifest.ai_provider) || 'claude').toLowerCase();
    const providers = providerStatusCatalog(selectedProvider);
    const cards = providers.map(providerStatusCard).join('');
    const selected = providers.find((provider) => provider.selected) || providers[0];

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-provider-status-panel workspace-provider-author-view-cleanup-20260708">
        <p class="placeholder">Read-only writing engine status for this project. This page shows which writing engines are available without checking API keys, calling providers, or enabling generation.</p>

        <section class="workspace-panel workspace-provider-summary">
          <h3>Writing Engine Status</h3>
          <div class="workspace-provider-summary-grid">
            ${statCard('Selected Writing Engine', selected ? selected.label : labelFor(selectedProvider))}
            ${statCard('Workspace Generation', bootstrap && bootstrap.generation_enabled ? 'Enabled' : 'Locked')}
            ${statCard('Connection Status', 'Not checked')}
            ${statCard('Provider Calls', 'Disabled')}
          </div>
          <div class="workspace-disabled-note">
            Generation remains locked until project-local runtime storage, prompt routing, validation, and output handling are migrated.
          </div>
        </section>

        <section class="workspace-panel">
          <h3>Available Writing Engines</h3>
          <div class="workspace-provider-grid">
            ${cards}
          </div>
        </section>

        <div class="workspace-disabled-note">
          No writing engine is contacted from this workspace. Account keys are never shown here.
        </div>
      </div>
    `;
  }

  function providerStatusCatalog(selectedProvider) {
    return [
      {
        id: 'claude',
        label: 'Claude',
        availability: 'Selected',
        description: 'Ready for future workspace connection after runtime migration.',
        selected: selectedProvider === 'claude'
      },
      {
        id: 'openai',
        label: 'OpenAI',
        availability: 'Available',
        description: 'Available as a writing engine option, but not connected to workspace generation yet.',
        selected: selectedProvider === 'openai'
      },
      {
        id: 'novelcraft',
        label: 'NovelCraft',
        availability: 'Available',
        description: 'Available as a writing engine option, but not connected to workspace generation yet.',
        selected: selectedProvider === 'novelcraft'
      }
    ];
  }

  function providerStatusCard(provider) {
    return `
      <article class="workspace-provider-card ${provider.selected ? 'selected' : ''}">
        <header>
          <strong>${escapeHtml(provider.label)}</strong>
          ${provider.selected ? statusBadge('SELECTED') : statusBadge('AVAILABLE')}
        </header>
        <p>${escapeHtml(provider.description)}</p>
        <dl class="workspace-definition-list compact">
          ${definition('Workspace Use', provider.selected ? 'Selected for this project' : 'Available for future selection')}
          ${definition('Generation', 'Locked until migration is complete')}
          ${definition('Connection', 'Not checked yet')}
        </dl>
      </article>
    `;
  }

  function renderArchiveView(manifest, wizard) {
    setHeading('Archive / Project Control');
    mainPanel.innerHTML = `
      <div class="workspace-content">
        <p class="placeholder">Project control is intentionally limited during workspace bootstrap.</p>
        <dl class="workspace-definition-list">
          ${definition('Project', manifest.project_name)}
          ${definition('Lifecycle', lifecycleLabel(manifest.lifecycle_state), { humanReadable: true })}
          ${definition('Workspace Access', wizard && wizard.can_enter_workspace ? 'Open' : 'Blocked')}
          ${definition('Resume Target', labelFor(wizard && wizard.resume_target), { humanReadable: true })}
        </dl>
        <div class="workspace-disabled-note">Archive controls will be wired after workspace bootstrap validation.</div>
      </div>
    `;
  }

  function renderDisabled(title, reason) {
    setHeading(title);
    mainPanel.innerHTML = `
      <div class="workspace-content workspace-navigation-detail-20260707">
        <p class="placeholder">${escapeHtml(reason)}</p>
        ${runtimeLockPanel(state.bootstrap || {})}
        <div class="workspace-disabled-note">
          This action is blocked by design. Runtime generation, validation, and output are not migrated yet.
        </div>
      </div>
    `;
  }


  function friendlyNumericIdentifier(value, prefix) {
    const raw = String(value || '').trim();
    const pattern = new RegExp(`^${prefix}_(\\d+)$`, 'i');
    const match = raw.match(pattern);

    if (!match) {
      return labelFor(raw || '—');
    }

    return `${labelFor(prefix)} ${Number(match[1])}`;
  }

  function friendlyChapterIdentifier(value) {
    const raw = String(value || '').trim();
    const match = raw.match(/^BOOK_(\d+)_CH_(\d+)$/i);

    if (!match) {
      return labelFor(raw || '—');
    }

    return `Book ${Number(match[1])}, Chapter ${Number(match[2])}`;
  }

  function chapterBookLabel(record) {
    const numberValue = Number(record && record.book_number);
    const idMatch = String(
      (record && record.book_id) || ''
    ).match(/BOOK_(\d+)/i);
    const parsedNumber = idMatch ? Number(idMatch[1]) : 0;
    const bookNumber = Number.isFinite(numberValue) && numberValue > 0
      ? numberValue
      : parsedNumber;
    const title = String(
      (record && record.book_title) || ''
    ).trim();

    if (bookNumber && title) {
      return `Book ${bookNumber}: ${title}`;
    }

    if (bookNumber) {
      return `Book ${bookNumber}`;
    }

    if (title) {
      return title;
    }

    return friendlyNumericIdentifier(
      record && record.book_id,
      'BOOK'
    );
  }

  function readOnlySampleTable(title, sample) {
    if (!sample.length) {
      return `
        <section class="workspace-panel">
          <h3>${escapeHtml(title)} Sample</h3>
          <p class="placeholder">No records are available in the current read-only payload.</p>
        </section>
      `;
    }

    if (title === 'Books') {
      const rows = sample.map((record) => {
        const numberValue = Number(record.book_number);
        const parsedNumber = Number(
          (String(record.book_id || '').match(/BOOK_(\d+)/i) || [])[1]
        );
        const bookNumber = Number.isFinite(numberValue) && numberValue > 0
          ? numberValue
          : parsedNumber;
        const titleValue = String(record.title || '').trim();
        const bookLabel = bookNumber
          ? `Book ${bookNumber}`
          : friendlyNumericIdentifier(record.book_id, 'BOOK');

        return `
          <tr>
            <td>${escapeHtml(bookLabel)}</td>
            <td>${escapeHtml(titleValue || 'Untitled Book')}</td>
            <td>${escapeHtml(labelFor(record.status || '—'))}</td>
          </tr>
        `;
      }).join('');

      return table(['Book', 'Title', 'Status'], rows);
    }

    if (title === 'Chapters') {
      const rows = sample.map((record) => `
        <tr>
          <td>${escapeHtml(friendlyChapterIdentifier(record.chapter_id))}</td>
          <td>${escapeHtml(chapterBookLabel(record))}</td>
          <td>${escapeHtml(record.title || `Chapter ${number(record.chapter_number)}`)}</td>
          <td>${escapeHtml(record.event_name || '—')}</td>
          <td>${escapeHtml(labelFor(record.status || '—'))}</td>
        </tr>
      `).join('');
      return table(['Chapter', 'Book', 'Title', 'Event', 'Status'], rows);
    }

    if (sample[0] && Object.prototype.hasOwnProperty.call(sample[0], 'name')) {
      const rows = sample.map((item) => `
        <tr>
          <td>${escapeHtml(item.name || '—')}</td>
          <td>${escapeHtml(Array.isArray(item.sources) ? item.sources.join(', ') : '—')}</td>
        </tr>
      `).join('');
      return table(['Name', 'Detected From'], rows);
    }

    const fields = Object.keys(sample[0] || {}).filter(
      (field) => !['book_title', 'book_number'].includes(field)
    );
    const rows = sample.map((record) => `
      <tr>
        ${fields.map((field) => `<td>${escapeHtml(formatCell(record[field]))}</td>`).join('')}
      </tr>
    `).join('');

    return table(fields.map(labelFor), rows);
  }

  function formatCell(value) {
    if (Array.isArray(value)) {
      return value.join(', ');
    }
    if (value && typeof value === 'object') {
      return JSON.stringify(value);
    }
    return value === undefined || value === null || value === '' ? '—' : String(value);
  }


  function readinessGate(label, status, detail) {
    const normalized = String(status || '').toLowerCase();
    return `
      <article class="workspace-readiness-gate ${normalized}">
        <div>
          <strong>${escapeHtml(label)}</strong>
          <span>${escapeHtml(detail)}</span>
        </div>
        <em>${escapeHtml(status)}</em>
      </article>
    `;
  }

  function runtimeLockPanel(bootstrap) {
    const runtimeReady = Boolean(bootstrap.runtime_ready);
    const generationEnabled = Boolean(bootstrap.generation_enabled);
    const validationEnabled = Boolean(bootstrap.validation_enabled);
    const exportsEnabled = Boolean(bootstrap.exports_enabled);

    return `
      <section class="workspace-panel workspace-runtime-lock-panel">
        <h3>Runtime Lock</h3>
        <p>Generation remains disabled until project-local runtime storage, prompt routing, validation, and provider execution are explicitly migrated.</p>
        <div class="workspace-lock-grid">
          ${lockCard('Project-local Runtime Storage', runtimeReady ? 'Ready' : 'Not Migrated')}
          ${lockCard('Prompt Builder Routing', 'Protected')}
          ${lockCard('AI Provider Runners', 'Protected')}
          ${lockCard('Generation Execution', generationEnabled ? 'Enabled' : 'Blocked')}
          ${lockCard('Validation Runtime', validationEnabled ? 'Enabled' : 'Disabled')}
          ${lockCard('Export Pipeline', exportsEnabled ? 'Enabled' : 'Disabled')}
        </div>
        ${renderRuntimeReadinessGateMap(bootstrap)}
      </section>
    `;
  }


  function renderRuntimeReadinessGateMap(bootstrap) {
    const gates = Array.isArray(bootstrap.runtime_readiness_gates) && bootstrap.runtime_readiness_gates.length
      ? bootstrap.runtime_readiness_gates
      : fallbackRuntimeReadinessGates(bootstrap);

    return `
      <section class="workspace-runtime-gate-map workspace-runtime-readiness-gate-map-20260707">
        <header>
          <h3>Runtime Readiness Gate Map</h3>
          <p>Read-only deployment control map. These gates explain why generation remains disabled.</p>
        </header>
        <div class="workspace-runtime-gate-grid">
          ${gates.map(runtimeReadinessGateCard).join('')}
        </div>
      </section>
    `;
  }

  function fallbackRuntimeReadinessGates(bootstrap) {
    const runtimeReady = Boolean(bootstrap.runtime_ready);
    const generationEnabled = Boolean(bootstrap.generation_enabled);
    const validationEnabled = Boolean(bootstrap.validation_enabled);
    const exportsEnabled = Boolean(bootstrap.exports_enabled);

    return [
      {
        label: 'Project Lifecycle',
        status: 'ready',
        owner: 'workspace service',
        reason: 'Project is allowed to enter the workspace shell.',
        next_step: 'Continue read-only workspace validation.'
      },
      {
        label: 'Canon Approval',
        status: 'ready',
        owner: 'canon setup',
        reason: 'Canon approval is complete for workspace access.',
        next_step: 'Preserve canon references as read-only runtime context.'
      },
      {
        label: 'Project-local Runtime Storage',
        status: runtimeReady ? 'ready' : 'blocked',
        owner: 'runtime migration',
        reason: runtimeReady ? 'Runtime storage is reported ready.' : 'Generation state has not been migrated into project-local storage.',
        next_step: 'Design project-local runtime storage before generation.'
      },
      {
        label: 'Prompt Builder Routing',
        status: 'locked',
        owner: 'prompt builder',
        reason: 'Prompt construction is protected from workspace execution.',
        next_step: 'Introduce a generation service boundary first.'
      },
      {
        label: 'AI Provider Execution',
        status: generationEnabled ? 'ready' : 'locked',
        owner: 'provider layer',
        reason: generationEnabled ? 'Generation is reported enabled.' : 'Provider runners are not called from workspace.',
        next_step: 'Define provider contracts before wiring execution.'
      },
      {
        label: 'Validation Runtime',
        status: validationEnabled ? 'ready' : 'blocked',
        owner: 'validation service',
        reason: validationEnabled ? 'Validation is reported enabled.' : 'Validation runtime is not wired.',
        next_step: 'Design validation service integration after runtime storage.'
      },
      {
        label: 'Export Pipeline',
        status: exportsEnabled ? 'ready' : 'blocked',
        owner: 'export workflow',
        reason: exportsEnabled ? 'Exports are reported enabled.' : 'Workspace exports are not available yet.',
        next_step: 'Define export workflow after manuscript state is project-local.'
      },
      {
        label: 'Generation Unlock',
        status: generationEnabled ? 'ready' : 'locked',
        owner: 'project control',
        reason: generationEnabled ? 'Generation is enabled.' : 'Generation remains intentionally disabled.',
        next_step: 'Unlock only after every runtime gate is resolved.'
      }
    ];
  }

  function runtimeReadinessGateCard(gate) {
    const status = String(gate.status || 'locked').toLowerCase();
    const normalized = ['ready', 'blocked', 'locked'].includes(status) ? status : 'locked';
    const gateLabel = gate.label || gate.id || 'Runtime Gate';
    const targetSection = runtimeGateTargetSection(gateLabel);
    const targetLabel = labelFor(targetSection);

    return `
      <article class="workspace-runtime-gate-card workspace-gate-panel-navigation-v2-20260708 ${escapeHtml(normalized)}">
        <header>
          <strong>${escapeHtml(gateLabel)}</strong>
          ${statusBadge((gate.status || 'locked').toUpperCase())}
        </header>
        <em>${escapeHtml(gate.owner || 'unassigned')}</em>
        <p>${escapeHtml(gate.reason || 'No reason provided.')}</p>
        <small>Next: ${escapeHtml(gate.next_step || gate.nextStep || 'No next step defined.')}</small>
        <div class="workspace-runtime-gate-navigation" aria-label="Read-only navigation target">
          <span>Navigation target: ${escapeHtml(targetLabel)}</span>
          <button
            type="button"
            class="workspace-runtime-gate-link"
            data-runtime-gate-section="${escapeHtml(targetSection)}"
            data-runtime-gate-label="${escapeHtml(gateLabel)}"
            data-runtime-gate-target-label="${escapeHtml(targetLabel)}"
          >
            Open panel: ${escapeHtml(targetLabel)}
          </button>
        </div>
      </article>
    `;
  }

  function runtimeGateTargetSection(label) {
    const normalizedLabel = String(label || '').toLowerCase();

    if (normalizedLabel.includes('canon')) return 'canon_dashboard';
    if (normalizedLabel.includes('storage')) return 'runtime_storage_preview';
    if (normalizedLabel.includes('provider')) return 'provider_status';
    if (normalizedLabel.includes('validation')) return 'validation';
    if (normalizedLabel.includes('export')) return 'output';

    return 'dashboard';
  }


  function lockCard(label, value) {
    return `
      <article class="workspace-lock-card">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </article>
    `;
  }

  function statusBadge(value) {
    return `<span class="workspace-status-badge">${escapeHtml(value || '—')}</span>`;
  }


  function renderInspector(bootstrap) {
    const manifest = bootstrap.manifest || {};
    const budget = bootstrap.budget_plan || {};
    const summary = bootstrap.summary || {};

    setText('inspector-project-status', lifecycleLabel(manifest.lifecycle_state));
    setText(
      'inspector-canon-status',
      summary.attention_required_section_count
        ? `${number(summary.attention_required_section_count)} section(s) need attention`
        : `${number(summary.completed_required_author_section_count)} / ${number(summary.required_author_section_count)} required complete`
    );
    const projectRuntime = state.projectRuntimeContext
      || (bootstrap.runtime_context || {}).project
      || {};
    setText(
      'inspector-runtime-status',
      bootstrap.generation_enabled
        ? 'Generation enabled'
        : `Project context: ${String(projectRuntime.status || 'not_generated').replace(/_/g, ' ')}`
    );
    setText('inspector-budget-status', `${budget.token_budget_status || '—'} · ${number(budget.token_budget_per_generation)} per generation`);
    if (modeLabel) {
      modeLabel.textContent = `Mode: ${modeNames[legacyMode] || 'Workspace'}`;
    }
  }

  function renderNoProject() {
    setHeading('Workspace');
    if (modeLabel) modeLabel.textContent = 'Mode: Workspace';
    if (mainPanel) {
      mainPanel.innerHTML = `
        <p class="placeholder">
          No project_id was provided. Return to Existing Projects and open a workspace-ready project.
        </p>
      `;
    }
    setLog('Workspace opened without project_id.');
  }

  function renderError(message) {
    setHeading('Workspace Error');
    if (mainPanel) {
      mainPanel.innerHTML = `<p class="placeholder workspace-error">${escapeHtml(message)}</p>`;
    }
  }

  function packetMatchesCanonIds(canonId, canonIds) {
    const normalized = String(canonId || '');
    return canonIds.some((expectedId) => {
      const expected = String(expectedId || '');
      return normalized === expected || normalized.startsWith(`${expected}_`);
    });
  }

  function packetStatusRow(packet) {
    return `
      <tr>
        <td>${escapeHtml(packet.canon_id || '—')}</td>
        <td>${escapeHtml(packet.status || '—')}</td>
        <td>${packet.required ? 'Required' : 'Optional'}</td>
        <td>${escapeHtml(packet.relative_path || '—')}</td>
        <td>${escapeHtml(packet.description || '—')}</td>
      </tr>
    `;
  }

  function referenceRow(canonId, ref) {
    if (!ref) {
      return `
        <tr>
          <td>${escapeHtml(canonId)}</td>
          <td>—</td>
          <td>—</td>
          <td>No approved reference found.</td>
        </tr>
      `;
    }

    const files = Array.isArray(ref.source_files)
      ? ref.source_files.map((file) => escapeHtml(file.display_path || file.relative_path || '')).join('<br>')
      : '—';

    return `
      <tr>
        <td>${escapeHtml(canonId)}</td>
        <td>${escapeHtml(ref.approval_type || '—')}</td>
        <td>${escapeHtml(ref.role || '—')}</td>
        <td>${files || '—'}</td>
      </tr>
    `;
  }

  async function apiFetch(url, options) {
    const response = await fetch(url, Object.assign({
      method: 'GET',
      headers: { Accept: 'application/json' }
    }, options || {}));

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
      throw new Error(payload.detail || response.statusText || 'Request failed');
    }

    return payload;
  }

  function setHeading(value) {
    if (heading) heading.textContent = value;
  }

  function setLog(value) {
    if (runtimeLog) runtimeLog.textContent = value;
  }

  function setText(id, value) {
    const node = document.getElementById(id);
    if (node) node.textContent = value;
  }

  function flattenMenu(groups) {
    const result = {};
    groups.forEach((group) => {
      (group.items || []).forEach((item) => {
        result[item.menu_id] = item;
      });
    });
    return result;
  }

  function statCard(label, value, options = {}) {
    const valueClass = options.humanReadable ? ' class="human-readable-value"' : '';
    return `
      <article class="workspace-stat-card">
        <span>${escapeHtml(label)}</span>
        <strong${valueClass}>${escapeHtml(value)}</strong>
      </article>
    `;
  }

  function definition(label, value, options = {}) {
    const valueClass = options.humanReadable ? ' class="human-readable-value"' : '';
    return `<div><dt>${escapeHtml(label)}</dt><dd${valueClass}>${escapeHtml(value)}</dd></div>`;
  }

  function table(headers, rows) {
    return `
      <div class="workspace-table-wrap">
        <table class="workspace-table">
          <thead>
            <tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join('')}</tr>
          </thead>
          <tbody>${rows || `<tr><td colspan="${headers.length}">No data available.</td></tr>`}</tbody>
        </table>
      </div>
    `;
  }

  function number(value) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed.toLocaleString() : '—';
  }

  const lifecycleLabels = {
    DRAFT_SETUP: 'Draft Setup',
    CANON_IN_PROGRESS: 'Canon Setup in Progress',
    READY_FOR_WORKSPACE: 'Ready for Workspace',
    ACTIVE: 'Active',
    ARCHIVED: 'Archived'
  };

  function lifecycleLabel(value) {
    const raw = String(value || '').trim();
    return lifecycleLabels[raw] || labelFor(raw || 'Unknown');
  }

  function labelFor(value) {
    return String(value || '')
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
})();
