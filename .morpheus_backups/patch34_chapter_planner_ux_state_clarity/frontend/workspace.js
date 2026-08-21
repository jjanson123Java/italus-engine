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
    bookPlanBookNumber: 1,
    bookRuntimeContext: null,
    bookRuntimeContextLoading: false,
    bookScope: null,
    bookScopeCatalog: null,
    bookScopeLoading: false,
    bookScopeSaving: false,
    bookScopeBookNumber: 1,
    bookScopeQuery: '',
    bookScopeIncludeFuture: false,
    bookScopeError: '',
    chapterPlan: null,
    chapterPlanBookCatalog: null,
    chapterPlanEventCandidates: null,
    chapterPlanPossibleDirections: null,
    chapterPlanLoading: false,
    chapterPlanSaving: false,
    chapterPlanBookNumber: 1,
    chapterPlanChapterNumber: 1,
    chapterPlanEventQuery: '',
    chapterPlanAnchorEventId: '',
    chapterPlanEffectiveScope: null,
    chapterPlanAmendCatalog: null,
    chapterPlanAmendQuery: '',
    chapterPlanIntentQuery: '',
    chapterPlanIntentResult: null,
    chapterPlanIntentLoading: false,
    storyControls: null,
    plannerRevealCatalog: null,
    storyControlSaving: false,
    chapterKnowledgePack: null,
    chapterKnowledgePackLoading: false,
    chapterBookKnowledgeCompileLoading: false,
    chapterPriorEndingContext: '',
    chapterPlanDraft: null,
    chapterPlanDirectionsLoading: false,
    chapterPlanDirectionsQueried: false,
    chapterPlanAmendLoading: false,
    chapterPlanAmendQueried: false,
    chapterPlanSavedNotice: '',
    chapterPlanDraftDirty: false,
    chapterPlannerDraftVersion: 0,
    chapterKnowledgePackRequestToken: 0
  };

  const workspaceJsVersion = 'workspace-book-plan-flattened-canon-timespan-20260818';
  console.info(`[ITALUS] ${workspaceJsVersion} loaded`);
  const plannerIntentVersion = 'workspace-planner-intent-model-v1-20260817';
  console.info(`[ITALUS] ${plannerIntentVersion} loaded`);
  const chapterKnowledgePackVersion = 'workspace-chapter-knowledge-pack-v1-20260817';
  console.info(`[ITALUS] ${chapterKnowledgePackVersion} loaded`);
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
    bindChapterPlannerDelegatedActions();

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
        if (menu === 'view') setLog('Author workspace uses the full available width; project status remains available from Dashboard and runtime views.');
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



  function refreshChapterSelectedCountFromDom() {
    if (!mainPanel) return;
    const canonCount = mainPanel.querySelectorAll('[data-chapter-canon-ref]:checked').length;
    const eventCount = mainPanel.querySelectorAll('#chapter-event-sequence-list [data-chapter-event-ref]:checked').length;
    const target = document.getElementById('chapter-selected-summary-count');
    if (target) target.textContent = `${canonCount} Canon · ${eventCount} sequenced events`;
  }

  function syncChapterPlannerEmptyStates() {
    const states = [
      ['chapter-selected-summary-body', '[data-chapter-canon-row]', 'Nothing selected for this chapter yet.'],
      ['chapter-available-canon-list', '[data-chapter-canon-row]', 'No additional characters or locations are available from Canon for This Book.'],
      ['chapter-event-sequence-list', '[data-chapter-event-row]', 'No events sequenced yet.'],
      ['chapter-event-available-list', '[data-chapter-event-row]', 'No additional Canon events are available.']
    ];
    states.forEach(([containerId, rowSelector, emptyMessage]) => {
      const container = document.getElementById(containerId);
      if (!container) return;
      const hasRows = Boolean(container.querySelector(rowSelector));
      const note = container.querySelector('.workspace-disabled-note');
      if (hasRows && note) note.remove();
      if (!hasRows && !note) {
        const empty = document.createElement('div');
        empty.className = 'workspace-disabled-note';
        empty.textContent = emptyMessage;
        container.appendChild(empty);
      }
    });
  }

  function moveChapterCanonRow(recordId, toSelected) {
    if (!mainPanel || !recordId) return;
    const row = mainPanel.querySelector(`[data-chapter-canon-row="${CSS.escape(recordId)}"]`);
    const selectedFlag = row?.querySelector('[data-chapter-canon-ref]');
    const batchBox = row?.querySelector('[data-chapter-canon-batch-ref]');
    const selectedContainer = document.getElementById('chapter-selected-summary-body');
    const availableContainer = document.getElementById('chapter-available-canon-list');
    if (!row || !selectedFlag || !selectedContainer || !availableContainer) return;
    selectedFlag.checked = toSelected;
    if (batchBox) batchBox.checked = false;
    row.classList.toggle('is-selected', toSelected);
    const povWrap = row.querySelector('[data-chapter-pov-wrap]');
    const pov = row.querySelector('[data-chapter-pov-ref]');
    if (povWrap) povWrap.hidden = !toSelected;
    if (!toSelected && pov) pov.checked = false;
    const actionButton = row.querySelector('[data-chapter-canon-add], [data-chapter-canon-return]');
    if (actionButton) {
      actionButton.textContent = toSelected ? 'Return' : 'Add to Chapter';
      actionButton.classList.toggle('primary-action', !toSelected);
      actionButton.classList.toggle('secondary-action', toSelected);
      actionButton.removeAttribute(toSelected ? 'data-chapter-canon-add' : 'data-chapter-canon-return');
      actionButton.setAttribute(toSelected ? 'data-chapter-canon-return' : 'data-chapter-canon-add', recordId);
    }
    (toSelected ? selectedContainer : availableContainer).appendChild(row);
    syncChapterPlannerEmptyStates();
    refreshChapterSelectedCountFromDom();
    markChapterPlannerDraftDirty();
  }

  function moveChapterEventCard(recordId, toSequence) {
    if (!mainPanel || !recordId) return;
    const row = mainPanel.querySelector(`[data-chapter-event-row="${CSS.escape(recordId)}"]`);
    const checkbox = row?.querySelector('[data-chapter-event-ref]');
    const controls = row?.querySelector('.chapter-event-controls');
    const sequence = document.getElementById('chapter-event-sequence-list');
    const available = document.getElementById('chapter-event-available-list');
    if (!row || !checkbox || !sequence || !available) return;
    checkbox.checked = toSequence;
    const batchBox = row.querySelector('[data-chapter-event-batch-ref]');
    if (batchBox) batchBox.checked = false;
    row.classList.toggle('is-selected', toSequence);
    if (controls) controls.hidden = !toSequence;
    const actionButton = row.querySelector('[data-event-add], [data-event-return]');
    if (actionButton) {
      actionButton.textContent = toSequence ? 'Return' : 'Add to Chapter';
      actionButton.removeAttribute(toSequence ? 'data-event-add' : 'data-event-return');
      actionButton.setAttribute(toSequence ? 'data-event-return' : 'data-event-add', recordId);
    }
    (toSequence ? sequence : available).appendChild(row);
    syncChapterPlannerEmptyStates();
    refreshChapterSelectedCountFromDom();
    markChapterPlannerDraftDirty();
  }

  function bindChapterPlannerDelegatedActions() {
    if (!mainPanel || mainPanel.dataset.chapterPlannerDelegatedBound === 'true') return;
    mainPanel.dataset.chapterPlannerDelegatedBound = 'true';
    mainPanel.addEventListener('click', (event) => {
      if (state.activeSection !== 'chapter_planner') return;

      const canonAdd = event.target.closest('[data-chapter-canon-add]');
      if (canonAdd) {
        event.preventDefault();
        moveChapterCanonRow(String(canonAdd.dataset.chapterCanonAdd || ''), true);
        return;
      }
      const canonReturn = event.target.closest('[data-chapter-canon-return]');
      if (canonReturn) {
        event.preventDefault();
        moveChapterCanonRow(String(canonReturn.dataset.chapterCanonReturn || ''), false);
        return;
      }
      const canonBatch = event.target.closest('[data-chapter-canon-batch-action]');
      if (canonBatch) {
        event.preventDefault();
        const action = String(canonBatch.dataset.chapterCanonBatchAction || '');
        const selectedContainer = document.getElementById('chapter-selected-summary-body');
        const availableContainer = document.getElementById('chapter-available-canon-list');

        if (action === 'return_all') {
          const selectedCount = selectedContainer?.querySelectorAll('[data-chapter-canon-row]').length || 0;
          if (!selectedCount) return;
          const confirmed = window.confirm(
            'Return all Canon selections from this chapter? ' +
            'This changes only the on-screen Chapter Plan draft until you press Save Chapter Plan. ' +
            'The existing Chapter Knowledge Pack files will remain unchanged until you compile the pack again.'
          );
          if (!confirmed) return;
        }

        const boxes = action === 'add_selected'
          ? Array.from(availableContainer?.querySelectorAll('[data-chapter-canon-batch-ref]:checked') || [])
          : Array.from(selectedContainer?.querySelectorAll('[data-chapter-canon-batch-ref]') || [])
              .filter((box) => action === 'return_all' || box.checked);
        boxes.forEach((box) =>
          moveChapterCanonRow(String(box.dataset.chapterCanonBatchRef || ''), action === 'add_selected')
        );
        return;
      }

      const eventBatch = event.target.closest('[data-chapter-event-batch-action]');
      if (eventBatch) {
        event.preventDefault();
        const action = String(eventBatch.dataset.chapterEventBatchAction || '');
        const container = action === 'add_selected'
          ? document.getElementById('chapter-event-available-list')
          : document.getElementById('chapter-event-sequence-list');
        const boxes = Array.from(container?.querySelectorAll('[data-chapter-event-batch-ref]:checked') || []);
        boxes.forEach((box) =>
          moveChapterEventCard(String(box.dataset.chapterEventBatchRef || ''), action === 'add_selected')
        );
        return;
      }

      const add = event.target.closest('[data-event-add]');
      if (add) {
        event.preventDefault();
        moveChapterEventCard(String(add.dataset.eventAdd || ''), true);
        return;
      }
      const remove = event.target.closest('[data-event-return]');
      if (remove) {
        event.preventDefault();
        moveChapterEventCard(String(remove.dataset.eventReturn || ''), false);
        return;
      }
      const move = event.target.closest('[data-event-move]');
      if (move) {
        event.preventDefault();
        const row = move.closest('[data-chapter-event-row]');
        if (!row) return;
        if (move.dataset.eventMove === 'up' && row.previousElementSibling) {
          row.parentElement.insertBefore(row, row.previousElementSibling);
        }
        if (move.dataset.eventMove === 'down' && row.nextElementSibling) {
          row.parentElement.insertBefore(row.nextElementSibling, row);
        }
        refreshChapterSelectedCountFromDom();
        markChapterPlannerDraftDirty();
      }
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
      book_canon: () => { state.activeSection = 'book_plan'; renderBookPlan(bootstrap); },
      book_plan: () => renderBookPlan(bootstrap),
      chapter_planner: () => {
        renderChapterPlanner(bootstrap);
        if (state.chapterPlan && !state.chapterKnowledgePackLoading) {
          void loadChapterKnowledgePackStatus();
        }
      },
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
    }
  }

  function plannerEligibilityRank(status) {
    const normalized = String(status || 'UNKNOWN').toUpperCase();
    if (normalized === 'ACTIVE' || normalized === 'AVAILABLE_TO_ADD') return 0;
    if (normalized === 'FUTURE') return 2;
    if (normalized === 'RESTRICTED') return 3;
    if (normalized === 'CANON_INCOMPLETE') return 4;
    return 5;
  }

  function plannerCatalogItems(catalog) {
    // The backend owns item ordering through the active template's Planner
    // sort policy. Do not re-sort here: client-side Event-only chronology
    // previously overrode genre/template ordering for Interactions.
    return (catalog.categories || []).map((category) => ({
      ...category,
      items: [...(category.items || [])]
    }));
  }

  function renderBookCanonPlanner(bootstrap) {
    setHeading('Planner — Canon for This Book');

    const loading = state.bookScopeLoading === true || state.bookScopeSaving === true;
    const readOnly = bootstrap.read_only === true;
    const bookCount = Math.max(1, Number((bootstrap.manifest || {}).book_count || 1));
    const selectedBookNumber = Math.min(bookCount, Math.max(1, Number(state.bookScopeBookNumber || 1)));
    state.bookScopeBookNumber = selectedBookNumber;

    const scopeResponse = state.bookScope || {};
    const document = scopeResponse.document || {};
    const scopeBook = (document.books || []).find((book) => Number(book.book_number) === selectedBookNumber) || {
      book_number: selectedBookNumber,
      selections: [],
      lifecycle_state: 'NOT_STARTED',
      approval_status: 'not_ready',
      approval_fresh: false,
      revision: 0,
      validation: { valid: false, issues: [] },
      freshness: { fresh: true, reconciliation_required: false }
    };
    const catalog = state.bookScopeCatalog || { categories: [], hidden_status_counts: {}, status_counts: {} };
    const categories = plannerCatalogItems(catalog);
    const approvalStatus = String(scopeBook.approval_status || 'not_ready');
    const approved = approvalStatus === 'approved' && scopeBook.approval_fresh === true;
    const mutationEnabled = !readOnly && !loading && !approved;
    const selectedIds = new Set((scopeBook.selections || []).map((item) => String(item.record_id || '')));
    const visibleCount = categories.reduce((total, category) => total + Number(category.total || (category.items || []).length || 0), 0);
    const availableCount = Number((catalog.status_counts || {}).AVAILABLE_TO_ADD || 0) + Number((catalog.status_counts || {}).ACTIVE || 0);
    const futureCount = Number((catalog.status_counts || {}).FUTURE || 0);

    const categoryMarkup = categories.map((category) => {
      const rows = (category.items || []).map((item) => {
        const recordId = String(item.record_id || '');
        const selected = selectedIds.has(recordId) || item.selected === true;
        const eligibility = item.eligibility || {};
        const status = String(eligibility.status || 'UNKNOWN');
        const addable = ['ACTIVE', 'AVAILABLE_TO_ADD'].includes(status);
        const disabled = !mutationEnabled || (!selected && !addable);
        const action = selected ? 'Return' : 'Add to Book';
        const technical = [item.date_or_sequence, item.story_code].filter(Boolean).join(' · ');
        return `
          <div class="book-canon-browser-row ${selected ? 'is-selected' : ''}">
            <div class="book-canon-browser-main">
              <div class="book-canon-browser-title">
                <strong>${escapeHtml(item.label || recordId)}</strong>
                ${statusBadge(selected ? 'SELECTED' : status)}
              </div>
              <small>${escapeHtml(item.summary || labelFor(item.record_type || category.category_key || 'Canon'))}</small>
              ${technical ? `<small class="planner-technical-id">${escapeHtml(technical)}</small>` : ''}
              <details>
                <summary>Details</summary>
                <div><strong>Type:</strong> ${escapeHtml(labelFor(item.record_group_id || item.record_type || 'Canon'))}</div>
                <div><strong>Available from:</strong> ${escapeHtml(item.available_from_book ? `Book ${item.available_from_book}` : 'All books / not book-gated')}</div>
                </details>
            </div>
            <button type="button" class="${selected ? 'secondary-action' : 'primary-action'} compact-action"
              data-book-canon-action="${selected ? 'remove' : 'add'}"
              data-record-id="${escapeHtml(recordId)}" ${disabled ? 'disabled' : ''}>${action}</button>
          </div>`;
      }).join('');
      return `
        <details class="book-canon-category" open>
          <summary><strong>${escapeHtml(labelFor(category.category_key || 'Canon'))}</strong>
            <span>${number(category.total || (category.items || []).length)} shown · ${number(category.selected_count || 0)} selected</span></summary>
          <div class="book-canon-browser-list">${rows || '<div class="workspace-disabled-note">No records in this category.</div>'}</div>
        </details>`;
    }).join('');

    const issueRows = ((scopeBook.validation || {}).issues || []).map((issue) => `
      <tr><td>${escapeHtml(issue.code || 'issue')}</td><td>${escapeHtml(issue.message || 'Canon selection issue')}</td></tr>
    `).join('');

    const errorMarkup = state.bookScopeError
      ? `<div class="workspace-error-note"><strong>Canon browser could not load.</strong> ${escapeHtml(state.bookScopeError)} <button type="button" id="book-canon-retry">Retry</button></div>`
      : '';

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-book-canon-planner-v2">
        <p class="placeholder">Choose the established Canon that belongs in Book ${selectedBookNumber}. The browser opens with usable Canon first; search is optional filtering only.</p>

        <div class="workspace-stat-grid">
          ${statCard('Book', String(selectedBookNumber))}
          ${statCard('Selected', number((scopeBook.selections || []).length))}
          ${statCard('Available now', number(availableCount))}
          ${statCard('Future', number(futureCount))}
          ${statCard('Approval', labelFor(approvalStatus))}
        </div>

        ${errorMarkup}

        <div class="book-canon-toolbar compact-planner-toolbar">
          <label>Book<select id="book-canon-book">${Array.from({ length: bookCount }, (_, index) => index + 1).map((bookNumber) => `<option value="${bookNumber}" ${bookNumber === selectedBookNumber ? 'selected' : ''}>Book ${bookNumber}</option>`).join('')}</select></label>
          <label class="book-canon-filter">Filter visible Canon (optional)<input id="book-canon-query" type="search" value="${escapeHtml(state.bookScopeQuery || '')}" placeholder="Type a name, event meaning, place, date, or ID" /></label>
          <label class="planner-toggle"><input id="book-canon-show-future" type="checkbox" ${state.bookScopeIncludeFuture ? 'checked' : ''} /> Show future Canon</label>
          <button type="button" id="book-canon-refresh" class="secondary-action" ${loading ? 'disabled' : ''}>${loading ? 'Loading…' : 'Refresh'}</button>
        </div>

        <details class="workspace-detail-card planner-selected-summary" ${selectedIds.size ? 'open' : ''}>
          <summary><strong>Selected for Book ${selectedBookNumber}</strong><span>${number(selectedIds.size)} records</span></summary>
          <div class="planner-selected-summary-body">
            ${(scopeBook.selections || []).map((item) => `<div class="chapter-planner-row planner-choice-row is-selected"><span>${statusBadge('SELECTED')}</span><div><strong>${escapeHtml(item.label || item.record_id || '')}</strong><small>${escapeHtml(labelFor(item.record_type || 'Canon'))}</small></div><button type="button" class="secondary-action compact-action" data-book-canon-action="remove" data-record-id="${escapeHtml(item.record_id || '')}" ${mutationEnabled ? '' : 'disabled'}>Return</button></div>`).join('') || '<div class="workspace-disabled-note">No Canon selected for this book yet.</div>'}
          </div>
        </details>

        <section class="workspace-detail-card">
          <div class="planner-section-heading"><h3>Canon available for Book ${selectedBookNumber}</h3><span>${number(visibleCount)} visible</span></div>
          ${loading && !visibleCount ? '<div class="workspace-disabled-note">Loading Canon browser…</div>' : (categoryMarkup || '<div class="workspace-disabled-note">No Canon records are visible. If this persists after Refresh, use the error message above rather than searching for records.</div>')}
        </section>

        <section class="workspace-detail-card"><h3>Canon for This Book check</h3>${(scopeBook.validation || {}).valid === false ? (issueRows ? table(['Code', 'Issue'], issueRows) : '<div class="workspace-disabled-note">Select at least one Canon record before approval.</div>') : '<div class="workspace-success-note">Current Canon for This Book selections are valid.</div>'}</section>

        <div class="workspace-action-row">
          <button type="button" id="book-canon-approve" class="primary-action" ${readOnly || loading || approved || !(scopeBook.validation || {}).valid ? 'disabled' : ''}>Approve Canon for This Book</button>
          <button type="button" id="book-canon-revoke" class="secondary-action" ${readOnly || loading || !['approved','outdated'].includes(approvalStatus) ? 'disabled' : ''}>Revoke Approval</button>
          <button type="button" id="book-canon-open-plan" class="secondary-action" ${selectedIds.size ? '' : 'disabled'}>Continue to Book Plan</button>
        </div>
        <div class="workspace-disabled-note">Add/Return updates Canon for This Book. Approve it when the selection is ready; later chapter-level additions or removals are handled from Chapter Planner.</div>
      </div>`;

    document.getElementById('book-canon-book')?.addEventListener('change', (event) => { state.bookScopeBookNumber = Number(event.target.value || 1); state.bookScopeCatalog = null; state.bookScopeError = ''; void loadBookCanonPlanner(); });
    let filterTimer = null;
    document.getElementById('book-canon-query')?.addEventListener('input', (event) => { clearTimeout(filterTimer); filterTimer = setTimeout(() => { state.bookScopeQuery = String(event.target.value || '').trim(); void loadBookScopeCatalog(); }, 250); });
    document.getElementById('book-canon-show-future')?.addEventListener('change', (event) => { state.bookScopeIncludeFuture = event.target.checked === true; void loadBookScopeCatalog(); });
    mainPanel.querySelectorAll('[data-book-canon-action]').forEach((button) => button.addEventListener('click', () => void mutateBookCanonSelection(button.dataset.recordId, button.dataset.bookCanonAction)));
    document.getElementById('book-canon-refresh')?.addEventListener('click', () => void loadBookCanonPlanner());
    document.getElementById('book-canon-retry')?.addEventListener('click', () => void loadBookCanonPlanner());
    document.getElementById('book-canon-approve')?.addEventListener('click', () => void approveBookCanon());
    document.getElementById('book-canon-revoke')?.addEventListener('click', () => void revokeBookCanonApproval());
    document.getElementById('book-canon-open-plan')?.addEventListener('click', () => renderSection('book_plan'));

    if (!state.bookScope && !state.bookScopeLoading) void loadBookCanonPlanner();
    else if (!state.bookScopeCatalog && !state.bookScopeLoading) void loadBookScopeCatalog();
  }

  function renderBookScopeAwarePlanner() {
    if (!state.bootstrap) return;
    if (state.activeSection === 'book_plan') renderBookPlan(state.bootstrap);
    else if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    else if (state.activeSection === 'book_canon') renderBookCanonPlanner(state.bootstrap);
  }

  async function loadBookCanonPlanner() {
    if (!projectId || state.bookScopeLoading || state.bookScopeSaving) return;
    state.bookScopeLoading = true;
    state.bookScopeError = '';
    renderBookScopeAwarePlanner();
    try {
      state.bookScope = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/book-scope`);
      await loadBookScopeCatalog(true);
      setLog(`Canon for Book ${state.bookScopeBookNumber} loaded.`);
    } catch (error) {
      state.bookScopeCatalog = { categories: [], status_counts: {}, hidden_status_counts: {} };
      state.bookScopeError = error.message || String(error);
      setLog(`Book Canon load failed: ${state.bookScopeError}`);
    } finally {
      state.bookScopeLoading = false;
      renderBookScopeAwarePlanner();
    }
  }

  async function loadBookScopeCatalog(keepLoading = false) {
    if (!projectId) return;
    if (!keepLoading) state.bookScopeLoading = true;
    renderBookScopeAwarePlanner();
    const params = new URLSearchParams({
      book_number: String(state.bookScopeBookNumber || 1),
      include_future: state.bookScopeIncludeFuture ? 'true' : 'false',
      query: state.bookScopeQuery || ''
    });
    try {
      state.bookScopeError = '';
      state.bookScopeCatalog = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/book-scope/catalog?${params.toString()}`);
      const visible = (state.bookScopeCatalog.categories || []).reduce((sum, category) => sum + Number(category.total || (category.items || []).length || 0), 0);
      setLog(`Book Canon catalog loaded: ${visible} visible records.`);
    } catch (error) {
      state.bookScopeCatalog = { categories: [], status_counts: {}, hidden_status_counts: {} };
      state.bookScopeError = error.message || String(error);
      setLog(`Book Canon catalog failed: ${state.bookScopeError}`);
    } finally {
      if (!keepLoading) {
        state.bookScopeLoading = false;
        renderBookScopeAwarePlanner();
      }
    }
  }

  async function mutateBookCanonSelection(recordId, action) {
    return mutateBookCanonSelections([recordId], action);
  }

  async function mutateBookCanonSelections(recordIds, action) {
    const ids = [...new Set((recordIds || []).map((value) => String(value || '').trim()).filter(Boolean))];
    if (!ids.length || state.bookScopeSaving || state.bootstrap.read_only === true) return;

    const documentScope = (state.bookScope || {}).document || {};
    const book = (documentScope.books || []).find(
      (item) => Number(item.book_number) === Number(state.bookScopeBookNumber || 1)
    );
    const existing = (book && book.selections) ? book.selections : [];
    let selections = existing.map((item) => ({
      record_id: item.record_id,
      source_class: item.source_class || 'master_canon',
      usage_mode: item.usage_mode || 'direct'
    }));
    const before = new Set(selections.map((item) => String(item.record_id || '')));

    if (action === 'add') {
      ids.forEach((recordId) => {
        if (!before.has(recordId)) {
          selections.push({ record_id: recordId, source_class: 'master_canon', usage_mode: 'direct' });
          before.add(recordId);
        }
      });
    } else if (action === 'remove') {
      const removeIds = new Set(ids);
      selections = selections.filter((item) => !removeIds.has(String(item.record_id || '')));
    } else {
      return;
    }

    const priorIds = existing.map((item) => String(item.record_id || '')).sort().join('|');
    const nextIds = selections.map((item) => String(item.record_id || '')).sort().join('|');
    if (priorIds === nextIds) {
      setLog('No Book Canon selections changed.');
      return;
    }

    state.bookScopeSaving = true;
    renderBookScopeAwarePlanner();
    try {
      // One batch action intentionally produces one Book Scope PUT and one
      // catalog refresh, regardless of the number of checked records.
      const saveResult = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-scope/${state.bookScopeBookNumber}`,
        {
          method: 'PUT',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({ selections, constraints: (book && book.constraints) || {} })
        }
      );
      state.bookScope = saveResult.book_scope || saveResult;
      try {
        await loadBookCanonPlannerAfterMutation(false);
        await refreshBookPlanAfterScopeChange();
      } catch (refreshError) {
        state.bookScopeError = `Selection saved, but the Canon browser refresh failed: ${refreshError.message || refreshError}`;
      }
      setLog(`${ids.length} Canon record${ids.length === 1 ? '' : 's'} ${action === 'remove' ? 'returned from' : 'added to'} Book ${state.bookScopeBookNumber}.`);
    } catch (error) {
      setLog(`Book Canon ${action} failed: ${error.message}`);
    } finally {
      state.bookScopeSaving = false;
      renderBookScopeAwarePlanner();
    }
  }

  async function loadBookCanonPlannerAfterMutation(refreshScope = true) {
    if (refreshScope) {
      state.bookScope = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-scope`
      );
    }
    const params = new URLSearchParams({
      book_number: String(state.bookScopeBookNumber || 1),
      include_future: state.bookScopeIncludeFuture ? 'true' : 'false',
      query: state.bookScopeQuery || ''
    });
    state.bookScopeCatalog = await apiFetch(
      `/api/project/${encodeURIComponent(projectId)}/book-scope/catalog?${params.toString()}`
    );
  }

  async function refreshBookPlanAfterScopeChange() {
    if (!projectId || (!state.bookPlan && state.activeSection !== 'book_plan')) return;
    state.bookPlan = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/book-plan`);
  }

  async function approveBookCanon() {
    if (state.bookScopeSaving || state.bootstrap.read_only === true) return;
    state.bookScopeSaving = true;
    renderBookScopeAwarePlanner();
    try {
      await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-scope/${state.bookScopeBookNumber}/approve`,
        { method: 'POST', headers: { Accept: 'application/json' } }
      );
      await loadBookCanonPlannerAfterMutation();
      await refreshBookPlanAfterScopeChange();
      setLog(`Book ${state.bookScopeBookNumber} Canon approved.`);
    } catch (error) {
      setLog(`Book Canon approval failed: ${error.message}`);
    } finally {
      state.bookScopeSaving = false;
      renderBookScopeAwarePlanner();
    }
  }

  async function revokeBookCanonApproval() {
    if (state.bookScopeSaving || state.bootstrap.read_only === true) return;
    state.bookScopeSaving = true;
    renderBookScopeAwarePlanner();
    try {
      await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-scope/${state.bookScopeBookNumber}/revoke`,
        { method: 'POST', headers: { Accept: 'application/json' } }
      );
      await loadBookCanonPlannerAfterMutation();
      await refreshBookPlanAfterScopeChange();
      setLog(`Book ${state.bookScopeBookNumber} Canon approval revoked.`);
    } catch (error) {
      setLog(`Book Canon approval revoke failed: ${error.message}`);
    } finally {
      state.bookScopeSaving = false;
      renderBookScopeAwarePlanner();
    }
  }


  function chapterDraftKey() {
    return `${Number(state.chapterPlanBookNumber || 1)}:${Number(state.chapterPlanChapterNumber || 1)}`;
  }

  function captureChapterPlannerDraft() {
    if (!mainPanel || state.activeSection !== 'chapter_planner') return;
    if (!document.getElementById('chapter-plan-kickoff')) return;
    const current = (state.chapterPlan || {}).chapter || {};
    const selectedCanonRefs = Array.from(mainPanel.querySelectorAll('[data-chapter-canon-ref]:checked'))
      .map((node) => ({ record_id: String(node.dataset.chapterCanonRef || '') }))
      .filter((ref) => ref.record_id);
    const pov = Array.from(mainPanel.querySelectorAll('[data-chapter-pov-ref]:checked'))
      .map((node) => ({ record_id: String(node.dataset.chapterPovRef || '') }))
      .filter((ref) => ref.record_id);
    const sequencedRows = Array.from(mainPanel.querySelectorAll('#chapter-event-sequence-list [data-chapter-event-row]'));
    const assignedEventRefs = sequencedRows.map((row) => ({
      record_id: String(row.dataset.chapterEventRow || '')
    })).filter((ref) => ref.record_id);
    const eventPlacements = sequencedRows.map((row) => {
      const recordId = String(row.dataset.chapterEventRow || '');
      const position = row.querySelector(`[data-chapter-event-position="${CSS.escape(recordId)}"]`);
      const role = row.querySelector(`[data-chapter-event-role="${CSS.escape(recordId)}"]`);
      const relationship = row.querySelector(`[data-chapter-event-relationship="${CSS.escape(recordId)}"]`);
      const anchor = row.querySelector(`[data-chapter-event-anchor="${CSS.escape(recordId)}"]`);
      const objective = row.querySelector(`[data-chapter-event-objective="${CSS.escape(recordId)}"]`);
      const anchorId = String(anchor?.value || '');
      return {
        event_ref: { record_id: recordId },
        position: String(position?.value || 'flexible'),
        chapter_role: String(role?.value || ''),
        relationship_to_anchor: String(relationship?.value || ''),
        anchor_event_ref: anchorId ? { record_id: anchorId } : null,
        objective: String(objective?.value || '').trim()
      };
    }).filter((placement) => String((placement.event_ref || {}).record_id || ''));
    const restrictions = String(document.getElementById('chapter-plan-restrictions')?.value || '')
      .split(/\r?\n/).map((value) => value.trim()).filter(Boolean);
    const storyControlRefs = Array.from(mainPanel.querySelectorAll('[data-story-control-ref]:checked'))
      .map((node) => String(node.dataset.storyControlRef || '')).filter(Boolean);
    state.chapterPlanDraft = {
      key: chapterDraftKey(),
      selected_canon_refs: selectedCanonRefs,
      pov,
      assigned_event_refs: assignedEventRefs,
      event_placements: eventPlacements,
      generation_kickoff: String(document.getElementById('chapter-plan-kickoff')?.value || current.generation_kickoff || ''),
      chapter_objective: String(document.getElementById('chapter-plan-objective')?.value || current.chapter_objective || ''),
      restrictions,
      story_control_refs: storyControlRefs,
      story_control_form: {
        control_type: String(document.getElementById('story-control-type')?.value || ''),
        subject_record_id: String(document.getElementById('story-control-subject')?.value || ''),
        instruction: String(document.getElementById('story-control-instruction')?.value || ''),
        certainty: String(document.getElementById('story-control-certainty')?.value || ''),
        presentation: String(document.getElementById('story-control-presentation')?.value || ''),
        narrative_weight: String(document.getElementById('story-control-weight')?.value || '')
      }
    };
  }

  function chapterForRender(savedChapter) {
    const draft = state.chapterPlanDraft;
    if (!draft || draft.key !== chapterDraftKey()) return savedChapter;
    return {
      ...savedChapter,
      selected_canon_refs: draft.selected_canon_refs || savedChapter.selected_canon_refs || [],
      pov: draft.pov || savedChapter.pov || [],
      assigned_event_refs: draft.assigned_event_refs || savedChapter.assigned_event_refs || [],
      event_placements: draft.event_placements || savedChapter.event_placements || [],
      generation_kickoff: draft.generation_kickoff ?? savedChapter.generation_kickoff ?? '',
      chapter_objective: draft.chapter_objective ?? savedChapter.chapter_objective ?? '',
      restrictions: draft.restrictions || savedChapter.restrictions || [],
      story_control_refs: draft.story_control_refs || savedChapter.story_control_refs || []
    };
  }

  function clearChapterPlannerDraft() {
    state.chapterPlanDraft = null;
    state.chapterPlanDraftDirty = false;
  }

  function markChapterPlannerDraftDirty() {
    captureChapterPlannerDraft();
    state.chapterPlanDraftDirty = true;
    state.chapterPlannerDraftVersion = Number(state.chapterPlannerDraftVersion || 0) + 1;
    state.chapterPlanSavedNotice = '';
    const reminder = document.getElementById('chapter-unsaved-reminder');
    if (reminder) reminder.hidden = false;
  }

  function recoverChapterPlannerFromPreviousPack() {
    if (!mainPanel || state.activeSection !== 'chapter_planner') return;

    const snapshot = (state.chapterKnowledgePack || {}).recovery_snapshot || {};
    if (snapshot.available !== true) {
      setLog('No previous compiled Chapter Knowledge Pack selections are available for recovery.');
      return;
    }

    const confirmed = window.confirm(
      'Recover the Canon and event selections from the previous compiled Chapter Knowledge Pack? ' +
      'Your current kickoff, objective, restrictions, and Story Controls will be preserved. ' +
      'Nothing is saved until you press Save Chapter Plan.'
    );
    if (!confirmed) return;

    let recoveredCanon = 0;
    let recoveredEvents = 0;
    let skippedCanon = 0;
    let skippedEvents = 0;

    (snapshot.selected_canon_refs || []).forEach((ref) => {
      const recordId = String((ref || {}).record_id || '');
      if (!recordId) return;
      const row = mainPanel.querySelector(
        `[data-chapter-canon-row="${CSS.escape(recordId)}"]`
      );
      if (!row) {
        skippedCanon += 1;
        return;
      }
      moveChapterCanonRow(recordId, true);
      recoveredCanon += 1;
    });

    (snapshot.assigned_event_refs || []).forEach((ref) => {
      const recordId = String((ref || {}).record_id || '');
      if (!recordId) return;
      const row = mainPanel.querySelector(
        `[data-chapter-event-row="${CSS.escape(recordId)}"]`
      );
      if (!row) {
        skippedEvents += 1;
        return;
      }
      moveChapterEventCard(recordId, true);
      recoveredEvents += 1;
    });

    (snapshot.event_placements || []).forEach((placement) => {
      const recordId = String((((placement || {}).event_ref) || {}).record_id || '');
      if (!recordId) return;
      const row = mainPanel.querySelector(
        `#chapter-event-sequence-list [data-chapter-event-row="${CSS.escape(recordId)}"]`
      );
      if (!row) return;

      const assignments = [
        [`[data-chapter-event-position="${CSS.escape(recordId)}"]`, String(placement.position || 'flexible')],
        [`[data-chapter-event-role="${CSS.escape(recordId)}"]`, String(placement.chapter_role || '')],
        [`[data-chapter-event-relationship="${CSS.escape(recordId)}"]`, String(placement.relationship_to_anchor || '')],
        [`[data-chapter-event-anchor="${CSS.escape(recordId)}"]`, String((((placement || {}).anchor_event_ref) || {}).record_id || '')],
        [`[data-chapter-event-objective="${CSS.escape(recordId)}"]`, String(placement.objective || '')]
      ];

      assignments.forEach(([selector, value]) => {
        const control = row.querySelector(selector);
        if (control) control.value = value;
      });
    });

    markChapterPlannerDraftDirty();
    refreshChapterSelectedCountFromDom();

    const skipped = skippedCanon + skippedEvents;
    setLog(
      `Recovered ${recoveredCanon} Canon selection(s) and ${recoveredEvents} event(s) from the previous compiled Chapter Knowledge Pack.` +
      (skipped ? ` ${skipped} previous item(s) were skipped because they are not available in the current Book Canon.` : '') +
      ' Review the recovered chapter, then Save Chapter Plan. Recompile the Chapter Knowledge Pack afterward.'
    );
  }

  function chapterPlanApprovalBlockerForCurrentBook() {
    const status = state.bookRuntimeContext || {};
    const bookNumber = Number(state.chapterPlanBookNumber || 1);
    const target = (status.targets || []).find((item) => Number(item.book_number) === bookNumber) || {};
    return (target.blockers || []).find((item) => String(item.code || '') === 'book_plan_not_approved') || null;
  }

  function currentBookKnowledgeTarget() {
    const status = state.bookRuntimeContext || {};
    const bookNumber = Number(state.chapterPlanBookNumber || 1);
    return (status.targets || []).find((item) => Number(item.book_number) === bookNumber) || {};
  }

  function showChapterSaveRequiredModal(nextActionLabel) {
    let modal = document.getElementById('chapter-save-required-modal');
    if (modal) modal.remove();
    modal = document.createElement('div');
    modal.id = 'chapter-save-required-modal';
    modal.className = 'workspace-modal-backdrop';
    modal.innerHTML = `
      <div class="workspace-modal-card" role="dialog" aria-modal="true" aria-labelledby="chapter-save-required-title">
        <h3 id="chapter-save-required-title">Save this Chapter Plan first</h3>
        <p>You have unsaved chapter changes. Save the Chapter Plan so the next Knowledge Pack is compiled from the selections, event order, kickoff, objectives, restrictions, and Story Controls currently on screen.</p>
        <p><strong>Next step after saving:</strong> ${escapeHtml(nextActionLabel || 'continue with Knowledge Pack compilation')}.</p>
        <div class="workspace-action-row">
          <button type="button" class="primary-action" id="chapter-modal-save">Save Chapter Plan</button>
          <button type="button" class="secondary-action" id="chapter-modal-cancel">Keep Editing</button>
        </div>
      </div>`;
    document.body.appendChild(modal);
    modal.querySelector('#chapter-modal-cancel')?.addEventListener('click', () => modal.remove());
    modal.querySelector('#chapter-modal-save')?.addEventListener('click', async () => {
      modal.remove();
      await saveChapterPlanner();
    });
  }


  function renderChapterPlanner(bootstrap) {
    setHeading('Chapter Planner');

    const readOnly = bootstrap.read_only === true;
    const loading = state.chapterPlanLoading === true || state.chapterPlanSaving === true;
    const manifest = bootstrap.manifest || {};
    const bookCount = Math.max(1, Number(manifest.book_count || 1));
    const chaptersPerBook = Math.max(1, Number(manifest.chapters_per_book || 1));
    state.chapterPlanBookNumber = Math.min(
      bookCount,
      Math.max(1, Number(state.chapterPlanBookNumber || 1))
    );
    state.chapterPlanChapterNumber = Math.min(
      chaptersPerBook,
      Math.max(1, Number(state.chapterPlanChapterNumber || 1))
    );

    const response = state.chapterPlan || {};
    const savedChapter = response.chapter || {
      book_number: state.chapterPlanBookNumber,
      chapter_number: state.chapterPlanChapterNumber,
      lifecycle_state: 'draft',
      revision: 0,
      selected_canon_refs: [],
      assigned_event_refs: [],
      event_placements: [],
      generation_kickoff: '',
      pov: [],
      chapter_objective: '',
      restrictions: [],
      story_control_refs: [],
      validation: { valid: true, issues: [] },
      freshness: { fresh: true, changes: [] },
      generation_readiness: { ready: false, generation_enabled: false }
    };
    const chapter = chapterForRender(savedChapter);

    const catalog = state.chapterPlanBookCatalog || { categories: [] };
    const effectiveScope = state.chapterPlanEffectiveScope || { selection_ids: [] };
    const effectiveIds = new Set(
      (effectiveScope.selection_ids || []).map((value) => String(value || ''))
    );
    const allCatalogItems = (catalog.categories || []).flatMap((category) => category.items || []);
    const catalogById = Object.fromEntries(
      allCatalogItems.map((item) => [String(item.record_id || ''), item])
    );
    const catalogItems = allCatalogItems.filter((item) =>
      effectiveIds.has(String(item.record_id || ''))
    );
    const selectedIds = new Set(
      (chapter.selected_canon_refs || []).map((item) => String(item.record_id || ''))
    );
    const povIds = new Set(
      (chapter.pov || []).map((item) => String(item.record_id || ''))
    );
    const assignedEventIds = new Set(
      (chapter.assigned_event_refs || []).map((item) => String(item.record_id || ''))
    );
    const selectedStoryControlIds = new Set(
      (chapter.story_control_refs || []).map((value) => String(value || ''))
    );
    const storyControls = (state.storyControls || {}).controls || [];
    const revealThreads = (state.plannerRevealCatalog || {}).threads || [];
    const bookScopeBook = (((state.bookScope || {}).document || {}).books || []).find((item) => Number(item.book_number) === Number(state.chapterPlanBookNumber)) || {};
    const bookScopeApproved = bookScopeBook.approval_status === 'approved' && bookScopeBook.approval_fresh === true;
    const chapterKnowledgePack = state.chapterKnowledgePack || {};
    const knowledgePackStatus = String(chapterKnowledgePack.status || 'missing');
    const knowledgePackBlockers = chapterKnowledgePack.blockers || [];
    const knowledgePackUnlockEvaluations = chapterKnowledgePack.unlock_evaluations || [];
    const knowledgePackTokens = chapterKnowledgePack.token_accounting || {};
    const knowledgePackFile = chapterKnowledgePack.pack || {};
    const recoverySnapshot = chapterKnowledgePack.recovery_snapshot || {};
    const knowledgePackDisplayStatus = knowledgePackFile.current === true
      ? 'Current'
      : knowledgePackFile.exists === true
        ? 'Needs Recompile'
        : chapterKnowledgePack.compiler_ready === true
          ? 'Ready to Compile'
          : labelFor(knowledgePackStatus || 'Blocked');
    const knowledgePackBusy = state.chapterKnowledgePackLoading === true;
    const bookKnowledgeCompileBusy = state.chapterBookKnowledgeCompileLoading === true;
    const bookKnowledgeOnlyBlocker = knowledgePackBlockers.length > 0
      && knowledgePackBlockers.every((item) => String(item.code || '') === 'book_runtime_context_not_current');
    const bookKnowledgeTarget = currentBookKnowledgeTarget();
    const bookPlanApprovalBlocker = chapterPlanApprovalBlockerForCurrentBook();
    const bookKnowledgeCompileAllowed = bookKnowledgeTarget.compiler_ready === true;
    const chapterDraftDirty = state.chapterPlanDraftDirty === true;
    const directionsBusy = state.chapterPlanDirectionsLoading === true;
    const amendBusy = state.chapterPlanAmendLoading === true;
    const storyDraft = (state.chapterPlanDraft && state.chapterPlanDraft.key === chapterDraftKey())
      ? (state.chapterPlanDraft.story_control_form || {})
      : {};
    const placementByEvent = {};
    (chapter.event_placements || []).forEach((placement) => {
      const eventId = String(((placement || {}).event_ref || {}).record_id || '');
      if (eventId) placementByEvent[eventId] = placement;
    });

    const canonRow = (item, isSelected) => {
      const recordId = String(item.record_id || '');
      const isCharacter = String(item.record_group_id || '') === 'characters' || String(item.record_type || '') === 'character';
      const isPov = povIds.has(recordId);
      return `
        <article class="chapter-canon-choice-row book-canon-browser-row ${isSelected ? 'is-selected' : ''}" data-chapter-canon-row="${escapeHtml(recordId)}">
          <input type="checkbox" data-chapter-canon-ref="${escapeHtml(recordId)}" ${isSelected ? 'checked' : ''} hidden />
          <div class="book-canon-browser-main">
            <strong>${escapeHtml(item.label || recordId)}</strong>
            <small>${escapeHtml(item.summary || labelFor(item.record_group_id || item.record_type || 'Canon'))}</small>
            ${isCharacter ? `<label class="chapter-pov-choice" data-chapter-pov-wrap="${escapeHtml(recordId)}" ${isSelected ? '' : 'hidden'}><input type="checkbox" data-chapter-pov-ref="${escapeHtml(recordId)}" ${isPov ? 'checked' : ''} ${readOnly || loading ? 'disabled' : ''} /> POV</label>` : ''}
          </div>
          <div class="chapter-row-actions">
            <label class="book-canon-batch-check" title="Mark for batch action"><input type="checkbox" data-chapter-canon-batch-ref="${escapeHtml(recordId)}" ${readOnly || loading ? 'disabled' : ''} /></label>
            ${isSelected
              ? `<button type="button" class="secondary-action compact-action book-canon-row-action-button" data-chapter-canon-return="${escapeHtml(recordId)}" ${readOnly || loading ? 'disabled' : ''}>Return</button>`
              : `<button type="button" class="primary-action compact-action book-canon-row-action-button" data-chapter-canon-add="${escapeHtml(recordId)}" ${readOnly || loading ? 'disabled' : ''}>Add to Chapter</button>`}
          </div>
        </article>
      `;
    };
    const selectedCanonRows = (chapter.selected_canon_refs || []).map((ref) => {
      const recordId = String((ref || {}).record_id || '');
      const recordType = String((ref || {}).record_type || 'canon');
      const groupByType = { character: 'characters', location: 'locations', event: 'events', interaction: 'interactions' };
      return catalogById[recordId] || {
        record_id: recordId,
        record_type: recordType,
        record_group_id: groupByType[recordType] || '',
        label: (ref || {}).label || recordId,
        summary: `Saved ${labelFor(recordType)} chapter selection`
      };
    }).filter((item) => item.record_id).map((item) => canonRow(item, true)).join('');
    const availableCanonRows = catalogItems
      .filter((item) => !selectedIds.has(String(item.record_id || '')) && ['characters','locations'].includes(String(item.record_group_id || '')))
      .map((item) => canonRow(item, false)).join('');

    const events = ((state.chapterPlanEventCandidates || {}).candidates || [])
      .filter((item) => item.in_book_scope === true);
    const eventById = {};
    events.forEach((item) => { eventById[String(item.record_id || '')] = item; });
    (chapter.assigned_event_refs || []).forEach((ref) => {
      const recordId = String((ref || {}).record_id || '');
      if (!recordId || eventById[recordId]) return;
      eventById[recordId] = {
        record_id: recordId,
        record_type: 'event',
        record_group_id: 'events',
        label: (ref || {}).label || recordId,
        summary: 'Saved Chapter event selection',
        date_or_sequence: ''
      };
    });
    const assignedOrder = (chapter.event_placements || []).map((placement) =>
      String(((placement || {}).event_ref || {}).record_id || '')
    ).filter(Boolean);
    (chapter.assigned_event_refs || []).forEach((ref) => {
      const id = String(ref.record_id || '');
      if (id && !assignedOrder.includes(id)) assignedOrder.push(id);
    });

    const eventCard = (item, assigned) => {
      const recordId = String(item.record_id || '');
      const placement = placementByEvent[recordId] || {};
      const position = String(placement.position || 'flexible');
      const chapterRole = String(placement.chapter_role || '');
      const relationship = String(placement.relationship_to_anchor || '');
      const anchorId = String(((placement.anchor_event_ref || {}).record_id) || '');
      const objective = String(placement.objective || '');
      const technical = [item.date_or_sequence, item.story_code].filter(Boolean).join(' · ');
      return `
        <article class="chapter-event-card ${assigned ? 'is-selected' : ''}" data-chapter-event-row="${escapeHtml(recordId)}">
          <input type="checkbox" data-chapter-event-ref="${escapeHtml(recordId)}" ${assigned ? 'checked' : ''} hidden />
          <div class="chapter-event-card-head">
            <div>
              <strong>${escapeHtml(item.label || item.summary || recordId)}</strong>
              <small>${escapeHtml(technical || 'Canon event')}</small>
            </div>
            <div class="chapter-row-actions">
              <label class="book-canon-batch-check" title="Mark for batch action"><input type="checkbox" data-chapter-event-batch-ref="${escapeHtml(recordId)}" ${readOnly || loading ? 'disabled' : ''} /></label>
              ${assigned
                ? `<button type="button" class="secondary-action compact-action" data-event-return="${escapeHtml(recordId)}" ${readOnly || loading ? 'disabled' : ''}>Return</button>`
                : `<button type="button" class="primary-action compact-action" data-event-add="${escapeHtml(recordId)}" ${readOnly || loading ? 'disabled' : ''}>Add to Chapter</button>`}
            </div>
          </div>
          <p>${escapeHtml(item.summary || 'No event summary available.')}</p>
          <div class="chapter-event-controls" ${assigned ? '' : 'hidden'}>
            <label>Role
              <select data-chapter-event-role="${escapeHtml(recordId)}">
                <option value="">Choose role</option>
                ${['opening','historical_anchor','setup','escalation','reaction','discussion','investigation','reveal','consequence','transition','closing_beat']
                  .map((value) => `<option value="${value}" ${value === chapterRole ? 'selected' : ''}>${escapeHtml(labelFor(value))}</option>`).join('')}
              </select>
            </label>
            <label>Placement
              <select data-chapter-event-position="${escapeHtml(recordId)}">
                ${['opening','early','middle','late','ending','after_break','flexible']
                  .map((value) => `<option value="${value}" ${value === position ? 'selected' : ''}>${escapeHtml(labelFor(value))}</option>`).join('')}
              </select>
            </label>
            <label>Relationship
              <select data-chapter-event-relationship="${escapeHtml(recordId)}">
                <option value="">No anchor relationship</option>
                ${['follows','precedes','same_anchor','parallel_reaction','alternate_perspective','caused_by','consequence_of','occurs_during','immediately_after','discusses','reaction_to','hears_report_of','remembers']
                  .map((value) => `<option value="${value}" ${value === relationship ? 'selected' : ''}>${escapeHtml(labelFor(value))}</option>`).join('')}
              </select>
            </label>
            <label>Anchor event
              <select data-chapter-event-anchor="${escapeHtml(recordId)}">
                <option value="">None</option>
                ${events.filter((candidate) => String(candidate.record_id || '') !== recordId).map((candidate) => `
                  <option value="${escapeHtml(candidate.record_id || '')}" ${String(candidate.record_id || '') === anchorId ? 'selected' : ''}>${escapeHtml(candidate.label || candidate.summary || candidate.record_id || '')}</option>
                `).join('')}
              </select>
            </label>
            <label class="chapter-event-objective">Beat objective
              <textarea rows="2" data-chapter-event-objective="${escapeHtml(recordId)}" placeholder="What must this beat accomplish?">${escapeHtml(objective)}</textarea>
            </label>
            <div class="planner-sequence-actions">
              <button type="button" data-event-move="up" data-record-id="${escapeHtml(recordId)}">↑ Earlier</button>
              <button type="button" data-event-move="down" data-record-id="${escapeHtml(recordId)}">↓ Later</button>
            </div>
          </div>
        </article>`;
    };

    const eventSequenceRows = assignedOrder
      .map((recordId) => eventById[recordId])
      .filter(Boolean)
      .map((item) => eventCard(item, true)).join('');
    const availableEvents = events
      .filter((item) => !assignedEventIds.has(String(item.record_id || '')));
    const availableEventRows = availableEvents
      .map((item) => eventCard(item, false)).join('');

    const recoveryCanBeOffered = recoverySnapshot.available === true
      && selectedIds.size === 0
      && assignedEventIds.size === 0
      && (
        Number(recoverySnapshot.selected_canon_count || 0) > 0
        || Number(recoverySnapshot.assigned_event_count || 0) > 0
      );
    const recoveryNotice = recoveryCanBeOffered
      ? `<div class="workspace-warning-note chapter-recovery-note">
          <strong>Previous compiled chapter selections are available.</strong>
          The current saved Chapter Plan contains no selected Canon or sequenced events, while the previous
          compiled Chapter Knowledge Pack (from Chapter Plan revision
          ${escapeHtml(number(recoverySnapshot.source_chapter_plan_revision || 0))}) contains
          ${escapeHtml(number(recoverySnapshot.selected_canon_count || 0))} Canon selection(s) and
          ${escapeHtml(number(recoverySnapshot.assigned_event_count || 0))} event(s).
          That compiled pack is outdated and is not the current Chapter Plan.
          <div class="workspace-action-row compact-action-row">
            <button type="button" id="chapter-recover-previous-pack" class="secondary-action compact-action"
              ${readOnly || loading ? 'disabled' : ''}>Recover Previous Compiled Selections</button>
          </div>
        </div>`
      : '';

    const eventOptions = events.map((item) => `
      <option value="${escapeHtml(item.record_id || '')}"
        ${String(state.chapterPlanAnchorEventId || '') === String(item.record_id || '') ? 'selected' : ''}>
        ${escapeHtml(item.label || item.record_id || '')}
      </option>
    `).join('');

    const possibleDirections = ((state.chapterPlanPossibleDirections || {}).results || []);
    const directionRows = possibleDirections.map((item) => {
      const recordId = String(item.record_id || '');
      const status = String(item.status || (item.eligibility || {}).status || 'UNKNOWN');
      const relationships = (item.relationships_to_anchor || [])
        .map((rel) => {
          const anchorLabel = String(rel.anchor_label || '');
          const relation = labelFor(rel.relationship_type || '');
          return anchorLabel ? `${relation} — ${anchorLabel}` : relation;
        })
        .filter(Boolean)
        .join('; ');
      const message = String((item.eligibility || {}).author_message || '');
      const canUseInChapter = item.in_book_scope === true
        && ['ACTIVE', 'AVAILABLE_TO_ADD'].includes(status);
      const canAddToBook = item.in_book_scope !== true
        && ['ACTIVE', 'AVAILABLE_TO_ADD'].includes(status);
      return `
        <div class="chapter-planner-row">
          <span>${statusBadge(status)}</span>
          <div>
            <strong>${escapeHtml(item.label || item.display_name || recordId)}</strong>
            <small>${escapeHtml(relationships || item.narrative_type || 'Canon-supported related event')}</small>
            ${message && !['ACTIVE', 'AVAILABLE_TO_ADD'].includes(status)
              ? `<small>${escapeHtml(message)}</small>`
              : ''}
          </div>
          ${canUseInChapter
            ? `<button type="button" data-planner-direction-select="${escapeHtml(recordId)}"
                ${readOnly || loading ? 'disabled' : ''}>Select in Event Board</button>`
            : canAddToBook
              ? `<button type="button" data-planner-direction-add-book="${escapeHtml(recordId)}"
                  ${readOnly || loading ? 'disabled' : ''}>Add to Book</button>`
              : '<span></span>'}
        </div>
      `;
    }).join('');

    const intentResult = state.chapterPlanIntentResult || {};
    const intentStatus = String(intentResult.status || '');
    const intentRows = (intentResult.results || []).map((item) => {
      const recordId = String(item.record_id || '');
      const status = String(item.status || (item.eligibility || {}).status || 'UNKNOWN');
      const canUseInChapter = item.in_book_scope === true
        && ['ACTIVE', 'AVAILABLE_TO_ADD'].includes(status);
      const canAddToBook = item.in_book_scope !== true
        && ['ACTIVE', 'AVAILABLE_TO_ADD'].includes(status);
      const relevance = item.relevance || {};
      const matched = [
        ...(relevance.matched_capabilities || []),
        ...(relevance.matched_roles || []),
        ...(relevance.matched_story_functions || [])
      ].filter(Boolean).slice(0, 4).join(', ');
      return `
        <div class="chapter-planner-row">
          <span>${statusBadge(status)}</span>
          <div>
            <strong>${escapeHtml(item.label || item.display_name || recordId)}</strong>
            <small>${escapeHtml(matched || item.summary || 'Canon Index candidate')}</small>
          </div>
          ${canUseInChapter
            ? `<button type="button" data-planner-intent-select="${escapeHtml(recordId)}"
                ${readOnly || loading ? 'disabled' : ''}>Select for Chapter</button>`
            : canAddToBook
              ? `<button type="button" data-planner-intent-add-book="${escapeHtml(recordId)}"
                  ${readOnly || loading ? 'disabled' : ''}>Add to Book</button>`
              : '<span></span>'}
        </div>
      `;
    }).join('');
    const intentAmbiguities = (intentResult.clarification_choices || intentResult.ambiguities || [])
      .map((item) => {
        const question = typeof item === 'string' ? item : String((item || {}).question || '');
        const choices = typeof item === 'object' && item
          ? ((item.choices || []).map((choice) => String(choice || '')).filter(Boolean))
          : [];
        if (!question && !choices.length) return '';
        return `<li>${escapeHtml(question || 'Clarification required')}${
          choices.length ? ` — ${escapeHtml(choices.join(' / '))}` : ''
        }</li>`;
      })
      .filter(Boolean)
      .join('');

    const issues = ((chapter.validation || {}).issues || []).map((issue) => `
      <li>${escapeHtml(issue.message || issue.code || 'Chapter Plan issue')}</li>
    `).join('');

    const knowledgePackBlockerRows = knowledgePackBlockers.map((item) => {
      const code = String(item.code || '');
      const authorMessages = {
        book_runtime_context_not_current: `Book ${state.chapterPlanBookNumber}'s Book Knowledge Pack must be compiled and current before this Chapter Knowledge Pack can be built.`,
        chapter_plan_not_complete: 'Save this Chapter Plan first so its selections, sequence, kickoff, objectives, restrictions, and controls are current.',
        chapter_plan_invalid: 'Resolve the Chapter Plan items marked as invalid before compiling.',
        chapter_plan_outdated: 'The Book Plan or Book Canon changed after this chapter was saved. Save the Chapter Plan again after reviewing it.',
        chapter_plan_dependencies_not_ready: 'One or more approved Book-level planning dependencies are not current yet.',
        story_controls_invalid: 'Resolve the Story Control issue shown above before compiling.'
      };
      return `<li>${escapeHtml(authorMessages[code] || item.message || code || 'Knowledge Pack blocker')}</li>`;
    }).join('');

    const knowledgePackUnlockRows = knowledgePackUnlockEvaluations.map((item) => {
      const decision = item.decision || {};
      const status = String(decision.status || 'UNKNOWN');
      const canOverride = decision.available !== true
        && (decision.allowed_actions || []).includes('request_explicit_override');
      const missing = (decision.missing_prerequisites || [])
        .map((req) => req.label || req.target_ref || req.type || '')
        .filter(Boolean)
        .join(', ');
      return `
        <div class="chapter-planner-row">
          <span>${statusBadge(status)}</span>
          <div>
            <strong>${escapeHtml(item.label || item.record_id || 'Canon target')}</strong>
            <small>${escapeHtml(decision.author_message || 'Story Eligibility evaluated this target.')}</small>
            ${missing ? `<small>Missing: ${escapeHtml(missing)}</small>` : ''}
            ${decision.override_applied === true
              ? '<small>Explicit one-time progression override is active for this position.</small>'
              : ''}
          </div>
          ${canOverride
            ? `<button type="button"
                data-progression-override="${escapeHtml(item.record_id || '')}"
                data-progression-requested-use="${escapeHtml(item.requested_use || 'chapter_selection')}"
                ${readOnly || loading || knowledgePackBusy ? 'disabled' : ''}>
                Authorize Early Use
              </button>`
            : '<span></span>'}
        </div>
      `;
    }).join('');

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-chapter-planner-v1">
        <p class="placeholder">
          Plan the chapter in one place. Choose Canon for This Chapter from the approved
          Canon for This Book, arrange any events you want to use, and add a short Generation Kickoff.
          Detailed beat planning is optional. Generation remains locked.
        </p>

        <div class="workspace-stat-grid">
          ${statCard('Book', String(state.chapterPlanBookNumber))}
          ${statCard('Chapter', String(state.chapterPlanChapterNumber))}
          ${statCard('Lifecycle', labelFor(chapter.lifecycle_state || chapter.status || 'draft'))}
          ${statCard('Revision', number(chapter.revision || 0))}
          ${statCard('Generation', 'Locked')}
        </div>

        ${bookScopeApproved ? '' : `<div class="workspace-error-note planner-gate-note"><strong>Canon for Book ${state.chapterPlanBookNumber} is not approved yet.</strong> Choose and approve Canon for This Book in Book Planner before building the chapter. <button type="button" id="chapter-open-book-canon" class="primary-action compact-action">Open Book Planner</button></div>`}

        <div class="chapter-planner-toolbar">
          <label>
            Book
            <select id="chapter-plan-book" ${loading ? 'disabled' : ''}>
              ${Array.from({ length: bookCount }, (_, index) => index + 1)
                .map((bookNumber) => `
                  <option value="${bookNumber}" ${bookNumber === state.chapterPlanBookNumber ? 'selected' : ''}>
                    Book ${bookNumber}
                  </option>
                `).join('')}
            </select>
          </label>
          <label>
            Chapter
            <select id="chapter-plan-chapter" ${loading ? 'disabled' : ''}>
              ${Array.from({ length: chaptersPerBook }, (_, index) => index + 1)
                .map((chapterNumber) => `
                  <option value="${chapterNumber}" ${chapterNumber === state.chapterPlanChapterNumber ? 'selected' : ''}>
                    Chapter ${chapterNumber}
                  </option>
                `).join('')}
            </select>
          </label>
          <label>
            Related-event anchor
            <select id="chapter-plan-anchor" ${loading ? 'disabled' : ''}>
              <option value="">All Book Canon events</option>
              ${eventOptions}
            </select>
          </label>
          <button type="button" id="chapter-plan-refresh" class="secondary-action"
            ${loading ? 'disabled' : ''}>${loading ? 'Loading…' : 'Refresh'}</button>
        </div>

        <details class="chapter-planner-card planner-selected-summary" open>
          <summary>
            <strong>Selected for This Chapter</strong>
            <span id="chapter-selected-summary-count">${number(selectedIds.size)} Canon · ${number(assignedEventIds.size)} sequenced events</span>
          </summary>
          <div class="chapter-batch-toolbar">
            <button type="button" class="secondary-action compact-action" data-chapter-canon-batch-action="return_selected" ${readOnly || loading ? 'disabled' : ''}>Return Selected</button>
            <button type="button" class="secondary-action compact-action" data-chapter-canon-batch-action="return_all" ${readOnly || loading ? 'disabled' : ''}>Return All</button>
          </div>
          <div id="chapter-selected-summary-body" class="planner-selected-summary-body">
            ${selectedCanonRows || '<div class="workspace-disabled-note">Nothing selected for this chapter yet.</div>'}
          </div>
        </details>

        ${recoveryNotice}
        <div id="chapter-unsaved-reminder" class="workspace-warning-note" ${chapterDraftDirty ? '' : 'hidden'}>
          <strong>Unsaved Chapter Plan changes.</strong>
          Save Chapter Plan to persist the current chapter selections and event order.
          The existing Chapter Knowledge Pack files are not updated by Save; compile the Chapter Knowledge Pack
          afterward to replace the derived pack.
        </div>

        <section class="chapter-planner-card">
          <h3>Available Characters & Locations</h3>
          <p class="placeholder">Choose deliberate chapter participants/settings. Mark several rows, then Add Selected, or use the per-item Add to Chapter button.</p>
          <div class="chapter-batch-toolbar">
            <button type="button" class="primary-action compact-action" data-chapter-canon-batch-action="add_selected" ${readOnly || loading ? 'disabled' : ''}>Add Selected</button>
          </div>
          <div id="chapter-available-canon-list" class="chapter-planner-list">
            ${availableCanonRows || '<div class="workspace-disabled-note">No additional characters or locations are available from the approved Book Canon.</div>'}
          </div>
        </section>

        <section class="chapter-planner-card">
          <h3>Chapter Event Sequence</h3>
          <p class="placeholder">The order below is authoritative planning order for the Chapter Knowledge Pack. Use Earlier/Later to arrange the narrative beats.</p>
          <div class="chapter-batch-toolbar">
            <button type="button" class="secondary-action compact-action" data-chapter-event-batch-action="return_selected" ${readOnly || loading ? 'disabled' : ''}>Return Selected</button>
          </div>
          <div id="chapter-event-sequence-list" class="chapter-event-sequence-list">
            ${eventSequenceRows || '<div class="workspace-disabled-note" id="chapter-event-sequence-empty">No events sequenced yet.</div>'}
          </div>
        </section>

        <details class="chapter-planner-card planner-selected-summary" open>
          <summary>
            <strong>Available Events</strong>
            <span>${escapeHtml(number(availableEvents.length))} available for this chapter</span>
          </summary>
          <p class="placeholder">
            Events stay available to later chapters and books. Adding an event here removes it only from this
            chapter's Available Events list and places it in the Chapter Event Sequence.
          </p>
          <label class="chapter-planner-field">
            Filter events
            <input id="chapter-plan-event-query" type="search"
              value="${escapeHtml(state.chapterPlanEventQuery || '')}"
              placeholder="Filter by event meaning, date, or identifier" />
          </label>
          <div class="chapter-batch-toolbar">
            <button type="button" class="primary-action compact-action" data-chapter-event-batch-action="add_selected" ${readOnly || loading ? 'disabled' : ''}>Add Selected</button>
          </div>
          <div id="chapter-event-available-list" class="chapter-event-sequence-list">
            ${availableEventRows || '<div class="workspace-disabled-note">No additional Book Canon events are available for this chapter.</div>'}
          </div>
        </details>

        <section class="chapter-planner-card">
          <h3>Related Events / Possible Next Directions</h3>
          <p class="placeholder">
            Use this when you want help spotting Canon-supported events that could logically follow,
            react to, or connect with the event anchor you chose. Suggestions are optional; you decide
            whether any belong in this chapter.
          </p>
          <div class="chapter-batch-toolbar">
            <button type="button" id="chapter-plan-directions-load" class="secondary-action compact-action" ${readOnly || loading || directionsBusy ? 'disabled' : ''}>${directionsBusy ? 'Looking…' : 'Load Possible Directions'}</button>
          </div>
          <div class="chapter-planner-list">
            ${directionRows || (state.chapterPlanDirectionsQueried
              ? '<div class="workspace-disabled-note"><strong>No related Canon directions were found.</strong> Choose a different event anchor or continue planning without a suggested direction.</div>'
              : '<div class="workspace-disabled-note">Choose an event anchor when useful, then click Load Possible Directions. Nothing is added to the chapter automatically.</div>')}
          </div>
        </section>

        <section class="chapter-planner-card">
          <h3>Generation Kickoff</h3>
          <label class="chapter-planner-field">
            Small starting instruction
            <textarea id="chapter-plan-kickoff" ${readOnly || loading ? 'disabled' : ''}
              placeholder="Open with…">${escapeHtml(chapter.generation_kickoff || '')}</textarea>
          </label>
          <label class="chapter-planner-field">
            Optional chapter objective
            <textarea id="chapter-plan-objective" ${readOnly || loading ? 'disabled' : ''}
              placeholder="Optional objective">${escapeHtml(chapter.chapter_objective || '')}</textarea>
          </label>
          <label class="chapter-planner-field">
            Optional restrictions — one per line
            <textarea id="chapter-plan-restrictions" ${readOnly || loading ? 'disabled' : ''}
              placeholder="Do not reveal…">${escapeHtml((chapter.restrictions || []).join('\n'))}</textarea>
          </label>
        </section>

        <section class="chapter-planner-card chapter-plan-amendment-card">
          <h3>Find More Canon</h3>
          ${bookScopeApproved ? '' : '<div class="workspace-disabled-note"><strong>Available after Canon for This Book is approved.</strong> Finish and approve the book’s initial Canon selection before adding new Canon from a chapter.</div>'}
          <p class="placeholder">
            Use this when the chapter needs a character, location, event, or other Canon item that you
            did not originally include in this book. Search the wider project Canon, review the choices,
            and explicitly add only what the chapter needs. The application will prevent future or
            restricted information from being introduced early without authorization.
          </p>
          <div class="workspace-disabled-note chapter-plan-amendment-shared-note">
            <strong>Applies to both options below.</strong> Adding or removing Book Canon through either
            <strong>Search Wider Canon</strong> or <strong>Ask the Planner</strong> changes what is available
            from this chapter forward. Review the change, then re-approve Canon for This Book in Book Planner before
            making another amendment.
          </div>

          <div class="chapter-plan-find-subsection">
            <strong>Search Wider Canon</strong>
            <p class="placeholder">
              Use this when you know roughly what Canon you want. Search by name, place, date, event, or keyword.
            </p>
            <label class="chapter-planner-field">
              Search wider project Canon
              <input id="chapter-plan-amend-query" type="search"
                value="${escapeHtml(state.chapterPlanAmendQuery || '')}"
                placeholder="Find more Canon" />
            </label>
            <div class="chapter-batch-toolbar">
              <button type="button" id="chapter-plan-amend-load" class="secondary-action compact-action" ${readOnly || loading || !bookScopeApproved ? 'disabled' : ''}>Search Wider Canon</button>
            </div>
          </div>
          <div class="chapter-planner-list chapter-plan-search-results">
            ${plannerCatalogItems(state.chapterPlanAmendCatalog || { categories: [] }).flatMap((category) => category.items || []).slice(0, 120).map((item) => {
              const recordId = String(item.record_id || '');
              const status = String((item.eligibility || {}).status || 'UNKNOWN');
              const selected = item.selected === true;
              const action = selected ? 'remove' : 'add';
              const allowed = selected || ['ACTIVE', 'AVAILABLE_TO_ADD'].includes(status);
              const canOverride = !selected
                && ((item.eligibility || {}).allowed_actions || []).includes('request_explicit_override');
              const actionButton = selected || allowed
                ? `<button type="button"
                    data-chapter-book-amend="${action}"
                    data-record-id="${escapeHtml(recordId)}"
                    ${readOnly || loading || !bookScopeApproved ? 'disabled' : ''}>
                    ${selected ? 'Remove from Book' : 'Add to Book'}
                  </button>`
                : canOverride
                  ? `<button type="button"
                      data-progression-override-add-book="${escapeHtml(recordId)}"
                      ${readOnly || loading || knowledgePackBusy || !bookScopeApproved ? 'disabled' : ''}>
                      Authorize & Add to Book
                    </button>`
                  : `<button type="button" disabled>Add to Book</button>`;
              return `
                <div class="chapter-planner-row">
                  <span>${statusBadge(status)}</span>
                  <div>
                    <strong>${escapeHtml(item.label || recordId)}</strong>
                    <small>${escapeHtml(labelFor(item.record_group_id || item.record_type || 'Canon'))}</small>
                  </div>
                  ${actionButton}
                </div>
              `;
            }).join('') || (state.chapterPlanAmendQueried
              ? '<div class="workspace-disabled-note"><strong>No wider Canon matches this search.</strong> Try a different name, date, place, event, or idea, or continue with the Canon already selected for the book.</div>'
              : '<div class="workspace-disabled-note">Enter a search only when this chapter needs Canon that was not already selected for the book.</div>')}
          </div>

          <div class="chapter-planner-field chapter-plan-find-subsection chapter-plan-intent-subsection">
            <strong>Ask the Planner for Canon (Optional)</strong>
            <p class="placeholder">
              Use this when you know what the story needs but do not know which Canon record fits. Describe
              that need in normal author language. For example: “I need someone who could plausibly hear this
              news without knowing Italus's secret.” The Planner suggests matching Canon; you decide what to use.
              Suggestions never bypass Book eligibility or future-knowledge restrictions.
            </p>
            <textarea id="chapter-plan-intent-query"
              placeholder="Example: I need someone who understands machine identity without involving an authority figure."
              ${state.chapterPlanIntentLoading ? 'disabled' : ''}>${escapeHtml(state.chapterPlanIntentQuery || '')}</textarea>
            <div class="chapter-batch-toolbar">
              <button type="button" id="chapter-plan-intent-run" class="secondary-action compact-action"
                ${state.chapterPlanIntentLoading ? 'disabled' : ''}>
                ${state.chapterPlanIntentLoading ? 'Interpreting…' : 'Interpret & Find Canon'}
              </button>
            </div>
          </div>

          ${intentStatus === 'model_unavailable'
            ? `<div class="workspace-disabled-note">${escapeHtml(intentResult.message || 'Local Planner Intent Model is not configured or unavailable. Deterministic Planner actions remain available.')}</div>`
            : ''}
          ${intentStatus === 'invalid_model_output' || intentStatus === 'model_error'
            ? `<div class="workspace-disabled-note">${escapeHtml(intentResult.message || 'Planner intent interpretation failed safely.')}</div>`
            : ''}
          ${intentStatus === 'clarification_required'
            ? `<div class="workspace-disabled-note"><strong>Clarification required.</strong><ul>${intentAmbiguities}</ul></div>`
            : ''}
          ${intentStatus === 'ok'
            ? `<div class="chapter-planner-list">${intentRows || '<div class="workspace-disabled-note">No Canon Index candidates matched the interpreted intent.</div>'}</div>`
            : ''}

        </section>

        <section class="chapter-planner-card story-control-registry-card">
          <h3>Story Controls</h3>
          <p class="placeholder">
            Use Story Controls to specify an important development this chapter must deliver without
            changing Master Canon. You can control what is revealed, what a character learns or suspects,
            how a relationship changes, and how strongly the development should land. Selected controls
            become part of this Chapter Plan and later guide chapter generation.
          </p>

          <details class="planner-reveal-catalog" open>
            <summary><strong>Available Mystery / Reveal Threads</strong> — ${number(revealThreads.length)}</summary>
            <div class="planner-reveal-grid">
              ${revealThreads.map((thread) => `
                <article class="planner-reveal-card">
                  <header><strong>${escapeHtml(thread.title || thread.reveal_id || 'Reveal')}</strong>
                    <span>${escapeHtml((thread.eligible_books || []).map((n) => `Book ${n}`).join(', '))}</span></header>
                  <p><strong>Reader question:</strong> ${escapeHtml(thread.reader_question || '')}</p>
                  <p>${escapeHtml(thread.purpose || '')}</p>
                  <small><strong>Next permitted reveal:</strong> ${escapeHtml(thread.next_reveal || '')}</small>
                  ${thread.forbidden_early_disclosure ? `<small><strong>Do not reveal early:</strong> ${escapeHtml(thread.forbidden_early_disclosure)}</small>` : ''}
                  <button type="button" class="secondary-action" data-reveal-use="${escapeHtml(thread.reveal_id || '')}"
                    ${readOnly || loading || state.storyControlSaving ? 'disabled' : ''}>Use This Reveal in Chapter</button>
                </article>`).join('') || '<div class="workspace-disabled-note">No project reveal threads are scheduled for this book.</div>'}
            </div>
          </details>

          <div class="chapter-planner-grid">
            <div>
              <h4>Controls for this chapter</h4>
              <div class="chapter-planner-list">
                ${storyControls.map((control) => {
                  const controlId = String(control.control_id || '');
                  const valid = (control.validation || {}).valid === true;
                  const checked = selectedStoryControlIds.has(controlId);
                  const issueText = ((control.validation || {}).issues || [])
                    .map((issue) => issue.message || issue.code || '')
                    .filter(Boolean)
                    .join(' ');
                  return `
                    <div class="chapter-planner-row">
                      <input type="checkbox" data-story-control-ref="${escapeHtml(controlId)}"
                        ${checked ? 'checked' : ''}
                        ${readOnly || loading || !valid ? 'disabled' : ''} />
                      <div>
                        <strong>${escapeHtml(labelFor(control.control_type || 'Story Control'))}</strong>
                        <small>${escapeHtml(control.instruction || 'No instruction')}</small>
                        ${issueText ? `<small>${escapeHtml(issueText)}</small>` : ''}
                      </div>
                      <span>${valid ? statusBadge('VALID') : statusBadge('RESTRICTED')}</span>
                    </div>
                  `;
                }).join('') || '<div class="workspace-disabled-note">No Story Controls are defined for this chapter.</div>'}
              </div>
            </div>

            <div class="story-control-form">
              <h4>+ Add Story Control</h4>
              <p class="placeholder">Choose the kind of development, who or what it affects, what must happen, how certain it becomes, how the reader encounters it, and how much narrative weight it should carry.</p>
              <label class="chapter-planner-field">
                Type
                <select id="story-control-type" ${readOnly || loading || state.storyControlSaving ? 'disabled' : ''}>
                  ${['mystery_reveal', 'knowledge_change', 'relationship_change', 'availability_change', 'escalation_change']
                    .map((value) => `<option value="${value}" ${String(storyDraft.control_type || '') === value ? 'selected' : ''}>${escapeHtml(labelFor(value))}</option>`).join('')}
                </select>
              </label>
              <label class="chapter-planner-field">
                Subject
                <select id="story-control-subject" ${readOnly || loading || state.storyControlSaving ? 'disabled' : ''}>
                  <option value="" ${!storyDraft.subject_record_id ? 'selected' : ''}>No specific Canon subject</option>
                  ${catalogItems.map((item) => `
                    <option value="${escapeHtml(item.record_id || '')}" ${String(storyDraft.subject_record_id || '') === String(item.record_id || '') ? 'selected' : ''}>
                      ${escapeHtml(item.label || item.record_id || '')}
                    </option>
                  `).join('')}
                </select>
              </label>
              <label class="chapter-planner-field">
                What happens here?
                <textarea id="story-control-instruction"
                  ${readOnly || loading || state.storyControlSaving ? 'disabled' : ''}
                  placeholder="State the story development in normal author language.">${escapeHtml(storyDraft.instruction || '')}</textarea>
              </label>
              <label class="chapter-planner-field">
                Certainty / effect
                <select id="story-control-certainty" ${readOnly || loading || state.storyControlSaving ? 'disabled' : ''}>
                  ${['hint', 'suspicion', 'supported_evidence', 'corroborated_fact', 'objective_truth']
                    .map((value) => `<option value="${value}" ${String(storyDraft.certainty || 'supported_evidence') === value ? 'selected' : ''}>${escapeHtml(labelFor(value))}</option>`).join('')}
                </select>
              </label>
              <label class="chapter-planner-field">
                Presentation
                <select id="story-control-presentation" ${readOnly || loading || state.storyControlSaving ? 'disabled' : ''}>
                  ${['foreshadowing', 'memory_fragment', 'physical_artifact', 'technical_record', 'testimony', 'visual_clue', 'dialogue', 'other']
                    .map((value) => `<option value="${value}" ${String(storyDraft.presentation || '') === value ? 'selected' : ''}>${escapeHtml(labelFor(value))}</option>`).join('')}
                </select>
              </label>
              <label class="chapter-planner-field">
                Narrative weight
                <select id="story-control-weight" ${readOnly || loading || state.storyControlSaving ? 'disabled' : ''}>
                  ${['brief_clue', 'short_reveal_beat', 'major_scene_beat']
                    .map((value) => `<option value="${value}" ${String(storyDraft.narrative_weight || '') === value ? 'selected' : ''}>${escapeHtml(labelFor(value))}</option>`).join('')}
                </select>
              </label>
              <div class="chapter-planner-actions">
                <button type="button" id="story-control-save"
                  ${readOnly || loading || state.storyControlSaving ? 'disabled' : ''}>
                  ${state.storyControlSaving ? 'Saving…' : 'Save Story Control'}
                </button>
              </div>
            </div>
          </div>
        </section>

        <section class="chapter-planner-card chapter-knowledge-pack-card">
          <h3>Chapter Knowledge Pack</h3>
          <p class="placeholder">
            The Chapter Knowledge Pack combines this saved Chapter Plan with the approved Book knowledge
            needed for later chapter generation. <strong>Save Chapter Plan</strong> stores your current
            selections and instructions. <strong>Compile Chapter Knowledge Pack</strong> is a separate next
            step and becomes available only when the Book Knowledge Pack and this saved Chapter Plan are current.
          </p>

          <div class="workspace-stat-grid">
            ${statCard('Pack Status', knowledgePackDisplayStatus)}
            ${statCard('Mode', labelFor(chapterKnowledgePack.mode || (state.chapterPlanChapterNumber === 1 ? 'chapter_1' : 'continuity_driven')))}
            ${statCard('Compiler', chapterKnowledgePack.compiler_ready === true ? 'Ready' : 'Blocked')}
            ${statCard('Generation', 'Locked')}
          </div>

          ${knowledgePackBlockerRows
            ? `<div class="workspace-disabled-note"><strong>Not ready to compile yet</strong><ul>${knowledgePackBlockerRows}</ul>${bookPlanApprovalBlocker ? `<p><strong>Book ${number(state.chapterPlanBookNumber)} Plan changed after its last approval.</strong> Review and approve the Book Plan before recompiling its Knowledge Pack.</p>` : ''}</div>`
            : knowledgePackFile.current === true
              ? '<div class="workspace-success-note"><strong>Chapter Knowledge Pack is current.</strong> It matches the saved Chapter Plan and current upstream planning dependencies.</div>'
              : knowledgePackFile.exists === true
                ? '<div class="workspace-warning-note"><strong>Chapter Knowledge Pack needs recompilation.</strong> The saved Chapter Plan or another dependency changed after this pack was compiled. Save any current chapter edits, then compile the Chapter Knowledge Pack to replace the outdated derived files.</div>'
                : '<div class="workspace-success-note">All upstream planning dependencies are current. Save any unsaved chapter edits, then compile the first Chapter Knowledge Pack for this chapter.</div>'}
          <div class="workspace-action-row compact-action-row knowledge-pack-workflow-actions">
            <button type="button" id="chapter-open-book-plan" class="secondary-action compact-action" ${bookPlanApprovalBlocker ? '' : 'disabled'}>Open Book ${number(state.chapterPlanBookNumber)} Plan</button>
            <button type="button" id="chapter-compile-book-knowledge" class="primary-action compact-action" ${readOnly || loading || knowledgePackBusy || bookKnowledgeCompileBusy || !bookKnowledgeCompileAllowed ? 'disabled' : ''}>${bookKnowledgeCompileBusy ? 'Compiling Book Knowledge Pack…' : `Compile Book ${number(state.chapterPlanBookNumber)} Knowledge Pack`}</button>
            <button type="button" id="chapter-open-book-knowledge" class="secondary-action compact-action">Open Book Knowledge Pack Details</button>
          </div>
          ${chapterDraftDirty ? '<div class="workspace-warning-note"><strong>Unsaved chapter changes.</strong> Save Chapter Plan before compiling a Knowledge Pack.</div>' : ''}

          <div class="chapter-planner-list">
            ${knowledgePackUnlockRows || '<div class="workspace-disabled-note">No selected Canon targets require an Unlock evaluation.</div>'}
          </div>

          ${state.chapterPlanChapterNumber > 1
            ? `<label class="chapter-planner-field">
                Optional bounded previous-chapter ending context
                <textarea id="chapter-knowledge-pack-prior-ending"
                  ${readOnly || loading || knowledgePackBusy ? 'disabled' : ''}
                  maxlength="8000"
                  placeholder="Optional local ending excerpt/context only; all prior prose is not resent.">${escapeHtml(state.chapterPriorEndingContext || '')}</textarea>
              </label>`
            : ''}

          ${(knowledgePackTokens.chapter_knowledge_pack_estimated_tokens || 0) > 0
            ? `<div class="workspace-disabled-note">
                Estimated tokens — Chapter Pack:
                ${escapeHtml(number(knowledgePackTokens.chapter_knowledge_pack_estimated_tokens || 0))};
                Book Runtime Context:
                ${escapeHtml(number(knowledgePackTokens.book_runtime_context_estimated_tokens || 0))};
                Full Project Runtime Context:
                ${escapeHtml(number(knowledgePackTokens.full_project_runtime_context_estimated_tokens || 0))}.
              </div>`
            : ''}

          <div class="chapter-planner-actions">
            <button type="button" id="chapter-knowledge-pack-compile"
              ${readOnly || loading || knowledgePackBusy || chapterKnowledgePack.compiler_ready !== true ? 'disabled' : ''}>
              ${knowledgePackBusy ? 'Compiling…' : 'Compile Chapter Knowledge Pack'}
            </button>
          </div>
        </section>

        <div class="chapter-planner-status">
          ${(chapter.validation || {}).valid === false
            ? `<strong>Reconciliation required.</strong><ul>${issues}</ul>`
            : (chapter.freshness || {}).fresh === false
              ? '<strong>Outdated:</strong> Canon for This Book or the Book Plan changed after this chapter draft was saved.'
              : 'Chapter Plan references are structurally valid against the current planning state.'}
        </div>

        <div class="chapter-planner-actions">
          <button type="button" id="chapter-plan-save"
            ${readOnly || loading ? 'disabled' : ''}>${state.chapterPlanSaving ? 'Saving…' : 'Save Chapter Plan'}</button>
          ${state.chapterPlanSavedNotice ? `<span class="chapter-save-confirmation">✓ ${escapeHtml(state.chapterPlanSavedNotice)}</span>` : ''}
        </div>

        <div class="workspace-disabled-note">
          Chapter planning controls what this chapter must use and accomplish. Knowledge Pack compilation
          prepares that approved planning context for later generation; it does not generate prose or write
          Approved Continuity.
        </div>
      </div>
    `;

    document.getElementById('chapter-plan-book')?.addEventListener('change', (event) => {
      state.chapterPlanBookNumber = Number(event.target.value || 1);
      state.chapterPlanChapterNumber = 1;
      state.chapterPlan = null;
      state.chapterPlanBookCatalog = null;
      state.chapterPlanEffectiveScope = null;
      state.chapterPlanAmendCatalog = null;
      state.chapterPlanIntentResult = null;
      state.chapterPlanIntentQuery = '';
      state.storyControls = null;
      state.plannerRevealCatalog = null;
      state.chapterKnowledgePack = null;
      state.chapterPriorEndingContext = '';
      state.chapterPlanEventCandidates = null;
      state.chapterPlanPossibleDirections = null;
      state.chapterPlanAnchorEventId = '';
      clearChapterPlannerDraft();
      state.chapterPlanDirectionsQueried = false;
      state.chapterPlanAmendQueried = false;
      state.chapterPlanSavedNotice = '';
      void loadChapterPlanner();
    });
    document.getElementById('chapter-plan-chapter')?.addEventListener('change', (event) => {
      state.chapterPlanChapterNumber = Number(event.target.value || 1);
      state.chapterPlan = null;
      state.chapterPlanEffectiveScope = null;
      state.chapterPlanIntentResult = null;
      state.chapterPlanIntentQuery = '';
      state.storyControls = null;
      state.chapterKnowledgePack = null;
      state.chapterPriorEndingContext = '';
      state.chapterPlanEventCandidates = null;
      state.chapterPlanPossibleDirections = null;
      clearChapterPlannerDraft();
      state.chapterPlanDirectionsQueried = false;
      state.chapterPlanAmendQueried = false;
      state.chapterPlanSavedNotice = '';
      void loadChapterPlanner();
    });
    document.getElementById('chapter-plan-anchor')?.addEventListener('change', (event) => {
      state.chapterPlanAnchorEventId = String(event.target.value || '');
      state.chapterPlanPossibleDirections = null;
      void loadChapterEventCandidates();
      setLog('Anchor updated. Load Possible Next Directions when you want relationship suggestions.');
    });
    document.getElementById('chapter-plan-event-query')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        state.chapterPlanEventQuery = String(event.target.value || '').trim();
        void loadChapterEventCandidates();
      }
    });
    document.getElementById('chapter-plan-directions-load')?.addEventListener('click', () => {
      void loadPossibleNextDirections();
    });
    document.getElementById('chapter-plan-amend-load')?.addEventListener('click', () => {
      const input = document.getElementById('chapter-plan-amend-query');
      state.chapterPlanAmendQuery = String(input?.value || '').trim();
      void loadChapterAmendCatalog();
    });
    document.getElementById('chapter-plan-amend-query')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        state.chapterPlanAmendQuery = String(event.target.value || '').trim();
        void loadChapterAmendCatalog();
      }
    });
    mainPanel.querySelectorAll('[data-chapter-book-amend]').forEach((button) => {
      button.addEventListener('click', () => {
        void amendChapterBookCanon(button.dataset.recordId, button.dataset.chapterBookAmend);
      });
    });
    mainPanel.querySelectorAll('[data-progression-override-add-book]').forEach((button) => {
      button.addEventListener('click', () => {
        void authorizeProgressionOverride(
          String(button.dataset.progressionOverrideAddBook || ''),
          'chapter_selection',
          true
        );
      });
    });
    mainPanel.querySelectorAll('[data-planner-direction-select]').forEach((button) => {
      button.addEventListener('click', () => {
        const recordId = String(button.dataset.plannerDirectionSelect || '');
        const row = mainPanel.querySelector(
          `[data-chapter-event-row="${CSS.escape(recordId)}"]`
        );
        if (!row) {
          setLog('Related event is not currently available in the Event Board.');
          return;
        }
        moveChapterEventCard(recordId, true);
        setLog('Related event added to this chapter. Save the Chapter Plan to persist the updated event order.');
      });
    });
    mainPanel.querySelectorAll('[data-planner-direction-add-book]').forEach((button) => {
      button.addEventListener('click', () => {
        void amendChapterBookCanon(button.dataset.plannerDirectionAddBook, 'add');
      });
    });
    document.getElementById('chapter-plan-intent-run')?.addEventListener('click', () => {
      const input = document.getElementById('chapter-plan-intent-query');
      state.chapterPlanIntentQuery = String(input?.value || '').trim();
      void runPlannerIntentQuery();
    });
    mainPanel.querySelectorAll('[data-planner-intent-add-book]').forEach((button) => {
      button.addEventListener('click', () => {
        void amendChapterBookCanon(button.dataset.plannerIntentAddBook, 'add');
      });
    });
    mainPanel.querySelectorAll('[data-planner-intent-select]').forEach((button) => {
      button.addEventListener('click', () => {
        const recordId = String(button.dataset.plannerIntentSelect || '');
        const row = mainPanel.querySelector(
          `[data-chapter-canon-row="${CSS.escape(recordId)}"]`
        );
        if (!row) {
          setLog('Planner suggestion is not currently available in Canon for This Book.');
          return;
        }
        moveChapterCanonRow(recordId, true);
        setLog('Planner suggestion added to this chapter. Save the Chapter Plan to persist it.');
      });
    });
    mainPanel.querySelectorAll('[data-reveal-use]').forEach((button) => {
      button.addEventListener('click', () => {
        const id = String(button.dataset.revealUse || '');
        const thread = revealThreads.find((item) => String(item.reveal_id || '') === id);
        if (!thread) return;
        const type = document.getElementById('story-control-type');
        const instruction = document.getElementById('story-control-instruction');
        const certainty = document.getElementById('story-control-certainty');
        const presentation = document.getElementById('story-control-presentation');
        const weight = document.getElementById('story-control-weight');
        const subject = document.getElementById('story-control-subject');
        if (type) type.value = 'mystery_reveal';
        if (instruction) instruction.value = String(thread.next_reveal || thread.purpose || '');
        if (certainty) certainty.value = String(thread.default_certainty || 'supported_evidence');
        if (presentation) presentation.value = String(thread.default_presentation || 'foreshadowing');
        if (weight) weight.value = String(thread.default_weight || 'brief_clue');
        if (subject && thread.subject_record_id) subject.value = String(thread.subject_record_id);
        setLog(`Reveal thread loaded: ${thread.title || id}. Review the Story Control fields, then save it.`);
      });
    });
    document.getElementById('story-control-save')?.addEventListener('click', () => void saveStoryControl());
    document.getElementById('chapter-knowledge-pack-compile')?.addEventListener('click', () => {
      const priorEnding = document.getElementById('chapter-knowledge-pack-prior-ending');
      state.chapterPriorEndingContext = String(priorEnding?.value || state.chapterPriorEndingContext || '');
      if (state.chapterPlanDraftDirty) {
        showChapterSaveRequiredModal('compile the Chapter Knowledge Pack');
        return;
      }
      void compileChapterKnowledgePack();
    });
    mainPanel.querySelectorAll('[data-progression-override]').forEach((button) => {
      button.addEventListener('click', () => {
        void authorizeProgressionOverride(
          String(button.dataset.progressionOverride || ''),
          String(button.dataset.progressionRequestedUse || 'chapter_selection')
        );
      });
    });
    document.getElementById('chapter-plan-refresh')?.addEventListener('click', () => void loadChapterPlanner());
    document.getElementById('chapter-open-book-canon')?.addEventListener('click', () => { state.bookPlanBookNumber = state.chapterPlanBookNumber; state.bookScopeBookNumber = state.chapterPlanBookNumber; state.bookScopeCatalog = null; renderSection('book_plan'); });
    document.getElementById('chapter-open-book-plan')?.addEventListener('click', () => {
      state.bookPlanBookNumber = Number(state.chapterPlanBookNumber || 1);
      renderSection('book_plan');
    });
    document.getElementById('chapter-compile-book-knowledge')?.addEventListener('click', () => {
      if (state.chapterPlanDraftDirty) {
        showChapterSaveRequiredModal(`compile Book ${Number(state.chapterPlanBookNumber || 1)} Knowledge Pack`);
        return;
      }
      void compileCurrentBookKnowledgePackFromChapter();
    });
    document.getElementById('chapter-open-book-knowledge')?.addEventListener('click', () => renderSection('book_runtime_context'));
    document.getElementById('chapter-recover-previous-pack')?.addEventListener('click', () => recoverChapterPlannerFromPreviousPack());
    document.getElementById('chapter-plan-save')?.addEventListener('click', () => void saveChapterPlanner());
    mainPanel.querySelectorAll('#chapter-plan-kickoff, #chapter-plan-objective, #chapter-plan-restrictions, [data-chapter-pov-ref], [data-chapter-event-position], [data-chapter-event-role], [data-chapter-event-relationship], [data-chapter-event-anchor], [data-chapter-event-objective], [data-story-control-ref], #story-control-type, #story-control-subject, #story-control-instruction, #story-control-certainty, #story-control-presentation, #story-control-weight').forEach((node) => {
      node.addEventListener(node.tagName === 'TEXTAREA' || node.tagName === 'INPUT' ? 'input' : 'change', () => markChapterPlannerDraftDirty());
      if (node.tagName === 'SELECT' || node.type === 'checkbox') node.addEventListener('change', () => markChapterPlannerDraftDirty());
    });

    if (!state.chapterPlan && !state.chapterPlanLoading) {
      void loadChapterPlanner();
    }
  }


  async function loadChapterPlanner() {
    if (!projectId || state.chapterPlanLoading || state.chapterPlanSaving) return;
    captureChapterPlannerDraft();
    state.chapterPlanLoading = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    try {
      const bookNumber = Number(state.chapterPlanBookNumber || 1);
      const chapterNumber = Number(state.chapterPlanChapterNumber || 1);
      const params = new URLSearchParams({
        book_number: String(bookNumber),
        include_future: 'false',
        query: ''
      });
      const eventParams = new URLSearchParams({
        anchor_event_id: state.chapterPlanAnchorEventId || '',
        query: state.chapterPlanEventQuery || ''
      });
      const [
        chapterPlanResult,
        scopeSnapshotResult,
        catalogResult,
        storyControlsResult,
        revealCatalogResult,
        eventCandidatesResult
      ] = await Promise.all([
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/chapter-plan/${bookNumber}/${chapterNumber}`),
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/book-scope/${bookNumber}/chapter-snapshot?chapter_number=${chapterNumber}`),
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/book-scope/catalog?${params.toString()}`),
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/story-controls?book_number=${bookNumber}&chapter_number=${chapterNumber}`),
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/planner-reveal-catalog?book_number=${bookNumber}`),
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/chapter-plan/${bookNumber}/${chapterNumber}/event-candidates?${eventParams.toString()}`)
      ]);
      state.chapterPlan = chapterPlanResult;
      state.bookScope = { document: { books: [scopeSnapshotResult.book || {}] } };
      state.chapterPlanBookCatalog = catalogResult;
      state.chapterPlanEffectiveScope = scopeSnapshotResult.effective || { selection_ids: [], selections: [] };
      state.storyControls = storyControlsResult;
      state.plannerRevealCatalog = revealCatalogResult;
      state.chapterPlanEventCandidates = eventCandidatesResult;
      setLog(`Chapter Plan loaded for Book ${bookNumber}, Chapter ${chapterNumber}.`);
    } catch (error) {
      setLog(`Chapter Plan load failed: ${error.message}`);
    } finally {
      state.chapterPlanLoading = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
      if (state.activeSection === 'chapter_planner') void loadChapterKnowledgePackStatus();
    }
  }


  async function loadChapterKnowledgePackStatus(keepLoading = false) {
    if (!projectId) return;
    if (!keepLoading) captureChapterPlannerDraft();
    const requestToken = Number(state.chapterKnowledgePackRequestToken || 0) + 1;
    state.chapterKnowledgePackRequestToken = requestToken;
    const draftVersionAtStart = Number(state.chapterPlannerDraftVersion || 0);
    if (!keepLoading) state.chapterKnowledgePackLoading = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    try {
      const [packStatus, bookStatus] = await Promise.all([
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/chapter-knowledge-pack/${state.chapterPlanBookNumber}/${state.chapterPlanChapterNumber}/status`),
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/runtime-context/books/${encodeURIComponent(Number(state.chapterPlanBookNumber || 1))}/readiness-fast`)
      ]);
      if (requestToken !== state.chapterKnowledgePackRequestToken) return;
      state.chapterKnowledgePack = packStatus;
      state.bookRuntimeContext = bookStatus;
    } catch (error) {
      state.chapterKnowledgePack = {
        status: 'blocked',
        compiler_ready: false,
        blockers: [{ code: 'status_load_failed', message: error.message }],
        unlock_evaluations: []
      };
      setLog(`Chapter Knowledge Pack status failed: ${error.message}`);
    } finally {
      if (!keepLoading) {
        state.chapterKnowledgePackLoading = false;
        if (state.activeSection === 'chapter_planner' && requestToken === state.chapterKnowledgePackRequestToken) {
          // Rendering is safe because author mutations are mirrored into chapterPlanDraft synchronously.
          // If the draft changed while status was loading, chapterForRender() uses the newer draft.
          renderChapterPlanner(state.bootstrap);
        }
      }
    }
  }


  async function compileCurrentBookKnowledgePackFromChapter() {
    if (!projectId || state.chapterBookKnowledgeCompileLoading || state.bootstrap.read_only === true) return;
    captureChapterPlannerDraft();
    const bookNumber = Number(state.chapterPlanBookNumber || 1);
    state.chapterBookKnowledgeCompileLoading = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    try {
      const result = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/books/generate?book_number=${encodeURIComponent(bookNumber)}`,
        {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' }
        }
      );
      setLog(
        `Book ${bookNumber} Knowledge Pack ${Number(result.generated_count || 0) > 0 ? 'compiled' : 'is already current'}. ` +
        'Refreshing Chapter Knowledge Pack readiness…'
      );
      state.bookRuntimeContext = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/books/status?book_number=${encodeURIComponent(bookNumber)}`
      );
      state.chapterKnowledgePack = null;
      await loadChapterKnowledgePackStatus(true);
    } catch (error) {
      setLog(`Book ${bookNumber} Knowledge Pack compilation failed: ${error.message}`);
      state.chapterKnowledgePack = null;
      await loadChapterKnowledgePackStatus(true);
    } finally {
      state.chapterBookKnowledgeCompileLoading = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    }
  }


  async function compileChapterKnowledgePack() {
    if (!projectId || state.chapterKnowledgePackLoading || state.bootstrap.read_only === true) return;
    captureChapterPlannerDraft();
    state.chapterKnowledgePackLoading = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    try {
      const result = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/chapter-knowledge-pack/${state.chapterPlanBookNumber}/${state.chapterPlanChapterNumber}/generate`,
        {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prior_ending_context: String(state.chapterPriorEndingContext || '')
          })
        }
      );
      setLog(
        `Chapter Knowledge Pack compiled for Book ${state.chapterPlanBookNumber}, ` +
        `Chapter ${state.chapterPlanChapterNumber}. Generation remains locked.`
      );
      await loadChapterKnowledgePackStatus(true);
      if ((result.token_accounting || {}).chapter_knowledge_pack_estimated_tokens) {
        state.chapterKnowledgePack.token_accounting = result.token_accounting;
      }
    } catch (error) {
      setLog(`Chapter Knowledge Pack compile blocked: ${error.message}`);
      await loadChapterKnowledgePackStatus(true);
    } finally {
      state.chapterKnowledgePackLoading = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    }
  }


  async function authorizeProgressionOverride(recordId, requestedUse, addToBookAfter = false) {
    if (!projectId || !recordId || state.chapterKnowledgePackLoading || state.bootstrap.read_only === true) return;
    const confirmed = window.confirm(
      'Authorize one-time early use at this exact book/chapter position? ' +
      'This does not change Canon, revise the original progression boundary, or establish continuity.'
    );
    if (!confirmed) return;

    state.chapterKnowledgePackLoading = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    try {
      const result = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/progression-overrides/authorize`,
        {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_number: Number(state.chapterPlanBookNumber || 1),
            chapter_number: Number(state.chapterPlanChapterNumber || 1),
            target_ref: recordId,
            requested_use: String(requestedUse || 'chapter_selection'),
            reason: 'Explicit author action from Chapter Planner.'
          })
        }
      );
      const status = String(result.status || 'authorized');
      setLog(
        status === 'already_authorized'
          ? 'One-time early-use authorization was already active for this position.'
          : 'One-time early use authorized. Continuity remains unestablished until a later accepted-continuity commit.'
      );
      await loadChapterKnowledgePackStatus(true);
      if (addToBookAfter) {
        state.chapterKnowledgePackLoading = false;
        await amendChapterBookCanon(recordId, 'add');
        return;
      }
    } catch (error) {
      setLog(`Progression override blocked: ${error.message}`);
      await loadChapterKnowledgePackStatus(true);
    } finally {
      state.chapterKnowledgePackLoading = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    }
  }


  async function loadChapterEventCandidates(keepLoading = false) {
    if (!projectId) return;
    if (!keepLoading) captureChapterPlannerDraft();
    if (!keepLoading) state.chapterPlanLoading = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    const params = new URLSearchParams({
      anchor_event_id: state.chapterPlanAnchorEventId || '',
      query: state.chapterPlanEventQuery || ''
    });
    try {
      state.chapterPlanEventCandidates = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/chapter-plan/${state.chapterPlanBookNumber}/${state.chapterPlanChapterNumber}/event-candidates?${params.toString()}`
      );
    } catch (error) {
      state.chapterPlanEventCandidates = { candidates: [] };
      setLog(`Event Board load failed: ${error.message}`);
    } finally {
      if (!keepLoading) {
        state.chapterPlanLoading = false;
        if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
      }
    }
  }


  async function loadPossibleNextDirections(keepLoading = false) {
    if (!projectId || state.chapterPlanDirectionsLoading) return;
    captureChapterPlannerDraft();
    state.chapterPlanDirectionsLoading = true;
    state.chapterPlanDirectionsQueried = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    try {
      state.chapterPlanPossibleDirections = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/planner-query`,
        {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: 'possible_next_directions',
            book_number: Number(state.chapterPlanBookNumber || 1),
            chapter_number: Number(state.chapterPlanChapterNumber || 1),
            query: '',
            record_types: ['event'],
            include_future: false,
            anchor_event_id: state.chapterPlanAnchorEventId || '',
            limit: 80
          })
        }
      );
    } catch (error) {
      state.chapterPlanPossibleDirections = { results: [] };
      setLog(`Possible Next Directions failed: ${error.message}`);
    } finally {
      state.chapterPlanDirectionsLoading = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    }
  }


  async function loadChapterAmendCatalog(keepLoading = false) {
    if (!projectId || state.chapterPlanAmendLoading) return;
    captureChapterPlannerDraft();
    state.chapterPlanAmendLoading = true;
    state.chapterPlanAmendQueried = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    try {
      state.chapterPlanAmendCatalog = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/planner-query`,
        {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: 'find_more_canon',
            book_number: Number(state.chapterPlanBookNumber || 1),
            chapter_number: Number(state.chapterPlanChapterNumber || 1),
            query: state.chapterPlanAmendQuery || '',
            record_types: [],
            include_future: true,
            anchor_event_id: '',
            limit: 80
          })
        }
      );
    } catch (error) {
      state.chapterPlanAmendCatalog = { categories: [] };
      setLog(`Find More Canon failed: ${error.message}`);
    } finally {
      state.chapterPlanAmendLoading = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    }
  }


  async function runPlannerIntentQuery() {
    if (!projectId || state.chapterPlanIntentLoading) return;
    const authorQuery = String(state.chapterPlanIntentQuery || '').trim();
    if (!authorQuery) {
      state.chapterPlanIntentResult = {
        status: 'invalid_request',
        message: 'Enter a natural-language planning request first.',
        results: []
      };
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
      return;
    }

    const chapter = (state.chapterPlan || {}).chapter || {};
    captureChapterPlannerDraft();
    state.chapterPlanIntentLoading = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    try {
      state.chapterPlanIntentResult = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/planner-query`,
        {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: 'interpret_intent',
            book_number: Number(state.chapterPlanBookNumber || 1),
            chapter_number: Number(state.chapterPlanChapterNumber || 1),
            query: '',
            record_types: [],
            include_future: false,
            anchor_event_id: '',
            limit: 80,
            author_query: authorQuery,
            minimal_context: {
              chapter_goal: String(chapter.chapter_objective || ''),
              chapter_conflict: '',
              current_pov: Array.isArray(chapter.pov) ? chapter.pov : [],
              active_locations: [],
              active_story_opportunity: null,
              story_phase: '',
              current_escalation_envelope: ''
            },
            allowed_search_domains: []
          })
        }
      );
      const status = String((state.chapterPlanIntentResult || {}).status || 'unknown');
      if (status === 'ok') {
        setLog(`Planner intent query returned ${Number(state.chapterPlanIntentResult.result_count || 0)} Canon Index candidate(s).`);
      } else if (status === 'clarification_required') {
        setLog('Planner intent query requires clarification before retrieval.');
      } else {
        setLog(`Planner intent query stopped safely: ${state.chapterPlanIntentResult.message || status}.`);
      }
    } catch (error) {
      state.chapterPlanIntentResult = { status: 'model_error', results: [], message: error.message };
      setLog(`Planner intent query failed: ${error.message}`);
    } finally {
      state.chapterPlanIntentLoading = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    }
  }


  async function amendChapterBookCanon(recordId, action) {
    if (!recordId || state.chapterPlanSaving || state.bootstrap.read_only === true) return;
    state.chapterPlanSaving = true;
    renderChapterPlanner(state.bootstrap);
    try {
      await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-scope/${state.chapterPlanBookNumber}/amend`,
        {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({
            chapter_number: Number(state.chapterPlanChapterNumber || 1),
            action: String(action || ''),
            record_id: recordId,
            source_class: 'master_canon',
            usage_mode: 'direct'
          })
        }
      );
      state.chapterPlan = null;
      state.chapterPlanBookCatalog = null;
      state.chapterPlanEffectiveScope = null;
      state.chapterPlanEventCandidates = null;
      state.chapterPlanPossibleDirections = null;
      state.chapterPlanAmendCatalog = null;
      state.chapterKnowledgePack = null;
      setLog(
        `${action === 'remove' ? 'Removed from' : 'Added to'} Book ${state.chapterPlanBookNumber} ` +
        `effective Chapter ${state.chapterPlanChapterNumber}. Re-approve Book Canon before another amendment.`
      );
      await loadChapterPlannerAfterAmendment();
    } catch (error) {
      setLog(`Book Canon amendment blocked: ${error.message}`);
    } finally {
      state.chapterPlanSaving = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    }
  }


  async function loadChapterPlannerAfterAmendment() {
    const bookNumber = Number(state.chapterPlanBookNumber || 1);
    const chapterNumber = Number(state.chapterPlanChapterNumber || 1);
    const [chapterPlanResult, bookScopeResult] = await Promise.all([
      apiFetch(`/api/project/${encodeURIComponent(projectId)}/chapter-plan/${bookNumber}/${chapterNumber}`),
      apiFetch(`/api/project/${encodeURIComponent(projectId)}/book-scope`)
    ]);
    state.chapterPlan = chapterPlanResult;
    state.bookScope = bookScopeResult;
    const normalParams = new URLSearchParams({
      book_number: String(bookNumber),
      include_future: 'false',
      query: ''
    });
    state.chapterPlanBookCatalog = await apiFetch(
      `/api/project/${encodeURIComponent(projectId)}/book-scope/catalog?${normalParams.toString()}`
    );
    state.chapterPlanEffectiveScope = await apiFetch(
      `/api/project/${encodeURIComponent(projectId)}/book-scope/${bookNumber}/effective?chapter_number=${chapterNumber}`
    );
    await loadChapterEventCandidates(true);
    state.chapterPlanPossibleDirections = null;
    state.chapterPlanAmendCatalog = null;
    state.storyControls = await apiFetch(
      `/api/project/${encodeURIComponent(projectId)}/story-controls?book_number=${bookNumber}&chapter_number=${chapterNumber}`
    );
  }


  async function saveStoryControl() {
    if (!projectId || state.storyControlSaving || state.bootstrap.read_only === true) return;
    captureChapterPlannerDraft();
    const formDraft = (state.chapterPlanDraft && state.chapterPlanDraft.key === chapterDraftKey())
      ? (state.chapterPlanDraft.story_control_form || {})
      : {};
    const instruction = String(formDraft.instruction || '').trim();
    if (!instruction) {
      setLog('Story Control requires an explicit author instruction.');
      return;
    }

    const subjectId = String(formDraft.subject_record_id || '').trim();
    state.storyControlSaving = true;
    renderChapterPlanner(state.bootstrap);
    try {
      const result = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/story-controls`,
        {
          method: 'POST',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_number: Number(state.chapterPlanBookNumber || 1),
            chapter_number: Number(state.chapterPlanChapterNumber || 1),
            control_type: String(formDraft.control_type || 'knowledge_change'),
            subject_ref: subjectId ? { record_id: subjectId } : null,
            instruction,
            certainty: String(formDraft.certainty || 'supported_evidence'),
            presentation: String(formDraft.presentation || 'other'),
            narrative_weight: String(formDraft.narrative_weight || 'brief_clue'),
            who_learns: [],
            effective_point: 'current_unit',
            knowledge_ceiling: 'inherit',
            allowed_interpretations: [],
            forbidden_assertions: [],
            persistence: 'chapter_local',
            notes: ''
          })
        }
      );
      state.storyControls = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/story-controls?book_number=${state.chapterPlanBookNumber}&chapter_number=${state.chapterPlanChapterNumber}`
      );
      const valid = ((result.control || {}).validation || {}).valid === true;
      if (state.chapterPlanDraft && state.chapterPlanDraft.key === chapterDraftKey()) {
        state.chapterPlanDraft.story_control_form = {};
      }
      setLog(
        valid
          ? 'Story Control saved. Select it in the chapter and save the Chapter Plan to activate the planning reference.'
          : 'Story Control saved with a validation warning. Resolve the conflict before attaching it to the Chapter Plan.'
      );
    } catch (error) {
      setLog(`Story Control save failed: ${error.message}`);
    } finally {
      state.storyControlSaving = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    }
  }


  async function saveChapterPlanner() {
    if (!projectId || state.chapterPlanSaving || state.bootstrap.read_only === true) return;

    captureChapterPlannerDraft();
    const draft = (state.chapterPlanDraft && state.chapterPlanDraft.key === chapterDraftKey()) ? state.chapterPlanDraft : {};
    const current = (state.chapterPlan || {}).chapter || {};
    const catalogItems = ((state.chapterPlanBookCatalog || {}).categories || [])
      .flatMap((category) => category.items || []);
    const itemById = {};
    catalogItems.forEach((item) => {
      itemById[String(item.record_id || '')] = item;
    });

    const selectedCanonRefs = draft.selected_canon_refs || [];
    const pov = draft.pov || [];
    const assignedEventRefs = draft.assigned_event_refs || [];
    const eventPlacements = draft.event_placements || [];
    const restrictions = draft.restrictions || [];

    state.chapterPlanSaving = true;
    renderChapterPlanner(state.bootstrap);
    try {
      const result = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/chapter-plan/${state.chapterPlanBookNumber}/${state.chapterPlanChapterNumber}`,
        {
          method: 'PUT',
          headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({
            selected_canon_refs: selectedCanonRefs,
            assigned_event_refs: assignedEventRefs,
            event_placements: eventPlacements,
            generation_kickoff: String(draft.generation_kickoff || '').trim(),
            pov,
            chapter_objective: String(draft.chapter_objective || '').trim(),
            restrictions,
            story_control_refs: draft.story_control_refs || [],
            advanced_sequence: current.advanced_sequence || []
          })
        }
      );
      const planDocument = ((result.chapter_plan || {}).document || {});
      const book = (planDocument.books || []).find(
        (item) => Number(item.book_number) === Number(state.chapterPlanBookNumber)
      );
      const chapter = (book && book.chapters || []).find(
        (item) => Number(item.chapter_number) === Number(state.chapterPlanChapterNumber)
      );
      state.chapterPlan = {
        status: 'ok',
        chapter: chapter || {}
      };
      clearChapterPlannerDraft();
      state.chapterPlanSavedNotice = `Chapter ${state.chapterPlanChapterNumber} plan saved. Selections and instructions are current.`;
      await loadChapterEventCandidates(true);
      state.chapterPlanPossibleDirections = null;
      state.chapterPlanDirectionsQueried = false;
      setLog(`Chapter Plan saved for Book ${state.chapterPlanBookNumber}, Chapter ${state.chapterPlanChapterNumber}.`);
      // Refresh pack status after the save without blocking the primary save interaction.
      void loadChapterKnowledgePackStatus();
    } catch (error) {
      setLog(`Chapter Plan save failed: ${error.message}`);
    } finally {
      state.chapterPlanSaving = false;
      if (state.activeSection === 'chapter_planner') renderChapterPlanner(state.bootstrap);
    }
  }


  function bookPlanScopeBook(bookNumber) {
    return ((((state.bookScope || {}).document || {}).books || []).find(
      (item) => Number(item.book_number) === Number(bookNumber)
    )) || {
      book_number: Number(bookNumber || 1),
      selections: [],
      lifecycle_state: 'NOT_STARTED',
      approval_status: 'not_ready',
      approval_fresh: false,
      revision: 0,
      validation: { valid: false, issues: [] }
    };
  }

  function bookPlanTimeSpanSuggestion(catalog) {
    const years = [];
    (catalog.categories || []).forEach((category) => {
      if (String(category.category_key || '') !== 'events') return;
      (category.items || []).forEach((item) => {
        if (item.selected !== true) return;
        const matches = String(item.date_or_sequence || '').match(/(?<!\d)\d{3,4}(?!\d)/g) || [];
        matches.forEach((value) => years.push(Number(value)));
      });
    });
    const usable = years.filter((year) => Number.isInteger(year) && year > 0);
    if (!usable.length) return { value: '', source_count: 0 };
    const first = Math.min(...usable);
    const last = Math.max(...usable);
    return {
      value: first === last ? String(first) : `${first}–${last}`,
      source_count: usable.length
    };
  }

  function renderEmbeddedBookCanon(bootstrap, bookNumber, scopeBook, catalog) {
    const loading = state.bookScopeLoading === true || state.bookScopeSaving === true;
    const readOnly = bootstrap.read_only === true;
    const categories = plannerCatalogItems(catalog || { categories: [] });
    const approvalStatus = String(scopeBook.approval_status || 'not_ready');
    const approved = approvalStatus === 'approved' && scopeBook.approval_fresh === true;
    const mutationEnabled = !readOnly && !loading && !approved;
    const selectedIds = new Set((scopeBook.selections || []).map((item) => String(item.record_id || '')));
    const availableCount = Number(((catalog || {}).status_counts || {}).AVAILABLE_TO_ADD || 0)
      + Number(((catalog || {}).status_counts || {}).ACTIVE || 0);
    const recommendedCount = Number((catalog || {}).recommended_count || 0);
    const futureCount = Number(((catalog || {}).status_counts || {}).FUTURE || 0);

    const plannerDisplayStatus = (item, selected) => {
      if (selected) return 'SELECTED';
      if (item.recommended_for_book === true) return 'RECOMMENDED_FOR_BOOK';
      const status = String(((item.eligibility || {}).status) || 'UNKNOWN');
      if (['ACTIVE', 'AVAILABLE_TO_ADD'].includes(status)) return 'AVAILABLE';
      return status;
    };

    const categoryMarkup = categories.map((category) => {
      const categoryKey = String(category.category_key || 'other');
      const allowSelectAllAvailable = categoryKey !== 'interactions';
      const rows = (category.items || []).map((item) => {
        const recordId = String(item.record_id || '');
        const selected = selectedIds.has(recordId) || item.selected === true;
        const eligibilityStatus = String(((item.eligibility || {}).status) || 'UNKNOWN');
        const addable = ['ACTIVE', 'AVAILABLE_TO_ADD'].includes(eligibilityStatus);
        const recommended = item.recommended_for_book === true;
        const disabled = !mutationEnabled || (!selected && !addable);
        const action = selected ? 'Return' : 'Add to Book';
        const technical = [item.date_or_sequence, (item.planner_sort_metadata || {}).date_or_period, item.story_code]
          .filter(Boolean).filter((value, index, values) => values.indexOf(value) === index).join(' · ');
        const reasons = (item.recommendation_reasons || []).map((value) => labelFor(value)).join(' · ');
        return `<div class="book-canon-browser-row ${selected ? 'is-selected' : ''} ${recommended ? 'is-recommended' : ''}">
          <div class="book-canon-browser-main">
            <div class="book-canon-browser-title"><strong>${escapeHtml(item.label || recordId)}</strong>${statusBadge(plannerDisplayStatus(item, selected))}</div>
            <small>${escapeHtml(item.summary || labelFor(item.record_type || categoryKey || 'Canon'))}</small>
            ${technical ? `<small class="planner-technical-id">${escapeHtml(technical)}</small>` : ''}
            ${recommended && reasons ? `<small class="planner-recommendation-reason">Recommended: ${escapeHtml(reasons)}</small>` : ''}
            <details><summary>Details</summary>
              <div><strong>Type:</strong> ${escapeHtml(labelFor(item.record_group_id || item.record_type || 'Canon'))}</div>
              <div><strong>Available from:</strong> ${escapeHtml(item.available_from_book ? `Book ${item.available_from_book}` : 'All books / not book-gated')}</div>
            </details>
          </div>
          <div class="book-canon-row-actions">
            <label class="book-canon-batch-check" title="Select this row for a batch action">
              <input type="checkbox" data-book-canon-select="1" data-category-key="${escapeHtml(categoryKey)}"
                data-record-id="${escapeHtml(recordId)}" data-selected="${selected ? 'true' : 'false'}"
                data-addable="${addable ? 'true' : 'false'}" data-recommended="${recommended ? 'true' : 'false'}"
                ${disabled ? 'disabled' : ''} />
            </label>
            <button type="button" class="${selected ? 'secondary-action' : 'primary-action'} compact-action book-canon-row-action-button"
              data-book-canon-action="${selected ? 'remove' : 'add'}" data-record-id="${escapeHtml(recordId)}" ${disabled ? 'disabled' : ''}>${action}</button>
          </div>
        </div>`;
      }).join('');

      const selectedInCategory = (category.items || []).filter((item) => selectedIds.has(String(item.record_id || '')) || item.selected === true).length;
      const recommendedInCategory = Number(category.recommended_count || 0);
      const availableInCategory = Number(category.available_count || 0);
      return `<details class="book-canon-category" ${category.selected_count ? 'open' : ''}>
        <summary><strong>${escapeHtml(labelFor(categoryKey || 'Canon'))}</strong><span>${number(category.total || (category.items || []).length)} shown · ${number(selectedInCategory)} selected · ${number(recommendedInCategory)} recommended</span></summary>
        <div class="book-canon-category-actions" data-category-actions="${escapeHtml(categoryKey)}">
          <button type="button" class="secondary-action compact-action" data-book-canon-batch-action="select_recommended" data-category-key="${escapeHtml(categoryKey)}" ${!mutationEnabled || !recommendedInCategory ? 'disabled' : ''}>Select All Recommended</button>
          ${allowSelectAllAvailable ? `<button type="button" class="secondary-action compact-action" data-book-canon-batch-action="select_available" data-category-key="${escapeHtml(categoryKey)}" ${!mutationEnabled || !availableInCategory ? 'disabled' : ''}>Select All Available</button>` : ''}
          <button type="button" class="primary-action compact-action" data-book-canon-batch-action="add_selected" data-category-key="${escapeHtml(categoryKey)}" ${!mutationEnabled ? 'disabled' : ''}>Add Selected</button>
          <button type="button" class="secondary-action compact-action" data-book-canon-batch-action="return_selected" data-category-key="${escapeHtml(categoryKey)}" ${!mutationEnabled || !selectedInCategory ? 'disabled' : ''}>Return Selected</button>
          <button type="button" class="secondary-action compact-action" data-book-canon-batch-action="return_all" data-category-key="${escapeHtml(categoryKey)}" ${!mutationEnabled || !selectedInCategory ? 'disabled' : ''}>Return All</button>
          ${categoryKey === 'interactions' ? '<small>Historical/genre interactions intentionally omit Select All Available; choose Recommended or specific interactions.</small>' : ''}
        </div>
        <div class="book-canon-browser-list">${rows || '<div class="workspace-disabled-note">No records in this category.</div>'}</div>
      </details>`;
    }).join('');

    const selectedMarkup = (scopeBook.selections || []).map((item) => `<div class="book-canon-browser-row is-selected book-canon-selected-summary-row">
      <div class="book-canon-browser-main">
        <div class="book-canon-browser-title">
          <strong>${escapeHtml(item.label || item.record_id || '')}</strong>
          ${statusBadge('SELECTED')}
        </div>
        <small>${escapeHtml(labelFor(item.record_type || 'Canon'))}</small>
      </div>
      <div class="book-canon-row-actions">
        <label class="book-canon-batch-check" title="Select this row for a batch return">
          <input type="checkbox" data-book-canon-selected-summary="1" data-record-id="${escapeHtml(item.record_id || '')}" ${mutationEnabled ? '' : 'disabled'} />
        </label>
        <button type="button" class="secondary-action compact-action book-canon-row-action-button"
          data-book-canon-action="remove" data-record-id="${escapeHtml(item.record_id || '')}" ${mutationEnabled ? '' : 'disabled'}>Return</button>
      </div>
    </div>`).join('');

    const errorMarkup = state.bookScopeError
      ? `<div class="workspace-error-note"><strong>Canon for This Book could not load.</strong> ${escapeHtml(state.bookScopeError)} <button type="button" class="secondary-action compact-action" id="book-plan-canon-retry">Retry</button></div>`
      : '';

    return `<details class="workspace-detail-card planner-book-canon-embedded" ${selectedIds.size && approved ? '' : 'open'}>
      <summary><strong>Canon for This Book</strong><span>${number(selectedIds.size)} selected · ${escapeHtml(labelFor(approvalStatus))}</span></summary>
      <div class="planner-book-canon-body">
        <p class="placeholder">Choose the established canon Book ${bookNumber} may use. These selections become available to Chapter Planner. Required and Major fields in the Book Plan are stronger obligations, not automatic selections.</p>
        <div class="planner-status-chips"><span>${number(recommendedCount)} Recommended</span><span>${number(availableCount)} Available</span><span>${number(selectedIds.size)} Selected</span><span>${number(futureCount)} Future</span></div>
        ${errorMarkup}
        <div class="book-canon-toolbar compact-planner-toolbar">
          <label class="book-canon-filter"><span>Filter visible Canon (optional)</span><input id="book-plan-canon-query" type="search" value="${escapeHtml(state.bookScopeQuery || '')}" placeholder="Filter by name, alias, summary, or date" /></label>
          <label class="planner-toggle"><input id="book-plan-canon-show-future" type="checkbox" ${state.bookScopeIncludeFuture ? 'checked' : ''}/> Show Future</label>
          <button type="button" id="book-plan-canon-refresh" class="secondary-action" ${loading ? 'disabled' : ''}>${loading ? 'Loading…' : 'Refresh'}</button>
        </div>
        <details class="planner-selected-summary" ${selectedIds.size ? 'open' : ''}><summary><strong>Selected for Book ${bookNumber}</strong><span>${number(selectedIds.size)} records</span></summary><div class="planner-selected-summary-actions">
          <button type="button" class="secondary-action compact-action" data-book-canon-batch-action="return_summary_selected" ${!mutationEnabled || !selectedIds.size ? 'disabled' : ''}>Return Selected</button>
          <button type="button" class="secondary-action compact-action" data-book-canon-batch-action="return_summary_all" ${!mutationEnabled || !selectedIds.size ? 'disabled' : ''}>Return All</button>
        </div><div class="planner-selected-summary-body">${selectedMarkup || '<div class="workspace-disabled-note">Nothing selected yet.</div>'}</div></details>
        <div class="book-canon-category-stack">${categoryMarkup || (loading ? '<div class="workspace-disabled-note">Loading Canon…</div>' : '<div class="workspace-disabled-note">No Canon records are visible for the current filter.</div>')}</div>
        <div class="workspace-action-row">
          <button type="button" id="book-plan-canon-approve" class="primary-action" ${readOnly || loading || approved || !(scopeBook.validation || {}).valid ? 'disabled' : ''}>Approve Canon for This Book</button>
          <button type="button" id="book-plan-canon-revoke" class="secondary-action" ${readOnly || loading || !['approved','outdated'].includes(approvalStatus) ? 'disabled' : ''}>Revoke Approval</button>
        </div>
        <div class="workspace-disabled-note">${approved ? 'Canon for This Book is approved. Direct changes are locked; later additions or removals are made from Chapter Planner.' : 'Add/Return and checkbox batch actions update Canon for This Book. Required/Major Book Plan fields are not changed by these actions.'}</div>
      </div>
    </details>`;
  }

  function bindEmbeddedBookCanonControls() {
    let filterTimer = null;
    document.getElementById('book-plan-canon-query')?.addEventListener('input', (event) => {
      clearTimeout(filterTimer);
      filterTimer = setTimeout(() => {
        state.bookScopeQuery = String(event.target.value || '').trim();
        void loadBookScopeCatalog();
      }, 250);
    });
    document.getElementById('book-plan-canon-show-future')?.addEventListener('change', (event) => {
      state.bookScopeIncludeFuture = event.target.checked === true;
      void loadBookScopeCatalog();
    });
    document.getElementById('book-plan-canon-refresh')?.addEventListener('click', () => void loadBookScopeCatalog());
    document.getElementById('book-plan-canon-retry')?.addEventListener('click', () => void loadBookScopeCatalog());
    mainPanel.querySelectorAll('[data-book-canon-action]').forEach((button) => button.addEventListener('click', () => void mutateBookCanonSelection(button.dataset.recordId, button.dataset.bookCanonAction)));
    mainPanel.querySelectorAll('[data-book-canon-batch-action]').forEach((button) => button.addEventListener('click', () => void handleBookCanonBatchAction(button.dataset.bookCanonBatchAction, button.dataset.categoryKey || '')));
    document.getElementById('book-plan-canon-approve')?.addEventListener('click', () => void approveBookCanon());
    document.getElementById('book-plan-canon-revoke')?.addEventListener('click', () => void revokeBookCanonApproval());
  }

  function handleBookCanonBatchAction(action, categoryKey) {
    const categorySelector = categoryKey ? `[data-category-key="${CSS.escape(categoryKey)}"]` : '';
    const rowBoxes = Array.from(mainPanel.querySelectorAll(`[data-book-canon-select]${categorySelector}`));

    if (action === 'select_recommended') {
      rowBoxes.forEach((box) => { box.checked = box.dataset.selected !== 'true' && box.dataset.addable === 'true' && box.dataset.recommended === 'true'; });
      return;
    }
    if (action === 'select_available') {
      rowBoxes.forEach((box) => { box.checked = box.dataset.selected !== 'true' && box.dataset.addable === 'true'; });
      return;
    }
    if (action === 'add_selected') {
      const ids = rowBoxes.filter((box) => box.checked && box.dataset.selected !== 'true' && box.dataset.addable === 'true').map((box) => box.dataset.recordId);
      void mutateBookCanonSelections(ids, 'add');
      return;
    }
    if (action === 'return_selected') {
      const ids = rowBoxes.filter((box) => box.checked && box.dataset.selected === 'true').map((box) => box.dataset.recordId);
      void mutateBookCanonSelections(ids, 'remove');
      return;
    }
    if (action === 'return_all') {
      const ids = rowBoxes.filter((box) => box.dataset.selected === 'true').map((box) => box.dataset.recordId);
      void mutateBookCanonSelections(ids, 'remove');
      return;
    }
    if (action === 'return_summary_selected') {
      const ids = Array.from(mainPanel.querySelectorAll('[data-book-canon-selected-summary]:checked')).map((box) => box.dataset.recordId);
      void mutateBookCanonSelections(ids, 'remove');
      return;
    }
    if (action === 'return_summary_all') {
      const documentScope = (state.bookScope || {}).document || {};
      const book = (documentScope.books || []).find((item) => Number(item.book_number) === Number(state.bookScopeBookNumber || 1));
      const ids = ((book && book.selections) || []).map((item) => item.record_id);
      void mutateBookCanonSelections(ids, 'remove');
    }
  }

  function renderBookPlan(bootstrap) {
    setHeading('Book Planner');

    const bootstrapPlan = (bootstrap.runtime_context || {}).book_plan || {};
    const response = state.bookPlan;
    const plan = response && response.plan ? response.plan : {
      status: bootstrapPlan.status || 'not_started', revision: bootstrapPlan.revision || 0,
      content_hash: bootstrapPlan.content_hash || '',
      book_count: bootstrapPlan.expected_book_count || bootstrapPlan.planned_book_count || (bootstrap.manifest || {}).book_count || 0,
      books: []
    };
    const validation = plan.validation || { valid: bootstrapPlan.valid === true, complete_book_count: bootstrapPlan.complete_book_count || 0, expected_book_count: bootstrapPlan.expected_book_count || plan.book_count || 0, issues: bootstrapPlan.issues || [], books: [] };
    const loading = state.bookPlanLoading === true || state.bookScopeLoading === true;
    const saving = state.bookPlanSaving === true;
    const approvalLoading = state.bookPlanApprovalLoading === true;
    const readOnly = bootstrap.read_only === true || bootstrapPlan.authoring_enabled === false;
    const expectedBookCount = Number(validation.expected_book_count || plan.book_count || (bootstrap.manifest || {}).book_count || 0);
    const books = normalizeBookPlanBooks(plan.books || [], expectedBookCount);
    state.bookPlanBookNumber = Math.min(Math.max(1, Number(state.bookPlanBookNumber || 1)), Math.max(1, expectedBookCount));
    state.bookScopeBookNumber = state.bookPlanBookNumber;
    const bookNumber = Number(state.bookPlanBookNumber || 1);
    const book = books.find((item) => Number(item.book_number) === bookNumber) || books[0] || { book_number: 1 };
    const scopeBook = bookPlanScopeBook(bookNumber);
    const bookValidation = (validation.books || []).find((item) => Number(item.book_number) === bookNumber) || { complete: false, book_scope_approved: false };
    const bookApproval = (plan.book_workflow || []).find((item) => Number(item.book_number) === bookNumber) || { approval_status: 'not_ready', approval_fresh: false, revision: 0 };
    const approvalStatus = String(bookApproval.approval_status || 'not_ready');
    const approvalFresh = bookApproval.approval_fresh === true;
    const scopeApproved = scopeBook.approval_status === 'approved' && scopeBook.approval_fresh === true;
    const canApprove = bookValidation.complete === true && scopeApproved && !readOnly && !loading && !saving && !approvalLoading && approvalStatus !== 'approved';
    const canRevoke = !readOnly && !loading && !saving && !approvalLoading && (approvalStatus === 'approved' || approvalStatus === 'outdated');
    const catalog = state.bookScopeCatalog || { categories: [], status_counts: {}, hidden_status_counts: {} };
    const suggestion = bookPlanTimeSpanSuggestion(catalog);
    const selectedBookIssues = (validation.issues || []).filter((issue) => !issue.book_number || Number(issue.book_number) === bookNumber);
    const issueRows = selectedBookIssues.map((issue) => `<tr><td>${escapeHtml(issue.book_number ? `Book ${issue.book_number}` : 'Plan')}</td><td>${escapeHtml(issue.code || 'validation_issue')}</td><td>${escapeHtml(issue.message || 'Book Plan validation issue.')}</td></tr>`).join('');

    mainPanel.innerHTML = `<div class="workspace-content workspace-book-plan-authoring-v1 planner-book-plan-unified">
      <p class="placeholder">Plan one book at a time. Choose Canon for This Book, then define the book’s story intent. Approved planning feeds the Book Knowledge Pack used by Chapter Planner.</p>
      <div class="workspace-stat-grid">${statCard('Status', String(plan.status || 'not_started').replace(/_/g, ' '))}${statCard('Complete Books', `${number(validation.complete_book_count)} / ${number(expectedBookCount)}`)}${statCard('Revision', number(plan.revision))}${statCard(`Book ${bookNumber} Approval`, approvalStatus.replace(/_/g, ' '))}${statCard('Freshness', approvalFresh ? 'current' : (approvalStatus === 'outdated' ? 'outdated' : 'not approved'))}</div>

      <section class="workspace-detail-card planner-book-selector"><label><span>Book</span><select id="book-plan-book-number">${Array.from({length: expectedBookCount}, (_, index) => index + 1).map((value) => `<option value="${value}" ${value === state.bookPlanBookNumber ? 'selected' : ''}>Book ${value}</option>`).join('')}</select></label></section>

      ${renderEmbeddedBookCanon(bootstrap, state.bookPlanBookNumber, scopeBook, catalog)}

      <form id="book-plan-form" class="book-plan-form">${renderBookPlanCard(book, expectedBookCount, readOnly, scopeBook, suggestion)}</form>

      <section class="workspace-detail-card"><h3>Book ${bookNumber} check</h3>${bookValidation.complete && scopeApproved ? '<div class="workspace-success-note">Book ' + bookNumber + ' is complete and Canon for This Book is approved/current.</div>' : (issueRows ? table(['Area','Code','Issue'], issueRows) : '<div class="workspace-disabled-note">Complete the Book Plan and approve Canon for This Book before approving the book.</div>')}</section>
      <section class="workspace-detail-card"><h3>Planning readiness</h3><div class="workspace-lock-grid">${lockCard('Canon for This Book', String(scopeBook.approval_status || 'not_ready').replace(/_/g,' '))}${lockCard(`Book ${bookNumber} Plan Approval`, approvalStatus.replace(/_/g,' '))}${lockCard('Book Knowledge Pack', approvalFresh && scopeApproved ? 'Planning approved' : 'Waiting for approvals')}${lockCard('Generation','Locked')}</div></section>
      <div class="workspace-action-row"><button type="button" id="book-plan-refresh" class="secondary-action" ${loading || saving ? 'disabled' : ''}>${loading ? 'Loading…' : 'Reload Plan'}</button><button type="button" id="book-plan-save" class="primary-action" ${readOnly || loading || saving || approvalLoading ? 'disabled' : ''}>${saving ? 'Saving…' : 'Save Book Plan'}</button><button type="button" id="book-plan-approve" class="primary-action" ${canApprove ? '' : 'disabled'}>${approvalLoading ? 'Updating…' : `Approve Book ${bookNumber} Plan`}</button><button type="button" id="book-plan-revoke" class="secondary-action" ${canRevoke ? '' : 'disabled'}>${`Revoke Book ${bookNumber} Approval`}</button></div>
    </div>`;

    document.getElementById('book-plan-book-number')?.addEventListener('change', (event) => {
      state.bookPlanBookNumber = Number(event.target.value || 1);
      state.bookScopeBookNumber = state.bookPlanBookNumber;
      state.bookScopeQuery = '';
      state.bookScopeIncludeFuture = false;
      state.bookScopeCatalog = null;
      void loadBookScopeCatalog();
    });
    bindEmbeddedBookCanonControls();
    document.getElementById('book-plan-use-time-suggestion')?.addEventListener('click', () => {
      const input = document.querySelector(`[data-book-plan-field="time_span"][data-book-number="${state.bookPlanBookNumber}"]`);
      if (input && suggestion.value) input.value = suggestion.value;
    });
    document.getElementById('book-plan-refresh')?.addEventListener('click', () => void loadBookPlan());
    document.getElementById('book-plan-save')?.addEventListener('click', () => void saveBookPlanDraft());
    document.getElementById('book-plan-approve')?.addEventListener('click', () => void approveBookPlan());
    document.getElementById('book-plan-revoke')?.addEventListener('click', () => void revokeBookPlanApproval());

    if (!state.bookPlan && !state.bookPlanLoading) void loadBookPlan();
    else if (!state.bookScopeCatalog && !state.bookScopeLoading) void loadBookScopeCatalog();
  }

  function renderBookPlanCard(book, expectedBookCount, readOnly, scopeBook, timeSuggestion) {
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
          ${bookPlanTimeSpanField(bookNumber, book.time_span, timeSuggestion, readonlyAttribute)}
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
          ${bookPlanReferenceField(bookNumber, 'major_events', 'Major events', book.major_events, scopeBook, 'event', disabledAttribute)}
          ${bookPlanReferenceField(bookNumber, 'required_characters', 'Required characters', book.required_characters, scopeBook, 'character', disabledAttribute)}
          ${bookPlanReferenceField(bookNumber, 'required_locations', 'Required locations', book.required_locations, scopeBook, 'location', disabledAttribute)}
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

  function bookPlanTimeSpanField(bookNumber, value, suggestion, readonlyAttribute) {
    const suggested = String((suggestion || {}).value || '');
    const effective = String(value || '').trim() || suggested;
    return `<label class="book-plan-field book-plan-time-span-field">
      <span>Time span *</span>
      <input type="text" data-book-plan-field="time_span" data-book-number="${bookNumber}" value="${escapeHtml(effective)}" required ${readonlyAttribute} />
      ${suggested ? `<small>Suggested from selected dated Book Canon events: <strong>${escapeHtml(suggested)}</strong>. You may edit this value.</small><button type="button" class="secondary-action compact-action" id="book-plan-use-time-suggestion" ${readonlyAttribute ? 'disabled' : ''}>Use Canon Suggestion</button>` : '<small>No dated Book Canon is selected yet. Enter the time span manually or select dated events above.</small>'}
    </label>`;
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

  function bookPlanReferenceField(bookNumber, field, label, values, scopeBook, recordType, disabledAttribute) {
    const selectedIds = new Set((values || []).map((item) =>
      String(item && typeof item === 'object' ? (item.record_id || '') : '')
    ).filter(Boolean));
    const options = ((scopeBook || {}).selections || []).filter((item) =>
      String(item.record_type || '').toLowerCase() === String(recordType || '').toLowerCase()
    );
    const chosen = options.filter((item) => selectedIds.has(String(item.record_id || '')));
    const unchosen = options.filter((item) => !selectedIds.has(String(item.record_id || '')));
    const row = (item, checked) => `
      <label class="planner-choice-row ${checked ? 'is-selected' : ''}">
        <input type="checkbox" data-book-plan-ref-field="${escapeHtml(field)}"
          data-book-number="${bookNumber}" data-record-id="${escapeHtml(item.record_id || '')}"
          ${checked ? 'checked' : ''} ${disabledAttribute} />
        <span><strong>${escapeHtml(item.label || item.record_id || '')}</strong>
          <small>${escapeHtml(labelFor(item.record_type || recordType))}</small></span>
      </label>`;
    return `
      <fieldset class="book-plan-field planner-reference-picker">
        <legend>${escapeHtml(label)}</legend>
        <details>
          <summary>${chosen.length} selected · ${options.length} available from Canon for This Book</summary>
          <div class="planner-choice-list">
            ${chosen.map((item) => row(item, true)).join('')}
            ${unchosen.map((item) => row(item, false)).join('')}
            ${options.length ? '' : `<div class="workspace-disabled-note">No matching canon is selected yet. Use Canon for This Book above.</div>`}
          </div>
        </details>
      </fieldset>`;
  }

  function bookPlanListField(bookNumber, field, label, values, disabledAttribute) {
    return `
      <label class="book-plan-field">
        <span>${escapeHtml(label)}</span>
        <textarea rows="4"
          data-book-plan-list-field="${escapeHtml(field)}"
          data-book-number="${bookNumber}"
          placeholder="One item per line"
          ${disabledAttribute}>${escapeHtml((values || []).map((item) => (
            item && typeof item === 'object'
              ? (item.label || item.legacy_label || item.record_id || '')
              : String(item || '')
          )).filter(Boolean).join('\n'))}</textarea>
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

    const expectedBookCount = Math.max(1, Number(((state.bookPlan || {}).plan || {}).book_count || (state.bootstrap.manifest || {}).book_count || 1));
    const currentBooks = normalizeBookPlanBooks((((state.bookPlan || {}).plan || {}).books || []), expectedBookCount);
    const bookNumber = Number(state.bookPlanBookNumber || 1);
    const current = { ...(currentBooks.find((item) => Number(item.book_number) === bookNumber) || { book_number: bookNumber }) };

    form.querySelectorAll(`[data-book-plan-field][data-book-number="${bookNumber}"]`).forEach((node) => {
      current[node.dataset.bookPlanField] = String(node.value || '').trim();
    });
    form.querySelectorAll(`[data-book-plan-list-field][data-book-number="${bookNumber}"]`).forEach((node) => {
      current[node.dataset.bookPlanListField] = String(node.value || '').split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
    });
    ['major_events','required_characters','required_locations'].forEach((field) => {
      current[field] = Array.from(form.querySelectorAll(`[data-book-plan-ref-field="${field}"][data-book-number="${bookNumber}"]:checked`)).map((node) => ({ record_id: node.dataset.recordId }));
    });

    return { books: currentBooks.map((item) => Number(item.book_number) === bookNumber ? current : item) };
  }

  async function loadBookPlan() {
    if (!projectId || state.bookPlanLoading || state.bookPlanSaving) return;
    state.bookPlanLoading = true;
    renderBookScopeAwarePlanner();
    try {
      const [bookPlanResult, bookScopeResult] = await Promise.all([
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/book-plan`),
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/book-scope`)
      ]);
      state.bookPlan = bookPlanResult;
      state.bookScope = bookScopeResult;
      state.bookScopeBookNumber = Number(state.bookPlanBookNumber || 1);
      const params = new URLSearchParams({ book_number: String(state.bookScopeBookNumber), include_future: state.bookScopeIncludeFuture ? 'true' : 'false', query: state.bookScopeQuery || '' });
      try {
        state.bookScopeError = '';
        state.bookScopeCatalog = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/book-scope/catalog?${params.toString()}`);
      } catch (catalogError) {
        state.bookScopeCatalog = { categories: [], status_counts: {}, hidden_status_counts: {} };
        state.bookScopeError = catalogError.message || String(catalogError);
      }
      setLog(`Book Plan loaded: ${state.bookPlan.plan.status || 'unknown'}, revision ${state.bookPlan.plan.revision || 0}.`);
    } catch (error) {
      state.bookPlan = { plan: { status: 'error', revision: 0, books: [], validation: { valid: false, issues: [{ code: 'load_failed', message: error.message }] } } };
      setLog(`Book Plan load failed: ${error.message}`);
    } finally {
      state.bookPlanLoading = false;
      renderBookScopeAwarePlanner();
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
        `Book Plan saved at revision ${state.bookPlan.plan.revision}. Review and approve this book before compiling its Book Knowledge Pack.`
      );
    } catch (error) {
      setLog(`Book Plan save failed: ${error.message}`);
    } finally {
      state.bookPlanSaving = false;
      renderBookPlan(state.bootstrap);
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
    const bookNumber = Number(state.bookPlanBookNumber || 1);
    setLog(`Approving Book ${bookNumber} Plan…`);

    try {
      state.bookPlan = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-plan/approve?book_number=${bookNumber}`,
        {
          method: 'POST',
          headers: { Accept: 'application/json' }
        }
      );
      const approval = (state.bookPlan.plan.book_workflow || []).find((item) => Number(item.book_number) === bookNumber) || {};
      setLog(`Book ${bookNumber} Plan approved at book revision ${approval.approved_revision || approval.revision || 0}. Refreshing Book Knowledge Pack readiness…`);
      try {
        state.bookRuntimeContext = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/runtime-context/books/status?book_number=${encodeURIComponent(bookNumber)}`);
      } catch (_error) {
        state.bookRuntimeContext = null;
      }
    } catch (error) {
      setLog(`Book Plan approval failed: ${error.message}`);
    } finally {
      state.bookPlanApprovalLoading = false;
      renderBookPlan(state.bootstrap);
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
    const bookNumber = Number(state.bookPlanBookNumber || 1);
    setLog(`Revoking Book ${bookNumber} Plan approval…`);

    try {
      state.bookPlan = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/book-plan/revoke?book_number=${bookNumber}`,
        {
          method: 'POST',
          headers: { Accept: 'application/json' }
        }
      );
      setLog(`Book ${bookNumber} Plan approval revoked. Downstream generation remains locked.`);
    } catch (error) {
      setLog(`Book Plan approval revocation failed: ${error.message}`);
    } finally {
      state.bookPlanApprovalLoading = false;
      renderBookPlan(state.bootstrap);
    }
  }

  function renderBookRuntimeContext(bootstrap) {
    setHeading('Book Knowledge Packs');

    const bootstrapContext = (bootstrap.runtime_context || {}).books || {};
    const bookContext = state.bookRuntimeContext || bootstrapContext;
    const plan = bookContext.book_plan || {};
    const scope = bookContext.book_scope || {};
    const authorCanon = bookContext.author_canon || {};
    const canonIndex = bookContext.canon_index || {};
    const targets = bookContext.targets || [];
    const blockers = bookContext.blockers || [];
    const locks = bookContext.execution_locks || {};
    const loading = state.bookRuntimeContextLoading === true;
    const readOnly = bootstrap.read_only === true;
    const compilerReady = bookContext.compiler_ready === true;
    const compileEnabled = compilerReady && !readOnly && !loading;
    const readyCount = number(bookContext.ready_count || 0);

    const targetRows = targets.map((target) => `
      <tr>
        <td>${escapeHtml(target.label || `Book ${target.book_number || '—'} Knowledge Pack`)}</td>
        <td>${statusBadge(String(target.status || (target.exists ? 'current' : 'missing')).toUpperCase())}</td>
        <td>${target.compiler_ready === true ? 'Ready' : 'Waiting for this book'} </td>
        <td>${number(target.selected_record_count || 0)}</td>
        <td>${number(target.estimated_tokens || 0)}</td>
        <td>${target.dependency_set_sha256
          ? `<code>${escapeHtml(String(target.dependency_set_sha256).slice(0, 16))}…</code>`
          : '—'}</td>
      </tr>
    `).join('');

    const blockerRows = blockers.map((blocker) => `
      <tr>
        <td>${escapeHtml(blocker.book_number ? `Book ${blocker.book_number}` : 'Project')}</td>
        <td>${escapeHtml(blocker.code || 'blocked')}</td>
        <td>${escapeHtml(blocker.message || 'Compilation is blocked.')}</td>
      </tr>
    `).join('');

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-book-runtime-context-v2">
        <p class="placeholder">
          Each Book Knowledge Pack contains the Canon you selected for that book,
          the approved Book Plan, and project-wide rules needed downstream. A book
          can compile as soon as its own Book Canon and Book Plan are approved;
          later unfinished books do not block it. Required/Major choices add
          stronger usage obligations but do not control which selected Canon enters the pack.
        </p>

        <div class="workspace-stat-grid">
          ${statCard('Status', String(bookContext.status || 'blocked').replace(/_/g, ' '))}
          ${statCard('Ready to Compile', readyCount)}
          ${statCard('Current', `${number(bookContext.current_count)} / ${number(bookContext.target_count)}`)}
          ${statCard('Missing', number(bookContext.missing_count))}
          ${statCard('Outdated', number(bookContext.outdated_count))}
        </div>

        <section class="workspace-detail-card">
          <h3>Source readiness</h3>
          <dl class="workspace-definition-grid workspace-definition-grid--compact">
            ${definition('Book Plan schema', plan.schema_version || '—')}
            ${definition('Completed Book Plans', number(plan.complete_book_count || 0))}
            ${definition('Ready Book Knowledge Packs', readyCount)}
            ${definition('Approved Book Canons', number(scope.approved_current_count || 0))}
            ${definition('Author Canon', authorCanon.exists ? 'Present' : 'Missing')}
            ${definition('Canon Index', labelFor(canonIndex.state || 'unknown'))}
          </dl>
          <details class="workspace-technical-details">
            <summary>Technical details</summary>
            <dl class="workspace-definition-grid workspace-definition-grid--compact">
              ${definition('Author Canon SHA-256', authorCanon.sha256
                ? `${String(authorCanon.sha256).slice(0, 20)}…`
                : '—')}
              ${definition('Canon Index revision', canonIndex.revision
                ? `${String(canonIndex.revision).slice(0, 20)}…`
                : '—')}
            </dl>
          </details>
        </section>

        <section class="workspace-detail-card">
          <h3>Book artifacts</h3>
          ${table(
            ['Artifact', 'State', 'Readiness', 'Selected Canon', 'Est. Tokens', 'Dependency Hash'],
            targetRows
          )}
        </section>

        <section class="workspace-detail-card">
          <h3>Compilation blockers</h3>
          ${blockers.length
            ? table(['Scope', 'Code', 'Reason'], blockerRows)
            : '<div class="workspace-success-note">No compilation blockers.</div>'}
        </section>

        <section class="workspace-detail-card">
          <h3>Execution boundary</h3>
          <div class="workspace-lock-grid">
            ${lockCard('Compilation', compilerReady ? 'Ready' : 'Blocked')}
            ${lockCard('Full Project Context Append', 'Disabled')}
            ${lockCard('Prompt Builder', locks.prompt_builder_called ? 'Called' : 'Not called')}
            ${lockCard('Provider', locks.provider_called ? 'Called' : 'Blocked')}
            ${lockCard('Approved Continuity Writes', locks.approved_continuity_written ? 'Written' : 'Blocked')}
            ${lockCard('Generation Unlock', locks.generation_unlocked ? 'Unlocked' : 'Locked')}
          </div>
        </section>

        <div class="workspace-action-row">
          <button type="button" id="book-runtime-context-refresh" class="secondary-action"
            ${loading ? 'disabled' : ''}>${loading ? 'Refreshing…' : 'Refresh Status'}</button>
          <button type="button" id="book-runtime-context-generate" class="primary-action"
            ${compileEnabled ? '' : 'disabled'}
            aria-disabled="${compileEnabled ? 'false' : 'true'}">
            ${loading ? 'Working…' : 'Compile Ready Book Knowledge Packs'}
          </button>
        </div>

        <div class="workspace-disabled-note">
          ${escapeHtml(bookContext.message || 'Book Runtime Context v2 status is unavailable.')}
          ${readOnly ? ' Archived projects are read-only.' : ''}
        </div>
      </div>
    `;

    document.getElementById('book-runtime-context-refresh')?.addEventListener(
      'click',
      () => void loadBookRuntimeContextStatus()
    );
    document.getElementById('book-runtime-context-generate')?.addEventListener(
      'click',
      () => void generateBookRuntimeContext()
    );

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
      setLog(`Book Knowledge Pack status: ${status.status || 'unknown'}; ${status.ready_count || 0} target(s) ready.`);
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
        message: `Unable to load Book Runtime Context v2 status: ${error.message}`,
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
        "No Book Knowledge Pack is ready to compile yet. Complete and approve a Book Canon and that book's Book Plan first."
      );
      return;
    }

    state.bookRuntimeContextLoading = true;
    renderBookRuntimeContext(state.bootstrap);
    setLog('Compiling each ready Book Knowledge Pack from its selected Book Canon and approved Book Plan…');

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
        `Compiled ${result.generated_count || 0} Book Knowledge Pack artifact(s). Downstream generation remains locked.`
      );
      state.bookRuntimeContext = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/books/status`
      );
      state.chapterKnowledgePack = null;
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
