(function () {
  'use strict';

  const API_ROOT = '/api/provider';
  const PROVIDER_SETTINGS_ID = 'provider-settings-modal';

  function createElement(tagName, options) {
    const element = document.createElement(tagName);
    const settings = options || {};
    if (settings.className) element.className = settings.className;
    if (settings.text !== undefined) element.textContent = String(settings.text);
    if (settings.type) element.type = settings.type;
    if (settings.name) element.name = settings.name;
    if (settings.id) element.id = settings.id;
    return element;
  }

  function appendLabelField(parent, labelText, control, helpText) {
    const label = createElement('label', { className: 'provider-settings-field' });
    const captionRow = createElement('span', { className: 'provider-settings-field-caption' });
    const caption = createElement('span', {
      className: 'provider-settings-field-label',
      text: labelText
    });
    captionRow.appendChild(caption);

    if (helpText) {
      const help = createElement('span', {
        className: 'provider-settings-help',
        text: '?'
      });
      help.title = String(helpText);
      help.setAttribute('aria-label', String(helpText));
      help.tabIndex = 0;
      captionRow.appendChild(help);
    }

    label.append(captionRow, control);
    parent.appendChild(label);
    return control;
  }

  function setStatus(node, message, tone) {
    node.textContent = String(message || '');
    node.dataset.tone = tone || 'neutral';
  }

  function validationFieldLabel(value) {
    const field = String(value || '');
    const labels = {
      provider_id: 'Provider',
      model_id: 'Model ID',
      api_key: 'API Key',
      service_tier: 'Service Tier',
      inference_scope: 'Inference Scope',
      freshness_threshold_days: 'Pricing Review Warning After (days)'
    };
    return labels[field] || field.replace(/_/g, ' ');
  }

  function apiErrorDetailText(detail, fallback) {
    if (typeof detail === 'string' && detail.trim()) return detail.trim();

    if (Array.isArray(detail)) {
      const messages = detail
        .map((item) => {
          if (typeof item === 'string') return item.trim();
          if (!item || typeof item !== 'object') return '';

          const location = Array.isArray(item.loc)
            ? item.loc.filter((part) => String(part) !== 'body')
            : [];
          const field = location.length
            ? validationFieldLabel(location[location.length - 1])
            : '';
          const message = String(item.msg || item.message || 'Invalid value').trim();

          return field ? `${field}: ${message}` : message;
        })
        .filter(Boolean);

      if (messages.length) return messages.join('; ');
    }

    if (detail && typeof detail === 'object') {
      if (detail.message) return String(detail.message);
      try {
        return JSON.stringify(detail);
      } catch (_) {
        return fallback;
      }
    }

    return fallback;
  }

  async function apiJson(path, options) {
    const response = await fetch(path, options);
    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = null;
    }

    if (!response.ok) {
      const fallback = `Request failed (${response.status})`;
      const detail = payload && payload.detail !== undefined
        ? payload.detail
        : fallback;
      const error = new Error(apiErrorDetailText(detail, fallback));
      error.status = response.status;
      throw error;
    }
    return payload || {};
  }

  function providerApiErrorMessage(error) {
    const status = Number(error && error.status);
    if (status === 404) {
      return 'Provider API is not loaded in the running Italus backend. Fully restart the backend after Primary 33.1, then reopen Provider Settings.';
    }
    return error && error.message
      ? String(error.message)
      : 'Provider settings request failed.';
  }

  function safeHttpUrl(value) {
    try {
      const parsed = new URL(String(value || ''), window.location.origin);
      if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return parsed.href;
    } catch (_) {
      return '';
    }
    return '';
  }

  function findProviderMenuPlaceholder() {
    const candidates = document.querySelectorAll('.dropdown-menu .disabled-item');
    for (const candidate of candidates) {
      if (String(candidate.textContent || '').trim() === 'Provider Settings') {
        return candidate;
      }
    }
    return null;
  }

  function closeProviderSettings(modal, layer) {
    modal.hidden = true;
    layer.setAttribute('aria-hidden', 'true');
  }

  function openProviderSettings(modal, layer) {
    if (window.ItalusProjectLifecycle && typeof window.ItalusProjectLifecycle.closeAllModals === 'function') {
      window.ItalusProjectLifecycle.closeAllModals();
    }
    layer.setAttribute('aria-hidden', 'false');
    modal.hidden = false;
  }

  function makeInput(type, name, value) {
    const input = createElement('input', { type, name });
    if (value !== undefined && value !== null) input.value = String(value);
    return input;
  }

  function makeDateTimePicker(name, placeholder) {
    const root = createElement('div', { className: 'provider-datetime-field' });
    const input = makeInput('hidden', name, '');
    const display = makeInput('text', `${name}_display`, '');
    display.readOnly = true;
    display.placeholder = placeholder || 'Select date and time';
    display.setAttribute('aria-haspopup', 'dialog');

    const button = createElement('button', {
      className: 'provider-datetime-button',
      type: 'button',
      text: '📅'
    });
    button.title = 'Choose date and time';
    button.setAttribute('aria-label', 'Choose date and time');

    root.append(input, display, button);
    return { root, input, display, button };
  }

  function makeSelect(name) {
    return createElement('select', { name });
  }

  function addOption(select, value, label, disabled) {
    const option = createElement('option', { text: label });
    option.value = String(value);
    option.disabled = Boolean(disabled);
    select.appendChild(option);
    return option;
  }

  function catalogProvider(ui, providerId) {
    const provider = String(providerId || '').trim().toLowerCase();
    return ui.catalogProviders instanceof Map
      ? (ui.catalogProviders.get(provider) || null)
      : null;
  }

  function catalogModels(ui, providerId) {
    const provider = catalogProvider(ui, providerId);
    return provider && Array.isArray(provider.models) ? provider.models : [];
  }

  function catalogModel(ui, providerId, modelId) {
    const wanted = String(modelId || '').trim();
    return catalogModels(ui, providerId).find((model) => {
      return String(model.model_id || '') === wanted;
    }) || null;
  }

  function selectedCatalogModel(ui) {
    return catalogModel(
      ui,
      ui.providerSelect.value,
      ui.modelSelect.value
    );
  }

  function updateModelNote(ui) {
    const provider = String(ui.providerSelect.value || '').trim();
    const modelId = String(ui.modelSelect.value || '').trim();
    if (!provider || !modelId) {
      ui.modelNote.textContent =
        'Choose a curated direct-provider model. Account-specific availability is checked by project provider setup validation before generation is enabled.';
      return;
    }

    const model = catalogModel(ui, provider, modelId);
    if (!model) {
      ui.modelNote.textContent =
        `Saved model ID "${modelId}" is not in the accepted direct-provider catalog. ` +
        'It remains visible for migration safety but cannot be saved or newly bound to a project.';
      return;
    }

    const tier = String(model.catalog_tier || '').trim();
    const tierText = tier ? ` (${tier})` : '';
    ui.modelNote.textContent =
      `${model.display_name || modelId}${tierText} — exact provider API model ID: ${modelId}. ` +
      'Provider execution remains locked.';
  }

  function populateModelSelect(ui, providerId, selectedModelId) {
    const provider = String(providerId || '').trim();
    const selected = String(selectedModelId || '').trim();
    ui.modelSelect.replaceChildren();
    addOption(ui.modelSelect, '', 'Select model', false);

    const models = catalogModels(ui, provider);
    for (const model of models) {
      if (!model || !model.enabled || String(model.status || '') !== 'production') continue;
      const tier = String(model.catalog_tier || '').trim();
      const suffix = tier ? ` — ${tier}` : '';
      const option = addOption(
        ui.modelSelect,
        model.model_id,
        `${model.display_name || model.model_id}${suffix}`,
        false
      );
      option.title = `Exact provider API model ID: ${model.model_id}`;
    }

    if (selected) {
      const accepted = models.some((model) => String(model.model_id || '') === selected);
      if (!accepted) {
        const legacy = addOption(
          ui.modelSelect,
          selected,
          `Saved unvalidated model — ${selected}`,
          true
        );
        legacy.title = 'Legacy model ID retained for migration safety; choose an accepted model before saving.';
      }
      ui.modelSelect.value = selected;
    } else {
      const defaultModel = models.find((model) => Boolean(model.is_default) && Boolean(model.enabled));
      if (defaultModel) ui.modelSelect.value = String(defaultModel.model_id || '');
    }

    updateModelNote(ui);
  }

  function selectedPricingCatalogModel(ui) {
    return catalogModel(
      ui,
      ui.providerSelect.value,
      ui.pricingModelSelect ? ui.pricingModelSelect.value : ''
    );
  }

  function populatePricingModelSelect(ui, providerId, selectedModelId) {
    const provider = String(providerId || '').trim();
    const selected = String(selectedModelId || '').trim();
    ui.pricingModelSelect.replaceChildren();
    addOption(ui.pricingModelSelect, '', 'Select pricing model', false);

    const models = catalogModels(ui, provider);
    for (const model of models) {
      if (!model || !model.enabled || String(model.status || '') !== 'production') continue;
      const tier = String(model.catalog_tier || '').trim();
      const suffix = tier ? ` — ${tier}` : '';
      const option = addOption(
        ui.pricingModelSelect,
        model.model_id,
        `${model.display_name || model.model_id}${suffix}`,
        false
      );
      option.title = `Pricing target exact model ID: ${model.model_id}`;
    }

    const accepted = models.some((model) => String(model.model_id || '') === selected);
    if (selected && accepted) {
      ui.pricingModelSelect.value = selected;
    } else {
      const defaultModel = models.find((model) => Boolean(model.is_default) && Boolean(model.enabled));
      if (defaultModel) ui.pricingModelSelect.value = String(defaultModel.model_id || '');
    }
  }

  function makeProjectSelectorControl() {
    const root = createElement('div', { className: 'provider-project-selector' });

    const select = makeSelect('project_id');
    select.hidden = true;
    select.tabIndex = -1;
    select.setAttribute('aria-hidden', 'true');

    const trigger = createElement('button', {
      className: 'provider-project-selector-trigger',
      type: 'button',
      text: 'Select project'
    });
    trigger.setAttribute('role', 'combobox');
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    trigger.setAttribute('aria-controls', 'provider-project-selector-listbox');

    const listbox = createElement('div', {
      className: 'provider-project-selector-listbox',
      id: 'provider-project-selector-listbox'
    });
    listbox.setAttribute('role', 'listbox');
    listbox.setAttribute('aria-label', 'Project');
    listbox.hidden = true;

    root.append(select, trigger, listbox);
    return { root, select, trigger, listbox };
  }

  function setProjectSelectorOpen(ui, open) {
    const shouldOpen = Boolean(open) && ui.projectSelectorList.children.length > 0;
    ui.projectSelectorList.hidden = !shouldOpen;
    ui.projectSelectorTrigger.setAttribute('aria-expanded', shouldOpen ? 'true' : 'false');
  }

  function syncProjectSelectorDisplay(ui) {
    const selected = Array.from(ui.projectSelect.options)
      .find((option) => option.value === ui.projectSelect.value);

    ui.projectSelectorTrigger.textContent = selected && selected.value
      ? selected.textContent
      : 'Select project';

    const choices = ui.projectSelectorList.querySelectorAll('[role="option"][data-project-id]');
    for (const choice of choices) {
      const isSelected = choice.dataset.projectId === ui.projectSelect.value;
      choice.setAttribute('aria-selected', isSelected ? 'true' : 'false');
    }
  }

  function renderProjectSelectorOptions(ui) {
    ui.projectSelectorList.replaceChildren();

    const options = Array.from(ui.projectSelect.options)
      .filter((option) => option.value && !option.disabled);

    if (!options.length) {
      const empty = createElement('div', {
        className: 'provider-project-selector-empty',
        text: 'No active projects available'
      });
      empty.setAttribute('role', 'option');
      empty.setAttribute('aria-disabled', 'true');
      ui.projectSelectorList.appendChild(empty);
      syncProjectSelectorDisplay(ui);
      return;
    }

    for (const option of options) {
      const choice = createElement('button', {
        className: 'provider-project-selector-option',
        type: 'button',
        text: option.textContent
      });
      choice.dataset.projectId = option.value;
      choice.setAttribute('role', 'option');
      choice.setAttribute('aria-selected', 'false');

      choice.addEventListener('click', () => {
        ui.projectSelect.value = option.value;
        syncProjectSelectorDisplay(ui);
        setProjectSelectorOpen(ui, false);
        ui.projectSelect.dispatchEvent(new Event('change', { bubbles: true }));
        ui.projectSelectorTrigger.focus();
      });

      ui.projectSelectorList.appendChild(choice);
    }

    syncProjectSelectorDisplay(ui);
  }

  function focusAdjacentProjectChoice(ui, step) {
    const choices = Array.from(
      ui.projectSelectorList.querySelectorAll('.provider-project-selector-option')
    );
    if (!choices.length) return;

    const activeIndex = choices.indexOf(document.activeElement);
    const baseIndex = activeIndex >= 0 ? activeIndex : (step > 0 ? -1 : 0);
    const nextIndex = (baseIndex + step + choices.length) % choices.length;
    choices[nextIndex].focus();
  }

  function buildModal(layer) {
    const modal = createElement('section', {
      className: 'studio-modal provider-settings-modal',
      id: PROVIDER_SETTINGS_ID
    });
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
    modal.setAttribute('aria-labelledby', 'provider-settings-title');
    modal.hidden = true;

    const closeButton = createElement('button', {
      className: 'studio-modal-close',
      type: 'button',
      text: '×'
    });
    closeButton.setAttribute('aria-label', 'Close Provider Settings');

    const header = createElement('header', { className: 'studio-modal-header' });
    const eyebrow = createElement('p', { className: 'eyebrow', text: 'Provider Control' });
    const title = createElement('h2', { id: 'provider-settings-title', text: 'Provider Settings' });
    const intro = createElement('p', {
      text: 'Configure a provider and credential, enter pricing for the models you plan to use, review saved profiles, then assign one to a project and validate the setup. Provider generation remains locked.'
    });
    header.append(eyebrow, title, intro);

    const lockBanner = createElement('div', {
      className: 'provider-settings-lock',
      text: 'Provider execution: LOCKED — provider/model setup validation is available, but real provider generation remains disabled until the later execution phase.'
    });

    const form = createElement('form', { className: 'provider-settings-form' });
    form.noValidate = true;

    const scroll = createElement('div', { className: 'provider-settings-scroll' });

    const providerSection = createElement('section', { className: 'provider-settings-section' });
    providerSection.appendChild(createElement('h3', { text: 'Provider Configuration' }));

    const providerGrid = createElement('div', { className: 'provider-settings-grid' });
    const providerSelect = makeSelect('provider_id');
    const modelSelect = makeSelect('model_id');
    addOption(modelSelect, '', 'Select model', false);

    const serviceTierSelect = makeSelect('service_tier');
    addOption(serviceTierSelect, 'standard', 'Standard', false);

    const scopeSelect = makeSelect('inference_scope');
    addOption(scopeSelect, 'global', 'Global', false);

    const credentialState = createElement('output', {
      className: 'provider-settings-readonly',
      text: 'Credential state unavailable'
    });
    credentialState.setAttribute('aria-live', 'polite');

    const apiKeyInput = makeInput('password', 'provider_api_key', '');
    apiKeyInput.placeholder = 'Paste API key to store securely';
    apiKeyInput.autocomplete = 'new-password';
    apiKeyInput.spellcheck = false;

    appendLabelField(providerGrid, 'Provider', providerSelect);
    appendLabelField(
      providerGrid,
      'Model',
      modelSelect,
      'Choose a curated direct-provider model. Italus stores the exact provider API model ID internally; display names are never substituted for execution IDs.'
    );
    appendLabelField(
      providerGrid,
      'Service Tier',
      serviceTierSelect,
      'Standard is the currently supported planning pricing tier. Additional provider billing modes remain disabled until provider setup validation supports them.'
    );
    appendLabelField(
      providerGrid,
      'Inference Scope',
      scopeSelect,
      'Global is the currently supported planning pricing scope. Additional scopes remain disabled until provider setup validation supports them.'
    );
    appendLabelField(
      providerGrid,
      'Credential State',
      credentialState,
      'Shows only whether Italus can resolve a credential. The API key itself is never returned to the browser.'
    );
    appendLabelField(
      providerGrid,
      'API Key',
      apiKeyInput,
      'Desktop credentials are protected by the trusted platform credential backend; explicit server deployments use server-managed credentials. The API key itself is never returned to the browser.'
    );

    const modelNote = createElement('p', {
      className: 'provider-settings-note',
      text: 'Curated direct-provider models are loaded for Anthropic and OpenAI. After saving the provider profile and pricing, use Project Provider Assignment & Lock to validate the configured account and exact bound model without generating text.'
    });

    const credentialNote = createElement('p', {
      className: 'provider-settings-note',
      text: 'Multiple provider credentials may be configured at the same time. Italus resolves credentials only through the trusted backend selected by deployment. Secrets are never written to project files or returned to this page.'
    });

    const configActions = createElement('div', { className: 'provider-settings-actions' });
    const saveConfig = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Save Provider Profile'
    });
    const saveCredential = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Save API Key Securely'
    });
    const removeCredential = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Remove Stored API Key'
    });
    configActions.append(saveConfig, saveCredential, removeCredential);

    const credentialReplaceConfirmation = createElement('div', {
      className: 'provider-settings-note'
    });
    credentialReplaceConfirmation.hidden = true;
    credentialReplaceConfirmation.setAttribute('role', 'group');
    credentialReplaceConfirmation.setAttribute(
      'aria-label',
      'Replace stored API key confirmation'
    );

    const credentialReplaceMessage = createElement('p', {
      text: 'This provider already has an Italus-managed API key. Saving the new key will replace the existing key.'
    });

    const credentialReplaceActions = createElement('div', {
      className: 'provider-settings-actions'
    });
    const cancelCredentialReplace = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Cancel'
    });
    const confirmCredentialReplace = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Replace API Key'
    });
    credentialReplaceActions.append(cancelCredentialReplace, confirmCredentialReplace);
    credentialReplaceConfirmation.append(
      credentialReplaceMessage,
      credentialReplaceActions
    );

    const credentialRemoveOverlay = createElement('div', {
      className: 'provider-settings-destructive-overlay'
    });
    credentialRemoveOverlay.hidden = true;

    const credentialRemoveDialog = createElement('section', {
      className: 'provider-settings-destructive-dialog'
    });
    credentialRemoveDialog.setAttribute('role', 'alertdialog');
    credentialRemoveDialog.setAttribute('aria-modal', 'true');
    credentialRemoveDialog.setAttribute(
      'aria-labelledby',
      'provider-settings-remove-key-title'
    );
    credentialRemoveDialog.setAttribute(
      'aria-describedby',
      'provider-settings-remove-key-warning'
    );

    const credentialRemoveTitle = createElement('h3', {
      id: 'provider-settings-remove-key-title',
      text: 'Remove Stored API Key?'
    });
    const credentialRemoveWarning = createElement('p', {
      id: 'provider-settings-remove-key-warning',
      text: 'Removing this stored API key is destructive for Italus. The stored credential cannot be recovered from Italus. Italus will no longer have access to this provider until you save an API key again. If you no longer have the current key, you will need to obtain a new API key from the provider. This action does not revoke the key at the provider.'
    });
    const credentialRemoveActions = createElement('div', {
      className: 'provider-settings-actions'
    });
    const cancelCredentialRemove = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Cancel'
    });
    const confirmCredentialRemove = createElement('button', {
      className: 'secondary-button provider-settings-destructive-button',
      type: 'button',
      text: 'Remove API Key'
    });

    credentialRemoveActions.append(
      cancelCredentialRemove,
      confirmCredentialRemove
    );
    credentialRemoveDialog.append(
      credentialRemoveTitle,
      credentialRemoveWarning,
      credentialRemoveActions
    );
    credentialRemoveOverlay.appendChild(credentialRemoveDialog);

    const configStatus = createElement('p', {
      className: 'provider-settings-status',
      text: 'No provider configuration loaded.'
    });
    configStatus.setAttribute('aria-live', 'polite');

    providerSection.append(
      providerGrid,
      modelNote,
      credentialNote,
      configActions,
      credentialReplaceConfirmation,
      configStatus
    );

    const projectSection = createElement('section', { className: 'provider-settings-section' });
    projectSection.appendChild(createElement('h3', { text: 'Project Provider Assignment & Lock' }));

    const projectNote = createElement('p', {
      className: 'provider-settings-note',
      text: 'Assign one saved provider/model profile to each project after the provider credential and model pricing are configured. You may correct the binding before provider usage begins. After the first provider usage event, provider/model switching is blocked to protect billing, model, and authorship lineage. A future controlled migration is required to change providers after that point.'
    });

    const projectGrid = createElement('div', { className: 'provider-settings-grid' });
    const projectSelector = makeProjectSelectorControl();
    const projectSelect = projectSelector.select;
    const projectBindingState = createElement('output', {
      className: 'provider-settings-readonly',
      text: 'Select a project'
    });
    const projectLockState = createElement('output', {
      className: 'provider-settings-readonly',
      text: 'Lock state unavailable'
    });

    const projectField = createElement('div', { className: 'provider-settings-field' });
    const projectCaption = createElement('span', {
      className: 'provider-settings-field-label',
      text: 'Project'
    });
    projectField.append(projectCaption, projectSelector.root);
    projectGrid.appendChild(projectField);

    appendLabelField(projectGrid, 'Bound Provider / Model', projectBindingState);
    appendLabelField(projectGrid, 'Provider Lock State', projectLockState);

    const projectPreflightState = createElement('output', {
      className: 'provider-settings-readonly',
      text: 'Not run'
    });
    projectPreflightState.setAttribute('aria-live', 'polite');
    appendLabelField(
      projectGrid,
      'Provider Setup Status',
      projectPreflightState,
      'Point-in-time validation of the project binding, exact model ID, secure credential, effective immutable pricing, and provider model metadata. No text generation or usage recording occurs.'
    );

    const projectActions = createElement('div', { className: 'provider-settings-actions' });
    const bindProject = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Bind Selected Provider Profile to Project'
    });
    const runProjectPreflight = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Validate Project Provider Setup'
    });
    runProjectPreflight.disabled = true;
    projectActions.append(bindProject, runProjectPreflight);

    const projectStatus = createElement('p', {
      className: 'provider-settings-status',
      text: 'No project binding loaded.'
    });
    projectStatus.setAttribute('aria-live', 'polite');

    projectSection.append(projectNote, projectGrid, projectActions, projectStatus);

    const profileSection = createElement('section', { className: 'provider-settings-section' });
    profileSection.appendChild(createElement('h3', { text: 'Saved Provider Profiles' }));

    const profileNote = createElement('p', {
      className: 'provider-settings-note',
      text: 'Italus stores one reusable provider profile per provider. Its saved model is the profile default for future project binding. Existing projects keep their own bound model until the author explicitly changes that project. A profile can be deleted only after it is disassociated from every project. Deleting an unassociated profile also removes its Italus-managed stored API key. Projects, pricing history, and usage history remain intact.'
    });
    const profileList = createElement('div', { className: 'provider-profile-list' });
    const profileStatus = createElement('p', {
      className: 'provider-settings-status',
      text: 'Saved provider profiles not loaded.'
    });
    profileStatus.setAttribute('aria-live', 'polite');
    profileSection.append(profileNote, profileList, profileStatus);

    const profileActionOverlay = createElement('div', {
      className: 'provider-settings-destructive-overlay'
    });
    profileActionOverlay.hidden = true;

    const profileActionDialog = createElement('section', {
      className: 'provider-settings-destructive-dialog'
    });
    profileActionDialog.setAttribute('role', 'alertdialog');
    profileActionDialog.setAttribute('aria-modal', 'true');
    profileActionDialog.setAttribute(
      'aria-labelledby',
      'provider-settings-profile-action-title'
    );
    profileActionDialog.setAttribute(
      'aria-describedby',
      'provider-settings-profile-action-warning'
    );

    const profileActionTitle = createElement('h3', {
      id: 'provider-settings-profile-action-title',
      text: 'Provider Profile Action'
    });
    const profileActionWarning = createElement('p', {
      id: 'provider-settings-profile-action-warning',
      text: ''
    });
    const profileActionButtons = createElement('div', {
      className: 'provider-settings-actions'
    });
    const cancelProfileAction = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Cancel'
    });
    const confirmProfileAction = createElement('button', {
      className: 'secondary-button provider-settings-destructive-button',
      type: 'button',
      text: 'Confirm'
    });
    profileActionButtons.append(cancelProfileAction, confirmProfileAction);
    profileActionDialog.append(
      profileActionTitle,
      profileActionWarning,
      profileActionButtons
    );
    profileActionOverlay.appendChild(profileActionDialog);

    const dateTimeOverlay = createElement('div', {
      className: 'provider-settings-picker-overlay'
    });
    dateTimeOverlay.hidden = true;

    const dateTimeDialog = createElement('section', {
      className: 'provider-settings-picker-dialog'
    });
    dateTimeDialog.setAttribute('role', 'dialog');
    dateTimeDialog.setAttribute('aria-modal', 'true');
    dateTimeDialog.setAttribute(
      'aria-labelledby',
      'provider-settings-datetime-picker-title'
    );

    const dateTimeTitle = createElement('h3', {
      id: 'provider-settings-datetime-picker-title',
      text: 'Choose Date and Time'
    });
    const dateTimeNote = createElement('p', {
      className: 'provider-settings-note',
      text: 'Choose the date and time, then select OK. The displayed value follows your system/browser 12-hour or 24-hour locale format.'
    });
    const dateTimeGrid = createElement('div', {
      className: 'provider-settings-grid provider-datetime-picker-grid'
    });
    const pickerDate = makeInput('date', 'pricing_picker_date', '');
    const pickerTime = makeInput('time', 'pricing_picker_time', '');
    pickerTime.step = '60';
    appendLabelField(dateTimeGrid, 'Date', pickerDate);
    appendLabelField(dateTimeGrid, 'Time', pickerTime);

    const dateTimeActions = createElement('div', {
      className: 'provider-settings-actions'
    });
    const cancelDateTime = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Cancel'
    });
    const confirmDateTime = createElement('button', {
      className: 'primary-button',
      type: 'button',
      text: 'OK'
    });
    dateTimeActions.append(cancelDateTime, confirmDateTime);
    dateTimeDialog.append(dateTimeTitle, dateTimeNote, dateTimeGrid, dateTimeActions);
    dateTimeOverlay.appendChild(dateTimeDialog);

    const pricingSection = createElement('section', { className: 'provider-settings-section' });
    pricingSection.appendChild(createElement('h3', { text: 'Provider Pricing Registry' }));
    pricingSection.appendChild(createElement('p', {
      className: 'provider-settings-note',
      text: 'Configure immutable pricing for each provider/model you plan to assign to projects. Pricing is reusable across projects and should be configured before project provider setup validation.'
    }));

    const pricingAccuracyWarning = createElement('div', {
      className: 'provider-settings-pricing-warning'
    });
    const pricingAccuracyText = document.createTextNode(
      'Cost estimate accuracy depends on the rates entered here. Italus does not automatically receive live provider pricing-rate updates. Verify rates against the official provider pricing source before saving. Incorrect rates can skew estimated cost per generation. 1 MTok = 1,000,000 tokens'
    );
    const tokenHelp = createElement('span', {
      className: 'provider-settings-help provider-settings-inline-help',
      text: '?'
    });
    tokenHelp.title = 'What is a token? A token is a unit the AI model processes and providers use for usage billing. Tokens are not the same as words. Words, word fragments, punctuation, whitespace, and formatting all contribute to token usage. In ordinary English, one token averages roughly 4 characters or about 0.75 words, but exact counts vary by provider, model, and text. 1 MTok = 1,000,000 tokens.';
    tokenHelp.setAttribute('aria-label', tokenHelp.title);
    tokenHelp.tabIndex = 0;
    pricingAccuracyWarning.append(pricingAccuracyText, tokenHelp);

    const pricingRegistryNote = createElement('p', {
      className: 'provider-settings-note',
      text: 'Pricing is maintained independently from the saved provider profile default model. Select the exact catalog model, service tier, and inference scope whose immutable price schedule you are maintaining. Existing project bindings and historical billing are never rewritten by a pricing update.'
    });

    const pricingTargetGrid = createElement('div', {
      className: 'provider-settings-grid provider-pricing-target-grid'
    });
    const pricingModelSelect = makeSelect('pricing_model_id');
    const pricingServiceTierSelect = makeSelect('pricing_service_tier');
    addOption(pricingServiceTierSelect, 'standard', 'Standard', false);
    const pricingScopeSelect = makeSelect('pricing_inference_scope');
    addOption(pricingScopeSelect, 'global', 'Global', false);
    const pricingChangeTypeSelect = makeSelect('pricing_update_type');
    addOption(
      pricingChangeTypeSelect,
      'new_price',
      'New Provider Price — new effective date',
      true
    );
    addOption(
      pricingChangeTypeSelect,
      'correction',
      'Correct Existing Price — same effective date',
      false
    );

    appendLabelField(
      pricingTargetGrid,
      'Pricing Model',
      pricingModelSelect,
      'The exact provider model whose immutable price schedule you are editing. This does not change the Provider Profile default model or any project model.'
    );
    appendLabelField(
      pricingTargetGrid,
      'Pricing Service Tier',
      pricingServiceTierSelect,
      'Standard is the currently supported immutable planning price tier. Additional provider billing modes remain disabled until provider setup validation supports them.'
    );
    appendLabelField(
      pricingTargetGrid,
      'Pricing Inference Scope',
      pricingScopeSelect,
      'Global is the currently supported immutable planning price scope. Additional scopes remain disabled until provider setup validation supports them.'
    );
    appendLabelField(
      pricingTargetGrid,
      'Pricing Update Type',
      pricingChangeTypeSelect,
      'Choose New Provider Price when the provider rate changes on a new effective date. Choose Correct Existing Price only when correcting an earlier entry while intentionally keeping the same provider effective date.'
    );
    const pricingChangeModeNote = createElement('p', {
      className: 'provider-settings-note',
      text: 'Initial pricing version — review the provider effective date before saving.'
    });
    pricingTargetGrid.appendChild(pricingChangeModeNote);

    const pricingRegistryList = createElement('div', {
      className: 'provider-pricing-registry-list'
    });
    const pricingRegistryStatus = createElement('p', {
      className: 'provider-settings-status',
      text: 'Select a provider to load its pricing registry.'
    });
    pricingRegistryStatus.setAttribute('aria-live', 'polite');

    const pricingMeta = createElement('div', { className: 'provider-settings-meta' });
    const currentVersion = createElement('span', { text: 'Current Effective Rate: none' });
    const scheduledVersion = createElement('span', { text: 'Next Scheduled Rate: none' });
    const verifiedLabel = createElement('span', { text: 'Rates Last Checked Against Provider: none' });
    const pricingLink = createElement('a', { text: 'Open Official Pricing ↗' });
    pricingLink.target = '_blank';
    pricingLink.rel = 'noopener noreferrer';
    pricingLink.hidden = true;
    const freshnessLabel = createElement('span', {
      className: 'provider-pricing-freshness',
      text: 'Rate Freshness: no verified version'
    });
    pricingMeta.append(currentVersion, scheduledVersion, verifiedLabel, pricingLink, freshnessLabel);

    const pricingGrid = createElement('div', { className: 'provider-settings-grid provider-settings-pricing-grid' });
    const currencyInput = makeInput('text', 'currency', 'USD');
    const freshnessThresholdDays = makeInput('number', 'freshness_threshold_days', '30');
    freshnessThresholdDays.min = '1';
    freshnessThresholdDays.max = '3650';
    freshnessThresholdDays.step = '1';
    const inputRate = makeInput('number', 'input_per_mtok', '0');
    const outputRate = makeInput('number', 'output_per_mtok', '0');
    const cache5mRate = makeInput('number', 'cache_write_5m_per_mtok', '0');
    const cache1hRate = makeInput('number', 'cache_write_1h_per_mtok', '0');
    const cacheReadRate = makeInput('number', 'cache_read_per_mtok', '0');
    const effectiveFromPicker = makeDateTimePicker(
      'effective_from',
      'Choose provider effective date and time'
    );
    const verifiedAtPicker = makeDateTimePicker(
      'verified_at',
      'Choose verification date and time'
    );
    const effectiveFrom = effectiveFromPicker.input;
    const verifiedAt = verifiedAtPicker.input;
    const sourceUrl = makeInput('url', 'source_url', '');
    const notes = createElement('textarea', { name: 'notes' });
    notes.rows = 3;

    for (const field of [inputRate, outputRate, cache5mRate, cache1hRate, cacheReadRate]) {
      field.min = '0';
      field.step = 'any';
    }

    appendLabelField(
      pricingGrid,
      'Billing Currency',
      currencyInput,
      'Currency used by the provider pricing source, normally USD.'
    );
    appendLabelField(
      pricingGrid,
      'Pricing Review Warning After (days)',
      freshnessThresholdDays,
      'Application-wide warning threshold for how long saved provider pricing may go without being rechecked against the official pricing source. Default: 30 days.'
    );
    appendLabelField(
      pricingGrid,
      'Prompt / Input Cost per 1M Tokens',
      inputRate,
      'Cost for one million input tokens sent to the model. Input tokens include the Italus prompt, instructions, Book Knowledge, Chapter Knowledge, and other request context.'
    );
    appendLabelField(
      pricingGrid,
      'Generated Output Cost per 1M Tokens',
      outputRate,
      'Cost for one million output tokens generated by the model.'
    );
    appendLabelField(
      pricingGrid,
      '5-Minute Cache Write Cost per 1M Tokens',
      cache5mRate,
      'Provider-specific charge for writing one million prompt tokens into a short-duration 5-minute prompt cache. Leave 0 when the selected provider/model does not use this billing category.'
    );
    appendLabelField(
      pricingGrid,
      '1-Hour Cache Write Cost per 1M Tokens',
      cache1hRate,
      'Provider-specific charge for writing one million prompt tokens into a 1-hour prompt cache. Leave 0 when the selected provider/model does not use this billing category.'
    );
    appendLabelField(
      pricingGrid,
      'Cache Read Cost per 1M Tokens',
      cacheReadRate,
      'Provider-specific charge for one million tokens read from an existing prompt cache. Leave 0 when the selected provider/model does not use this billing category.'
    );
    appendLabelField(
      pricingGrid,
      'Provider Price Effective Date',
      effectiveFromPicker.root,
      'Date/time when this provider rate became effective according to the official pricing source.'
    );
    appendLabelField(
      pricingGrid,
      'Rates Checked / Verified On',
      verifiedAtPicker.root,
      'Date/time when the author or operator last checked these entered rates against the official provider pricing page.'
    );
    appendLabelField(
      pricingGrid,
      'Official Provider Pricing URL',
      sourceUrl,
      'Source page used to verify these rates. Italus does not automatically refresh prices from this page.'
    );
    appendLabelField(
      pricingGrid,
      'Pricing Notes',
      notes,
      'Optional notes about discounts, service tiers, geography, cache assumptions, or other pricing conditions.'
    );

    const pricingWarning = createElement('p', {
      className: 'provider-settings-note',
      text: 'Saving creates a new immutable pricing version for future estimates. Completed generation receipts keep the pricing snapshot used when they ran. Provider invoices may differ because of provider-side rounding, discounts, taxes, or billing rules.'
    });

    const pricingActions = createElement('div', { className: 'provider-settings-actions' });
    const savePricing = createElement('button', {
      className: 'primary-button',
      type: 'button',
      text: 'Save New Pricing Version'
    });
    const viewHistory = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'View Pricing History'
    });
    const discardPricing = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Discard Unsaved Changes'
    });
    const savePricingPolicy = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Save Pricing Review Threshold'
    });
    pricingActions.append(
      savePricing,
      viewHistory,
      discardPricing,
      savePricingPolicy
    );

    const historyList = createElement('ol', { className: 'provider-pricing-history' });
    historyList.hidden = true;

    const pricingStatus = createElement('p', {
      className: 'provider-settings-status',
      text: 'No pricing version loaded.'
    });
    pricingStatus.setAttribute('aria-live', 'polite');

    pricingSection.append(
      pricingAccuracyWarning,
      pricingRegistryNote,
      pricingTargetGrid,
      pricingRegistryList,
      pricingRegistryStatus,
      pricingMeta,
      pricingGrid,
      pricingWarning,
      pricingActions,
      historyList,
      pricingStatus
    );

    const footer = createElement('div', { className: 'wizard-actions' });
    const footerClose = createElement('button', {
      className: 'secondary-button',
      type: 'button',
      text: 'Close'
    });
    footer.appendChild(footerClose);

    scroll.append(providerSection, pricingSection, profileSection, projectSection);
    form.append(scroll, footer);
    modal.append(
      closeButton,
      header,
      lockBanner,
      form,
      credentialRemoveOverlay,
      profileActionOverlay,
      dateTimeOverlay
    );
    layer.appendChild(modal);

    return {
      modal,
      closeButton,
      footerClose,
      providerSelect,
      modelSelect,
      modelNote,
      catalogProviders: new Map(),
      serviceTierSelect,
      scopeSelect,
      credentialState,
      apiKeyInput,
      saveConfig,
      saveCredential,
      removeCredential,
      credentialReplaceConfirmation,
      credentialReplaceMessage,
      cancelCredentialReplace,
      confirmCredentialReplace,
      credentialRemoveOverlay,
      credentialRemoveDialog,
      cancelCredentialRemove,
      confirmCredentialRemove,
      currentCredential: null,
      configStatus,
      projectSelect,
      projectSelectorRoot: projectSelector.root,
      projectSelectorTrigger: projectSelector.trigger,
      projectSelectorList: projectSelector.listbox,
      projectBindingState,
      projectLockState,
      projectPreflightState,
      bindProject,
      runProjectPreflight,
      projectStatus,
      profileList,
      profileStatus,
      profileActionOverlay,
      profileActionTitle,
      profileActionWarning,
      cancelProfileAction,
      confirmProfileAction,
      pendingProfileAction: null,
      dateTimeOverlay,
      dateTimeDialog,
      dateTimeTitle,
      pickerDate,
      pickerTime,
      cancelDateTime,
      confirmDateTime,
      pendingDateTimePicker: null,
      effectiveFromPicker,
      verifiedAtPicker,
      pricingModelSelect,
      pricingServiceTierSelect,
      pricingScopeSelect,
      pricingChangeTypeSelect,
      pricingChangeModeNote,
      pricingEditBase: null,
      pricingRegistryList,
      pricingRegistryStatus,
      currentVersion,
      scheduledVersion,
      verifiedLabel,
      pricingLink,
      freshnessLabel,
      currencyInput,
      freshnessThresholdDays,
      currentPricingPolicy: null,
      inputRate,
      outputRate,
      cache5mRate,
      cache1hRate,
      cacheReadRate,
      effectiveFrom,
      verifiedAt,
      sourceUrl,
      notes,
      savePricing,
      viewHistory,
      discardPricing,
      savePricingPolicy,
      historyList,
      pricingStatus
    };
  }

  function toLocalDateTime(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) return raw.slice(0, 16);
    const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
    return local.toISOString().slice(0, 16);
  }

  function formatHumanDateTime(value) {
    const raw = String(value || '').trim();
    if (!raw) return '—';
    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) return raw;
    try {
      return new Intl.DateTimeFormat(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit'
      }).format(parsed);
    } catch (_) {
      return parsed.toLocaleString();
    }
  }

  function providerPricingLabel(providerId) {
    const value = String(providerId || '').trim().toLowerCase();
    const labels = {
      anthropic: 'Anthropic / Claude',
      openai: 'OpenAI',
      openrouter: 'OpenRouter'
    };
    return labels[value] || String(providerId || 'Provider');
  }

  function pricingDisplayLabel(pricing) {
    if (!pricing) return 'No active pricing';
    const provider = providerPricingLabel(pricing.provider_id);
    const model = String(pricing.model_id || 'model');
    const verified = pricing.verified_at || pricing.effective_from || pricing.created_at;
    return verified
      ? `${provider} — ${model} — verified ${formatHumanDateTime(verified)}`
      : `${provider} — ${model}`;
  }

  function syncDateTimePickerDisplay(picker) {
    if (!picker) return;
    picker.display.value = picker.input.value
      ? formatHumanDateTime(picker.input.value)
      : '';
  }

  function setDateTimePickerValue(picker, value) {
    if (!picker) return;
    picker.input.value = toLocalDateTime(value);
    syncDateTimePickerDisplay(picker);
  }

  function hideDateTimePicker(ui) {
    ui.pendingDateTimePicker = null;
    ui.dateTimeOverlay.hidden = true;
  }

  function openDateTimePicker(ui, picker, title) {
    ui.pendingDateTimePicker = picker;
    ui.dateTimeTitle.textContent = title || 'Choose Date and Time';

    let localValue = String(picker.input.value || '').trim();
    if (!localValue) {
      localValue = toLocalDateTime(new Date().toISOString());
    }
    const parts = localValue.split('T');
    ui.pickerDate.value = parts[0] || '';
    ui.pickerTime.value = String(parts[1] || '').slice(0, 5);
    ui.dateTimeOverlay.hidden = false;
    ui.pickerDate.focus();
  }

  function commitDateTimePicker(ui) {
    const picker = ui.pendingDateTimePicker;
    if (!picker) return;

    const date = String(ui.pickerDate.value || '').trim();
    const time = String(ui.pickerTime.value || '').trim();
    if (!date || !time) {
      return;
    }

    picker.input.value = `${date}T${time.slice(0, 5)}`;
    syncDateTimePickerDisplay(picker);
    hideDateTimePicker(ui);
    picker.display.focus();
  }

  function toIso(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) return raw;
    return parsed.toISOString().replace(/\.\d{3}Z$/, 'Z');
  }

  function pricingReferenceForModel(ui, providerId, modelId, serviceTier, inferenceScope) {
    const model = catalogModel(ui, providerId, modelId);
    const reference = model && model.pricing_reference;
    if (!reference || typeof reference !== 'object') return null;
    if (String(reference.service_tier || '') !== String(serviceTier || '')) return null;
    if (String(reference.inference_scope || '') !== String(inferenceScope || '')) return null;
    return reference;
  }

  function pricingReferenceForSelection(ui) {
    return pricingReferenceForModel(
      ui,
      ui.providerSelect.value,
      ui.pricingModelSelect ? ui.pricingModelSelect.value : '',
      ui.pricingServiceTierSelect.value,
      ui.pricingScopeSelect.value
    );
  }

  function compactPricingId(value) {
    const raw = String(
      value && typeof value === 'object' ? value.pricing_version_id || '' : value || ''
    ).trim();
    return raw.startsWith('pricing_') ? raw.slice('pricing_'.length) : raw || 'unavailable';
  }

  function samePricingEffectiveDate(left, right) {
    if (!left || !right) return false;
    const leftValue = toIso(left.effective_from || '');
    const rightValue = toIso(right.effective_from || '');
    return Boolean(leftValue && rightValue && leftValue === rightValue);
  }

  function previousPricingLabel(current, previous) {
    return samePricingEffectiveDate(current, previous)
      ? 'SUPERSEDED SAME-EFFECTIVE VERSION'
      : 'PREVIOUS EFFECTIVE PRICING';
  }

  function setEffectivePickerEnabled(ui, enabled) {
    const allowEdit = Boolean(enabled);
    ui.effectiveFromPicker.display.disabled = !allowEdit;
    ui.effectiveFromPicker.button.disabled = !allowEdit;
    ui.effectiveFromPicker.display.title = allowEdit
      ? 'Choose provider effective date and time'
      : 'Correction mode keeps the effective date of the version being corrected.';
    ui.effectiveFromPicker.button.title = ui.effectiveFromPicker.display.title;
  }

  function applyPricingUpdateType(ui, options = {}) {
    const base = ui.pricingEditBase || null;
    const hasBase = Boolean(base && base.pricing_version_id);

    if (!hasBase) {
      ui.pricingChangeTypeSelect.value = 'new_price';
      ui.pricingChangeTypeSelect.disabled = true;
      setEffectivePickerEnabled(ui, true);
      ui.pricingChangeModeNote.textContent =
        'Initial pricing version — review the provider effective date from the curated reference before saving.';
      return;
    }

    ui.pricingChangeTypeSelect.disabled = false;
    const mode = String(ui.pricingChangeTypeSelect.value || 'new_price');

    if (mode === 'correction') {
      setDateTimePickerValue(ui.effectiveFromPicker, base.effective_from || '');
      setEffectivePickerEnabled(ui, false);
      if (options.resetVerified !== false) {
        setDateTimePickerValue(ui.verifiedAtPicker, new Date().toISOString());
      }
      ui.pricingChangeModeNote.textContent =
        `Correction mode — keeps ${formatHumanDateTime(base.effective_from)} as the provider effective date. The new immutable version supersedes the earlier same-effective entry for pricing resolution; historical usage is not rewritten.`;
      return;
    }

    setEffectivePickerEnabled(ui, true);
    if (options.resetEffective !== false) {
      setDateTimePickerValue(ui.effectiveFromPicker, new Date().toISOString());
    }
    if (options.resetVerified !== false) {
      setDateTimePickerValue(ui.verifiedAtPicker, new Date().toISOString());
    }
    ui.pricingChangeModeNote.textContent =
      'New Provider Price mode — Effective From defaults to now. Change it only if the provider price actually starts at another past or future date.';
  }


  function applyPricingApplicability(ui, reference) {
    const notApplicable = new Set(
      reference && Array.isArray(reference.not_applicable_registry_fields)
        ? reference.not_applicable_registry_fields
        : []
    );
    const mappings = [
      ['cache_write_5m_per_mtok', ui.cache5mRate],
      ['cache_write_1h_per_mtok', ui.cache1hRate]
    ];
    for (const [fieldName, control] of mappings) {
      const disabled = notApplicable.has(fieldName);
      control.disabled = disabled;
      control.placeholder = disabled ? 'N/A' : '';
      control.title = disabled
        ? 'Not applicable to this provider in the current immutable pricing registry.'
        : '';
      if (disabled) control.value = '';
    }
  }

  function applyCatalogPricingReference(ui) {
    const reference = pricingReferenceForSelection(ui);
    if (!reference) {
      applyPricingApplicability(ui, null);
      return false;
    }

    const rates = reference.registry_rates_per_mtok || {};
    ui.currencyInput.value = reference.currency || 'USD';
    ui.inputRate.value = rates.input_per_mtok || '0';
    ui.outputRate.value = rates.output_per_mtok || '0';
    ui.cache5mRate.value = rates.cache_write_5m_per_mtok || '0';
    ui.cache1hRate.value = rates.cache_write_1h_per_mtok || '0';
    ui.cacheReadRate.value = rates.cache_read_per_mtok || '0';
    applyPricingApplicability(ui, reference);
    setDateTimePickerValue(ui.effectiveFromPicker, reference.effective_from || '');
    setDateTimePickerValue(ui.verifiedAtPicker, reference.verified_at || '');
    ui.sourceUrl.value = reference.source_url || '';
    ui.notes.value = reference.notes || '';
    updatePricingLink(ui, reference.source_url || '');

    ui.pricingEditBase = null;
    applyPricingUpdateType(ui, { resetEffective: false, resetVerified: false });

    ui.currentVersion.textContent =
      'Current Pricing: none — REFERENCE AVAILABLE — saving will create the initial immutable pricing version.';
    ui.verifiedLabel.textContent =
      `Curated Reference Checked: ${formatHumanDateTime(reference.verified_at)}`;
    ui.freshnessLabel.textContent =
      'Curated reference only — save an immutable pricing version before project provider setup validation can pass.';
    ui.freshnessLabel.dataset.stale = 'false';
    return true;
  }

  function collectPricingPayload(ui) {
    return {
      provider_id: ui.providerSelect.value,
      model_id: ui.pricingModelSelect.value.trim(),
      service_tier: ui.pricingServiceTierSelect.value,
      inference_scope: ui.pricingScopeSelect.value,
      currency: ui.currencyInput.value.trim() || 'USD',
      input_per_mtok: ui.inputRate.value,
      output_per_mtok: ui.outputRate.value,
      cache_write_5m_per_mtok: ui.cache5mRate.value || '0',
      cache_write_1h_per_mtok: ui.cache1hRate.value || '0',
      cache_read_per_mtok: ui.cacheReadRate.value || '0',
      effective_from: toIso(ui.effectiveFrom.value),
      verified_at: toIso(ui.verifiedAt.value),
      source_url: ui.sourceUrl.value.trim(),
      notes: ui.notes.value.trim()
    };
  }

  function renderPricing(ui, pricing, freshness, policy, nextScheduled) {
    const effectivePolicy = policy || ui.currentPricingPolicy || {};
    if (effectivePolicy && effectivePolicy.freshness_threshold_days) {
      ui.currentPricingPolicy = effectivePolicy;
      ui.freshnessThresholdDays.value = String(
        effectivePolicy.freshness_threshold_days
      );
    }

    ui.pricingEditBase = pricing || null;

    if (!pricing) {
      ui.currentVersion.textContent = 'Current Pricing: none';
      ui.currentVersion.title = '';
      ui.scheduledVersion.textContent = nextScheduled
        ? `Scheduled Pricing — ${pricingRateSummary(nextScheduled)} — Pricing ID: ${compactPricingId(nextScheduled)} — Effective From ${formatHumanDateTime(nextScheduled.effective_from)}`
        : 'Scheduled Pricing: none';
      ui.scheduledVersion.title = '';
      ui.verifiedLabel.textContent = 'Rates Last Checked Against Provider: none';
      ui.freshnessLabel.textContent = 'Rate Freshness: no verified version';
      ui.freshnessLabel.dataset.stale = 'false';
      ui.currencyInput.value = 'USD';
      ui.inputRate.value = '0';
      ui.outputRate.value = '0';
      ui.cache5mRate.value = '0';
      ui.cache1hRate.value = '0';
      ui.cacheReadRate.value = '0';
      applyPricingApplicability(ui, null);
      setDateTimePickerValue(ui.effectiveFromPicker, '');
      setDateTimePickerValue(ui.verifiedAtPicker, '');
      ui.notes.value = '';
      applyPricingUpdateType(ui, { resetEffective: false, resetVerified: false });
      return;
    }

    ui.currentVersion.textContent =
      `Current Pricing — ${pricingRateSummary(pricing)} — Pricing ID: ${compactPricingId(pricing)}`;
    ui.currentVersion.title = pricing.pricing_version_id || '';
    ui.scheduledVersion.textContent = nextScheduled
      ? `Scheduled Pricing — ${pricingRateSummary(nextScheduled)} — Pricing ID: ${compactPricingId(nextScheduled)} — Effective From ${formatHumanDateTime(nextScheduled.effective_from)}`
      : 'Scheduled Pricing: none';
    ui.scheduledVersion.title = nextScheduled ? nextScheduled.pricing_version_id || '' : '';
    ui.verifiedLabel.textContent =
      `Rates Last Checked Against Provider: ${formatHumanDateTime(pricing.verified_at)}`;

    const freshnessState = freshness || {};
    const ageDays = Number(freshnessState.age_days);
    const thresholdDays = Number(
      freshnessState.threshold_days ||
      effectivePolicy.freshness_threshold_days ||
      30
    );
    if (freshnessState.warning) {
      ui.freshnessLabel.textContent =
        `Rate freshness warning: ${freshnessState.message || 'Review official pricing before relying on new cost estimates.'}`;
      ui.freshnessLabel.dataset.stale = 'true';
    } else if (Number.isFinite(ageDays)) {
      ui.freshnessLabel.textContent =
        `Rate Freshness: checked ${Math.max(ageDays, 0)} days ago; review warning threshold ${thresholdDays} days.`;
      ui.freshnessLabel.dataset.stale = 'false';
    } else {
      ui.freshnessLabel.textContent =
        `Rate Freshness: ${freshnessState.status || 'verification state unavailable'}.`;
      ui.freshnessLabel.dataset.stale = 'false';
    }
    ui.currencyInput.value = pricing.currency || 'USD';

    const rates = pricing.rates_per_mtok || {};
    applyPricingApplicability(ui, pricingReferenceForSelection(ui));
    ui.inputRate.value = rates.input_per_mtok || '0';
    ui.outputRate.value = rates.output_per_mtok || '0';
    ui.cache5mRate.value = rates.cache_write_5m_per_mtok || '0';
    ui.cache1hRate.value = rates.cache_write_1h_per_mtok || '0';
    ui.cacheReadRate.value = rates.cache_read_per_mtok || '0';
    setDateTimePickerValue(ui.verifiedAtPicker, pricing.verified_at);
    ui.sourceUrl.value = pricing.source_url || '';
    ui.notes.value = pricing.notes || '';

    ui.pricingChangeTypeSelect.value = 'new_price';
    applyPricingUpdateType(ui, { resetEffective: true, resetVerified: true });
  }

  function updatePricingLink(ui, source) {
    const safe = safeHttpUrl(source);
    if (!safe) {
      ui.pricingLink.hidden = true;
      ui.pricingLink.removeAttribute('href');
      return;
    }
    ui.pricingLink.href = safe;
    ui.pricingLink.hidden = false;
  }

  async function loadPricingPolicy(ui) {
    const payload = await apiJson(`${API_ROOT}/pricing/policy`);
    const policy = payload.policy || {};
    ui.currentPricingPolicy = policy;
    ui.freshnessThresholdDays.value = String(
      policy.freshness_threshold_days || 30
    );
    return policy;
  }

  async function savePricingReviewPolicy(ui) {
    const parsed = Number(ui.freshnessThresholdDays.value);
    if (!Number.isInteger(parsed) || parsed < 1 || parsed > 3650) {
      throw new Error('Pricing review warning threshold must be a whole number from 1 to 3650 days.');
    }

    const payload = await apiJson(`${API_ROOT}/pricing/policy`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ freshness_threshold_days: parsed })
    });
    ui.currentPricingPolicy = payload.policy || {};
    ui.freshnessThresholdDays.value = String(
      ui.currentPricingPolicy.freshness_threshold_days || parsed
    );
    setStatus(
      ui.pricingStatus,
      `Pricing review warning threshold saved at ${ui.freshnessThresholdDays.value} days.`,
      'success'
    );
    await loadCurrentPricing(ui);
  }

  async function loadCurrentPricing(ui) {
    const provider = ui.providerSelect.value;
    const model = ui.pricingModelSelect.value.trim();
    if (!provider || !model) {
      renderPricing(ui, null, null, ui.currentPricingPolicy, null);
      return;
    }

    const params = new URLSearchParams({
      provider_id: provider,
      model_id: model,
      service_tier: ui.pricingServiceTierSelect.value,
      inference_scope: ui.pricingScopeSelect.value
    });

    const payload = await apiJson(`${API_ROOT}/pricing/current?${params.toString()}`);
    const currentPricing = payload.pricing || null;
    const nextScheduled = payload.next_scheduled_pricing || null;
    renderPricing(
      ui,
      currentPricing,
      payload.freshness || null,
      payload.policy || ui.currentPricingPolicy,
      nextScheduled
    );
    if (currentPricing && currentPricing.source_url) {
      updatePricingLink(ui, currentPricing.source_url);
    } else if (nextScheduled && nextScheduled.source_url) {
      updatePricingLink(ui, nextScheduled.source_url);
      const rates = nextScheduled.rates_per_mtok || {};
      ui.currencyInput.value = nextScheduled.currency || 'USD';
      ui.inputRate.value = rates.input_per_mtok || '0';
      ui.outputRate.value = rates.output_per_mtok || '0';
      ui.cache5mRate.value = rates.cache_write_5m_per_mtok || '0';
      ui.cache1hRate.value = rates.cache_write_1h_per_mtok || '0';
      ui.cacheReadRate.value = rates.cache_read_per_mtok || '0';
      applyPricingApplicability(ui, pricingReferenceForSelection(ui));
      setDateTimePickerValue(ui.effectiveFromPicker, nextScheduled.effective_from || '');
      setDateTimePickerValue(ui.verifiedAtPicker, nextScheduled.verified_at || '');
      ui.sourceUrl.value = nextScheduled.source_url || '';
      ui.notes.value = nextScheduled.notes || '';
      ui.pricingEditBase = nextScheduled;
      ui.pricingChangeTypeSelect.value = 'correction';
      applyPricingUpdateType(ui, { resetEffective: false, resetVerified: true });
      setStatus(
        ui.pricingStatus,
        'No current rate is effective yet. The editor is showing the next scheduled immutable pricing version in Correction mode. Choose New Provider Price to create a separate effective period.',
        'neutral'
      );
    } else if (applyCatalogPricingReference(ui)) {
      setStatus(
        ui.pricingStatus,
        'Curated pricing reference loaded. Review it, then save an immutable pricing version for this exact pricing model/tier/scope.',
        'neutral'
      );
    }
  }

  function pricingRateSummary(pricing) {
    if (!pricing || typeof pricing !== 'object') return '—';
    const rates = pricing.rates_per_mtok || {};
    const currency = String(pricing.currency || 'USD');
    return `${currency} input ${rates.input_per_mtok || '0'} / output ${rates.output_per_mtok || '0'} per MTok`;
  }

  function pricingVersionTimingSummary(pricing) {
    if (!pricing || typeof pricing !== 'object') return '';
    const effective = formatHumanDateTime(pricing.effective_from);
    const saved = formatHumanDateTime(pricing.created_at);
    return `Effective From ${effective} — Entered in Italus ${saved}`;
  }

  function renderPricingRegistry(ui, payload) {
    const rows = Array.isArray(payload && payload.models) ? payload.models : [];
    ui.pricingRegistryList.replaceChildren();

    if (!rows.length) {
      ui.pricingRegistryStatus.textContent = 'No catalog pricing models are available for this provider.';
      return;
    }

    for (const row of rows) {
      const reference = pricingReferenceForModel(
        ui,
        payload.provider_id,
        row.model_id,
        payload.service_tier || 'standard',
        payload.inference_scope || 'global'
      );
      const referenceAvailable =
        row.registry_status === 'MISSING' && Boolean(reference);

      const card = createElement('article', { className: 'provider-pricing-registry-card' });
      const heading = createElement('div', { className: 'provider-pricing-registry-heading' });
      const title = createElement('strong', {
        text: `${row.display_name || row.model_id} — ${row.model_id || ''}`
      });
      const displayStatus = row.registry_status === 'CURRENT'
        ? 'CURRENT'
        : row.registry_status === 'SCHEDULED_ONLY'
          ? 'SCHEDULED'
          : referenceAvailable
            ? 'REFERENCE AVAILABLE'
            : 'MISSING';
      const badge = createElement('span', {
        className: 'provider-pricing-registry-badge',
        text: displayStatus
      });
      badge.dataset.status = referenceAvailable
        ? 'reference_available'
        : String(row.registry_status || '').toLowerCase();
      heading.append(title, badge);

      const details = createElement('div', { className: 'provider-pricing-registry-details' });
      const current = row.current_pricing || null;
      const scheduled = row.next_scheduled_pricing || null;
      const retiredVersions = Array.isArray(row.retired_versions) ? row.retired_versions : [];
      const previous = retiredVersions.length ? retiredVersions[0] : null;
      const previousLabel = previousPricingLabel(current, previous);

      details.appendChild(createElement('span', {
        text: current
          ? `CURRENT PRICING — ${pricingRateSummary(current)} — Pricing ID: ${compactPricingId(current)} — ${pricingVersionTimingSummary(current)}`
          : referenceAvailable
            ? `CURRENT PRICING — no saved immutable version — curated reference ${reference.currency || 'USD'} input ${(reference.registry_rates_per_mtok || {}).input_per_mtok || '0'} / output ${(reference.registry_rates_per_mtok || {}).output_per_mtok || '0'} per MTok`
            : 'CURRENT PRICING — no effective saved rate'
      }));
      details.appendChild(createElement('span', {
        text: previous
          ? `${previousLabel} — ${pricingRateSummary(previous)} — Pricing ID: ${compactPricingId(previous)} — ${pricingVersionTimingSummary(previous)}`
          : 'PREVIOUS EFFECTIVE PRICING — none'
      }));
      details.appendChild(createElement('span', {
        text: scheduled
          ? `NEXT SCHEDULED PRICING — ${pricingRateSummary(scheduled)} — Pricing ID: ${compactPricingId(scheduled)} — ${pricingVersionTimingSummary(scheduled)}`
          : 'NEXT SCHEDULED PRICING — none'
      }));
      details.appendChild(createElement('span', {
        text: `Retired immutable versions retained: ${retiredVersions.length}`
      }));

      const edit = createElement('button', {
        className: 'secondary-button',
        type: 'button',
        text: referenceAvailable ? 'Create Initial Pricing Version' : 'Edit Pricing'
      });
      edit.addEventListener('click', async () => {
        ui.pricingModelSelect.value = String(row.model_id || '');
        try {
          await loadCurrentPricing(ui);
          setStatus(
            ui.pricingStatus,
            referenceAvailable
              ? `Curated reference loaded for ${providerPricingLabel(payload.provider_id)} / ${row.model_id}. Review the fields, then Save New Pricing Version to create the first immutable version.`
              : `Pricing editor loaded for ${providerPricingLabel(payload.provider_id)} / ${row.model_id}. New Provider Price defaults Effective From to now; choose Correct Existing Price only for a same-effective correction.`,
            'neutral'
          );
          ui.pricingModelSelect.focus();
        } catch (error) {
          setStatus(ui.pricingStatus, error.message, 'error');
        }
      });

      card.append(heading, details, edit);
      ui.pricingRegistryList.appendChild(card);
    }

    ui.pricingRegistryStatus.textContent =
      `Pricing registry loaded for ${providerPricingLabel(payload.provider_id)} / ${payload.service_tier || 'standard'} / ${payload.inference_scope || 'global'}. CURRENT PRICING is used now. PREVIOUS EFFECTIVE PRICING means an earlier effective period; SUPERSEDED SAME-EFFECTIVE VERSION means a later entry corrected the same effective period. REFERENCE AVAILABLE means curated baseline rates exist but no immutable version has been saved yet.`;
  }


  async function loadPricingRegistry(ui) {
    const provider = String(ui.providerSelect.value || '').trim();
    if (!provider) {
      ui.pricingRegistryList.replaceChildren();
      ui.pricingRegistryStatus.textContent = 'Select a provider to load its pricing registry.';
      return;
    }
    const params = new URLSearchParams({
      provider_id: provider,
      service_tier: ui.pricingServiceTierSelect.value,
      inference_scope: ui.pricingScopeSelect.value
    });
    const payload = await apiJson(`${API_ROOT}/pricing/registry?${params.toString()}`);
    renderPricingRegistry(ui, payload);
  }

  function hideCredentialReplaceConfirmation(ui) {
    ui.credentialReplaceConfirmation.hidden = true;
  }

  function hideCredentialRemoveConfirmation(ui) {
    ui.credentialRemoveOverlay.hidden = true;
  }

  function showCredentialRemoveConfirmation(ui) {
    ui.credentialRemoveOverlay.hidden = false;
    ui.cancelCredentialRemove.focus();
  }

  function managedCredentialAlreadyExists(ui) {
    const credential = ui.currentCredential;
    if (!credential || !Boolean(credential.managed_by_application)) return false;
    return String(credential.status || '').toLowerCase() !== 'missing';
  }

  function renderCredentialState(ui, credential) {
    ui.currentCredential = credential || null;
    hideCredentialReplaceConfirmation(ui);
    hideCredentialRemoveConfirmation(ui);

    if (!credential) {
      ui.credentialState.textContent = 'No provider selected';
      ui.saveCredential.disabled = true;
      ui.removeCredential.disabled = true;
      return;
    }

    const status = String(credential.status || 'unknown');
    const source = String(credential.source || '');
    const sourceLabel = source === 'windows_dpapi'
      ? 'Windows secure store'
      : source === 'environment'
        ? 'server/process environment'
        : '';

    ui.credentialState.textContent = sourceLabel
      ? `${status} — ${sourceLabel}`
      : status;

    const interactive = Boolean(credential.interactive_management_available);
    ui.saveCredential.disabled = !interactive || source === 'environment';
    ui.removeCredential.disabled = !interactive || !Boolean(credential.managed_by_application);
  }

  async function loadProviderProfile(ui, providerId) {
    const provider = String(providerId || '').trim();
    if (!provider) {
      populateModelSelect(ui, '', '');
      populatePricingModelSelect(ui, '', '');
      ui.serviceTierSelect.value = 'standard';
      ui.scopeSelect.value = 'global';
      ui.pricingServiceTierSelect.value = 'standard';
      ui.pricingScopeSelect.value = 'global';
      renderCredentialState(ui, null);
      renderPricing(ui, null, null, ui.currentPricingPolicy, null);
      ui.pricingRegistryList.replaceChildren();
      ui.pricingRegistryStatus.textContent = 'Select a provider to load its pricing registry.';
      return;
    }

    const configPayload = await apiJson(
      `${API_ROOT}/config?provider_id=${encodeURIComponent(provider)}`
    );
    const config = configPayload.config || {};
    ui.serviceTierSelect.value = config.service_tier || 'standard';
    ui.scopeSelect.value = config.inference_scope || 'global';
    populateModelSelect(ui, provider, config.model_id || '');
    ui.pricingServiceTierSelect.value = config.service_tier || 'standard';
    ui.pricingScopeSelect.value = config.inference_scope || 'global';
    populatePricingModelSelect(ui, provider, config.model_id || '');
    renderCredentialState(ui, configPayload.credential || null);

    if (configPayload.pricing_source_url) {
      ui.sourceUrl.value = configPayload.pricing_source_url;
      updatePricingLink(ui, configPayload.pricing_source_url);
    }

    const validation = configPayload.model_validation || {};
    setStatus(
      ui.configStatus,
      config.model_id
        ? Boolean(validation.accepted)
          ? `Saved ${provider} profile loaded with an accepted catalog model. Provider execution remains locked.`
          : `Saved ${provider} profile uses an unvalidated legacy model ID. Choose an accepted model before saving or creating a new project binding.`
        : `No saved ${provider} model profile yet. The curated default is selected but not saved.`,
      Boolean(config.model_id) && !Boolean(validation.accepted) ? 'error' : 'neutral'
    );
    await Promise.all([loadCurrentPricing(ui), loadPricingRegistry(ui)]);
  }

  async function commitProviderCredential(ui) {
    const provider = ui.providerSelect.value;
    const apiKey = ui.apiKeyInput.value.trim();
    if (!provider) throw new Error('Select a provider before saving an API key.');
    if (!apiKey) throw new Error('Enter an API key before saving.');

    hideCredentialReplaceConfirmation(ui);
    setStatus(ui.configStatus, 'Saving API key to the local secure store…', 'neutral');
    try {
      const response = await apiJson(`${API_ROOT}/credentials/${encodeURIComponent(provider)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ api_key: apiKey })
      });
      renderCredentialState(ui, response.credential || null);
      setStatus(
        ui.configStatus,
        'API key saved securely. The secret is not returned to the browser.',
        'success'
      );
      await loadProfileInventory(ui);
    } finally {
      ui.apiKeyInput.value = '';
    }
  }

  async function saveProviderCredential(ui) {
    const provider = ui.providerSelect.value;
    const apiKey = ui.apiKeyInput.value.trim();
    if (!provider) throw new Error('Select a provider before saving an API key.');
    if (!apiKey) throw new Error('Enter an API key before saving.');

    if (managedCredentialAlreadyExists(ui)) {
      ui.credentialReplaceMessage.textContent =
        'This provider already has an Italus-managed API key. Replacing it keeps the existing stored key in place until the new key is securely written. Continue?';
      ui.credentialReplaceConfirmation.hidden = false;
      setStatus(
        ui.configStatus,
        'API key replacement is waiting for confirmation.',
        'neutral'
      );
      ui.confirmCredentialReplace.focus();
      return;
    }

    await commitProviderCredential(ui);
  }

  async function removeProviderCredential(ui) {
    const provider = ui.providerSelect.value;
    if (!provider) throw new Error('Select a provider before removing a stored API key.');

    const response = await apiJson(`${API_ROOT}/credentials/${encodeURIComponent(provider)}`, {
      method: 'DELETE'
    });
    renderCredentialState(ui, response.credential || null);
    ui.apiKeyInput.value = '';
    setStatus(ui.configStatus, 'Italus-managed API key removed.', 'success');
    await loadProfileInventory(ui);
  }

  function credentialStateLabel(credential) {
    if (!credential) return 'missing';
    const status = String(credential.status || 'unknown');
    const source = String(credential.source || '');
    const sourceLabel = source === 'windows_dpapi'
      ? 'Windows secure store'
      : source === 'environment'
        ? 'server/process environment'
        : '';
    return sourceLabel ? `${status} — ${sourceLabel}` : status;
  }

  function hideProfileActionConfirmation(ui) {
    ui.pendingProfileAction = null;
    ui.profileActionOverlay.hidden = true;
  }

  function showProfileActionConfirmation(ui, action) {
    ui.pendingProfileAction = action;
    ui.profileActionTitle.textContent = action.kind === 'disassociate'
      ? 'Disassociate Provider Profile?'
      : 'Delete Provider Profile?';

    if (action.kind === 'disassociate') {
      ui.profileActionWarning.textContent =
        `Disassociate ${action.projectName} from ${action.providerId} / ${action.modelId}? ` +
        'The project and all of its content remain intact. The project will no longer have a provider/model binding. ' +
        'The stored API key is not deleted.';
      ui.confirmProfileAction.textContent = 'Disassociate Project';
    } else {
      ui.profileActionWarning.textContent =
        `Delete the saved ${action.providerId} / ${action.modelId} provider profile? ` +
        'This removes the saved provider/model configuration and any Italus-managed stored API key for that provider. ' +
        'The project, pricing history, and usage history remain intact. ' +
        'If you no longer have the deleted key, you will need to obtain or enter a provider API key again before future provider use. ' +
        'Environment-managed credentials are external and cannot be deleted by Italus.';
      ui.confirmProfileAction.textContent = 'Delete Profile and Stored API Key';
    }

    ui.profileActionOverlay.hidden = false;
    ui.cancelProfileAction.focus();
  }

  function renderProfileInventory(ui, profiles) {
    ui.profileList.replaceChildren();

    if (!profiles.length) {
      ui.profileList.appendChild(
        createElement('p', {
          className: 'provider-settings-note',
          text: 'No saved provider profiles.'
        })
      );
      setStatus(ui.profileStatus, 'No saved provider profiles.', 'neutral');
      return;
    }

    for (const profile of profiles) {
      const providerId = String(profile.provider_id || '');
      const modelId = String(profile.model_id || '');
      const card = createElement('article', { className: 'provider-profile-card' });

      const heading = createElement('h4', {
        text: `${providerId || 'provider'} / default ${modelId || 'model not set'}`
      });

      const meta = createElement('div', { className: 'provider-profile-meta' });
      meta.append(
        createElement('span', {
          text: `Service Tier: ${profile.service_tier || 'standard'}`
        }),
        createElement('span', {
          text: `Inference Scope: ${profile.inference_scope || 'global'}`
        }),
        createElement('span', {
          text: `Credential: ${credentialStateLabel(profile.credential)}`
        }),
        createElement('span', {
          text: `Credential Instance: ${
            profile.credential && profile.credential.credential_instance_id
              ? String(profile.credential.credential_instance_id)
              : 'not assigned'
          }`
        })
      );

      const associations = Array.isArray(profile.associations)
        ? profile.associations
        : [];
      const associationBlock = createElement('div', {
        className: 'provider-profile-associations'
      });
      associationBlock.appendChild(
        createElement('strong', {
          text: associations.length
            ? `Associated Projects (${associations.length})`
            : 'Associated Projects: none'
        })
      );

      if (associations.length) {
        const associationList = createElement('ul', {
          className: 'provider-profile-association-list'
        });

        for (const association of associations) {
          const item = createElement('li', {
            className: 'provider-profile-association'
          });
          const lock = association.lock || {};
          const locked = Boolean(lock.locked);
          const bindingInstance = String(association.binding_instance_id || '');
          const boundModelId = String(association.model_id || 'model not set');
          const projectLabel = createElement('span', {
            text: `${association.project_name || association.project_id} — ` +
              `Bound Model: ${boundModelId} — ` +
              `${association.lifecycle_state || 'unknown state'} — ` +
              `${locked ? `LOCKED (${lock.usage_event_count || 0} usage event(s))` : 'UNLOCKED'}` +
              `${bindingInstance ? ` — Binding ${bindingInstance}` : ''}`
          });

          const disassociate = createElement('button', {
            className: 'secondary-button',
            type: 'button',
            text: 'Disassociate'
          });
          disassociate.disabled = locked;
          disassociate.title = locked
            ? 'This project has provider usage and cannot be disassociated until a controlled migration workflow exists.'
            : 'Remove only this project provider/model binding. The project remains intact.';
          disassociate.addEventListener('click', () => {
            showProfileActionConfirmation(ui, {
              kind: 'disassociate',
              projectId: String(association.project_id || ''),
              projectName: String(
                association.project_name || association.project_id || 'project'
              ),
              providerId,
              modelId: String(association.model_id || modelId)
            });
          });

          item.append(projectLabel, disassociate);
          associationList.appendChild(item);
        }

        associationBlock.appendChild(associationList);
      }

      const actions = createElement('div', { className: 'provider-settings-actions' });
      const deleteProfile = createElement('button', {
        className: 'secondary-button provider-profile-delete',
        type: 'button',
        text: 'Delete Provider Profile'
      });
      deleteProfile.disabled = associations.length > 0;
      deleteProfile.title = associations.length
        ? 'Disassociate this profile from every project before deleting it.'
        : 'Delete this saved provider/model profile and its Italus-managed stored API key. Project and history remain intact.';
      deleteProfile.addEventListener('click', () => {
        showProfileActionConfirmation(ui, {
          kind: 'delete-profile',
          providerId,
          modelId
        });
      });
      actions.appendChild(deleteProfile);

      card.append(heading, meta, associationBlock, actions);
      ui.profileList.appendChild(card);
    }

    setStatus(
      ui.profileStatus,
      'Saved provider profiles and project associations loaded.',
      'neutral'
    );
  }

  async function loadProfileInventory(ui) {
    const payload = await apiJson(`${API_ROOT}/profiles`);
    const profiles = Array.isArray(payload.profiles) ? payload.profiles : [];
    renderProfileInventory(ui, profiles);
  }

  async function commitProfileAction(ui) {
    const action = ui.pendingProfileAction;
    if (!action) return;

    if (action.kind === 'disassociate') {
      const projectId = action.projectId;
      hideProfileActionConfirmation(ui);
      await apiJson(
        `${API_ROOT}/projects/${encodeURIComponent(projectId)}/binding`,
        { method: 'DELETE' }
      );
      await loadProfileInventory(ui);

      if (ui.projectSelect.value === projectId) {
        await loadProjectBinding(ui);
      }

      setStatus(
        ui.profileStatus,
        `Project ${action.projectName} disassociated. The project remains intact and no API key was deleted.`,
        'success'
      );
      return;
    }

    if (action.kind === 'delete-profile') {
      const providerId = action.providerId;
      hideProfileActionConfirmation(ui);
      const result = await apiJson(
        `${API_ROOT}/config/${encodeURIComponent(providerId)}`,
        { method: 'DELETE' }
      );

      if (ui.providerSelect.value === providerId) {
        await loadProviderProfile(ui, providerId);
      }
      await loadProfileInventory(ui);

      const credentialResult = result.credential_deleted
        ? 'The Italus-managed stored API key was also removed.'
        : result.external_credential_preserved
          ? 'The provider profile was deleted; its environment-managed credential remains external to Italus.'
          : 'No Italus-managed stored API key was present.';

      setStatus(
        ui.profileStatus,
        `Provider profile ${providerId} deleted. ${credentialResult} Project, pricing history, and usage history were preserved.`,
        'success'
      );
    }
  }

  async function loadProjects(ui) {
    const payload = await apiJson('/api/projects?state=active');
    const projects = Array.isArray(payload.projects) ? payload.projects : [];

    const previous = ui.projectSelect.value;
    ui.projectSelect.replaceChildren();
    addOption(ui.projectSelect, '', 'Select project', false);

    for (const project of projects) {
      const projectId = String(project.project_id || '');
      const manifest = project.manifest || {};
      const projectName = String(manifest.project_name || projectId);
      if (projectId) addOption(ui.projectSelect, projectId, projectName, false);
    }

    if (previous && projects.some((item) => String(item.project_id || '') === previous)) {
      ui.projectSelect.value = previous;
    }

    renderProjectSelectorOptions(ui);

    if (!ui.projectSelect.value) {
      ui.projectBindingState.textContent = 'Select a project';
      ui.projectLockState.textContent = 'Not loaded';
      ui.bindProject.disabled = true;
      resetProjectPreflight(ui, 'Not run');
    }
  }

  function resetProjectPreflight(ui, message) {
    ui.projectPreflightState.textContent = String(message || 'Not run');
    ui.runProjectPreflight.disabled = !ui.projectSelect.value;
  }

  function preflightSummary(payload) {
    const result = String(payload && payload.result || 'BLOCKED');
    const binding = payload && payload.binding ? payload.binding : {};
    const providerId = String(binding.provider_id || 'unknown');
    const modelId = String(binding.model_id || 'unknown');
    const blockers = Array.isArray(payload && payload.blockers) ? payload.blockers : [];
    const warnings = Array.isArray(payload && payload.warnings) ? payload.warnings : [];
    const blockerText = blockers.length
      ? ` Blockers: ${blockers.map((item) => String(item.message || item.code || 'blocked')).join(' | ')}`
      : '';
    const warningText = warnings.length
      ? ` Warnings: ${warnings.map((item) => String(item.message || item.code || 'warning')).join(' | ')}`
      : '';
    return `${result} — ${providerId} / ${modelId}.${blockerText}${warningText}`;
  }

  async function runProjectProviderPreflight(ui) {
    const projectId = String(ui.projectSelect.value || '').trim();
    if (!projectId) throw new Error('Select a project before validating provider setup.');

    ui.runProjectPreflight.disabled = true;
    ui.projectPreflightState.textContent = 'Running…';
    setStatus(
      ui.projectStatus,
      'Validating project provider setup without generation or usage recording…',
      'neutral'
    );

    const payload = await apiJson(
      `${API_ROOT}/projects/${encodeURIComponent(projectId)}/preflight`,
      { method: 'POST' }
    );

    ui.projectPreflightState.textContent = preflightSummary(payload);
    const passed = Boolean(payload && payload.ready);
    setStatus(
      ui.projectStatus,
      passed
        ? 'Provider setup validation passed. Credential authentication, exact model availability, and effective pricing are valid. Generation remains locked.'
        : 'Provider setup validation is blocked. Review the blocker details shown in Provider Setup Status.',
      passed ? 'success' : 'error'
    );
    ui.runProjectPreflight.disabled = false;
  }

  async function loadProjectBinding(ui) {
    const projectId = ui.projectSelect.value;
    if (!projectId) {
      ui.projectBindingState.textContent = 'Select a project';
      ui.projectLockState.textContent = 'Not loaded';
      ui.bindProject.disabled = true;
      resetProjectPreflight(ui, 'Not run');
      setStatus(ui.projectStatus, 'No project selected.', 'neutral');
      return;
    }

    const payload = await apiJson(
      `${API_ROOT}/projects/${encodeURIComponent(projectId)}/binding`
    );
    const binding = payload.binding || null;
    const lock = payload.lock || {};

    ui.projectBindingState.textContent = binding
      ? `${binding.provider_id || 'unknown'} / ${binding.model_id || 'unknown'}`
      : 'No provider bound';

    ui.projectLockState.textContent = lock.locked
      ? `LOCKED — ${lock.usage_event_count || 0} usage event(s)`
      : 'UNLOCKED — may change before first provider usage';

    ui.bindProject.disabled = Boolean(lock.locked);
    resetProjectPreflight(
      ui,
      binding ? 'Not run for current binding' : 'Bind a provider before validation'
    );
    ui.runProjectPreflight.disabled = !binding;
    setStatus(
      ui.projectStatus,
      binding
        ? 'Project-local provider/model binding loaded.'
        : 'Select a saved accepted provider profile and bind it to this project before later provider execution.',
      'neutral'
    );
  }

  async function saveProjectBinding(ui) {
    const projectId = ui.projectSelect.value;
    const providerId = ui.providerSelect.value;
    if (!projectId) throw new Error('Select a project to bind.');
    if (!providerId) throw new Error('Select and save a provider profile first.');

    setStatus(ui.projectStatus, 'Saving project-local provider/model binding…', 'neutral');
    const payload = await apiJson(
      `${API_ROOT}/projects/${encodeURIComponent(projectId)}/binding`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider_id: providerId })
      }
    );

    const binding = payload.binding || null;
    const lock = payload.lock || {};
    ui.projectBindingState.textContent = binding
      ? `${binding.provider_id || 'unknown'} / ${binding.model_id || 'unknown'}`
      : 'No provider bound';
    ui.projectLockState.textContent = lock.locked
      ? `LOCKED — ${lock.usage_event_count || 0} usage event(s)`
      : 'UNLOCKED — may change before first provider usage';
    ui.bindProject.disabled = Boolean(lock.locked);
    resetProjectPreflight(
      ui,
      binding ? 'Not run for current binding' : 'Bind a provider before validation'
    );
    ui.runProjectPreflight.disabled = !binding;
    setStatus(
      ui.projectStatus,
      'Project provider/model binding saved with an accepted catalog model. Validate the project provider setup before later execution; generation remains locked.',
      'success'
    );
    await loadProfileInventory(ui);
  }

  async function loadCatalogAndConfig(ui) {
    const [catalogPayload, configPayload] = await Promise.all([
      apiJson(`${API_ROOT}/catalog`),
      apiJson(`${API_ROOT}/config`)
    ]);

    ui.providerSelect.replaceChildren();
    addOption(ui.providerSelect, '', 'Select provider', false);

    const providers = Array.isArray(catalogPayload.providers) ? catalogPayload.providers : [];
    ui.catalogProviders = new Map(
      providers.map((provider) => [String(provider.provider_id || ''), provider])
    );
    for (const provider of providers) {
      const suffix = provider.configuration_enabled
        ? ''
        : ' — Experimental / disabled';
      addOption(
        ui.providerSelect,
        provider.provider_id,
        `${provider.label}${suffix}`,
        !provider.configuration_enabled
      );
    }

    addOption(
      ui.providerSelect,
      '__additional__',
      'Additional providers — model catalog source required',
      true
    );

    const config = configPayload.config || {};
    if (config.provider_id) ui.providerSelect.value = String(config.provider_id);

    if (ui.providerSelect.value) {
      await loadProviderProfile(ui, ui.providerSelect.value);
    } else {
      populateModelSelect(ui, '', '');
      renderCredentialState(ui, null);
      setStatus(ui.configStatus, 'No provider profile selected.', 'neutral');
    }

    await loadProjects(ui);
    if (ui.projectSelect.value) await loadProjectBinding(ui);
    await loadProfileInventory(ui);
  }

  async function saveProviderConfig(ui) {
    const payload = {
      provider_id: ui.providerSelect.value,
      model_id: ui.modelSelect.value.trim(),
      service_tier: ui.serviceTierSelect.value,
      inference_scope: ui.scopeSelect.value
    };

    if (!payload.provider_id) {
      throw new Error('Select a provider before saving a provider profile.');
    }
    if (!payload.model_id) {
      throw new Error('Select a curated model before saving the provider profile.');
    }
    if (!catalogModel(ui, payload.provider_id, payload.model_id)) {
      throw new Error(
        'The selected model ID is not accepted by the curated direct-provider catalog. Choose an accepted model before saving.'
      );
    }

    setStatus(ui.configStatus, 'Saving provider configuration…', 'neutral');
    const response = await apiJson(`${API_ROOT}/config`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    renderCredentialState(ui, response.credential || null);
    const savedConfig = response.config || payload;
    populateModelSelect(ui, payload.provider_id, savedConfig.model_id || payload.model_id);
    if (response.pricing_source_url && !ui.sourceUrl.value.trim()) {
      ui.sourceUrl.value = response.pricing_source_url;
    }
    updatePricingLink(ui, ui.sourceUrl.value || response.pricing_source_url);
    setStatus(
      ui.configStatus,
      'Provider profile saved with an accepted direct-provider model ID. Other provider profiles are preserved. Configure pricing for the models you plan to use, then bind the profile to a project and validate the project provider setup. Generation remains locked.',
      'success'
    );
    await loadProfileInventory(ui);
  }

  async function savePricingVersion(ui) {
    const payload = collectPricingPayload(ui);
    const base = ui.pricingEditBase || null;
    const hasBase = Boolean(base && base.pricing_version_id);
    const mode = hasBase
      ? String(ui.pricingChangeTypeSelect.value || 'new_price')
      : 'initial';

    setStatus(ui.pricingStatus, 'Saving immutable pricing version…', 'neutral');
    if (!payload.provider_id || !payload.model_id) {
      throw new Error('Select a provider and Pricing Model before saving pricing.');
    }
    if (!payload.effective_from) {
      throw new Error('Provider Price Effective Date is required.');
    }

    if (hasBase) {
      const baseEffective = toIso(base.effective_from || '');
      if (mode === 'correction' && payload.effective_from !== baseEffective) {
        throw new Error(
          'Correction mode must keep the effective date of the version being corrected.'
        );
      }
      if (mode === 'new_price' && payload.effective_from === baseEffective) {
        throw new Error(
          'New Provider Price must use a different effective date. Choose Correct Existing Price if this is intentionally a same-effective correction.'
        );
      }
    }

    const response = await apiJson(`${API_ROOT}/pricing/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    await Promise.all([loadCurrentPricing(ui), loadPricingRegistry(ui)]);
    const lifecycle = String(response.lifecycle_status || 'SAVED');
    const created = response.pricing || {};
    const actionLabel = mode === 'correction'
      ? 'CORRECTED SAME-EFFECTIVE VERSION'
      : mode === 'new_price'
        ? 'NEW PROVIDER PRICE'
        : 'INITIAL PRICING VERSION';
    setStatus(
      ui.pricingStatus,
      `Created ${actionLabel}: Pricing ID ${compactPricingId(created)} for ${providerPricingLabel(payload.provider_id)} / ${payload.model_id} / ${payload.service_tier} / ${payload.inference_scope}. Effective From ${formatHumanDateTime(created.effective_from)}. Entered in Italus ${formatHumanDateTime(created.created_at)}. Lifecycle: ${lifecycle}. Existing immutable versions and historical usage were not modified.`,
      'success'
    );
  }

  async function showPricingHistory(ui) {
    const provider = String(ui.providerSelect.value || '').trim();
    const model = String(ui.pricingModelSelect.value || '').trim();
    ui.historyList.replaceChildren();

    if (provider && model) {
      const params = new URLSearchParams({
        provider_id: provider,
        service_tier: ui.pricingServiceTierSelect.value,
        inference_scope: ui.pricingScopeSelect.value
      });
      const registry = await apiJson(`${API_ROOT}/pricing/registry?${params.toString()}`);
      const rows = Array.isArray(registry.models) ? registry.models : [];
      const row = rows.find((item) => String((item || {}).model_id || '') === model) || null;
      const versions = row && Array.isArray(row.versions) ? row.versions : [];
      const current = row ? row.current_pricing || null : null;
      const retired = row && Array.isArray(row.retired_versions) ? row.retired_versions : [];
      const previous = retired.length ? retired[0] : null;
      const previousId = previous ? String(previous.pricing_version_id || '') : '';

      if (versions.length) {
        for (const record of versions) {
          const item = createElement('li');
          const recordId = String(record.pricing_version_id || '');
          let lifecycle = String(record.lifecycle_status || 'VERSION');
          if (current && recordId === String(current.pricing_version_id || '')) {
            lifecycle = 'CURRENT PRICING';
          } else if (previous && recordId === previousId) {
            lifecycle = previousPricingLabel(current, previous);
          } else if (lifecycle === 'SCHEDULED') {
            lifecycle = 'SCHEDULED PRICING';
          } else if (lifecycle === 'RETIRED') {
            lifecycle = 'RETIRED PRICING';
          }
          item.textContent =
            `${lifecycle} — ${pricingRateSummary(record)} — Pricing ID: ${compactPricingId(record)} — ${pricingVersionTimingSummary(record)}`;
          ui.historyList.appendChild(item);
        }
        ui.historyList.hidden = false;
        return;
      }
    }

    const params = new URLSearchParams();
    if (provider) params.set('provider_id', provider);
    if (model) params.set('model_id', model);
    params.set('limit', '50');

    const payload = await apiJson(`${API_ROOT}/pricing/history?${params.toString()}`);
    const records = Array.isArray(payload.history) ? payload.history : [];
    if (!records.length) {
      ui.historyList.appendChild(createElement('li', { text: 'No pricing history recorded.' }));
    } else {
      for (const record of records) {
        const item = createElement('li');
        item.textContent =
          `Pricing ID: ${compactPricingId(record)} — ${pricingDisplayLabel(record)} — Effective From ${formatHumanDateTime(record.effective_from)} — Entered in Italus ${formatHumanDateTime(record.created_at)}`;
        ui.historyList.appendChild(item);
      }
    }
    ui.historyList.hidden = false;
  }

  async function initialize() {
    const placeholder = findProviderMenuPlaceholder();
    const layer = document.getElementById('studio-modal-layer');
    if (!placeholder || !layer) return;

    const menuButton = createElement('button', {
      className: 'theme-menu-action provider-menu-action',
      type: 'button',
      text: 'Provider Settings'
    });
    menuButton.setAttribute('data-provider-settings-open', '');
    placeholder.replaceWith(menuButton);

    const ui = buildModal(layer);

    ui.closeButton.addEventListener('click', () => closeProviderSettings(ui.modal, layer));
    ui.footerClose.addEventListener('click', () => closeProviderSettings(ui.modal, layer));

    menuButton.addEventListener('click', async () => {
      hideCredentialRemoveConfirmation(ui);
      hideProfileActionConfirmation(ui);
      hideDateTimePicker(ui);
      openProviderSettings(ui.modal, layer);
      try {
        await loadPricingPolicy(ui);
        await loadCatalogAndConfig(ui);
      } catch (error) {
        ui.providerSelect.replaceChildren();
        addOption(
          ui.providerSelect,
          '',
          'Provider API unavailable — restart Italus backend',
          true
        );
        ui.credentialState.textContent = 'Provider API unavailable';
        setStatus(ui.configStatus, providerApiErrorMessage(error), 'error');
      }
    });

    ui.providerSelect.addEventListener('change', async () => {
      ui.apiKeyInput.value = '';
      hideCredentialReplaceConfirmation(ui);
      hideCredentialRemoveConfirmation(ui);
      try {
        await loadProviderProfile(ui, ui.providerSelect.value);
      } catch (error) {
        setStatus(ui.configStatus, providerApiErrorMessage(error), 'error');
      }
    });

    ui.projectSelectorTrigger.addEventListener('click', () => {
      const open = ui.projectSelectorTrigger.getAttribute('aria-expanded') !== 'true';
      setProjectSelectorOpen(ui, open);
    });

    ui.projectSelectorTrigger.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setProjectSelectorOpen(ui, true);
        focusAdjacentProjectChoice(ui, 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        setProjectSelectorOpen(ui, true);
        focusAdjacentProjectChoice(ui, -1);
      } else if (event.key === 'Escape') {
        setProjectSelectorOpen(ui, false);
      }
    });

    ui.projectSelectorList.addEventListener('keydown', (event) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        focusAdjacentProjectChoice(ui, 1);
      } else if (event.key === 'ArrowUp') {
        event.preventDefault();
        focusAdjacentProjectChoice(ui, -1);
      } else if (event.key === 'Escape') {
        event.preventDefault();
        setProjectSelectorOpen(ui, false);
        ui.projectSelectorTrigger.focus();
      }
    });

    document.addEventListener('click', (event) => {
      if (!ui.projectSelectorRoot.contains(event.target)) {
        setProjectSelectorOpen(ui, false);
      }
    });

    ui.projectSelect.addEventListener('change', async () => {
      syncProjectSelectorDisplay(ui);
      try {
        await loadProjectBinding(ui);
      } catch (error) {
        setStatus(ui.projectStatus, error.message, 'error');
      }
    });

    ui.modelSelect.addEventListener('change', () => {
      updateModelNote(ui);
    });

    for (const control of [ui.pricingModelSelect, ui.pricingServiceTierSelect, ui.pricingScopeSelect]) {
      control.addEventListener('change', async () => {
        try {
          await Promise.all([loadCurrentPricing(ui), loadPricingRegistry(ui)]);
        } catch (error) {
          setStatus(ui.pricingStatus, error.message, 'error');
        }
      });
    }

    ui.saveConfig.addEventListener('click', async () => {
      try {
        await saveProviderConfig(ui);
      } catch (error) {
        setStatus(ui.configStatus, error.message, 'error');
      }
    });

    ui.saveCredential.addEventListener('click', async () => {
      try {
        await saveProviderCredential(ui);
      } catch (error) {
        ui.apiKeyInput.value = '';
        hideCredentialReplaceConfirmation(ui);
        setStatus(ui.configStatus, error.message, 'error');
      }
    });

    ui.cancelCredentialReplace.addEventListener('click', () => {
      hideCredentialReplaceConfirmation(ui);
      ui.apiKeyInput.value = '';
      setStatus(
        ui.configStatus,
        'API key replacement cancelled. The existing stored key remains configured.',
        'neutral'
      );
      ui.saveCredential.focus();
    });

    ui.confirmCredentialReplace.addEventListener('click', async () => {
      try {
        await commitProviderCredential(ui);
      } catch (error) {
        hideCredentialReplaceConfirmation(ui);
        setStatus(ui.configStatus, error.message, 'error');
      }
    });

    ui.apiKeyInput.addEventListener('input', () => {
      if (!ui.credentialReplaceConfirmation.hidden) {
        hideCredentialReplaceConfirmation(ui);
        setStatus(
          ui.configStatus,
          'API key replacement confirmation reset because the entered key changed.',
          'neutral'
        );
      }
    });

    ui.removeCredential.addEventListener('click', () => {
      hideCredentialReplaceConfirmation(ui);
      ui.apiKeyInput.value = '';
      showCredentialRemoveConfirmation(ui);
      setStatus(
        ui.configStatus,
        'API key removal is waiting for confirmation.',
        'neutral'
      );
    });

    ui.cancelCredentialRemove.addEventListener('click', () => {
      hideCredentialRemoveConfirmation(ui);
      setStatus(
        ui.configStatus,
        'API key removal cancelled. The stored key remains configured.',
        'neutral'
      );
      ui.removeCredential.focus();
    });

    ui.confirmCredentialRemove.addEventListener('click', async () => {
      try {
        await removeProviderCredential(ui);
      } catch (error) {
        hideCredentialRemoveConfirmation(ui);
        setStatus(ui.configStatus, error.message, 'error');
      }
    });

    ui.cancelProfileAction.addEventListener('click', () => {
      hideProfileActionConfirmation(ui);
      setStatus(ui.profileStatus, 'Provider profile action cancelled.', 'neutral');
    });

    ui.confirmProfileAction.addEventListener('click', async () => {
      try {
        await commitProfileAction(ui);
      } catch (error) {
        hideProfileActionConfirmation(ui);
        setStatus(ui.profileStatus, error.message, 'error');
      }
    });

    ui.bindProject.addEventListener('click', async () => {
      try {
        await saveProjectBinding(ui);
      } catch (error) {
        setStatus(ui.projectStatus, error.message, 'error');
      }
    });

    ui.runProjectPreflight.addEventListener('click', async () => {
      try {
        await runProjectProviderPreflight(ui);
      } catch (error) {
        ui.projectPreflightState.textContent = 'BLOCKED — provider setup validation request failed';
        ui.runProjectPreflight.disabled = false;
        setStatus(ui.projectStatus, error.message, 'error');
      }
    });

    const openEffectivePicker = () => {
      if (ui.effectiveFromPicker.button.disabled) {
        setStatus(
          ui.pricingStatus,
          'Correction mode keeps the original effective date. Choose New Provider Price to enter a different effective date.',
          'neutral'
        );
        return;
      }
      openDateTimePicker(ui, ui.effectiveFromPicker, 'Provider Price Effective Date');
    };
    const openVerifiedPicker = () => {
      openDateTimePicker(ui, ui.verifiedAtPicker, 'Rates Checked / Verified On');
    };

    ui.effectiveFromPicker.display.addEventListener('click', openEffectivePicker);
    ui.effectiveFromPicker.button.addEventListener('click', openEffectivePicker);
    ui.verifiedAtPicker.display.addEventListener('click', openVerifiedPicker);
    ui.verifiedAtPicker.button.addEventListener('click', openVerifiedPicker);

    ui.cancelDateTime.addEventListener('click', () => {
      hideDateTimePicker(ui);
    });
    ui.confirmDateTime.addEventListener('click', () => {
      commitDateTimePicker(ui);
    });

    ui.dateTimeOverlay.addEventListener('click', (event) => {
      if (event.target === ui.dateTimeOverlay) {
        hideDateTimePicker(ui);
      }
    });

    ui.dateTimeDialog.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        hideDateTimePicker(ui);
      }
    });

    ui.pricingChangeTypeSelect.addEventListener('change', () => {
      applyPricingUpdateType(ui, { resetEffective: true, resetVerified: true });
    });

    ui.savePricing.addEventListener('click', async () => {
      try {
        await savePricingVersion(ui);
      } catch (error) {
        setStatus(ui.pricingStatus, error.message, 'error');
      }
    });

    ui.savePricingPolicy.addEventListener('click', async () => {
      try {
        await savePricingReviewPolicy(ui);
      } catch (error) {
        setStatus(ui.pricingStatus, error.message, 'error');
      }
    });

    ui.viewHistory.addEventListener('click', async () => {
      try {
        await showPricingHistory(ui);
      } catch (error) {
        setStatus(ui.pricingStatus, error.message, 'error');
      }
    });

    ui.discardPricing.addEventListener('click', async () => {
      try {
        await loadCurrentPricing(ui);
        setStatus(ui.pricingStatus, 'Unsaved pricing edits discarded.', 'neutral');
      } catch (error) {
        setStatus(ui.pricingStatus, error.message, 'error');
      }
    });
  }

  initialize().catch(() => {
    // Provider Settings must never break the landing page if its optional API
    // surface is unavailable.
  });
})();
