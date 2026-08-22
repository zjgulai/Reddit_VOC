(async (page) => {
  const originMatch = page.url().match(/^(https?:\/\/[^/]+)/);
  if (!originMatch) throw new Error(`cannot determine origin from ${page.url()}`);
  const origin = originMatch[1];
  const screenshotRoot = '/Users/pray/project/Reddit_VOC/tmp/reddit-voc-v3/candidate-orchestration/v3-daily-refresh-20260723/e2e-screenshots';
  const errors = [];
  const failedRequests = [];
  const externalRequests = [];

  page.on('pageerror', (error) => errors.push(`pageerror:${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'assert') {
      errors.push(`console-${message.type()}:${message.text()}`);
    }
  });
  page.on('requestfailed', (request) => {
    failedRequests.push(`${request.method()}:${request.url()}`);
  });
  page.on('request', (request) => {
    const url = request.url();
    if (
      !url.startsWith(origin)
      && !url.startsWith('blob:')
      && !url.startsWith('data:')
    ) {
      externalRequests.push(url);
    }
  });

  const goto = async (route) => {
    const response = await page.goto(`${origin}${route}`, {
      waitUntil: 'domcontentloaded',
      timeout: 30_000,
    });
    await page.locator('body').waitFor({ state: 'visible', timeout: 15_000 });
    await page.waitForLoadState('networkidle', { timeout: 20_000 });
    return response;
  };

  const sha256 = async (raw) => {
    const digest = await page.evaluate(async (value) => {
      const bytes = new TextEncoder().encode(value);
      const hash = await crypto.subtle.digest('SHA-256', bytes);
      return [...new Uint8Array(hash)]
        .map((part) => part.toString(16).padStart(2, '0'))
        .join('');
    }, raw);
    return digest;
  };

  const releaseResponse = await page.request.get(`${origin}/data/reddit-voc/current-release.json`);
  const releaseRaw = await releaseResponse.text();
  const release = JSON.parse(releaseRaw);
  const datasetKeys = Object.keys(release.datasets ?? {}).sort();
  const expectedDatasetKeys = [
    'base',
    'brand_health',
    'casebook',
    'insights',
    'personas',
    'quarter_insights',
    'reports',
  ];
  const datasetBindings = [];
  for (const key of datasetKeys) {
    const binding = release.datasets[key];
    const response = await page.request.get(`${origin}/${binding.manifest_path}`);
    const raw = await response.text();
    datasetBindings.push({
      key,
      status: response.status(),
      expectedSha256: binding.public_manifest_sha256,
      observedSha256: await sha256(raw),
    });
  }

  const routeMarkers = {
    '/dashboard': '真实数据概览',
    '/dashboard/reports': '舆情报告',
    '/dashboard/analytics': '真实数据分析',
    '/dashboard/insights': 'Momcozy Reddit VOC 洞察',
    '/dashboard/search': '真实帖子搜索',
    '/dashboard/ugc-showcase': 'Momcozy 高价值内容',
    '/dashboard/messages': 'Momcozy 舆情信号',
    '/dashboard/settings': '数据与指标口径',
    '/cases': 'Reddit 数据应用案例精选',
  };
  const routeRows = [];
  for (const viewport of [
    { name: 'desktop', width: 1440, height: 1000 },
    { name: 'mobile', width: 390, height: 844 },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const [route, marker] of Object.entries(routeMarkers)) {
      const response = await goto(route);
      const text = await page.locator('body').innerText();
      const geometry = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }));
      routeRows.push({
        viewport: viewport.name,
        route,
        status: response?.status() ?? 0,
        finalPath: await page.evaluate(() => location.pathname),
        markerPresent: text.includes(marker),
        horizontalOverflow: geometry.scrollWidth > geometry.clientWidth + 1,
        passwordInputs: await page.locator('input[type="password"]').count(),
      });
    }
  }

  await page.setViewportSize({ width: 1440, height: 1000 });
  await goto('/dashboard');
  const dashboard = {
    releaseIdVisible: (await page.locator('body').innerText()).includes(release.release_id),
    freshnessAsOfVisible: (await page.locator('body').innerText()).includes('2026-07-23'),
    brandScore: await page.getByTestId('brand-health-overall-score').getAttribute('data-score'),
    radarGridType: await page.getByTestId('brand-health-radar-grid').getAttribute('data-grid-type'),
    collectorHref: await page.getByRole('link', { name: '采集后台', exact: true }).first().getAttribute('href'),
    storyPresent: await page.getByTestId('dashboard-insight-story').count(),
  };

  const reportRows = [];
  for (const period of [
    { id: 'daily', label: '日报', heading: '昨日发生了什么，今天先处理什么' },
    { id: 'weekly', label: '周报', heading: '本周结构如何变化，下周资源放在哪里' },
    { id: 'monthly', label: '月报', heading: '本月品牌发生了什么，下一阶段如何取舍' },
  ]) {
    await goto(`/dashboard/reports?period=${period.id}`);
    await page.getByRole('heading', { name: period.heading, exact: true }).waitFor({
      state: 'visible',
      timeout: 20_000,
    });
    const metricCards = page.locator('[data-report-indicator]');
    const metricTexts = await metricCards.allInnerTexts();
    const screenshot = `${screenshotRoot}/${period.id}.png`;
    await page.screenshot({ path: screenshot, fullPage: true });
    reportRows.push({
      period: period.label,
      metricCount: metricTexts.length,
      unavailableCardCount: metricTexts.filter((text) => /(?:^|\s)—(?:\s|$)/.test(text)).length,
      storyMapCount: await page.getByTestId('report-insight-mind-map').count(),
      screenshot,
    });
  }

  await goto('/dashboard/insights');
  const overviewInsightsBody = await page.locator('body').innerText();
  await page.getByRole('tab', { name: /舆情与内容合规/ }).click();
  const reputationInsightsBody = await page.getByRole('tabpanel').innerText();
  const insights = {
    quarterPeriodVisible: overviewInsightsBody.includes('2026-04-25 至 2026-07-23'),
    personaCohortCount: await page.getByTestId('persona-cohort-card').count(),
    personaDistributionCount: await page.getByTestId('persona-distribution-chart').count(),
    themeTabs: await page.getByRole('tab').count(),
    automationBoundaryVisible: reputationInsightsBody.includes('自动化评论 ≠ 品牌机器人'),
  };

  await goto('/cases');
  const casesBody = await page.locator('body').innerText();
  const cases = {
    stockPresent: casesBody.includes('Reddit 数据应用案例精选'),
    caseCards: await page.locator('[data-case-id]').count(),
  };

  const passed = (
    releaseResponse.status() === 200
    && release.schema_version === 'reddit_voc_current_release_v2'
    && release.release_id === 'reddit_voc_release_20260723_daily_v2'
    && release.freshness?.data_as_of_utc === '2026-07-22T23:00:00Z'
    && JSON.stringify(datasetKeys) === JSON.stringify(expectedDatasetKeys)
    && datasetBindings.every((row) => row.status === 200 && row.observedSha256 === row.expectedSha256)
    && routeRows.every((row) => (
      row.status === 200
      && row.finalPath === row.route
      && row.markerPresent
      && !row.horizontalOverflow
      && row.passwordInputs === 0
    ))
    && dashboard.brandScore !== null
    && dashboard.brandScore !== ''
    && dashboard.radarGridType === 'circle'
    && dashboard.collectorHref === 'https://reddit.brand.lute-tlz-dddd.top/'
    && dashboard.storyPresent === 1
    && reportRows.every((row) => (
      row.metricCount > 0
      && row.unavailableCardCount === 0
      && row.storyMapCount === 1
    ))
    && insights.quarterPeriodVisible
    && insights.personaCohortCount === 8
    && insights.personaDistributionCount === 1
    && insights.themeTabs === 4
    && insights.automationBoundaryVisible
    && cases.stockPresent
    && errors.length === 0
    && failedRequests.length === 0
    && externalRequests.length === 0
  );

  return {
    status: passed ? 'passed' : 'failed',
    observedAt: new Date().toISOString(),
    origin,
    release: {
      schemaVersion: release.schema_version,
      releaseId: release.release_id,
      releasePointerSha256: await sha256(releaseRaw),
      freshness: release.freshness,
      datasetKeys,
      datasetBindings,
    },
    routes: routeRows,
    dashboard,
    reports: reportRows,
    insights,
    cases,
    errors,
    failedRequests,
    externalRequests,
  };
})
