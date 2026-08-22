(async (page) => {
  // Replaced exactly once by scripts/validate_insights_exports.py. Playwright
  // run-code intentionally does not expose Node environment variables here.
  const outputDir = __REDDIT_VOC_EXPORT_OUTPUT_DIR__;
  if (!outputDir || typeof outputDir !== 'string') throw new Error('export output directory is required');

  const baseUrlMatch = page.url().match(/^(https?:\/\/[^/]+)/);
  if (!baseUrlMatch) throw new Error(`cannot determine base URL from ${page.url()}`);
  const baseUrl = baseUrlMatch[1];
  const browserErrors = [];
  const sameOriginHttpFailures = [];
  const externalRequests = [];
  page.on('pageerror', (error) => browserErrors.push(`pageerror:${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error') browserErrors.push(`console-error:${message.text()}`);
  });
  page.on('requestfailed', (request) => browserErrors.push(`requestfailed:${request.method()}:${request.url()}`));
  page.on('response', (observedResponse) => {
    const observedUrl = observedResponse.url();
    const status = observedResponse.status();
    if (observedUrl.startsWith(baseUrl) && status >= 400) {
      sameOriginHttpFailures.push(`${status}:${observedUrl}`);
    }
  });
  page.on('request', (request) => {
    const observedUrl = request.url();
    if (observedUrl.startsWith('http') && !observedUrl.startsWith(baseUrl)) {
      externalRequests.push(observedUrl);
    }
  });
  const sha256Text = async (raw) => page.evaluate(async (input) => {
    if (!globalThis.crypto?.subtle) throw new Error('browser SHA-256 unavailable');
    const digest = await globalThis.crypto.subtle.digest(
      'SHA-256',
      new TextEncoder().encode(input),
    );
    return [...new Uint8Array(digest)]
      .map((value) => value.toString(16).padStart(2, '0'))
      .join('');
  }, raw);
  const fetchJson = async (path) => {
    const response = await page.request.get(`${baseUrl}${path}`, { failOnStatusCode: false });
    if (response.status() !== 200) throw new Error(`${path} HTTP ${response.status()}`);
    const raw = await response.text();
    return { value: JSON.parse(raw), sha256: await sha256Text(raw) };
  };

  await page.setViewportSize({ width: 1440, height: 1000 });
  const response = await page.goto(`${baseUrl}/dashboard/reports`, {
    waitUntil: 'domcontentloaded',
    timeout: 20_000,
  });
  if (response?.status() !== 200) throw new Error(`reports route returned HTTP ${response?.status() ?? 0}`);
  await page.waitForLoadState('networkidle', { timeout: 10_000 });
  await page.getByRole('heading', { name: '舆情报告', exact: true }).waitFor();

  const releaseMarkerResult = await fetchJson('/release.json');
  const pointerResult = await fetchJson('/data/reddit-voc/current-release.json');
  const pointer = pointerResult.value;
  const reportsBinding = pointer.datasets?.reports;
  if (!reportsBinding?.manifest_path || !reportsBinding?.dataset_version) {
    throw new Error('reports release binding is missing');
  }
  const reportManifestResult = await fetchJson(`/${reportsBinding.manifest_path}`);
  if (reportManifestResult.sha256 !== reportsBinding.public_manifest_sha256) {
    throw new Error('reports manifest SHA mismatch');
  }
  const manifestDir = reportsBinding.manifest_path.slice(0, reportsBinding.manifest_path.lastIndexOf('/'));
  const reportIndexResult = await fetchJson(`/${manifestDir}/report-index.json`);
  const dailyBinding = reportIndexResult.value.reports?.daily
    ?? reportIndexResult.value.current?.daily;
  const dailyArtifactPath = dailyBinding?.artifact_path ?? dailyBinding?.path;
  if (!dailyArtifactPath) throw new Error('latest complete daily report binding is missing');
  const reportDocumentResult = await fetchJson(`/${manifestDir}/${dailyArtifactPath}`);

  const historicalPeriodSelect = page.getByRole('combobox', { name: '选择历史报告周期', exact: true });
  const dailyButton = page.locator('[aria-label="报告周期"] button').filter({ hasText: '日报' });
  if (await historicalPeriodSelect.count() !== 1 || await dailyButton.count() !== 1) {
    throw new Error('unique latest complete daily report controls are missing');
  }
  if (await historicalPeriodSelect.locator('option[value="current"]').count() !== 1) {
    throw new Error('latest complete report option is missing');
  }
  const pageText = await page.locator('body').innerText();
  if (pageText.includes('当前闭合期') || pageText.includes('闭合归档')) {
    throw new Error('legacy report collection terminology is still visible');
  }
  await dailyButton.click();
  await historicalPeriodSelect.selectOption('current');

  const exportButton = page.getByRole('button', { name: '导出', exact: true });
  if (await exportButton.count() !== 1) throw new Error(`expected one report export button, got ${await exportButton.count()}`);

  const formats = [
    { key: 'csv', label: '导出 CSV', filename: 'report-latest-complete-daily.csv', timeout: 30_000 },
    { key: 'pdf', label: '导出 PDF', filename: 'report-latest-complete-daily.pdf', timeout: 120_000 },
    { key: 'pptx', label: '导出 PPT', filename: 'report-latest-complete-daily.pptx', timeout: 120_000 },
    { key: 'docx', label: '导出 Word', filename: 'report-latest-complete-daily.docx', timeout: 60_000 },
  ];
  const downloads = {};
  for (const format of formats) {
    await exportButton.click();
    const downloadPromise = page.waitForEvent('download', { timeout: format.timeout });
    await page.getByRole('button', { name: format.label, exact: true }).click();
    const download = await downloadPromise;
    const failure = await download.failure();
    if (failure !== null) throw new Error(`${format.key} download failed: ${failure}`);
    await download.saveAs(`${outputDir}/${format.filename}`);
    downloads[format.key] = {
      suggestedFilename: download.suggestedFilename(),
      savedFilename: format.filename,
    };
  }

  return {
    status: 'passed',
    route: '/dashboard/reports',
    releaseSha256: releaseMarkerResult.value.release_sha256,
    releaseId: pointer.release_id,
    releasePointerSha256: pointerResult.sha256,
    reportsDatasetVersion: reportsBinding.dataset_version,
    reportManifestSha256: reportManifestResult.sha256,
    reportIndexSha256: reportIndexResult.sha256,
    reportDocumentSha256: reportDocumentResult.sha256,
    reportId: reportDocumentResult.value.identity?.report_id ?? reportDocumentResult.value.period?.period_id,
    reportCollection: '最新完整周期',
    reportPeriod: '日报',
    downloads,
    browserErrors: [...new Set(browserErrors)],
    sameOriginHttpFailures: [...new Set(sameOriginHttpFailures)],
    externalRequests: [...new Set(externalRequests)],
  };
})
