(async (page) => {
  const baseUrl = 'https://reddit.lute-tlz-dddd.top';
  const expectedRelease = '6b0012d72a07261866b0a5fb1933276ef26adbaa7da6a8dff8ac42b3352d46a2';
  const checks = [
    ['/dashboard', '真实数据概览'],
    ['/dashboard/reports', '舆情报告'],
    ['/dashboard/insights', 'Momcozy Reddit VOC 洞察'],
    ['/cases', 'Reddit 数据应用案例精选'],
  ];
  const results = [];
  const consoleErrors = [];
  const failedRequests = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('requestfailed', (request) => {
    failedRequests.push(`${request.method()}:${request.url()}`);
  });
  for (const [route, marker] of checks) {
    const response = await page.goto(`${baseUrl}${route}`, {
      waitUntil: 'domcontentloaded',
      timeout: 20_000,
    });
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    const bodyText = await page.locator('body').innerText();
    results.push({
      route,
      status: response?.status() ?? 0,
      finalPath: await page.evaluate(() => window.location.pathname),
      markerPresent: bodyText.includes(marker),
      textLength: bodyText.length,
      horizontalOverflow: await page.evaluate(() => (
        document.documentElement.scrollWidth > document.documentElement.clientWidth + 1
      )),
    });
  }
  const releaseResponse = await page.request.get(`${baseUrl}/release.json`);
  const release = await releaseResponse.json();
  const failed = results.filter((row) => (
    row.status !== 200
    || row.finalPath !== row.route
    || row.markerPresent !== true
    || row.textLength < 100
    || row.horizontalOverflow !== false
  ));
  if (
    failed.length > 0
    || consoleErrors.length > 0
    || failedRequests.length > 0
    || releaseResponse.status() !== 200
    || release.release_sha256 !== expectedRelease
  ) {
    throw new Error(JSON.stringify({ failed, consoleErrors, failedRequests, release }));
  }
  return {
    status: 'passed',
    observedAt: new Date().toISOString(),
    origin: baseUrl,
    expectedRelease,
    observedRelease: release.release_sha256,
    routes: results,
    consoleErrors,
    failedRequests,
  };
})
