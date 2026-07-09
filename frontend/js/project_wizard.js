/*
Project wizard helpers for the landing-page setup flow.

This module prepares backend-compatible project payloads, estimates budget
locally, and hydrates the setup form when an existing project is resumed.
*/
(function () {
  const TOKEN_MULTIPLIER = 1.3;
  const WARNING_THRESHOLD = 0.85;

  function toPositiveInteger(value, fallback) {
    const parsed = Number.parseInt(value, 10);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function collectProjectBasics(form) {
    const formData = new FormData(form);
    const bookCount = toPositiveInteger(formData.get('book_count'), 1);
    const chaptersPerBook = toPositiveInteger(formData.get('chapters_per_book'), 1);
    const targetWordsPerChapter = toPositiveInteger(formData.get('target_words_per_chapter'), 1000);
    const tokenBudgetTotal = toPositiveInteger(formData.get('token_budget_total'), 1);
    const tokenBudgetPerGeneration = toPositiveInteger(formData.get('token_budget_per_generation'), 1);

    return {
      project_name: String(formData.get('project_name') || '').trim(),
      project_kind: String(formData.get('project_kind') || 'single_book'),
      book_count: bookCount,
      chapters_per_book: chaptersPerBook,
      target_words_per_chapter: targetWordsPerChapter,
      target_words_per_book: chaptersPerBook * targetWordsPerChapter,
      target_total_words: bookCount * chaptersPerBook * targetWordsPerChapter,
      token_budget_total: tokenBudgetTotal,
      token_budget_per_generation: tokenBudgetPerGeneration,
      genre: String(formData.get('genre') || 'historical_epic'),
      template_id: String(formData.get('genre') || 'historical_epic'),
      engine_id: 'italus',
      ai_provider: 'claude'
    };
  }

  function buildProjectPayload(form, options) {
    const payload = collectProjectBasics(form);
    payload.continue_to_canon = Boolean(options && options.continueToCanon);
    return payload;
  }

  function estimateBudget(projectBasics) {
    const estimatedTokensTotal = Math.ceil(projectBasics.target_total_words * TOKEN_MULTIPLIER);
    const estimatedTokensPerBook = Math.ceil(projectBasics.target_words_per_book * TOKEN_MULTIPLIER);
    const estimatedTokensPerChapter = Math.ceil(projectBasics.target_words_per_chapter * TOKEN_MULTIPLIER);
    const estimatedGenerationPasses = Math.max(
      1,
      Math.ceil(estimatedTokensTotal / projectBasics.token_budget_per_generation)
    );

    let status = 'OK';
    if (estimatedTokensTotal > projectBasics.token_budget_total) {
      status = 'EXCEEDS_BUDGET';
    } else if (estimatedTokensTotal >= projectBasics.token_budget_total * WARNING_THRESHOLD) {
      status = 'WARNING';
    }

    return {
      estimated_words_per_book: projectBasics.target_words_per_book,
      estimated_words_total: projectBasics.target_total_words,
      estimated_tokens_per_book: estimatedTokensPerBook,
      estimated_tokens_total: estimatedTokensTotal,
      estimated_tokens_per_chapter: estimatedTokensPerChapter,
      estimated_generation_passes_required: estimatedGenerationPasses,
      token_budget_status: status,
      recommendations: []
    };
  }

  function normalizeBackendBudgetPlan(responseOrPlan) {
    if (!responseOrPlan) return null;
    return responseOrPlan.budget_plan || responseOrPlan;
  }

  function formatNumber(value) {
    return new Intl.NumberFormat().format(Number(value || 0));
  }

  function renderBudgetPreview(target, estimate) {
    if (!target || !estimate) return;

    const plan = normalizeBackendBudgetPlan(estimate);
    const status = plan.token_budget_status || 'OK';
    const statusText = {
      OK: 'Within planning budget.',
      WARNING: 'Approaching the total token budget.',
      EXCEEDS_BUDGET: 'Projected story size exceeds the total token budget.'
    }[status] || 'Budget status unavailable.';

    const recommendations = Array.isArray(plan.recommendations) && plan.recommendations.length
      ? `<ul class="budget-recommendations">${plan.recommendations.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`
      : '';

    target.dataset.status = status;
    target.innerHTML = `
      <strong>Budget Estimate: ${escapeHtml(status)}</strong>
      <span>${escapeHtml(statusText)}</span>
      <dl>
        <div><dt>Total Words</dt><dd>${formatNumber(plan.estimated_words_total || plan.target_total_words)}</dd></div>
        <div><dt>Total Tokens</dt><dd>${formatNumber(plan.estimated_tokens_total)}</dd></div>
        <div><dt>Tokens / Chapter</dt><dd>${formatNumber(plan.estimated_tokens_per_chapter)}</dd></div>
        <div><dt>Generation Passes</dt><dd>${formatNumber(plan.estimated_generation_passes_required)}</dd></div>
      </dl>
      ${recommendations}
    `;
  }

  function hydrateProjectForm(form, projectPayload) {
    if (!form || !projectPayload || !projectPayload.manifest) return;

    const manifest = projectPayload.manifest;
    setValue(form, 'project_name', manifest.project_name);
    setValue(form, 'project_kind', manifest.project_kind);
    setValue(form, 'book_count', manifest.book_count);
    setValue(form, 'chapters_per_book', manifest.chapters_per_book);
    setValue(form, 'target_words_per_chapter', manifest.target_words_per_chapter);
    setValue(form, 'token_budget_total', manifest.token_budget_total);
    setValue(form, 'token_budget_per_generation', manifest.token_budget_per_generation);
    setValue(form, 'genre', manifest.genre);
  }

  function resetProjectForm(form) {
    if (!form) return;
    form.reset();
    setValue(form, 'book_count', 1);
    setValue(form, 'chapters_per_book', 40);
    setValue(form, 'target_words_per_chapter', 4000);
    setValue(form, 'token_budget_total', 250000);
    setValue(form, 'token_budget_per_generation', 12000);
    setValue(form, 'genre', 'historical_epic');
    setValue(form, 'project_kind', 'single_book');
  }

  function setValue(form, fieldName, value) {
    const field = form.elements[fieldName];
    if (!field || value === undefined || value === null) return;
    field.value = value;
  }

  window.ItalusProjectWizard = {
    buildProjectPayload,
    collectProjectBasics,
    estimateBudget,
    normalizeBackendBudgetPlan,
    renderBudgetPreview,
    hydrateProjectForm,
    resetProjectForm,
    escapeHtml
  };
})();
