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
    bookRuntimeContextByBook: {},
    dashboardBookKnowledgeRefreshNeeded: true,
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
    chapterKnowledgePackRequestToken: 0,
    chapterEventSequenceDefaultAppliedKey: '',
    plannerViewModes: { book_plan: 'default', chapter_planner: 'default', library: 'default' },
    authorLibrary: null,
    authorLibraryLoading: false
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

      // Populate template-specific Library navigation after the Dashboard paints.
      // This preserves the lightweight bootstrap path while making the full
      // Library menu available after a hard refresh without requiring a Library click first.
      void ensureAuthorLibrary()
        .then(() => {
          if (state.activeSection === 'dashboard') renderSection('dashboard');
        })
        .catch((error) => setLog(`Library navigation unavailable: ${error.message}`));

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
          closeWorkspaceViewMenu();
          setLog(`${labelFor(menu)} is visible but disabled until project-scoped runtime migration is complete.`);
          return;
        }

        if (menu !== 'file') {
          event.preventDefault();
        }

        if (menu === 'view') {
          toggleWorkspaceViewMenu();
          return;
        }

        closeWorkspaceViewMenu();
        if (menu === 'project') renderSection('dashboard');
        if (menu === 'engine') renderSection('settings');
        if (menu === 'settings') renderSection('settings');
      });
    });

    document.querySelectorAll('[data-view-submenu-trigger]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        const target = String(button.dataset.viewSubmenuTrigger || '');
        toggleWorkspaceViewSubmenu(target);
      });
    });

    document.querySelectorAll('[data-planner-view-target][data-planner-view-mode]').forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();

        const target = String(button.dataset.plannerViewTarget || '');
        const mode = String(button.dataset.plannerViewMode || 'default');
        if (!['book_plan', 'chapter_planner', 'library'].includes(target)) return;
        if (!['default', 'collapse', 'expand'].includes(mode)) return;

        state.plannerViewModes[target] = mode;
        updatePlannerViewMenuSelection(target);
        applyPlannerViewMode(target, mode === 'default');

        const plannerLabel = target === 'book_plan' ? 'Book Planner' : (target === 'chapter_planner' ? 'Chapter Planner' : 'Library');
        const modeLabel = mode === 'collapse' ? 'Collapse All' : (mode === 'expand' ? 'Expand All' : 'Default');
        setLog(`${plannerLabel} view set to ${modeLabel}.`);
      });
    });

    document.addEventListener('click', (event) => {
      const menu = document.querySelector('.workspace-view-menu');
      if (menu && !menu.contains(event.target)) closeWorkspaceViewMenu();
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') closeWorkspaceViewMenu();
    });

    updatePlannerViewMenuSelection('book_plan');
    updatePlannerViewMenuSelection('chapter_planner');
    updatePlannerViewMenuSelection('library');
  }

  function toggleWorkspaceViewMenu() {
    const trigger = document.getElementById('workspace-view-trigger');
    const panel = document.getElementById('workspace-view-menu-panel');
    if (!trigger || !panel) return;

    const willOpen = panel.hidden === true;
    panel.hidden = !willOpen;
    trigger.setAttribute('aria-expanded', willOpen ? 'true' : 'false');

    if (!willOpen) {
      closeWorkspaceViewSubmenus();
    } else {
      setLog('View controls are available for Book Planner, Chapter Planner, and Library.');
    }
  }

  function closeWorkspaceViewMenu() {
    const trigger = document.getElementById('workspace-view-trigger');
    const panel = document.getElementById('workspace-view-menu-panel');
    if (!panel || panel.hidden) return;
    panel.hidden = true;
    trigger?.setAttribute('aria-expanded', 'false');
    closeWorkspaceViewSubmenus();
  }

  function closeWorkspaceViewSubmenus(exceptTarget = '') {
    document.querySelectorAll('[data-view-submenu-trigger]').forEach((button) => {
      const target = String(button.dataset.viewSubmenuTrigger || '');
      if (target === exceptTarget) return;
      button.setAttribute('aria-expanded', 'false');
      const options = document.querySelector(`[data-view-submenu-options="${CSS.escape(target)}"]`);
      if (options) options.hidden = true;
    });
  }

  function toggleWorkspaceViewSubmenu(target) {
    const button = document.querySelector(`[data-view-submenu-trigger="${CSS.escape(target)}"]`);
    const options = document.querySelector(`[data-view-submenu-options="${CSS.escape(target)}"]`);
    if (!button || !options) return;

    const willOpen = options.hidden === true;
    closeWorkspaceViewSubmenus(target);
    options.hidden = !willOpen;
    button.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
  }

  function updatePlannerViewMenuSelection(target) {
    const mode = String((state.plannerViewModes || {})[target] || 'default');
    document.querySelectorAll(`[data-planner-view-target="${CSS.escape(target)}"]`).forEach((button) => {
      const selected = String(button.dataset.plannerViewMode || '') === mode;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
  }

  function plannerDisclosureNodes(target) {
    if (!mainPanel) return [];
    if (target === 'book_plan') {
      return Array.from(mainPanel.querySelectorAll([
        '.planner-book-plan-unified details.planner-book-canon-embedded',
        '.planner-book-plan-unified details.planner-selected-summary',
        '.planner-book-plan-unified details.book-canon-category'
      ].join(', ')));
    }
    if (target === 'chapter_planner') {
      return Array.from(mainPanel.querySelectorAll('details.chapter-planner-card'));
    }
    if (target === 'library') {
      return Array.from(mainPanel.querySelectorAll('details.library-author-section'));
    }
    return [];
  }

  function applyPlannerViewMode(target, restoreDefault = false) {
    const nodes = plannerDisclosureNodes(target);
    if (!nodes.length) return;

    nodes.forEach((node) => {
      if (!Object.prototype.hasOwnProperty.call(node.dataset, 'viewDefaultOpen')) {
        node.dataset.viewDefaultOpen = node.open === true ? 'true' : 'false';
      }
    });

    const mode = String((state.plannerViewModes || {})[target] || 'default');
    nodes.forEach((node) => {
      if (mode === 'collapse') {
        node.open = false;
      } else if (mode === 'expand') {
        node.open = true;
      } else if (restoreDefault) {
        node.open = node.dataset.viewDefaultOpen === 'true';
      }
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

  function refreshChapterAvailabilityCountsFromDom() {
    if (!mainPanel) return;
    const availableCanonCount = mainPanel.querySelectorAll('#chapter-available-canon-list [data-chapter-canon-row]').length;
    const availableEventCount = mainPanel.querySelectorAll('#chapter-event-available-list [data-chapter-event-row]').length;
    const canonTarget = document.getElementById('chapter-available-canon-count');
    const eventTarget = document.getElementById('chapter-available-event-count');
    if (canonTarget) canonTarget.textContent = `${availableCanonCount} available for this chapter`;
    if (eventTarget) eventTarget.textContent = `${availableEventCount} available for this chapter`;
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
    refreshChapterAvailabilityCountsFromDom();
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
    refreshChapterAvailabilityCountsFromDom();
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
          const selectedCanonRows = Array.from(
            selectedContainer?.querySelectorAll('[data-chapter-canon-row]') || []
          );
          const sequencedEventRows = Array.from(
            document.getElementById('chapter-event-sequence-list')
              ?.querySelectorAll('[data-chapter-event-row]') || []
          );

          if (!selectedCanonRows.length && !sequencedEventRows.length) return;

          const confirmed = window.confirm(
            `Return all chapter selections? This will return ${selectedCanonRows.length} Canon selection(s) ` +
            `and ${sequencedEventRows.length} sequenced event(s) from this chapter. ` +
            'This changes only the on-screen Chapter Plan draft until you press Save Chapter Plan. ' +
            'The existing Chapter Knowledge Pack files remain unchanged until you compile the pack again.'
          );
          if (!confirmed) return;

          selectedCanonRows.forEach((row) =>
            moveChapterCanonRow(String(row.dataset.chapterCanonRow || ''), false)
          );
          sequencedEventRows.forEach((row) =>
            moveChapterEventCard(String(row.dataset.chapterEventRow || ''), false)
          );
          return;
        }

        const boxes = action === 'add_selected'
          ? Array.from(availableContainer?.querySelectorAll('[data-chapter-canon-batch-ref]:checked') || [])
          : Array.from(selectedContainer?.querySelectorAll('[data-chapter-canon-batch-ref]:checked') || []);
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

    const nextSection = sectionId || 'dashboard';
    if (state.activeSection === 'dashboard' && nextSection !== 'dashboard') {
      state.dashboardBookKnowledgeRefreshNeeded = true;
    }
    state.activeSection = nextSection;

    document.querySelectorAll('[data-workspace-section]').forEach((button) => {
      button.classList.toggle('active', button.dataset.workspaceSection === state.activeSection);
    });

    const manifest = bootstrap.manifest || {};
    const budget = bootstrap.budget_plan || {};
    const wizard = bootstrap.wizard_state || {};
    const context = bootstrap.project_context || {};
    const summary = bootstrap.summary || {};

    const viewMap = {
      dashboard: () => {
        renderDashboard(manifest, budget, wizard, bootstrap);
        if (state.dashboardBookKnowledgeRefreshNeeded && !state.bookRuntimeContextLoading) {
          void loadBookRuntimeContextStatus();
        }
      },
      manuscript_plan: () => renderManuscriptPlan(manifest, budget, wizard, summary),
      budget_plan: () => renderBudgetPlan(budget, manifest),
      books: () => { void renderAuthorLibrary('books', bootstrap); },
      chapters: () => { void renderAuthorLibrary('chapters', bootstrap); },
      scenes: () => { void renderAuthorLibrary('scenes', bootstrap); },
      events: () => { void renderAuthorLibraryByRecordId('events', bootstrap); },
      characters: () => { void renderAuthorLibraryByRecordId('characters', bootstrap); },
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

    if (state.activeSection.startsWith('library__')) {
      void renderAuthorLibrary(state.activeSection.slice('library__'.length), bootstrap);
      return;
    }

    const renderer = viewMap[state.activeSection] || viewMap.dashboard;
    renderer();
  }

  function renderDashboard(manifest, budget, wizard, bootstrap) {
    setHeading('Dashboard');

    const summary = bootstrap.summary || {};
    const runtimeContext = bootstrap.runtime_context || {};
    const projectContext = state.projectRuntimeContext || runtimeContext.project || {};
    const bookContext = state.bookRuntimeContext || runtimeContext.books || {};
    const bookKnowledgeDetailLoaded = Boolean(state.bookRuntimeContext);
    const bookKnowledgeStatusError = String(bookContext.status || '') === 'error';
    const bookKnowledgeStatusFresh = Boolean(
      bookKnowledgeDetailLoaded
      && !bookKnowledgeStatusError
      && state.dashboardBookKnowledgeRefreshNeeded !== true
      && state.bookRuntimeContextLoading !== true
    );
    const bookKnowledgeChecking = Boolean(
      state.dashboardBookKnowledgeRefreshNeeded === true
      || state.bookRuntimeContextLoading === true
    );
    const bookKnowledgeTargets = bookKnowledgeStatusFresh && Array.isArray(bookContext.targets)
      ? bookContext.targets
      : [];
    const actionableBookKnowledgeTargets = bookKnowledgeTargets.filter((target) =>
      target
      && target.compiler_ready === true
      && String(target.status || '').trim().toLowerCase() !== 'current'
    );
    const authorLibrary = state.authorLibrary || null;
    const libraryBooks = Array.isArray((((authorLibrary || {}).universal || {}).books || {}).items)
      ? (((authorLibrary || {}).universal || {}).books || {}).items
      : [];
    const libraryChapters = Array.isArray((((authorLibrary || {}).universal || {}).chapters || {}).items)
      ? (((authorLibrary || {}).universal || {}).chapters || {}).items
      : [];
    const libraryLoaded = Boolean(authorLibrary);
    const attention = [];

    const projectContextStatus = String(projectContext.status || 'not generated').replace(/_/g, ' ');
    let projectContextSummary = `${projectContextStatus} — project-wide Canon knowledge status.`;
    if (projectContext.artifact_current === true && projectContext.approval_fresh === true) {
      projectContextSummary = 'Current and approved — project-wide Canon context is ready for downstream Book Knowledge.';
    } else if (projectContext.artifact_current === true && String(projectContext.approval_status || '') === 'approval_required') {
      projectContextSummary = 'Current — project-wide Canon context is compiled and waiting for author approval.';
    } else if (String(projectContext.status || '') === 'outdated') {
      projectContextSummary = 'Outdated — Canon changed after this Project Context was compiled; update and approve it.';
    } else if (String(projectContext.status || '') === 'missing') {
      projectContextSummary = 'Not generated — create the project-wide Canon context before relying on downstream knowledge.';
    } else if (String(projectContext.status || '') === 'blocked') {
      projectContextSummary = 'Blocked — required Canon or rendered source material needs attention first.';
    }

    const plannedBooks = libraryBooks
      .filter((item) =>
        number(item.planned_chapters) > 0
        || !['', 'not_ready'].includes(String(item.approval_status || '').trim().toLowerCase())
      )
      .sort((a, b) => number(b.book_number) - number(a.book_number));

    const latestChapter = libraryChapters
      .slice()
      .sort((a, b) =>
        number(b.book_number) - number(a.book_number)
        || number(b.chapter_number) - number(a.chapter_number)
      )[0] || null;

    const latestBookNumber = latestChapter
      ? number(latestChapter.book_number)
      : (plannedBooks[0] ? number(plannedBooks[0].book_number) : 0);
    const latestBook = libraryBooks.find((item) => number(item.book_number) === latestBookNumber) || {};
    const latestBookTitle = String(latestBook.title || '').trim();
    const latestBookDisplay = latestBookNumber
      ? `Book ${latestBookNumber}${latestBookTitle ? ` — ${latestBookTitle}` : ''}`
      : 'No Book Plan activity recorded';

    const bookPlanningSummary = !libraryLoaded
      ? 'Loading Book and Chapter planning summary…'
      : latestBookNumber
        ? `${latestBookDisplay} · ${bookPlanApprovalStatusLabel(latestBook.approval_status || 'not_ready')} · ${number(latestBook.planned_chapters)} / ${number(latestBook.target_chapters || manifest.chapters_per_book)} chapters planned`
        : 'No Book Plan or Chapter Plan activity is recorded yet.';

    const latestChapterSummary = !libraryLoaded
      ? 'Loading latest planned Chapter…'
      : latestChapter
        ? `Book ${number(latestChapter.book_number)}, Chapter ${number(latestChapter.chapter_number)} — ${chapterPlanningStatusLabel(latestChapter.status || 'draft')}`
        : 'No Chapter Plan has been created yet.';

    const planningCoverageSummary = !libraryLoaded
      ? 'Loading planning coverage…'
      : latestBookNumber
        ? `${number(latestBook.planned_chapters)} / ${number(latestBook.target_chapters || manifest.chapters_per_book)} chapters planned in Book ${latestBookNumber}`
        : `0 / ${number(manifest.chapters_per_book)} chapters planned`;

    const seriesName = String(manifest.series_name || manifest.project_name || 'This project').trim();
    const seriesPlanSummary = number(manifest.book_count) === 1
      ? 'This project is planned as 1 book.'
      : `${seriesName} is planned as a ${number(manifest.book_count)}-book series.`;

    const bookKnowledgeSummary = bookKnowledgeChecking
      ? `Checking current Book Knowledge status across ${number(manifest.book_count)} books…`
      : bookKnowledgeStatusError
        ? 'Book Knowledge status could not be refreshed. Open Book Knowledge and retry the status check.'
        : bookKnowledgeStatusFresh
          ? `${number(bookContext.current_count)} current Book Knowledge pack(s) across ${number(bookContext.target_count || manifest.book_count)} books. ${actionableBookKnowledgeTargets.length ? `${number(actionableBookKnowledgeTargets.length)} pack(s) need compilation or recompilation and are ready now.` : 'No Book Knowledge pack currently needs compilation.'} These are compiled per-book Canon + Book Plan context, not completed manuscripts.`
          : `Per-book compiled Canon + Book Plan context for ${number(manifest.book_count)} books. Currentness has not been checked in this Dashboard session yet.`;

    if (number(summary.attention_required_section_count) > 0) {
      attention.push(`${number(summary.attention_required_section_count)} Canon section(s) need author attention.`);
    }
    if (projectContext.artifact_current === false || String(projectContext.approval_status || '') === 'outdated') {
      attention.push('Project Context needs to be updated before downstream knowledge remains current.');
    }

    if (libraryLoaded) {
      const approvalNeeded = libraryBooks
        .filter((item) => String(item.approval_status || '').trim().toLowerCase() === 'approval_required')
        .sort((a, b) => number(a.book_number) - number(b.book_number));
      const outdatedPlans = libraryBooks
        .filter((item) => String(item.approval_status || '').trim().toLowerCase() === 'outdated')
        .sort((a, b) => number(a.book_number) - number(b.book_number));
      const chapterIssues = libraryChapters
        .filter((item) => ['outdated', 'reconciliation_required'].includes(String(item.status || '').trim().toLowerCase()))
        .sort((a, b) =>
          number(a.book_number) - number(b.book_number)
          || number(a.chapter_number) - number(b.chapter_number)
        );

      if (approvalNeeded.length) {
        attention.push(`Book ${number(approvalNeeded[0].book_number)} Plan is ready for author approval.`);
      }
      if (outdatedPlans.length) {
        attention.push(`Book ${number(outdatedPlans[0].book_number)} Plan is outdated and needs review.`);
      }
      if (chapterIssues.length) {
        const issue = chapterIssues[0];
        attention.push(`Book ${number(issue.book_number)}, Chapter ${number(issue.chapter_number)} planning needs review: ${chapterPlanningStatusLabel(issue.status || 'outdated')}.`);
      }
    }

    if (bookKnowledgeStatusError && !bookKnowledgeChecking) {
      attention.push('Book Knowledge status could not be refreshed. Open Book Knowledge and retry the status check.');
    }
    if (bookKnowledgeStatusFresh && actionableBookKnowledgeTargets.length) {
      const actionableMissing = actionableBookKnowledgeTargets.filter((target) =>
        String(target.status || '').trim().toLowerCase() === 'missing'
      );
      const actionableOutdated = actionableBookKnowledgeTargets.filter((target) =>
        String(target.status || '').trim().toLowerCase() === 'outdated'
      );
      const actionableOther = actionableBookKnowledgeTargets.length - actionableMissing.length - actionableOutdated.length;

      if (actionableMissing.length) {
        attention.push(`${number(actionableMissing.length)} Book Knowledge pack(s) are ready to compile.`);
      }
      if (actionableOutdated.length) {
        attention.push(`${number(actionableOutdated.length)} Book Knowledge pack(s) are outdated and ready to recompile.`);
      }
      if (actionableOther > 0) {
        attention.push(`${number(actionableOther)} Book Knowledge pack(s) are ready for compilation.`);
      }
    }

    const attentionBody = attention.length
      ? `<ul class="workspace-author-attention-list">${attention.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
      : `<div class="workspace-success-note">
          No project-wide issue is currently flagged. Book Planner, Chapter Planner, and Book Knowledge
          perform their detailed per-book checks when those pages are opened.
        </div>`;

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-author-dashboard-phase-a">
        <section class="workspace-author-hero">
          <span class="workspace-author-eyebrow">CURRENT PROJECT</span>
          <h3>${escapeHtml(manifest.project_name || 'Untitled Project')}</h3>
          <p>
            Your author command center. This page summarizes project-wide readiness, the latest recorded
            planning position, and where to continue without replacing the dedicated working pages.
          </p>
        </section>

        <section class="workspace-author-dashboard-grid">
          <article class="workspace-author-summary-card">
            <h3>Project Progress</h3>
            <div class="workspace-author-metric-list">
              <div><strong>Author Canon</strong><span>${number(summary.completed_required_author_section_count)} / ${number(summary.required_author_section_count)} required sections complete</span></div>
              <div><strong>Project Context</strong><span>${escapeHtml(projectContextSummary)}</span></div>
              <div><strong>Book Planning</strong><span>${escapeHtml(bookPlanningSummary)}</span></div>
              <div><strong>Book Knowledge</strong><span>${escapeHtml(bookKnowledgeSummary)}</span></div>
            </div>
          </article>

          <article class="workspace-author-summary-card">
            <h3>Writing Position</h3>
            <div class="workspace-author-metric-list">
              <div><strong>Series Plan</strong><span>${escapeHtml(seriesPlanSummary)}</span></div>
              <div><strong>Latest Planned Book</strong><span>${escapeHtml(latestBookDisplay)}</span></div>
              <div><strong>Latest Planned Chapter</strong><span>${escapeHtml(latestChapterSummary)}</span></div>
              <div><strong>Planning Coverage</strong><span>${escapeHtml(planningCoverageSummary)}</span></div>
              <div><strong>Author-Accepted Chapters</strong><span>Not tracked until manuscript acceptance becomes authoritative.</span></div>
            </div>
          </article>
        </section>

        <section class="workspace-author-summary-card">
          <h3>Needs Attention</h3>
          ${attentionBody}
        </section>

        <section class="workspace-author-summary-card">
          <h3>Continue</h3>
          <p class="placeholder">Choose the dedicated page for the work you want to do next.</p>
          <div class="workspace-author-action-grid">
            <button type="button" class="workspace-author-action" data-dashboard-target="book_plan">Book Planner</button>
            <button type="button" class="workspace-author-action" data-dashboard-target="chapter_planner">Chapter Planner</button>
            <button type="button" class="workspace-author-action" data-dashboard-target="project_runtime_context">Project Context</button>
            <button type="button" class="workspace-author-action" data-dashboard-target="book_runtime_context">Book Knowledge</button>
            <button type="button" class="workspace-author-action" data-dashboard-target="books">Library — Books</button>
          </div>
        </section>

        <details class="workspace-technical-details workspace-author-dashboard-technical">
          <summary>Technical Status</summary>
          <div class="workspace-lock-grid">
            ${lockCard('Generation', bootstrap.generation_enabled ? 'Enabled' : 'Locked')}
            ${lockCard('Validation', bootstrap.validation_enabled ? 'Enabled' : 'Locked')}
            ${lockCard('Export', bootstrap.exports_enabled ? 'Enabled' : 'Locked')}
          </div>
        </details>
      </div>
    `;

    mainPanel.querySelectorAll('[data-dashboard-target]').forEach((button) => {
      button.addEventListener('click', () => renderSection(button.dataset.dashboardTarget || 'dashboard'));
    });
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

  async function ensureAuthorLibrary() {
    if (state.authorLibrary) return state.authorLibrary;
    if (state.authorLibraryLoading) {
      while (state.authorLibraryLoading) {
        await new Promise((resolve) => window.setTimeout(resolve, 25));
      }
      return state.authorLibrary;
    }

    state.authorLibraryLoading = true;
    try {
      const payload = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/workspace/library`);
      state.authorLibrary = payload;
      syncAuthorLibrarySidebar(payload);
      return payload;
    } finally {
      state.authorLibraryLoading = false;
    }
  }

  function syncAuthorLibrarySidebar(library) {
    const container = document.getElementById('workspace-library-canon-menu');
    if (!container || !library) return;
    const navigation = Array.isArray(library.navigation) ? library.navigation : [];
    const dynamic = navigation.filter((item) => item && !['books', 'chapters', 'scenes'].includes(String(item.key || '')));
    container.innerHTML = dynamic.map((item) => {
      const key = String(item.key || '');
      const label = String(item.label || key || 'Library');
      const count = Number.isFinite(Number(item.count)) ? ` <span class="library-menu-count">${number(item.count)}</span>` : '';
      return `<button type="button" data-workspace-section="library__${escapeHtml(key)}" data-workspace-enabled="true">${escapeHtml(label)}${count}</button>`;
    }).join('');
  }

  async function renderAuthorLibraryByRecordId(recordId, bootstrap) {
    const library = await ensureAuthorLibrary();
    const collection = ((library || {}).canon || {}).collections || [];
    const match = collection.find((item) => String(item.record_id || '') === String(recordId || ''));
    if (!match) {
      renderAuthorLibraryEmpty(labelFor(recordId), 'This Canon collection is not defined by the active project template.');
      return;
    }
    await renderAuthorLibrary(String(match.key || ''), bootstrap);
  }

  async function renderAuthorLibrary(key, bootstrap) {
    setHeading('Library');
    mainPanel.innerHTML = `<div class="workspace-content"><p class="placeholder">Loading author Library…</p></div>`;
    let library;
    try {
      library = await ensureAuthorLibrary();
    } catch (error) {
      renderError(`Library failed to load: ${error.message}`);
      return;
    }

    if (!library || state.activeSection === 'dashboard') return;

    if (key === 'books') {
      renderAuthorLibraryBooks(library);
    } else if (key === 'chapters') {
      renderAuthorLibraryChapters(library);
    } else if (key === 'scenes') {
      renderAuthorLibraryScenes(library);
    } else if (String(key).startsWith('canon_collection__')) {
      renderAuthorLibraryCollection(library, key);
    } else if (String(key).startsWith('canon_reference__')) {
      renderAuthorLibraryReference(library, key);
    } else {
      renderAuthorLibraryEmpty('Library', 'This Library view is not available for the active project template.');
    }
    applyPlannerViewMode('library');
  }

  function librarySection(title, subtitle, body) {
    return `
      <details class="library-author-section" open data-view-default-open="true">
        <summary><span class="library-disclosure-chevron" aria-hidden="true"></span><span>${escapeHtml(title)}</span></summary>
        <div class="library-author-section-body">
          ${subtitle ? `<p class="placeholder">${escapeHtml(subtitle)}</p>` : ''}
          ${body}
        </div>
      </details>
    `;
  }

  function libraryProgress(value, label) {
    const numeric = Math.max(0, Math.min(100, Number(value) || 0));
    return `
      <div class="library-progress" role="progressbar" aria-label="${escapeHtml(label)}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${numeric}">
        <span style="width:${numeric}%"></span>
      </div>
    `;
  }

  function bookPlanApprovalStatusLabel(status) {
    const normalized = String(status || 'not_ready').trim().toLowerCase();
    const labels = {
      not_ready: 'PLAN NOT READY',
      approval_required: 'PLAN APPROVAL REQUIRED',
      approved: 'PLAN APPROVED',
      outdated: 'PLAN OUTDATED'
    };
    return labels[normalized] || `PLAN ${String(status || 'not_ready').replace(/_/g, ' ').toUpperCase()}`;
  }

  function renderAuthorLibraryBooks(library) {
    setHeading('Library — Books');
    const books = (((library || {}).universal || {}).books || {});
    const items = Array.isArray(books.items) ? books.items : [];
    const planned = Number(books.planned_count || 0);
    const expected = Number(books.expected_count || 0);
    const summary = `
      <div class="workspace-stat-grid library-stat-grid">
        ${statCard('Books', `${planned} / ${expected}`)}
        ${statCard('Target Chapters / Book', number(books.chapters_per_book))}
        ${statCard('Genre', labelFor(library.genre || '—'))}
        ${statCard('Token Usage', ((library.budget || {}).actual_usage_available ? 'Tracked' : 'Not yet tracked'))}
      </div>
    `;
    const cards = items.map((book) => {
      const pct = Number(book.planning_percent || 0);
      const active = book.active_chapter ? `Chapter ${number(book.active_chapter)}` : 'Not yet planned';
      const tokens = Number(book.estimated_tokens || 0);
      return `
        <article class="library-card">
          <header><div><span class="library-kicker">Book ${number(book.book_number)}</span><h4>${escapeHtml(book.title || `Book ${number(book.book_number)}`)}</h4></div>${statusBadge(bookPlanApprovalStatusLabel(book.approval_status))}</header>
          ${book.time_span ? `<p class="library-muted">${escapeHtml(book.time_span)}</p>` : ''}
          <div class="library-card-grid">
            <div><strong>Planning Progress</strong><span>${number(book.planned_chapters)} / ${number(book.target_chapters)} chapters</span></div>
            <div><strong>Latest Planned Chapter</strong><span>${escapeHtml(active)}</span></div>
          </div>
          ${libraryProgress(pct, `Book ${number(book.book_number)} planning progress`)}
          <p class="library-progress-label">${pct.toFixed(1)}% planning coverage</p>
          <div class="library-card-grid">
            <div><strong>Estimated Book Tokens</strong><span>${tokens ? number(tokens) : 'Not configured'}</span></div>
            <div><strong>Remaining Tokens</strong><span>${book.actual_token_usage_available ? 'Available' : 'Tracking not yet available'}</span></div>
          </div>
        </article>
      `;
    }).join('') || `<p class="placeholder">No Book Plan entries exist yet.</p>`;

    mainPanel.innerHTML = `<div class="workspace-content library-author-view">
      ${librarySection('Series Progress', 'A planning view of the current series. Draft completion is intentionally separate from planning progress.', summary)}
      ${librarySection('Books', 'Book titles, planning coverage, approval state, and configured budget estimates.', `<div class="library-card-list">${cards}</div>`)}
    </div>`;
  }

  function chapterPlanningStatusLabel(status) {
    const normalized = String(status || 'draft').trim().toLowerCase();
    const labels = {
      draft: 'PLANNING DRAFT',
      complete: 'PLANNING COMPLETE',
      outdated: 'PLANNING OUTDATED',
      reconciliation_required: 'PLANNING RECONCILIATION REQUIRED'
    };
    return labels[normalized] || `PLANNING ${String(status || 'draft').replace(/_/g, ' ').toUpperCase()}`;
  }

  function renderAuthorLibraryChapters(library) {
    setHeading('Library — Chapters');
    const chapters = (((library || {}).universal || {}).chapters || {});
    const books = (((library || {}).universal || {}).books || {});
    const items = Array.isArray(chapters.items) ? chapters.items : [];
    const bookItems = Array.isArray(books.items) ? books.items : [];
    const bookTitleByNumber = new Map(
      bookItems.map((book) => [Number(book.book_number || 0), String(book.title || '').trim()])
    );
    const expected = Number(chapters.expected_count || 0);
    const planned = Number(chapters.planned_count || 0);
    const pct = expected > 0 ? Math.min(100, (planned / expected) * 100) : 0;
    const overview = `
      <div class="workspace-stat-grid library-stat-grid">
        ${statCard('Planned Chapters', `${planned} / ${expected}`)}
        ${statCard('Planning Coverage', `${pct.toFixed(1)}%`)}
      </div>
      ${libraryProgress(pct, 'Overall chapter planning coverage')}
    `;
    const cards = items.map((chapter) => {
      const bookNumber = Number(chapter.book_number || 0);
      const bookTitle = bookTitleByNumber.get(bookNumber) || '';
      const bookLabel = bookTitle ? `Book ${number(bookNumber)} — ${bookTitle}` : `Book ${number(bookNumber)}`;
      return `
        <article class="library-card compact library-chapter-card">
          <header>
            <div>
              <span class="library-chapter-book-context">${escapeHtml(bookLabel)}</span>
              <h4>${escapeHtml(chapter.title || `Chapter ${number(chapter.chapter_number)}`)}</h4>
            </div>
            <div class="library-card-status">${statusBadge(chapterPlanningStatusLabel(chapter.status))}</div>
          </header>
          <div class="library-card-grid">
            <div><strong>Selected Canon</strong><span>${number(chapter.canon_count)}</span></div>
            <div><strong>Assigned Events</strong><span>${number(chapter.event_count)}</span></div>
            <div><strong>Revision</strong><span>${number(chapter.revision)}</span></div>
          </div>
          ${chapter.kickoff ? `<p class="library-excerpt"><strong>Kickoff:</strong> ${escapeHtml(chapter.kickoff)}</p>` : ''}
        </article>
      `;
    }).join('') || `<p class="placeholder">No Chapter Plans have been saved yet.</p>`;
    mainPanel.innerHTML = `<div class="workspace-content library-author-view">
      ${librarySection('Chapter Planning Progress', 'Planning coverage reflects saved Chapter Plans, not manuscript completion.', overview)}
      ${librarySection('Chapters', 'Saved Chapter Plans across the series.', `<div class="library-card-list">${cards}</div>`)}
    </div>`;
  }

  function renderAuthorLibraryScenes(library) {
    setHeading('Library — Scenes');
    const scenes = (((library || {}).universal || {}).scenes || {});
    const context = scenes.planning_context || {};
    const types = Array.isArray(context.scene_types) ? context.scene_types : [];
    const governing = Array.isArray(context.governing_canon_sections) ? context.governing_canon_sections : [];
    const contextBody = `
      <div class="workspace-stat-grid library-stat-grid">
        ${statCard('Genre', labelFor(library.genre || '—'))}
        ${statCard('Scene Types', types.length ? number(types.length) : 'Template governed')}
        ${statCard('Canon Sections', number(governing.length))}
      </div>
      ${types.length ? `<div class="library-chip-list">${types.map((item) => `<span>${escapeHtml(labelFor(item))}</span>`).join('')}</div>` : ''}
      <div class="library-reference-list">
        ${governing.map((item) => `<article><strong>${escapeHtml(item.label || item.section_id)}</strong>${item.purpose ? `<span>${escapeHtml(item.purpose)}</span>` : ''}</article>`).join('')}
      </div>
    `;
    const sceneItems = Array.isArray(scenes.items) ? scenes.items : [];
    const sceneBody = sceneItems.length
      ? `<div class="library-card-list">${sceneItems.map((scene) => `
          <article class="library-card compact">
            <header><div><span class="library-kicker">${escapeHtml(scene.chapter_id || scene.book_id || 'Scene')}</span><h4>${escapeHtml(scene.title || scene.scene_id || 'Untitled Scene')}</h4></div>${statusBadge(String(scene.status || 'saved').toUpperCase())}</header>
            ${scene.event_name ? `<p class="library-muted">${escapeHtml(scene.event_name)}</p>` : ''}
          </article>`).join('')}</div>`
      : `<div class="library-empty-state"><strong>No manuscript scenes have been created yet.</strong><span>Your current Canon and Chapter Plans remain available as scene-planning context.</span></div>`;
    mainPanel.innerHTML = `<div class="workspace-content library-author-view">
      ${librarySection('Scene Planning Context', 'Genre-aware Canon and optional scene vocabulary that govern scene construction.', contextBody)}
      ${librarySection('Manuscript Scenes', 'Persisted manuscript scene records appear here when they exist.', sceneBody)}
    </div>`;
  }

  function libraryRecordHeading(record) {
    return String(
      record.name || record.title || record.label || record.event_summary ||
      record.story_code || record.internal_id || record.item_id || 'Canon Record'
    );
  }

  function libraryVisibleRecordFields(collection, record) {
    const schemaFields = Array.isArray(collection.fields) ? collection.fields : [];
    const hidden = new Set(schemaFields.filter((field) => field.author_hidden).map((field) => String(field.field_id || '')));
    const preferred = schemaFields.map((field) => String(field.field_id || '')).filter(Boolean);
    const keys = preferred.length ? preferred : Object.keys(record || {});
    return keys.filter((key) => !hidden.has(key) && !['internal_id', 'record_id', 'item_id', 'source_record_hash'].includes(key));
  }

  function libraryInlineRichText(value) {
    return escapeHtml(String(value || '')).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  }

  function libraryFormattedText(value) {
    if (value === undefined || value === null || value === '') {
      return '<span class="library-readable-empty">—</span>';
    }

    if (Array.isArray(value)) {
      if (!value.length) return '<span class="library-readable-empty">—</span>';
      return `<div class="library-readable-text"><ul>${value.map((item) => `<li>${libraryInlineRichText(formatCell(item))}</li>`).join('')}</ul></div>`;
    }

    if (value && typeof value === 'object') {
      return `<div class="library-readable-text"><p>${libraryInlineRichText(formatCell(value))}</p></div>`;
    }

    const text = String(value).replace(/\r\n/g, '\n').trim();
    if (!text) return '<span class="library-readable-empty">—</span>';

    const lines = text.split('\n');
    const blocks = [];
    let listItems = [];

    const flushList = () => {
      if (!listItems.length) return;
      blocks.push(`<ul>${listItems.join('')}</ul>`);
      listItems = [];
    };

    lines.forEach((rawLine) => {
      const line = rawLine.trim();

      if (!line) {
        flushList();
        return;
      }

      const headingMatch = line.match(/^#{2,4}\s+(.+)$/);
      if (headingMatch) {
        flushList();
        blocks.push(`<h5>${libraryInlineRichText(headingMatch[1])}</h5>`);
        return;
      }

      const bulletMatch = line.match(/^[-•]\s+(.+)$/);
      if (bulletMatch) {
        listItems.push(`<li>${libraryInlineRichText(bulletMatch[1])}</li>`);
        return;
      }

      flushList();
      blocks.push(`<p>${libraryInlineRichText(line)}</p>`);
    });

    flushList();

    return `<div class="library-readable-text">${blocks.join('')}</div>`;
  }

  function renderAuthorLibraryCollection(library, key) {
    const collections = (((library || {}).canon || {}).collections || []);
    const collection = collections.find((item) => String(item.key || '') === String(key || ''));
    if (!collection) {
      renderAuthorLibraryEmpty('Canon Library', 'This collection is not available for the active project.');
      return;
    }
    setHeading(`Library — ${collection.label}`);
    const records = Array.isArray(collection.records) ? collection.records : [];
    const overview = `
      <div class="workspace-stat-grid library-stat-grid">
        ${statCard('Records', number(collection.count))}
        ${statCard('Canon Section', collection.section_label || collection.label)}
      </div>
      ${collection.author_guidance ? `<p class="library-guidance">${escapeHtml(collection.author_guidance)}</p>` : ''}
    `;
    const cards = records.map((record) => {
      const fields = libraryVisibleRecordFields(collection, record).filter((key) => {
        const value = record[key];
        return value !== undefined && value !== null && value !== '';
      });
      return `<article class="library-card compact">
        <header><div><span class="library-kicker">${escapeHtml(collection.label)}</span><h4>${escapeHtml(libraryRecordHeading(record))}</h4></div></header>
        <dl class="library-record-fields">
          ${fields.map((field) => `<div><dt>${escapeHtml(labelFor(field))}</dt><dd>${libraryFormattedText(record[field])}</dd></div>`).join('')}
        </dl>
      </article>`;
    }).join('') || `<p class="placeholder">No ${escapeHtml(collection.label)} records have been added yet.</p>`;
    mainPanel.innerHTML = `<div class="workspace-content library-author-view">
      ${librarySection(`${collection.label} Overview`, collection.purpose || 'Author Canon collection.', overview)}
      ${librarySection(collection.label, `Author Canon records from ${collection.section_label || collection.label}.`, `<div class="library-card-list">${cards}</div>`)}
    </div>`;
  }

  function renderAuthorLibraryReference(library, key) {
    const references = (((library || {}).canon || {}).references || []);
    const reference = references.find((item) => String(item.key || '') === String(key || ''));
    if (!reference) {
      renderAuthorLibraryEmpty('Canon Reference', 'This reference section is not available for the active project.');
      return;
    }
    setHeading(`Library — ${reference.label}`);
    const answers = reference.answers && typeof reference.answers === 'object' ? reference.answers : {};
    const fields = Array.isArray(reference.fields) ? reference.fields : [];
    const body = fields.map((field) => {
      const value = answers[field.field_id];
      if (value === undefined || value === null || value === '') return '';
      return `<article class="library-reference-card"><strong>${escapeHtml(field.label || labelFor(field.field_id))}</strong>${libraryFormattedText(value)}</article>`;
    }).join('') || `<p class="placeholder">No authored values have been saved in this Canon reference section yet.</p>`;
    mainPanel.innerHTML = `<div class="workspace-content library-author-view">
      ${librarySection(`${reference.label} Overview`, reference.purpose || 'Genre-specific Canon guidance.', reference.author_guidance ? `<div class="library-guidance">${libraryFormattedText(reference.author_guidance)}</div>` : '')}
      ${librarySection(reference.label, 'Read-only author Canon reference.', `<div class="library-reference-grid">${body}</div>`)}
    </div>`;
  }

  function renderAuthorLibraryEmpty(title, message) {
    setHeading(`Library — ${title}`);
    mainPanel.innerHTML = `<div class="workspace-content library-author-view">
      ${librarySection(title, '', `<div class="library-empty-state"><strong>${escapeHtml(message)}</strong></div>`)}
    </div>`;
    applyPlannerViewMode('library');
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
    setHeading('Project Context');

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
    const artifactExists = Number(projectContext.generated_count || 0) > 0
      || targets.some((target) => target && target.exists === true);
    const needsUpdate = String(projectContext.status || '') === 'outdated';
    const generateEnabled = validationReady && !artifactCurrent && !loading && !readOnly;
    const approveEnabled = artifactCurrent && !approvalFresh && !loading && !readOnly;
    const revokeEnabled = ['approved', 'outdated'].includes(approvalStatus)
      && !loading && !readOnly;

    const contextStateHeading = !validationReady
      ? 'PROJECT CONTEXT WAITING ON CANON'
      : !artifactExists
        ? 'PROJECT CONTEXT READY TO CREATE'
        : !artifactCurrent
          ? 'PROJECT CONTEXT NEEDS UPDATE'
          : !approvalFresh
            ? 'PROJECT CONTEXT READY FOR APPROVAL'
            : 'PROJECT CONTEXT CURRENT';

    const contextStatusLabel = !validationReady
      ? 'Waiting on Canon'
      : !artifactExists
        ? 'Not Created'
        : !artifactCurrent
          ? 'Needs Update'
          : 'Current';

    const approvalLabel = approvalFresh
      ? 'Approved'
      : approvalStatus === 'outdated'
        ? 'Needs Reapproval'
        : artifactCurrent
          ? 'Ready for Approval'
          : 'Not Ready';

    const generateLabel = artifactCurrent
      ? 'Project Context Up to Date'
      : artifactExists
        ? 'Update Project Context'
        : 'Create Project Context';

    const generateTitle = artifactCurrent
      ? 'Project Context already matches the current Canon, so no rebuild is needed. Rebuilding is disabled to avoid creating a new artifact and unnecessary reapproval.'
      : artifactExists
        ? 'Rebuilds Project Context from the project’s current Canon because the saved context no longer matches it. This does not change Canon or generate prose. Approve the rebuilt version before downstream knowledge uses it.'
        : 'Creates Project Context from the project’s current Canon. This does not change Canon or generate prose. Approve the new Project Context before downstream knowledge uses it.';

    const targetRows = targets.map((target) => `
      <tr>
        <td>${escapeHtml(target.label || 'Project Context')}</td>
        <td>${statusBadge(String(target.status || (target.exists ? 'generated' : 'missing')).toUpperCase())}</td>
        <td><code>${escapeHtml(target.project_relative_path || target.relative_path || '—')}</code></td>
        <td>${target.sha256 ? `<code>${escapeHtml(String(target.sha256).slice(0, 16))}…</code>` : '—'}</td>
        <td>${target.source_set_sha256 ? `<code>${escapeHtml(String(target.source_set_sha256).slice(0, 16))}…</code>` : '—'}</td>
      </tr>
    `).join('');

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-project-context-author-phase-a">
        <section class="workspace-author-hero">
          <h3 class="workspace-author-hero-title">PROJECT KNOWLEDGE FOUNDATION</h3>
          <div class="workspace-author-status-heading">${contextStateHeading}</div>
          <p>
            Project Context brings together the current Canon for your project so Italus has a consistent
            understanding of your world, characters, history, and story foundations. When you change Canon,
            update Project Context and approve the new version before continuing with book and chapter planning.
          </p>
        </section>

        <section class="workspace-author-summary-card">
          <div class="workspace-author-metric-list">
            <div>
              <strong>Canon Readiness</strong>
              <span>${validationReady ? 'Ready' : 'Needs Attention'}</span>
              <small>${validationReady
                ? 'Required Canon is complete enough to build Project Context.'
                : 'Complete required Canon and current Canon Markdown before Project Context can be created or updated.'}</small>
            </div>
            <div>
              <strong>Context Status</strong>
              <span>${escapeHtml(contextStatusLabel)}</span>
              <small>${!validationReady
                ? 'Project Context cannot be prepared until Canon is ready.'
                : !artifactExists
                  ? 'No Project Context has been created for this project yet.'
                  : !artifactCurrent
                    ? 'Canon changed after this Project Context was created.'
                    : 'Project Context matches the Canon currently saved for this project.'}</small>
            </div>
            <div>
              <strong>Author Approval</strong>
              <span>${escapeHtml(approvalLabel)}</span>
              <small>${approvalFresh
                ? 'You approved this exact current Project Context.'
                : approvalStatus === 'outdated'
                  ? 'A previously approved version no longer matches the current Project Context.'
                  : artifactCurrent
                    ? 'The current Project Context is ready for your approval.'
                    : 'Approval becomes available after Project Context is current.'}</small>
            </div>
            <div>
              <strong>Needs Update</strong>
              <span>${needsUpdate ? 'Yes' : 'No'}</span>
              <small>${needsUpdate
                ? 'Canon has changed since this Project Context was built.'
                : artifactCurrent
                  ? 'No Canon changes require a Project Context rebuild.'
                  : !artifactExists
                    ? 'Create Project Context first; there is no older context to update.'
                    : 'No update is available until Canon is ready.'}</small>
            </div>
          </div>
        </section>

        <div class="workspace-action-row workspace-author-gold-actions">
          <button type="button" id="project-runtime-context-refresh" class="secondary-action"
            title="Reloads Project Context and approval status. It does not rebuild Project Context or change saved project data."
            ${loading ? 'disabled' : ''}>${loading ? 'Working…' : 'Refresh'}</button>
          <button type="button" id="project-runtime-context-generate" class="primary-action"
            title="${escapeHtml(generateTitle)}" ${generateEnabled ? '' : 'disabled'}>${generateLabel}</button>
          <button type="button" id="project-runtime-context-approve" class="primary-action"
            title="Approves the current Project Context for use when preparing Book Knowledge and Chapter Knowledge. It does not change Canon or generate prose."
            ${approveEnabled ? '' : 'disabled'}>Approve Project Context</button>
          <button type="button" id="project-runtime-context-revoke" class="secondary-action"
            title="Removes approval from the current Project Context without deleting it or changing Canon. Book and chapter readiness may be blocked until Project Context is approved again."
            ${revokeEnabled ? '' : 'disabled'}>Revoke Approval</button>
        </div>

        <div class="workspace-disabled-note">${escapeHtml(projectContext.message || 'Project Context status is unavailable.')}</div>

        <details class="workspace-technical-details">
          <summary>Technical Details</summary>
          <div class="workspace-author-technical-stack">
            <section class="workspace-detail-card">
              <h3>Canon and approval metadata</h3>
              <dl class="workspace-definition-grid workspace-definition-grid--compact">
                ${definition('Required sections', `${number(validation.required_sections_complete)} / ${number(validation.required_sections_total)}`)}
                ${definition('Rendered Markdown sources', number(validation.rendered_sources_total))}
                ${definition('Source-set SHA-256', projectContext.source_set_sha256 ? `${String(projectContext.source_set_sha256).slice(0, 20)}…` : '—')}
                ${definition('Approved artifact SHA-256', projectContext.approved_artifact_sha256 ? `${String(projectContext.approved_artifact_sha256).slice(0, 20)}…` : '—')}
                ${definition('Approved source-set SHA-256', projectContext.approved_source_set_sha256 ? `${String(projectContext.approved_source_set_sha256).slice(0, 20)}…` : '—')}
                ${definition('Approved at', projectContext.approved_at || '—')}
              </dl>
            </section>
            <section class="workspace-detail-card">
              <h3>Artifact</h3>
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
          </div>
        </details>
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

  function captureChapterPlannerDisclosureState() {
    const sectionIds = [
      'chapter-selected-section',
      'chapter-available-canon-section',
      'chapter-available-events-section',
      'chapter-event-sequence-section',
      'chapter-related-directions-section',
      'chapter-generation-kickoff-section',
      'chapter-find-more-canon-section',
      'chapter-story-controls-section',
      'chapter-knowledge-pack-section'
    ];
    return Object.fromEntries(
      sectionIds
        .map((sectionId) => [sectionId, document.getElementById(sectionId)])
        .filter(([, element]) => Boolean(element))
        .map(([sectionId, element]) => [sectionId, element.open === true])
    );
  }

  function restoreChapterPlannerDisclosureState(snapshot) {
    Object.entries(snapshot || {}).forEach(([sectionId, isOpen]) => {
      const element = document.getElementById(sectionId);
      if (element && element.tagName === 'DETAILS') {
        element.open = isOpen === true;
      }
    });
  }

  function renderChapterPlannerPreservingUi(anchorId = '') {
    const disclosureState = captureChapterPlannerDisclosureState();
    const currentAnchor = anchorId ? document.getElementById(anchorId) : null;
    const anchorTop = currentAnchor ? currentAnchor.getBoundingClientRect().top : null;

    renderChapterPlanner(state.bootstrap);
    if (String((state.plannerViewModes || {}).chapter_planner || 'default') === 'default') {
      restoreChapterPlannerDisclosureState(disclosureState);
    } else {
      applyPlannerViewMode('chapter_planner');
    }

    if (anchorTop !== null && Number.isFinite(anchorTop)) {
      const nextAnchor = document.getElementById(anchorId);
      if (nextAnchor) {
        const nextTop = nextAnchor.getBoundingClientRect().top;
        const delta = nextTop - anchorTop;
        if (Math.abs(delta) > 1) window.scrollBy(0, delta);
      }
    }
  }

  function captureChapterPlannerDraft() {
    if (!mainPanel || state.activeSection !== 'chapter_planner') return;
    const current = (state.chapterPlan || {}).chapter || null;
    if (!current) return;
    if (!document.getElementById('chapter-plan-kickoff')) return;
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
    const povType = String(document.getElementById('chapter-pov-type')?.value || current.pov_type || '');
    const povOmniscientStyle = povType === 'third_person_omniscient'
      ? String(document.getElementById('chapter-pov-omniscient-style')?.value || current.pov_omniscient_style || 'restrained')
      : '';
    state.chapterPlanDraft = {
      key: chapterDraftKey(),
      selected_canon_refs: selectedCanonRefs,
      pov,
      pov_type: povType,
      pov_omniscient_style: povOmniscientStyle,
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
      pov_type: draft.pov_type ?? savedChapter.pov_type ?? '',
      pov_omniscient_style: draft.pov_omniscient_style ?? savedChapter.pov_omniscient_style ?? '',
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
    refreshChapterAvailabilityCountsFromDom();

    if ((recoveredCanon + recoveredEvents) > 0) {
      const recoveryKey = [
        Number(state.chapterPlanBookNumber || 1),
        Number(state.chapterPlanChapterNumber || 1),
        Number(snapshot.source_chapter_plan_revision || 0)
      ].join(':');
      state.chapterRecoveryConsumedKey = recoveryKey;
      document.getElementById('chapter-recovery-note')?.remove();
    }

    const skipped = skippedCanon + skippedEvents;
    setLog(
      `Recovered ${recoveredCanon} Canon selection(s) and ${recoveredEvents} event(s) from the previous compiled Chapter Knowledge Pack.` +
      (skipped ? ` ${skipped} previous item(s) were skipped because they are not available in the current Book Canon.` : '') +
      ' Review the recovered chapter, then Save Chapter Plan. Recompile the Chapter Knowledge Pack afterward.'
    );
  }

  function cacheBookRuntimeContextForBook(status, fallbackBookNumber = 0) {
    const targets = Array.isArray((status || {}).targets) ? status.targets : [];
    const targetBookNumber = Number(
      (status || {}).requested_book_number
      || fallbackBookNumber
      || ((targets[0] || {}).book_number)
      || 0
    );
    if (!targetBookNumber) return;
    state.bookRuntimeContextByBook[String(targetBookNumber)] = status;
  }

  function clearBookRuntimeContextForBook(bookNumber) {
    const key = String(Number(bookNumber || 0));
    if (!key || key === '0') return;
    delete state.bookRuntimeContextByBook[key];
  }

  function bookRuntimeContextForBook(bookNumber) {
    const key = String(Number(bookNumber || 0));
    return state.bookRuntimeContextByBook[key] || state.bookRuntimeContext || {};
  }

  function chapterPlanApprovalBlockerForCurrentBook() {
    const bookNumber = Number(state.chapterPlanBookNumber || 1);
    const status = bookRuntimeContextForBook(bookNumber);
    const target = (status.targets || []).find((item) => Number(item.book_number) === bookNumber) || {};
    return (target.blockers || []).find((item) => String(item.code || '') === 'book_plan_not_approved') || null;
  }

  function currentBookKnowledgeTarget() {
    const bookNumber = Number(state.chapterPlanBookNumber || 1);
    const status = bookRuntimeContextForBook(bookNumber);
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
      pov_type: '',
      pov_omniscient_style: '',
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
    const povType = String(chapter.pov_type || '');
    const povOmniscientStyle = String(chapter.pov_omniscient_style || '');
    const povCharacterSelectionDisabled = !povType || povType === 'third_person_objective';
    const povTypeOptions = [
      ['', 'Not configured'],
      ['first_person', 'First-Person'],
      ['second_person', 'Second-Person'],
      ['third_person_limited', 'Third-Person Limited'],
      ['third_person_omniscient', 'Third-Person Omniscient'],
      ['third_person_objective', 'Third-Person Objective'],
      ['choral_collective', 'Choral / Collective']
    ];
    const omniscientStyleOptions = [
      ['restrained', 'Restrained Omniscient'],
      ['broad', 'Broad Omniscient'],
      ['narrator_led', 'Narrator-Led Omniscient']
    ];
    const povHelpByType = {
      '': 'Choose the narrative perspective first. Character POV checkboxes stay disabled until the selected type uses character interior access.',
      first_person: 'Exactly one selected Character may be POV. That Character narrates in first person; all other characters remain fully interactive but their private interiors stay inaccessible.',
      second_person: 'Exactly one selected Character may be POV. The focal Character is rendered through second-person narration; other characters remain external participants.',
      third_person_limited: 'Exactly one selected Character may be POV. Third-person narration may enter only that Character\'s interior; other characters may speak, act, and interact normally.',
      third_person_omniscient: 'One or more selected Characters may be authorized for interior access. The omniscient style controls how the narrator moves among those interiors; rapid ungrounded head-hopping remains prohibited.',
      third_person_objective: 'No Character POV is used. Narration remains external and may report observable action, dialogue, expression, sound, and environment without direct access to any private interior.',
      choral_collective: 'Select at least two Characters to form the collective voice. Shared knowledge may be narrated collectively; private knowledge belonging to one member must not silently become group knowledge.'
    };
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
    const knowledgePackStatusPending = state.chapterKnowledgePack === null;
    const chapterKnowledgePack = state.chapterKnowledgePack || {};
    const knowledgePackStatus = String(chapterKnowledgePack.status || 'missing');
    const knowledgePackBlockers = chapterKnowledgePack.blockers || [];
    const knowledgePackUnlockEvaluations = chapterKnowledgePack.unlock_evaluations || [];
    const knowledgePackTokens = chapterKnowledgePack.token_accounting || {};
    const knowledgePackFile = chapterKnowledgePack.pack || {};
    const recoverySnapshot = chapterKnowledgePack.recovery_snapshot || {};
    const knowledgePackDisplayStatus = knowledgePackStatusPending
      ? 'Checking…'
      : knowledgePackFile.current === true
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
    const bookKnowledgeIsCurrent = String(bookKnowledgeTarget.status || '') === 'current';
    const bookKnowledgeCompileAllowed = bookKnowledgeTarget.compiler_ready === true && !bookKnowledgeIsCurrent;
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
            <div class="chapter-canon-choice-flags">
              <label class="book-canon-batch-check chapter-batch-row-selector" title="${isSelected ? 'Select this row for Return Selected' : 'Select this row for Add Selected'}"><input type="checkbox" data-chapter-canon-batch-ref="${escapeHtml(recordId)}" ${readOnly || loading ? 'disabled' : ''} /><span>Select</span></label>
              ${isCharacter ? `<label class="chapter-pov-choice" data-chapter-pov-wrap="${escapeHtml(recordId)}" ${isSelected ? '' : 'hidden'} title="${povCharacterSelectionDisabled ? 'Choose an Advanced POV type that uses character interior access first.' : 'Authorize this selected character for the active POV contract.'}"><input type="checkbox" data-chapter-pov-ref="${escapeHtml(recordId)}" ${isPov ? 'checked' : ''} ${readOnly || loading || povCharacterSelectionDisabled ? 'disabled' : ''} /><span>POV</span></label>` : ''}
            </div>
          </div>
          <div class="chapter-row-actions">
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
    const availableCanonItems = catalogItems
      .filter((item) => !selectedIds.has(String(item.record_id || '')) && ['characters','locations'].includes(String(item.record_group_id || '')));
    const availableCanonRows = availableCanonItems
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
      const assignedControls = assigned
        ? `<div class="chapter-event-controls">
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
          </div>`
        : '';
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
          ${assignedControls}
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

    const recoveryKey = [
      Number(state.chapterPlanBookNumber || 1),
      Number(state.chapterPlanChapterNumber || 1),
      Number(recoverySnapshot.source_chapter_plan_revision || 0)
    ].join(':');
    const recoveryCanBeOffered = recoverySnapshot.available === true
      && selectedIds.size === 0
      && assignedEventIds.size === 0
      && state.chapterRecoveryConsumedKey !== recoveryKey
      && (
        Number(recoverySnapshot.selected_canon_count || 0) > 0
        || Number(recoverySnapshot.assigned_event_count || 0) > 0
      );
    const recoveryNotice = recoveryCanBeOffered
      ? `<div id="chapter-recovery-note" class="workspace-warning-note chapter-recovery-note">
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
                title="Authorizes one-time use of this Canon target at the current book/chapter position. It does not change Canon, revise the original progression boundary, or establish continuity."
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

        <details id="chapter-selected-section" class="chapter-planner-card planner-selected-summary" open>
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

        <details id="chapter-pov-settings-section" class="chapter-planner-card chapter-pov-settings-card" open>
          <summary><strong>Advanced POV</strong></summary>
          <p class="placeholder">
            Choose how narration handles consciousness for this chapter. The POV checkboxes beside selected Characters authorize
            Character interior access only; they do not remove other selected Characters from dialogue, action, or interaction.
          </p>
          <div class="chapter-pov-settings-grid">
            <label class="chapter-planner-field">
              POV Type
              <select id="chapter-pov-type" ${readOnly || loading ? 'disabled' : ''}>
                ${povTypeOptions.map(([value, label]) => `
                  <option value="${escapeHtml(value)}" ${povType === value ? 'selected' : ''}>${escapeHtml(label)}</option>
                `).join('')}
              </select>
            </label>
            <label class="chapter-planner-field" id="chapter-pov-omniscient-style-wrap" ${povType === 'third_person_omniscient' ? '' : 'hidden'}>
              Omniscient Interior Style
              <select id="chapter-pov-omniscient-style" ${readOnly || loading ? 'disabled' : ''}>
                ${omniscientStyleOptions.map(([value, label]) => `
                  <option value="${escapeHtml(value)}" ${(povOmniscientStyle || 'restrained') === value ? 'selected' : ''}>${escapeHtml(label)}</option>
                `).join('')}
              </select>
            </label>
          </div>
          <div class="workspace-disabled-note chapter-pov-help">
            ${escapeHtml(povHelpByType[povType] || povHelpByType[''])}
          </div>
        </details>

        ${recoveryNotice}
        <div id="chapter-unsaved-reminder" class="workspace-warning-note" ${chapterDraftDirty ? '' : 'hidden'}>
          <strong>Unsaved Chapter Plan changes.</strong>
          Save Chapter Plan to persist the current chapter selections and event order.
          The existing Chapter Knowledge Pack files are not updated by Save; compile the Chapter Knowledge Pack
          afterward to replace the derived pack.
        </div>

        <details id="chapter-available-canon-section" class="chapter-planner-card planner-selected-summary" open>
          <summary>
            <strong>Available Characters & Locations</strong>
            <span id="chapter-available-canon-count">${escapeHtml(number(availableCanonItems.length))} available for this chapter</span>
          </summary>
          <p class="placeholder">Choose deliberate chapter participants/settings. Mark several rows, then Add Selected, or use the per-item Add to Chapter button. Adding Canon here removes it only from this chapter's available list; it remains available to later chapters and books.</p>
          <div class="chapter-batch-toolbar">
            <button type="button" class="primary-action compact-action" data-chapter-canon-batch-action="add_selected" ${readOnly || loading ? 'disabled' : ''}>Add Selected</button>
          </div>
          <div id="chapter-available-canon-list" class="chapter-planner-list">
            ${availableCanonRows || '<div class="workspace-disabled-note">No additional characters or locations are available from the approved Book Canon.</div>'}
          </div>
        </details>

        <details id="chapter-available-events-section" class="chapter-planner-card planner-selected-summary" open>
          <summary>
            <strong>Available Events</strong>
            <span id="chapter-available-event-count">${escapeHtml(number(availableEvents.length))} available for this chapter</span>
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

        <details id="chapter-event-sequence-section" class="chapter-planner-card planner-selected-summary">
          <summary>
            <strong>Chapter Event Sequence</strong>
          </summary>
          <p class="placeholder">The order below is authoritative planning order for the Chapter Knowledge Pack. Use Earlier/Later to arrange the narrative beats.</p>
          <div class="chapter-batch-toolbar">
            <button type="button" class="secondary-action compact-action" data-chapter-event-batch-action="return_selected" ${readOnly || loading ? 'disabled' : ''}>Return Selected</button>
          </div>
          <div id="chapter-event-sequence-list" class="chapter-event-sequence-list">
            ${eventSequenceRows || '<div class="workspace-disabled-note" id="chapter-event-sequence-empty">No events sequenced yet.</div>'}
          </div>
        </details>

        <details id="chapter-related-directions-section" class="chapter-planner-card">
          <summary><strong>Related Events / Possible Next Directions</strong></summary>
          <p class="placeholder">
            Use this when you want help spotting Canon-supported events that could logically follow,
            react to, or connect with an event anchor. You do not need to add an event to this chapter first:
            choose a <strong>Related-event anchor</strong> at the top of Chapter Planner, or leave that selector
            blank to use events already sequenced in this chapter. If neither exists, Italus has no event anchor
            to evaluate. Suggestions are optional; you decide whether any belong in this chapter.
          </p>
          <div class="chapter-batch-toolbar">
            <button type="button" id="chapter-plan-directions-load" class="secondary-action compact-action" ${readOnly || loading || directionsBusy ? 'disabled' : ''}>${directionsBusy ? 'Looking…' : 'Load Possible Directions'}</button>
          </div>
          <div class="chapter-planner-list">
            ${directionRows || (state.chapterPlanDirectionsQueried
              ? '<div class="workspace-disabled-note"><strong>No related Canon directions were found.</strong> Choose a different event anchor or continue planning without a suggested direction.</div>'
              : '<div class="workspace-disabled-note">Choose an event anchor when useful, then click Load Possible Directions. Nothing is added to the chapter automatically.</div>')}
          </div>
        </details>

        <details id="chapter-generation-kickoff-section" class="chapter-planner-card" open>
          <summary><strong>Generation Kickoff</strong></summary>
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
        </details>

        <details id="chapter-find-more-canon-section" class="chapter-planner-card chapter-plan-amendment-card">
          <summary><strong>Find More Canon</strong></summary>
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
              <button type="button" id="chapter-plan-amend-reset" class="secondary-action compact-action"
                ${readOnly || loading || (!state.chapterPlanAmendQueried && !String(state.chapterPlanAmendQuery || '').trim()) ? 'disabled' : ''}>Reset Search</button>
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
              <button type="button" id="chapter-plan-intent-reset" class="secondary-action compact-action"
                ${state.chapterPlanIntentLoading || (!String(state.chapterPlanIntentQuery || '').trim() && !state.chapterPlanIntentResult) ? 'disabled' : ''}>
                Reset Planner Request
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

        </details>

        <details id="chapter-story-controls-section" class="chapter-planner-card story-control-registry-card">
          <summary><strong>Story Controls</strong></summary>
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
                      <button type="button" class="secondary-action compact-action"
                        data-story-control-delete="${escapeHtml(controlId)}"
                        ${readOnly || loading || state.storyControlSaving || checked ? 'disabled' : ''}
                        title="${checked ? 'Uncheck this Story Control and Save Chapter Plan before deleting it.' : 'Delete this PLANNED Story Control from the registry.'}">
                        ${checked ? 'Detach & Save First' : 'Delete'}
                      </button>
                    </div>
                  `;
                }).join('') || '<div class="workspace-disabled-note">No Story Controls are defined for this chapter.</div>'}
              </div>
            </div>

            <div class="story-control-form">
              <h4>Add Story Control</h4>
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
        </details>

        <details id="chapter-knowledge-pack-section" class="chapter-planner-card chapter-knowledge-pack-card" open>
          <summary><strong>Chapter Knowledge Pack</strong></summary>
          <p class="placeholder">
            <strong>Chapter workflow:</strong>
            <strong class="chapter-workflow-emphasis">Plan the chapter → Save Chapter Plan → Compile Chapter Knowledge Pack.</strong>
            The Book ${number(state.chapterPlanBookNumber)} Knowledge Pack is the shared book foundation used by every chapter in this book.
            Normal chapter edits do not require rebuilding it. Italus will ask you to update the Book Knowledge Pack only when the approved
            Canon for This Book or the Book Plan changes. When you compile this Chapter Knowledge Pack again, it is rebuilt from the current
            saved Chapter Plan, so Canon or events you returned from this chapter are removed from the rebuilt chapter pack.
          </p>

          <div class="workspace-stat-grid">
            ${statCard('Pack Status', knowledgePackDisplayStatus)}
            ${statCard('Mode', labelFor(chapterKnowledgePack.mode || (state.chapterPlanChapterNumber === 1 ? 'chapter_1' : 'continuity_driven')))}
            ${statCard('Compiler', chapterKnowledgePack.compiler_ready === true ? 'Ready' : 'Blocked')}
            ${statCard('Generation', 'Locked')}
          </div>

          ${knowledgePackStatusPending
            ? '<div class="workspace-disabled-note chapter-pack-next-step"><strong>Checking Chapter Knowledge Pack status…</strong> Italus is confirming whether this chapter pack is current, needs recompilation, or has not been compiled yet.</div>'
            : chapterDraftDirty
              ? '<div class="workspace-warning-note chapter-pack-next-step"><strong>Next: Save Chapter Plan.</strong> Your current selections and instructions are still only on screen. Save them first; then compile the Chapter Knowledge Pack.</div>'
              : bookKnowledgeOnlyBlocker
              ? `<div class="workspace-warning-note chapter-pack-next-step"><strong>Book ${number(state.chapterPlanBookNumber)} needs its shared Knowledge Pack updated first.</strong> This happens when Book-level Canon or the Book Plan changed. Click <strong>Update Book ${number(state.chapterPlanBookNumber)} Knowledge Pack</strong> once, then compile the Chapter Knowledge Pack.</div>`
              : knowledgePackBlockerRows
                ? `<div class="workspace-disabled-note"><strong>This chapter is not ready to compile yet.</strong><ul>${knowledgePackBlockerRows}</ul>${bookPlanApprovalBlocker ? `<p><strong>Book ${number(state.chapterPlanBookNumber)} Plan changed after its last approval.</strong> Review and approve the Book Plan before updating its Knowledge Pack.</p>` : ''}</div>`
                : knowledgePackFile.current === true
                  ? '<div class="workspace-success-note chapter-pack-next-step"><strong>Chapter Knowledge Pack is up to date.</strong> No action is needed unless you change and save this Chapter Plan or Italus reports that the Book Knowledge Pack needs updating.</div>'
                  : chapterKnowledgePack.compiler_ready === true
                    ? '<div class="workspace-warning-note chapter-pack-next-step"><strong>Next: Compile Chapter Knowledge Pack.</strong> This rebuilds the chapter pack from the saved Chapter Plan. Canon or events that you returned and saved will not be carried into the rebuilt pack.</div>'
                    : '<div class="workspace-disabled-note chapter-pack-next-step"><strong>Chapter Knowledge Pack cannot be compiled yet.</strong> Follow the planning message above, then return here.</div>'}
          <div class="workspace-action-row compact-action-row knowledge-pack-workflow-actions">
            <button type="button" id="chapter-open-book-plan" class="secondary-action compact-action"
              title="Opens Book ${number(state.chapterPlanBookNumber)} Plan for review. Navigation only; no saved Book or Chapter data is changed."
              ${bookPlanApprovalBlocker ? '' : 'disabled'}>Open Book ${number(state.chapterPlanBookNumber)} Plan</button>
            <button type="button" id="chapter-compile-book-knowledge" class="primary-action compact-action"
              title="Updates Book ${number(state.chapterPlanBookNumber)} Knowledge Pack from the currently approved Book Canon and Book Plan. Existing Book Knowledge Pack files may be rebuilt; Chapter Plan content is not changed."
              ${readOnly || loading || knowledgePackBusy || bookKnowledgeCompileBusy || !bookKnowledgeCompileAllowed ? 'disabled' : ''}>${bookKnowledgeCompileBusy ? 'Updating Book Knowledge Pack…' : bookKnowledgeIsCurrent ? `Book ${number(state.chapterPlanBookNumber)} Knowledge Pack — Up to Date` : `Update Book ${number(state.chapterPlanBookNumber)} Knowledge Pack`}</button>
            <button type="button" id="chapter-open-book-knowledge" class="secondary-action compact-action"
              title="Opens the Book Knowledge Pack view. Navigation only; no saved Book or Chapter data is changed.">View Book Knowledge Pack</button>
          </div>

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
              title="Rebuilds the Chapter Knowledge Pack from the current saved Chapter Plan and current Book Knowledge Pack. Existing Chapter Knowledge Pack files are replaced; it does not generate prose or write Approved Continuity."
              ${readOnly || loading || knowledgePackBusy || chapterKnowledgePack.compiler_ready !== true || knowledgePackFile.current === true ? 'disabled' : ''}>
              ${knowledgePackBusy
                ? 'Compiling…'
                : knowledgePackFile.current === true
                  ? 'Chapter Knowledge Pack — Up to Date'
                  : 'Compile Chapter Knowledge Pack'}
            </button>
          </div>
        </details>

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

    const disclosureDefaultKey = chapterDraftKey();
    if (state.chapterEventSequenceDefaultAppliedKey !== disclosureDefaultKey) {
      const eventSequenceSection = document.getElementById('chapter-event-sequence-section');
      if (eventSequenceSection && eventSequenceSection.tagName === 'DETAILS') {
        eventSequenceSection.open = false;
      }
      state.chapterEventSequenceDefaultAppliedKey = disclosureDefaultKey;
    }

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
    document.getElementById('chapter-plan-amend-reset')?.addEventListener('click', () => {
      state.chapterPlanAmendQuery = '';
      state.chapterPlanAmendCatalog = null;
      state.chapterPlanAmendQueried = false;
      renderChapterPlannerPreservingUi('chapter-find-more-canon-section');
      document.getElementById('chapter-plan-amend-query')?.focus();
      setLog('Wider Canon search reset.');
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
    document.getElementById('chapter-plan-intent-reset')?.addEventListener('click', () => {
      state.chapterPlanIntentQuery = '';
      state.chapterPlanIntentResult = null;
      renderChapterPlannerPreservingUi('chapter-find-more-canon-section');
      document.getElementById('chapter-plan-intent-query')?.focus();
      setLog('Planner Canon request reset.');
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
    mainPanel.querySelectorAll('[data-story-control-delete]').forEach((button) => {
      button.addEventListener('click', () => {
        void deleteStoryControl(String(button.dataset.storyControlDelete || ''));
      });
    });
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

    document.getElementById('chapter-pov-type')?.addEventListener('change', (event) => {
      const nextType = String(event.target.value || '');
      const povBoxes = Array.from(mainPanel.querySelectorAll('[data-chapter-pov-ref]'));
      const checkedBoxes = povBoxes.filter((node) => node.checked);
      const singleCharacterTypes = new Set(['first_person', 'second_person', 'third_person_limited']);
      if (!nextType || nextType === 'third_person_objective') {
        povBoxes.forEach((node) => { node.checked = false; });
      } else if (singleCharacterTypes.has(nextType) && checkedBoxes.length > 1) {
        povBoxes.forEach((node) => { node.checked = false; });
      }
      markChapterPlannerDraftDirty();
      renderChapterPlannerPreservingUi('chapter-pov-settings-section');
    });

    mainPanel.querySelectorAll('[data-chapter-pov-ref]').forEach((node) => {
      node.addEventListener('change', () => {
        const type = String(document.getElementById('chapter-pov-type')?.value || '');
        if (!type || type === 'third_person_objective') {
          node.checked = false;
        } else if (
          node.checked
          && ['first_person', 'second_person', 'third_person_limited'].includes(type)
        ) {
          mainPanel.querySelectorAll('[data-chapter-pov-ref]').forEach((other) => {
            if (other !== node) other.checked = false;
          });
        }
        markChapterPlannerDraftDirty();
      });
    });

    mainPanel.querySelectorAll('#chapter-plan-kickoff, #chapter-plan-objective, #chapter-plan-restrictions, #chapter-pov-omniscient-style, [data-chapter-event-position], [data-chapter-event-role], [data-chapter-event-relationship], [data-chapter-event-anchor], [data-chapter-event-objective], [data-story-control-ref], #story-control-type, #story-control-subject, #story-control-instruction, #story-control-certainty, #story-control-presentation, #story-control-weight').forEach((node) => {
      node.addEventListener(node.tagName === 'TEXTAREA' || node.tagName === 'INPUT' ? 'input' : 'change', () => markChapterPlannerDraftDirty());
      if (node.tagName === 'SELECT' || node.type === 'checkbox') node.addEventListener('change', () => markChapterPlannerDraftDirty());
    });

    applyPlannerViewMode('chapter_planner');

    if (!state.chapterPlan && !state.chapterPlanLoading) {
      void loadChapterPlanner();
    }
  }


  async function loadChapterPlanner() {
    if (!projectId || state.chapterPlanLoading || state.chapterPlanSaving) return;
    const hadLoadedChapter = Boolean((state.chapterPlan || {}).chapter);
    if (hadLoadedChapter) {
      captureChapterPlannerDraft();
    } else {
      clearChapterPlannerDraft();
    }
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
    const bookNumber = Number(state.chapterPlanBookNumber || 1);
    try {
      const [packStatus, bookStatus] = await Promise.all([
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/chapter-knowledge-pack/${state.chapterPlanBookNumber}/${state.chapterPlanChapterNumber}/status`),
        apiFetch(`/api/project/${encodeURIComponent(projectId)}/runtime-context/books/${encodeURIComponent(bookNumber)}/readiness-fast`)
      ]);
      if (requestToken !== state.chapterKnowledgePackRequestToken) return;
      state.chapterKnowledgePack = packStatus;
      cacheBookRuntimeContextForBook(bookStatus, bookNumber);
    } catch (error) {
      if (requestToken !== state.chapterKnowledgePackRequestToken) return;
      state.chapterKnowledgePack = {
        status: 'blocked',
        compiler_ready: false,
        blockers: [{ code: 'status_load_failed', message: error.message }],
        unlock_evaluations: []
      };
      setLog(`Chapter Knowledge Pack status failed: ${error.message}`);
    } finally {
      if (!keepLoading && state.activeSection === 'chapter_planner' && requestToken === state.chapterKnowledgePackRequestToken) {
        const disclosureState = captureChapterPlannerDisclosureState();
        const anchor = document.getElementById('chapter-plan-save');
        const anchorTop = anchor ? anchor.getBoundingClientRect().top : null;
        renderChapterPlanner(state.bootstrap);
        restoreChapterPlannerDisclosureState(disclosureState);
        if (anchorTop !== null) {
          const nextAnchor = document.getElementById('chapter-plan-save');
          if (nextAnchor) {
            window.scrollBy(0, nextAnchor.getBoundingClientRect().top - anchorTop);
          }
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
      const refreshedBookStatus = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/books/status?book_number=${encodeURIComponent(bookNumber)}`
      );
      cacheBookRuntimeContextForBook(refreshedBookStatus, bookNumber);
      state.dashboardBookKnowledgeRefreshNeeded = true;
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
    if (state.activeSection === 'chapter_planner') {
      renderChapterPlannerPreservingUi('chapter-knowledge-pack-section');
    }
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
      if (state.activeSection === 'chapter_planner') {
        renderChapterPlannerPreservingUi('chapter-knowledge-pack-section');
      }
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
    if (!keepLoading && state.activeSection === 'chapter_planner') {
      renderChapterPlanner(state.bootstrap);
    }
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
    if (state.activeSection === 'chapter_planner') renderChapterPlannerPreservingUi('chapter-related-directions-section');
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
      if (state.activeSection === 'chapter_planner') renderChapterPlannerPreservingUi('chapter-related-directions-section');
    }
  }


  async function loadChapterAmendCatalog(keepLoading = false) {
    if (!projectId || state.chapterPlanAmendLoading) return;
    captureChapterPlannerDraft();
    state.chapterPlanAmendLoading = true;
    state.chapterPlanAmendQueried = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlannerPreservingUi('chapter-find-more-canon-section');
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
      if (state.activeSection === 'chapter_planner') renderChapterPlannerPreservingUi('chapter-find-more-canon-section');
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
      if (state.activeSection === 'chapter_planner') renderChapterPlannerPreservingUi('chapter-find-more-canon-section');
      return;
    }

    const chapter = (state.chapterPlan || {}).chapter || {};
    captureChapterPlannerDraft();
    state.chapterPlanIntentLoading = true;
    if (state.activeSection === 'chapter_planner') renderChapterPlannerPreservingUi('chapter-find-more-canon-section');
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
      if (state.activeSection === 'chapter_planner') renderChapterPlannerPreservingUi('chapter-find-more-canon-section');
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
    renderChapterPlannerPreservingUi('chapter-story-controls-section');
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
      if (state.activeSection === 'chapter_planner') renderChapterPlannerPreservingUi('chapter-story-controls-section');
    }
  }


  async function deleteStoryControl(controlId) {
    if (!projectId || !controlId || state.storyControlSaving || state.bootstrap.read_only === true) return;

    const control = ((state.storyControls || {}).controls || [])
      .find((item) => String(item.control_id || '') === String(controlId));
    if (!control) {
      setLog('Story Control no longer exists in the current registry.');
      return;
    }

    captureChapterPlannerDraft();
    const draft = (state.chapterPlanDraft && state.chapterPlanDraft.key === chapterDraftKey())
      ? state.chapterPlanDraft
      : {};
    if ((draft.story_control_refs || []).map((value) => String(value || '')).includes(String(controlId))) {
      setLog('Uncheck this Story Control and Save Chapter Plan before deleting it.');
      return;
    }

    const confirmed = window.confirm(
      `Delete this PLANNED Story Control?\n\n${String(control.instruction || labelFor(control.control_type || 'Story Control'))}\n\n` +
      'This removes the Story Control from the project registry. It does not erase Canon or manuscript prose. ' +
      'Because the control must already be detached from every saved Chapter Plan, compile any Chapter Knowledge Pack that is now outdated before generation. ' +
      'After that rebuild, this Story Control will no longer be included as an instruction in the Chapter Knowledge Pack sent to the LLM. ' +
      'Italus will block deletion if any saved Chapter Plan still references this control.'
    );
    if (!confirmed) return;

    state.storyControlSaving = true;
    renderChapterPlannerPreservingUi('chapter-story-controls-section');
    try {
      await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/story-controls/${encodeURIComponent(controlId)}`,
        { method: 'DELETE', headers: { Accept: 'application/json' } }
      );
      state.storyControls = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/story-controls?book_number=${state.chapterPlanBookNumber}&chapter_number=${state.chapterPlanChapterNumber}`
      );
      setLog('Story Control deleted from the project registry.');
    } catch (error) {
      setLog(`Story Control delete blocked: ${error.message}`);
    } finally {
      state.storyControlSaving = false;
      if (state.activeSection === 'chapter_planner') {
        renderChapterPlannerPreservingUi('chapter-story-controls-section');
      }
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

    const disclosureState = captureChapterPlannerDisclosureState();
    const saveAnchor = document.getElementById('chapter-plan-save');
    const saveAnchorTop = saveAnchor ? saveAnchor.getBoundingClientRect().top : null;

    state.chapterPlanSaving = true;
    if (mainPanel && state.activeSection === 'chapter_planner') {
      mainPanel.setAttribute('aria-busy', 'true');
      mainPanel.querySelectorAll('button, input, select, textarea').forEach((control) => {
        control.disabled = true;
      });
      const saveButton = document.getElementById('chapter-plan-save');
      if (saveButton) saveButton.textContent = 'Saving…';
    }

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
            pov_type: String(draft.pov_type || '').trim(),
            pov_omniscient_style: String(draft.pov_omniscient_style || '').trim(),
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

      // Saving persists the Chapter Plan only. Refresh readiness without entering the compiler busy state.
      await loadChapterKnowledgePackStatus(true);
    } catch (error) {
      setLog(`Chapter Plan save failed: ${error.message}`);
    } finally {
      state.chapterPlanSaving = false;
      if (state.activeSection === 'chapter_planner') {
        renderChapterPlanner(state.bootstrap);
        restoreChapterPlannerDisclosureState(disclosureState);
        if (saveAnchorTop !== null) {
          const nextSaveAnchor = document.getElementById('chapter-plan-save');
          if (nextSaveAnchor) {
            window.scrollBy(0, nextSaveAnchor.getBoundingClientRect().top - saveAnchorTop);
          }
        }
      }
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
            <label class="book-canon-batch-check" title="Select this Canon row for a batch action">
              <input type="checkbox" data-book-canon-select="1" data-category-key="${escapeHtml(categoryKey)}"
                data-record-id="${escapeHtml(recordId)}" data-selected="${selected ? 'true' : 'false'}"
                data-addable="${addable ? 'true' : 'false'}" data-recommended="${recommended ? 'true' : 'false'}"
                ${disabled ? 'disabled' : ''} />
              <span>Select</span>
            </label>
            <button type="button" class="${selected ? 'secondary-action' : 'primary-action'} compact-action book-canon-row-action-button"
              data-book-canon-action="${selected ? 'remove' : 'add'}" data-record-id="${escapeHtml(recordId)}" ${disabled ? 'disabled' : ''}>${action}</button>
          </div>
        </div>`;
      }).join('');

      const selectedInCategory = (category.items || []).filter((item) => selectedIds.has(String(item.record_id || '')) || item.selected === true).length;
      const recommendedInCategory = Number(category.recommended_count || 0);
      const availableInCategory = Number(category.available_count || 0);
      return `<details class="book-canon-category">
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
        <label class="book-canon-batch-check" title="Select this Canon row for a batch return">
          <input type="checkbox" data-book-canon-selected-summary="1" data-record-id="${escapeHtml(item.record_id || '')}" ${mutationEnabled ? '' : 'disabled'} />
          <span>Select</span>
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
          <label class="planner-toggle book-canon-future-toggle" title="Include future Canon records in the visible browser">
            <input id="book-plan-canon-show-future" type="checkbox" ${state.bookScopeIncludeFuture ? 'checked' : ''}/>
            <span>Show Future Canon</span>
          </label>
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

      <section class="workspace-detail-card planner-book-selector">
        <select id="book-plan-book-number" aria-label="Choose book to configure">${Array.from({length: expectedBookCount}, (_, index) => index + 1).map((value) => `<option value="${value}" ${value === state.bookPlanBookNumber ? 'selected' : ''}>Book ${value}</option>`).join('')}</select>
      </section>

      ${renderEmbeddedBookCanon(bootstrap, state.bookPlanBookNumber, scopeBook, catalog)}

      <form id="book-plan-form" class="book-plan-form">${renderBookPlanCard(book, expectedBookCount, readOnly, scopeBook, suggestion)}</form>

      <section class="workspace-detail-card"><h3>Book ${bookNumber} check</h3>${bookValidation.complete && scopeApproved ? '<div class="workspace-success-note">Book ' + bookNumber + ' is complete and Canon for This Book is approved/current.</div>' : (issueRows ? table(['Area','Code','Issue'], issueRows) : '<div class="workspace-disabled-note">Complete the Book Plan and approve Canon for This Book before approving the book.</div>')}</section>
      <section class="workspace-detail-card"><h3>Planning readiness</h3><div class="workspace-lock-grid">${lockCard('Canon for This Book', String(scopeBook.approval_status || 'not_ready').replace(/_/g,' '))}${lockCard(`Book ${bookNumber} Plan Approval`, approvalStatus.replace(/_/g,' '))}${lockCard('Book Knowledge Pack', approvalFresh && scopeApproved ? 'Planning approved' : 'Waiting for approvals')}${lockCard('Generation','Locked')}</div></section>
      <div class="workspace-action-row">
        <button type="button" id="book-plan-refresh" class="secondary-action"
          title="Reloads the saved Book Plan and Canon state from project storage. Unsaved on-screen Book Plan edits are discarded; saved approvals and Knowledge Packs are not changed."
          ${loading || saving ? 'disabled' : ''}>${loading ? 'Loading…' : 'Reload Plan'}</button>
        <button type="button" id="book-plan-save" class="primary-action"
          title="Saves the current Book Plan fields to project storage. If Book ${bookNumber} content changed, its existing Plan approval becomes outdated and its Book Knowledge Pack may need rebuilding."
          ${readOnly || loading || saving || approvalLoading ? 'disabled' : ''}>${saving ? 'Saving…' : 'Save Book Plan'}</button>
        <button type="button" id="book-plan-approve" class="primary-action"
          title="Approves the current saved Book ${bookNumber} Plan revision. This makes the Plan eligible for Book Knowledge Pack readiness; it does not compile a pack or generate prose."
          ${canApprove ? '' : 'disabled'}>${approvalLoading ? 'Updating…' : `Approve Book ${bookNumber} Plan`}</button>
        <button type="button" id="book-plan-revoke" class="secondary-action"
          title="Revokes Book ${bookNumber} Plan approval without changing Plan content. Book Knowledge Pack and generation readiness can become blocked until the Plan is approved again."
          ${canRevoke ? '' : 'disabled'}>${`Revoke Book ${bookNumber} Approval`}</button>
      </div>
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

    applyPlannerViewMode('book_plan');

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
    const suggestionUnavailable = !suggested;
    return `<label class="book-plan-field book-plan-time-span-field">
      <span>Time span *</span>
      <input type="text" data-book-plan-field="time_span" data-book-number="${bookNumber}" value="${escapeHtml(effective)}" required ${readonlyAttribute} />
      ${suggested
        ? `<small>Suggested from selected dated Book Canon events: <strong>${escapeHtml(suggested)}</strong>. You may edit this value.</small>`
        : '<small><strong>Use Canon Suggestion activates after at least one dated Event is selected in Canon for This Book.</strong> Typing a Time span manually does not activate this button; manual entry is already valid.</small>'}
      <button type="button" class="secondary-action compact-action" id="book-plan-use-time-suggestion"
        ${readonlyAttribute || suggestionUnavailable ? 'disabled' : ''}
        ${suggestionUnavailable ? 'title="Select at least one dated Event in Canon for This Book to activate this suggestion."' : 'title="Apply the dated Canon range to Time span."'}>Use Canon Suggestion</button>
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
        const bookStatus = await apiFetch(`/api/project/${encodeURIComponent(projectId)}/runtime-context/books/status?book_number=${encodeURIComponent(bookNumber)}`);
        cacheBookRuntimeContextForBook(bookStatus, bookNumber);
      } catch (_error) {
        clearBookRuntimeContextForBook(bookNumber);
      }
      state.dashboardBookKnowledgeRefreshNeeded = true;
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
      clearBookRuntimeContextForBook(bookNumber);
      state.dashboardBookKnowledgeRefreshNeeded = true;
      setLog(`Book ${bookNumber} Plan approval revoked. Downstream generation remains locked.`);
    } catch (error) {
      setLog(`Book Plan approval revocation failed: ${error.message}`);
    } finally {
      state.bookPlanApprovalLoading = false;
      renderBookPlan(state.bootstrap);
    }
  }

  function renderBookRuntimeContext(bootstrap) {
    setHeading('Book Knowledge');

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

    const libraryBooks = ((((state.authorLibrary || {}).universal || {}).books || {}).items || []);
    const libraryChapters = ((((state.authorLibrary || {}).universal || {}).chapters || {}).items || []);

    const cards = targets.map((target) => {
      const bookNumber = Number(target.book_number || 0);
      const libraryBook = libraryBooks.find((book) => Number(book.book_number || 0) === bookNumber) || {};
      const plannedChapters = Number(libraryBook.planned_chapters || 0);
      const targetChapters = Number(libraryBook.target_chapters || (bootstrap.manifest || {}).chapters_per_book || 0);
      const activeChapter = Number(libraryBook.active_chapter || 0);
      const chapterRecord = libraryChapters.find((chapter) =>
        Number(chapter.book_number || 0) === bookNumber
        && Number(chapter.chapter_number || 0) === activeChapter
      ) || {};
      const chapterStatus = activeChapter
        ? chapterPlanningStatusLabel(chapterRecord.status || 'draft')
        : 'NOT YET PLANNED';
      const title = String(libraryBook.title || `Book ${bookNumber}`);
      const knowledgeStatus = String(target.status || (target.exists ? 'current' : 'missing')).toUpperCase();
      const targetBlockers = Array.isArray(target.blockers) ? target.blockers : [];

      return `
        <article class="workspace-book-knowledge-card">
          <header>
            <div>
              <span class="workspace-author-eyebrow">BOOK ${number(bookNumber)}</span>
              <h3>${escapeHtml(title)}</h3>
            </div>
            <div>${statusBadge(`KNOWLEDGE ${knowledgeStatus}`)}</div>
          </header>

          <div class="workspace-author-metric-list">
            <div><strong>Planning Coverage</strong><span>${state.authorLibrary ? `${number(plannedChapters)} / ${number(targetChapters)} chapters planned` : 'Loading planning coverage…'}</span></div>
            <div><strong>Author-Accepted Chapters</strong><span>Not tracked yet</span></div>
            <div><strong>Chapter in Progress</strong><span>${activeChapter ? `Chapter ${number(activeChapter)} — ${escapeHtml(chapterStatus)}` : 'Not yet planned'}</span></div>
            <div><strong>Selected Canon</strong><span>${number(target.selected_record_count || 0)} items</span></div>
            <div><strong>Estimated Context</strong><span>${number(target.estimated_tokens || 0)} tokens</span></div>
          </div>

          ${targetBlockers.length
            ? `<div class="workspace-author-warning"><strong>Needs attention</strong>${targetBlockers.map((item) => `<span>${escapeHtml(item.message || item.code || 'Compilation is blocked.')}</span>`).join('')}</div>`
            : ''}

          <details class="workspace-technical-details">
            <summary>Technical Details</summary>
            <dl class="workspace-definition-grid workspace-definition-grid--compact">
              ${definition('Artifact state', knowledgeStatus)}
              ${definition('Compiler readiness', target.compiler_ready === true ? 'Ready' : 'Waiting')}
              ${definition('Artifact path', target.project_relative_path || '—')}
              ${definition('SHA-256', target.sha256 ? `${String(target.sha256).slice(0, 20)}…` : '—')}
              ${definition('Dependency SHA-256', target.dependency_set_sha256 ? `${String(target.dependency_set_sha256).slice(0, 20)}…` : '—')}
            </dl>
          </details>
        </article>
      `;
    }).join('') || '<div class="workspace-disabled-note">No Book Knowledge targets are available yet.</div>';

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-book-knowledge-author-phase-a">
        <section class="workspace-author-hero">
          <span class="workspace-author-eyebrow">BOOK-SCOPED KNOWLEDGE</span>
          <h3>Book Knowledge</h3>
          <p>
            Each card shows the knowledge prepared for one book: its planning coverage,
            current planning position, selected Canon, and estimated context size.
          </p>
          <p class="workspace-author-term-note">
            <strong>Author-Accepted Chapters</strong> will mean chapters whose manuscript prose the author has accepted.
            <strong>Continuity commit</strong> is a separate internal synchronization checkpoint and is intentionally hidden
            unless it falls behind accepted manuscript state.
          </p>
        </section>

        <div class="workspace-book-knowledge-list">${cards}</div>

        <div class="workspace-action-row workspace-author-gold-actions">
          <button type="button" id="book-runtime-context-refresh" class="secondary-action"
            ${loading ? 'disabled' : ''}>${loading ? 'Refreshing…' : 'Refresh'}</button>
          <button type="button" id="book-runtime-context-generate" class="primary-action"
            ${compileEnabled ? '' : 'disabled'}
            aria-disabled="${compileEnabled ? 'false' : 'true'}">
            ${loading ? 'Working…' : 'Update Ready Book Knowledge'}
          </button>
        </div>

        ${blockers.length ? `
          <details class="workspace-technical-details">
            <summary>Compilation Details</summary>
            ${table(
              ['Scope', 'Code', 'Reason'],
              blockers.map((blocker) => `
                <tr>
                  <td>${escapeHtml(blocker.book_number ? `Book ${blocker.book_number}` : 'Project')}</td>
                  <td>${escapeHtml(blocker.code || 'blocked')}</td>
                  <td>${escapeHtml(blocker.message || 'Compilation is blocked.')}</td>
                </tr>
              `).join('')
            )}
          </details>
        ` : ''}

        <details class="workspace-technical-details">
          <summary>System Details</summary>
          <dl class="workspace-definition-grid workspace-definition-grid--compact">
            ${definition('Book Plan schema', plan.schema_version || '—')}
            ${definition('Completed Book Plans', number(plan.complete_book_count || 0))}
            ${definition('Ready Book Knowledge', readyCount)}
            ${definition('Approved Book Canons', number(scope.approved_current_count || 0))}
            ${definition('Author Canon', authorCanon.exists ? 'Present' : 'Missing')}
            ${definition('Canon Index', labelFor(canonIndex.state || 'unknown'))}
          </dl>
          <div class="workspace-lock-grid">
            ${lockCard('Compilation', compilerReady ? 'Ready' : 'Blocked')}
            ${lockCard('Full Project Context Append', 'Disabled')}
            ${lockCard('Prompt Builder', locks.prompt_builder_called ? 'Called' : 'Not called')}
            ${lockCard('Provider', locks.provider_called ? 'Called' : 'Blocked')}
            ${lockCard('Approved Continuity Writes', locks.approved_continuity_written ? 'Written' : 'Blocked')}
            ${lockCard('Generation Unlock', locks.generation_unlocked ? 'Unlocked' : 'Locked')}
          </div>
        </details>

        <div class="workspace-disabled-note">
          ${escapeHtml(bookContext.message || 'Book Knowledge status is unavailable.')}
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

    if (!state.authorLibrary && !state.authorLibraryLoading) {
      void ensureAuthorLibrary()
        .then(() => {
          if (state.activeSection === 'book_runtime_context') renderBookRuntimeContext(bootstrap);
        })
        .catch((error) => setLog(`Book Knowledge planning coverage unavailable: ${error.message}`));
    }
  }

  async function loadBookRuntimeContextStatus() {
    if (!projectId || state.bookRuntimeContextLoading) return;

    state.bookRuntimeContextLoading = true;
    state.dashboardBookKnowledgeRefreshNeeded = false;
    if (state.activeSection === 'book_runtime_context') {
      renderBookRuntimeContext(state.bootstrap);
    }

    try {
      const status = await apiFetch(
        `/api/project/${encodeURIComponent(projectId)}/runtime-context/books/status`
      );
      state.bookRuntimeContext = status;
      state.bookRuntimeContextByBook = {};
      setLog(`Book Knowledge Pack status: ${status.status || 'unknown'}; ${status.ready_count || 0} target(s) ready.`);
    } catch (error) {
      state.bookRuntimeContextByBook = {};
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
      } else if (state.activeSection === 'dashboard') {
        const bootstrap = state.bootstrap || {};
        renderDashboard(
          bootstrap.manifest || {},
          bootstrap.budget_plan || {},
          bootstrap.wizard_state || {},
          bootstrap
        );
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
      state.bookRuntimeContextByBook = {};
      state.dashboardBookKnowledgeRefreshNeeded = false;
      state.chapterKnowledgePack = null;
    } catch (error) {
      state.bookRuntimeContextByBook = {};
      state.dashboardBookKnowledgeRefreshNeeded = false;
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
    setHeading('Writing Memory');

    const projectIdValue = (manifest && manifest.project_id) || projectId || '<project_id>';
    const projectNameValue = (manifest && manifest.project_name) || projectIdValue;
    const runtimeStorage = (bootstrap && bootstrap.runtime_storage) || {};
    const storageRoot = runtimeStorage.runtime_root || (context && context.runtime_data_dir) || `data/projects/${projectIdValue}/runtime/`;
    const runtimeStatus = runtimeStorage.status || 'not_initialized';
    const runtimeFiles = Array.isArray(runtimeStorage.files) && runtimeStorage.files.length
      ? runtimeStorage.files
      : [
          { label: 'Books', role: 'author_facing', relative_path: `${storageRoot}books.json`, description: 'Project-local generated book-level manuscript records.', status: 'not_created' },
          { label: 'Chapters', role: 'author_facing', relative_path: `${storageRoot}chapters.json`, description: 'Project-local generated chapter records.', status: 'not_created' },
          { label: 'Scenes', role: 'author_facing', relative_path: `${storageRoot}scenes.json`, description: 'Project-local generated scene text and scene metadata.', status: 'not_created' },
          { label: 'Writing Session', role: 'author_facing', relative_path: `${storageRoot}session_state.json`, description: 'Project-local resumable writing session state.', status: 'not_created' },
          { label: 'Continuity Coverage', role: 'author_facing', relative_path: `${storageRoot}coverage_map.json`, description: 'Project-local continuity and coverage tracking.', status: 'not_created' },
          { label: 'Book State', role: 'internal_continuity', relative_path: `${storageRoot}book_state.json`, description: 'Internal project-local book generation state.', status: 'not_created' },
          { label: 'Chapter Continuity Digests', role: 'internal_continuity', relative_path: `${storageRoot}chapter_continuity_digests.json`, description: 'Internal project-local continuity digests used by later runtime migration stages.', status: 'not_created' }
        ];

    const writingMemoryConcepts = [
      {
        label: 'Manuscript Progress',
        description: 'Keeps track of the books, chapters, and scenes created for this project and where the manuscript currently stands.'
      },
      {
        label: 'Resume Your Work',
        description: 'Remembers where you stopped so you can return to the project and continue from the appropriate book, chapter, or writing step.'
      },
      {
        label: 'Story Continuity',
        description: 'Keeps track of important story developments already established in the manuscript so later writing can remain consistent with what came before.'
      }
    ];

    mainPanel.innerHTML = `
      <div class="workspace-content workspace-writing-memory-author-phase-a">
        <section class="workspace-author-hero">
          <h3 class="workspace-author-hero-title">PROJECT WRITING STATE</h3>
          <p>
            Writing Memory helps Italus remember your manuscript, where you left off, and what has already
            happened in the story. It allows you to return to your project and continue writing without losing
            the important story details established along the way.
          </p>
        </section>

        <section class="workspace-author-summary-card">
          <div class="workspace-author-metric-list">
            <div><strong>Project</strong><span>${escapeHtml(projectNameValue)}</span></div>
            <div><strong>Memory Status</strong><span>${runtimeStatus === 'initialized' ? 'Ready' : 'Not Ready Yet'}</span></div>
            <div><strong>Writing Availability</strong><span>${bootstrap && bootstrap.generation_enabled ? 'Available' : 'Not Available Yet'}</span></div>
          </div>
        </section>

        <section class="workspace-author-summary-card">
          <h3>What Italus Remembers</h3>
          <div class="workspace-writing-memory-concept-grid">
            ${writingMemoryConcepts.map((item) => `
              <article class="workspace-writing-memory-concept-card">
                <h4>${escapeHtml(item.label)}</h4>
                <p>${escapeHtml(item.description)}</p>
              </article>
            `).join('')}
          </div>
        </section>

        <details class="workspace-technical-details">
          <summary>Technical Details</summary>
          <dl class="workspace-definition-list">
            ${definition('Project ID', projectIdValue)}
            ${definition('Runtime Folder', storageRoot)}
            ${definition('Runtime Folder Exists', runtimeStorage.runtime_root_exists ? 'Yes' : 'No')}
            ${definition('Runtime File Contract', runtimeStorage.file_contract_version || 'stage9_seven_file_contract')}
            ${definition('Required Runtime Files', runtimeStorage.required_file_count || runtimeFiles.length)}
            ${definition('Current Storage Mode', context && context.storage_mode ? context.storage_mode : 'legacy root data')}
            ${definition('Runtime Storage', runtimeStatus === 'initialized' ? 'Prepared automatically' : 'Not prepared')}
          </dl>
          <div class="workspace-runtime-storage-grid">
            ${runtimeStorageFolderCard(storageRoot, runtimeStorage).map(runtimeStorageStatusCard).concat(runtimeFiles.map(runtimeStorageStatusCard)).join('')}
          </div>
          <div class="workspace-lock-grid">
            ${lockCard('Runtime Containers', runtimeStatus === 'initialized' ? 'Prepared' : 'Not prepared')}
            ${lockCard('Copy Legacy Data', 'Blocked')}
            ${lockCard('Save Generated Scenes', 'Blocked')}
            ${lockCard('Enable Generation', 'Blocked')}
          </div>
        </details>
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
