(function () {
  const params = new URLSearchParams(window.location.search);
  const projectId = params.get('project_id');
  const legacyMode = params.get('mode') || 'workspace';

  const state = {
    bootstrap: null,
    activeSection: 'dashboard',
    activeTab: 'overview'
  };

  const workspaceJsVersion = 'workspace-navigation-detail-20260707';
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
    bindTabs();
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
      state.activeTab = 'overview';

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

  function bindTabs() {
    document.querySelectorAll('[data-workspace-tab]').forEach((button) => {
      button.addEventListener('click', () => {
        document.querySelectorAll('[data-workspace-tab]').forEach((item) => item.classList.remove('active'));
        button.classList.add('active');
        state.activeTab = button.dataset.workspaceTab || 'overview';
        renderSection(state.activeSection);
      });
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
    const approvedRefs = bootstrap.approved_canon_refs || {};
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
      canon_dashboard: () => renderCanonDashboard(wizard, approvedRefs, summary),
      world_canon: () => renderCanonFiltered('World Canon', approvedRefs, ['world_bible']),
      character_canon: () => renderCanonFiltered('Character Canon', approvedRefs, ['character_bible', 'historical_character_interaction_map']),
      story_flow: () => renderCanonFiltered('Story Flow / Saga Canon', approvedRefs, ['master_storytelling_context', 'book_generation_engine']),
      timeline_backbone: () => renderCanonFiltered('Timeline / Event Backbone', approvedRefs, ['events_manifest', 'timeline_drift_detector']),
      continuity_rules: () => renderCanonFiltered('Continuity Rules', approvedRefs, ['continuity_prompt', 'timeline_drift_detector']),
      core_pack: () => renderRuntimePacks('Core Pack', approvedRefs, ['core_knowledge_pack']),
      generation_pack: () => renderRuntimePacks('Generation Pack', approvedRefs, ['generation_knowledge_pack']),
      book_packs: () => renderRuntimePacks('Book Packs', approvedRefs, ['book_knowledge_packs']),
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
    const gates = [
      ['Workspace Access', wizard.can_enter_workspace ? 'PASS' : 'BLOCKED', wizard.resume_target || 'workspace'],
      ['Canon Setup', summary.canon_setup_completed ? 'PASS' : 'BLOCKED', `${number(summary.approved_reference_count)} / ${number(summary.required_canon_count)} approved`],
      ['Runtime Ready', bootstrap.runtime_ready ? 'PASS' : 'LOCKED', 'Project-local generation runtime is not migrated'],
      ['Generation', bootstrap.generation_enabled ? 'ENABLED' : 'DISABLED', 'Protected until runtime migration'],
      ['Validation', bootstrap.validation_enabled ? 'ENABLED' : 'DISABLED', 'Validation runtime is not wired'],
      ['Exports', bootstrap.exports_enabled ? 'ENABLED' : 'DISABLED', 'Output pipeline is not enabled']
    ];

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-navigation-detail-20260707">
        <p class="placeholder">Project setup is complete. This workspace is a read-only command surface until runtime migration is complete.</p>

        <section class="workspace-panel">
          <h3>Project Readiness</h3>
          <div class="workspace-stat-grid">
            ${statCard('Project', manifest.project_name || 'Untitled Project')}
            ${statCard('Lifecycle', manifest.lifecycle_state || 'UNKNOWN')}
            ${statCard('Resume Target', wizard.resume_target || 'workspace')}
            ${statCard('Canon Setup', summary.canon_setup_completed ? 'Complete' : 'Incomplete')}
            ${statCard('Approved Canon', `${number(summary.approved_reference_count)} / ${number(summary.required_canon_count)}`)}
            ${statCard('Runtime Packs', `${number(summary.runtime_pack_count)} approved`)}
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
          ${definition('Canon References', summary ? `${number(summary.approved_reference_count)} / ${number(summary.required_canon_count)}` : '—')}
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
            ${definition('Lifecycle', manifest.lifecycle_state || 'UNKNOWN')}
            ${definition('Canon Gate', summary.canon_setup_completed ? 'Complete' : 'Incomplete')}
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

  function renderCanonDashboard(wizard, approvedRefs, summary) {
    setHeading('Canon Dashboard');
    const statuses = wizard.canon_set_statuses || {};
    const canonIds = Object.keys(statuses).sort();
    const items = canonIds.map((canonId) => {
      const ref = approvedRefs[canonId] || {};
      const fileCount = Array.isArray(ref.source_files) ? ref.source_files.length : 0;
      return `
        <tr>
          <td>${escapeHtml(canonId)}</td>
          <td>${statusBadge(statuses[canonId])}</td>
          <td>${escapeHtml(ref.approval_type || '—')}</td>
          <td>${escapeHtml(ref.role || '—')}</td>
          <td>${number(fileCount)}</td>
        </tr>
      `;
    }).join('');

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-navigation-detail-20260707">
        <p class="placeholder">Approved canon is read-only in the workspace phase. Canon mutation remains blocked.</p>

        <div class="workspace-stat-grid">
          ${statCard('Approved References', `${number(summary && summary.approved_reference_count)} / ${number(summary && summary.required_canon_count)}`)}
          ${statCard('Runtime Packs', `${number(summary && summary.runtime_pack_count)} approved`)}
          ${statCard('Canon Editing', 'Disabled')}
          ${statCard('Canon Mutation', 'Blocked')}
        </div>

        ${table(['Canon ID', 'Status', 'Approval Type', 'Role', 'Sources'], items)}
      </div>
    `;
  }

  function renderCanonFiltered(title, approvedRefs, canonIds) {
    setHeading(title);
    const rows = canonIds.map((canonId) => referenceRow(canonId, approvedRefs[canonId])).join('');
    mainPanel.innerHTML = `
      <div class="workspace-content workspace-navigation-detail-20260707">
        <p class="placeholder">Reference-approved canon. Review/edit actions are not enabled in this patch.</p>
        ${table(['Canon ID', 'Approval Type', 'Role', 'Source Files'], rows)}
        <div class="workspace-disabled-note">This panel proves reference availability only. It does not mutate canon or route prompts.</div>
      </div>
    `;
  }

  function renderRuntimePacks(title, approvedRefs, canonIds) {
    setHeading(title);
    const rows = canonIds.map((canonId) => referenceRow(canonId, approvedRefs[canonId])).join('');
    mainPanel.innerHTML = `
      <div class="workspace-content workspace-navigation-detail-20260707">
        <p class="placeholder">Runtime packs are approved reference artifacts for token control. They are visible but not injected into live generation here.</p>
        <div class="workspace-lock-grid">
          ${lockCard('Runtime Pack Status', 'Approved Reference')}
          ${lockCard('Prompt Injection', 'Disabled')}
          ${lockCard('Generation Runtime', 'Disabled')}
          ${lockCard('Provider Calls', 'Blocked')}
        </div>
        ${table(['Pack ID', 'Approval Type', 'Role', 'Source Files'], rows)}
      </div>
    `;
  }

  function renderSettings(manifest, context, bootstrap) {
    setHeading('Settings');
    mainPanel.innerHTML = `
      <div class="workspace-content">
        <p class="placeholder">Settings are read-only until project setup editing rules are defined for workspace-ready projects.</p>
        <dl class="workspace-definition-list">
          ${definition('Project ID', manifest.project_id)}
          ${definition('Template', manifest.template_id)}
          ${definition('Genre', manifest.genre)}
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
          ${definition('Lifecycle', manifest.lifecycle_state)}
          ${definition('Workspace Access', wizard && wizard.can_enter_workspace ? 'Open' : 'Blocked')}
          ${definition('Resume Target', wizard && wizard.resume_target)}
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


  function readOnlySampleTable(title, sample) {
    if (!sample.length) {
      return `
        <section class="workspace-panel">
          <h3>${escapeHtml(title)} Sample</h3>
          <p class="placeholder">No records are available in the current read-only payload.</p>
        </section>
      `;
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

    const fields = Object.keys(sample[0] || {});
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

    setText('inspector-project-status', manifest.lifecycle_state || 'UNKNOWN');
    setText(
      'inspector-canon-status',
      summary.canon_setup_completed
        ? `Complete · ${number(summary.approved_reference_count)} approved`
        : 'Incomplete'
    );
    setText('inspector-runtime-status', bootstrap.generation_enabled ? 'Enabled' : 'Generation disabled');
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

  function statCard(label, value) {
    return `
      <article class="workspace-stat-card">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </article>
    `;
  }

  function definition(label, value) {
    return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;
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
