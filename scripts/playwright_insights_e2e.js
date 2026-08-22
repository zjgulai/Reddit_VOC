(async (page) => {
  const baseUrlMatch = page.url().match(/^(https?:\/\/[^/]+)/);
  if (!baseUrlMatch) throw new Error(`cannot determine base URL from ${page.url()}`);
  const baseUrl = baseUrlMatch[1];
  const casebookRoot = '/data/reddit-voc/reddit_voc_casebook_20260716_public_a1';
  const expectedCasebookManifestSha256 = '8e79fe8c86e08e60b693ca93f3ca6560476bec53a979c67ed8120d00ec121126';
  const expectedCasebookDataSha256 = '5ad81e7af5f9744332baacd0a87ac947f1097894f4ef27c6aab692b0f90b249c';
  const routes = [
    '/',
    '/dashboard',
    '/dashboard/reports',
    '/dashboard/analytics',
    '/dashboard/insights',
    '/dashboard/search',
    '/dashboard/ugc-showcase',
    '/dashboard/messages',
    '/dashboard/settings',
    '/features',
    '/how-it-works',
    '/faq',
    '/cases',
  ];
  const viewports = [
    { name: 'desktop', width: 1440, height: 1000 },
    { name: 'mobile', width: 390, height: 844 },
  ];
  const requiredText = {
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
  const forbiddenLegacyGateTexts = [
    'UGC 素材库暂不展示数据',
    '消息中心暂不展示数据',
    '生产设置当前为只读',
  ];

  const browserErrors = [];
  const externalRequests = [];
  const sameOriginHttpFailures = [];
  const contractFailures = [];
  const assertContract = (condition, label) => {
    if (!condition) contractFailures.push(label);
  };
  const readQueryParam = (rawUrl, key) => {
    const query = (String(rawUrl).split('?')[1] ?? '').split('#')[0];
    for (const pair of query.split('&')) {
      const [name, ...valueParts] = pair.split('=');
      if (name === key) return valueParts.join('=') || '';
    }
    return null;
  };
  const captureContract = async (label, callback) => {
    try {
      return await callback();
    } catch (error) {
      contractFailures.push(`${label}:${error instanceof Error ? error.message : String(error)}`);
      return null;
    }
  };

  const observePage = (targetPage) => {
    targetPage.on('pageerror', (error) => browserErrors.push(`pageerror:${error.message}`));
    targetPage.on('console', (message) => {
      if (message.type() === 'error' || message.type() === 'assert') {
        browserErrors.push(`console-${message.type()}:${message.text()}`);
      }
    });
    targetPage.on('requestfailed', (request) => {
      browserErrors.push(`requestfailed:${request.method()}:${request.url()}`);
    });
    targetPage.on('response', (response) => {
      if (response.url().startsWith(baseUrl) && response.status() >= 400) {
        sameOriginHttpFailures.push(`${response.status()}:${response.url()}`);
      }
    });
    targetPage.on('request', (request) => {
      if (
        !request.url().startsWith('blob:')
        && !request.url().startsWith('data:')
        && request.url() !== baseUrl
        && !request.url().startsWith(`${baseUrl}/`)
      ) {
        externalRequests.push(request.url());
      }
    });
  };
  observePage(page);

  const gotoRoute = async (route, timeout = 20_000) => {
    const response = await page.goto(`${baseUrl}${route}`, {
      waitUntil: 'domcontentloaded',
      timeout,
    });
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    await page.locator('body').waitFor({ state: 'visible', timeout: 10_000 });
    return response;
  };

  const searchContract = await captureContract('search-real-data-filters', captureSearchFilters);
  const urlStateContract = await captureContract('url-state-and-browser-back', captureUrlState);

  const results = [];
  for (const viewport of viewports) {
    await page.setViewportSize(viewport);
    for (const route of routes) {
      try {
        const response = await gotoRoute(route);
        const bodyText = await page.locator('body').innerText();
        const horizontalOverflow = await page.evaluate(() => {
          const documentWidth = Math.max(
            document.documentElement.scrollWidth,
            document.body?.scrollWidth ?? 0,
          );
          return documentWidth > document.documentElement.clientWidth + 1;
        });
        const overflowDiagnostics = horizontalOverflow ? await page.evaluate(() => {
          const viewportWidth = document.documentElement.clientWidth;
          const items = [...document.querySelectorAll('body *')]
            .map((element) => {
              const rectangle = element.getBoundingClientRect();
              return {
                tag: element.tagName.toLowerCase(),
                namespace: element.namespaceURI,
                testId: element.getAttribute('data-testid'),
                className: typeof element.className === 'string' ? element.className.slice(0, 180) : '',
                left: Math.round(rectangle.left),
                right: Math.round(rectangle.right),
                width: Math.round(rectangle.width),
                clientWidth: element.clientWidth,
                scrollWidth: element.scrollWidth,
              };
            });
          return {
            viewportWidth,
            documentScrollWidth: document.documentElement.scrollWidth,
            bodyScrollWidth: document.body?.scrollWidth ?? 0,
            rectangleOverflow: items
              .filter((item) => item.left < -1 || item.right > viewportWidth + 1)
              .sort((left, right) => (right.right - viewportWidth) - (left.right - viewportWidth))
              .slice(0, 12),
            htmlScrollOverflow: items
              .filter((item) => item.namespace === 'http://www.w3.org/1999/xhtml'
                && item.left + item.scrollWidth > viewportWidth + 1)
              .sort((left, right) => (right.left + right.scrollWidth) - (left.left + left.scrollWidth))
              .slice(0, 12),
          };
        }) : [];
        const loginControls = await page.locator('a,button').evaluateAll((elements) => elements
          .map((element) => (element.textContent ?? '').replace(/\s+/g, ' ').trim().toLowerCase())
          .filter((text) => ['登录', '注册', 'login', 'log in', 'sign in', 'sign up'].includes(text)));
        const passwordInputs = await page.locator('input[type="password"]').count();
        const abnormalPromptIcons = await page.locator([
          '[data-ui-warning-icon]',
          '[data-alert-icon]',
          '[role="img"][aria-label*="警告"]',
          '[role="img"][aria-label*="感叹"]',
          '[data-ui-severity="warning"] svg',
        ].join(',')).count();
        const marker = requiredText[route];
        const finalPath = await page.evaluate(() => window.location.pathname);
        results.push({
          viewport: viewport.name,
          route,
          finalPath,
          status: response?.status() ?? 0,
          title: await page.title(),
          textLength: bodyText.length,
          requiredTextPresent: marker ? bodyText.includes(marker) : true,
          forbiddenLegacyGateTextPresent: forbiddenLegacyGateTexts.some((text) => bodyText.includes(text)),
          horizontalOverflow,
          overflowDiagnostics,
          passwordInputs,
          loginControls,
          abnormalPromptIcons,
        });
      } catch (error) {
        results.push({ viewport: viewport.name, route, error: String(error) });
      }
    }
  }

  const releaseArtifacts = await captureContract('current-release-cases-casebook-and-quarter-insights', async () => {
    await page.setViewportSize(viewports[0]);
    await gotoRoute('/dashboard');
    return page.evaluate(async ({ origin, casebookPath }) => {
      const sha256Text = async (raw) => {
        if (!globalThis.crypto?.subtle) throw new Error('browser SHA-256 unavailable');
        const digest = await globalThis.crypto.subtle.digest(
          'SHA-256',
          new TextEncoder().encode(raw),
        );
        return [...new Uint8Array(digest)]
          .map((value) => value.toString(16).padStart(2, '0'))
          .join('');
      };
      const fetchJson = async (path) => {
        const response = await fetch(`${origin}${path}`, { cache: 'no-cache' });
        if (!response.ok) throw new Error(`${path} HTTP ${response.status}`);
        const raw = await response.text();
        return {
          value: JSON.parse(raw),
          sha256: await sha256Text(raw),
          bytes: new TextEncoder().encode(raw).byteLength,
        };
      };
      const siteReleaseMarker = await fetchJson('/release.json');
      const release = await fetchJson('/data/reddit-voc/current-release.json');
      const quarterBinding = release.value.datasets?.quarter_insights;
      if (!quarterBinding?.manifest_path) {
        throw new Error('quarter-insights binding missing from current release');
      }
      const quarterPath = `/${quarterBinding.manifest_path.replace(/\/manifest\.json$/, '')}`;
      const caseManifest = await fetchJson('/data/cases/manifest.v1.json');
      const caseIndex = await fetchJson('/data/cases/case-index.v1.json');
      const casebookManifest = await fetchJson(`${casebookPath}/manifest.json`);
      const casebookData = await fetchJson(`${casebookPath}/casebook.json`);
      const quarterManifest = await fetchJson(`${quarterPath}/manifest.json`);
      const quarterData = await fetchJson(`${quarterPath}/quarter-insights.json`);
      return {
        siteReleaseMarker: siteReleaseMarker.value,
        release: release.value,
        releaseSha256: release.sha256,
        caseManifest: caseManifest.value,
        caseManifestSha256: caseManifest.sha256,
        caseIndex: caseIndex.value,
        caseIndexSha256: caseIndex.sha256,
        casebookManifest: casebookManifest.value,
        casebookManifestSha256: casebookManifest.sha256,
        casebookData: casebookData.value,
        casebookDataSha256: casebookData.sha256,
        casebookDataBytes: casebookData.bytes,
        quarterManifest: quarterManifest.value,
        quarterManifestSha256: quarterManifest.sha256,
        quarterData: quarterData.value,
        quarterDataSha256: quarterData.sha256,
        quarterDataBytes: quarterData.bytes,
        quarterBinding,
      };
    }, { origin: baseUrl, casebookPath: casebookRoot });
  });

  if (releaseArtifacts) {
    const { release, caseManifest, caseIndex } = releaseArtifacts;
    const datasetVersions = Object.fromEntries(
      Object.entries(release.datasets ?? {}).map(([key, binding]) => [key, binding?.dataset_version]),
    );
    const recentSentimentBuckets = releaseArtifacts.quarterData?.dashboard_windows
      ?.find((window) => window.id === 'rolling_30_days')?.buckets
      ?.filter((bucket) => bucket.bucket >= '2026-07-16') ?? [];
    assertContract(
      ['reddit_voc_current_release_v1', 'reddit_voc_current_release_v2']
        .includes(release.schema_version),
      'release-schema-supported',
    );
    assertContract(
      /^[a-f0-9]{64}$/.test(releaseArtifacts.siteReleaseMarker?.release_sha256 ?? ''),
      'site-release-marker-sha256',
    );
    const versionPrefixes = {
      base: 'reddit_voc_site_snapshot_',
      insights: 'reddit_voc_insights_',
      reports: 'reddit_voc_reports_',
      personas: 'reddit_voc_personas_',
      brand_health: 'reddit_voc_brand_health_',
      quarter_insights: 'reddit_voc_quarter_insights_',
      casebook: 'reddit_voc_casebook_',
    };
    assertContract(
      Object.entries(versionPrefixes).every(([key, prefix]) => (
        typeof datasetVersions[key] === 'string'
        && datasetVersions[key].startsWith(prefix)
        && /^[a-z0-9][a-z0-9_-]{2,127}$/.test(datasetVersions[key])
      )),
      'all-selected-datasets-have-safe-versioned-identities',
    );
    assertContract(release.boundaries?.login_required === false, 'release-no-login');
    assertContract(release.boundaries?.collector_isolation_required === true, 'release-collector-isolation');
    assertContract(release.boundaries?.case_gallery_stock_preserved === true, 'release-case-stock-preserved');
    assertContract(release.cases?.stock_content_preserved === true, 'cases-pointer-stock-preserved');
    assertContract(
      release.cases?.public_manifest_sha256 === releaseArtifacts.caseManifestSha256,
      'cases-manifest-pointer-sha',
    );
    assertContract(release.cases?.index_sha256 === releaseArtifacts.caseIndexSha256, 'cases-index-pointer-sha');
    assertContract(caseManifest.datasetVersion === release.cases?.dataset_version, 'cases-manifest-version');
    assertContract(caseIndex.datasetVersion === release.cases?.dataset_version, 'cases-index-version');
    assertContract(caseManifest.index?.sha256 === releaseArtifacts.caseIndexSha256, 'cases-manifest-index-sha');
    assertContract(
      caseManifest.seed?.version === 'case_seed_bundled_v1'
      && caseManifest.seed?.count === 38
      && caseManifest.seed?.contentSha256 === '372fa672767ed2585300cd1d47141b6189d3d6784b98c4bc8a69074db5ba48a7',
      'cases-curated-stock-immutable',
    );
    assertContract(
      caseManifest.legacyUnverified?.version === 'legacy_unverified_bundled_v1'
      && caseManifest.legacyUnverified?.count === 12
      && caseManifest.legacyUnverified?.contentSha256 === '9d09b10949eb3790b34507d13dcbddcaf5fcd6e9f81e96dddd7e12ef86691de2',
      'cases-legacy-stock-immutable',
    );
    assertContract(
      Array.isArray(caseIndex.approvedDelta)
      && caseManifest.approvedDelta?.count === caseIndex.approvedDelta.length
      && release.cases?.approved_delta_count === caseIndex.approvedDelta.length,
      'cases-approved-delta-conserved',
    );
    const publicDossier = releaseArtifacts.casebookData?.dossiers?.[0];
    assertContract(
      releaseArtifacts.casebookManifestSha256 === expectedCasebookManifestSha256
      && releaseArtifacts.casebookDataSha256 === expectedCasebookDataSha256
      && releaseArtifacts.casebookManifest?.schema_version === 'reddit_voc_governance_casebook_public_manifest_v1'
      && releaseArtifacts.casebookManifest?.status === 'ready'
      && releaseArtifacts.casebookManifest?.lifecycle_status === 'review_required'
      && releaseArtifacts.casebookManifest?.files?.['casebook.json']?.sha256 === expectedCasebookDataSha256
      && releaseArtifacts.casebookManifest?.files?.['casebook.json']?.bytes === releaseArtifacts.casebookDataBytes
      && releaseArtifacts.casebookData?.schema_version === 'reddit_voc_governance_casebook_public_v1'
      && publicDossier?.title === 'Momcozy 社区信任与疑似非自然推广治理事件'
      && publicDossier?.assessment?.commercial_relation === 'C2'
      && publicDossier?.assessment?.integrity_level === 'I3'
      && publicDossier?.assessment?.brand_control_confirmed === false
      && publicDossier?.lifecycle_status === 'review_required'
      && publicDossier?.stages?.map((stage) => stage.label).join('|') === '洞察|证据|行动|监测|复盘'
      && releaseArtifacts.casebookData?.boundaries?.external_navigation === false
      && releaseArtifacts.casebookData?.boundaries?.robot_attribution_confirmed === false,
      'public-casebook-a1-byte-and-semantic-contract',
    );
    assertContract(
      releaseArtifacts.quarterManifestSha256 === releaseArtifacts.quarterBinding?.public_manifest_sha256
      && releaseArtifacts.quarterManifest?.schema_version === 'reddit_voc_quarter_insights_public_manifest_v1'
      && releaseArtifacts.quarterManifest?.status === 'ready'
      && releaseArtifacts.quarterManifest?.files?.['quarter-insights.json']?.sha256 === releaseArtifacts.quarterDataSha256
      && releaseArtifacts.quarterManifest?.files?.['quarter-insights.json']?.bytes === releaseArtifacts.quarterDataBytes
      && releaseArtifacts.quarterData?.schema_version === 'reddit_voc_quarter_insights_public_v1'
      && releaseArtifacts.quarterData?.period?.start_date === '2026-04-25'
      && releaseArtifacts.quarterData?.period?.end_date === '2026-07-23'
      && releaseArtifacts.quarterData?.counts?.analysis_post_vocs + releaseArtifacts.quarterData?.counts?.analysis_comment_context_vocs === 9252
      && releaseArtifacts.quarterData?.counts?.momcozy?.total_vocs === 1865
      && releaseArtifacts.quarterData?.personas?.main_assignment_count === 408
      && releaseArtifacts.quarterData?.themes?.geo?.comparison_decision_posts === 115
      && releaseArtifacts.quarterData?.themes?.reputation?.automation_comments === 344
      && recentSentimentBuckets.length === 8
      && recentSentimentBuckets.at(-1)?.bucket === '2026-07-23'
      && recentSentimentBuckets.every((bucket) => (
        bucket.classified_vocs > 0 && Number.isFinite(bucket.negative_rate)
      ))
      && releaseArtifacts.quarterData?.boundaries?.automation_comments_are_not_brand_attribution === true
      && releaseArtifacts.quarterData?.boundaries?.case_references_are_method_only === true,
      'quarter-insights-a1-byte-semantic-and-boundary-contract',
    );
  }

  const dashboardContract = await captureContract('dashboard-ranges-radar-formulas-and-primary-story', async () => {
    await page.setViewportSize(viewports[0]);
    await gotoRoute('/dashboard');
    const missionBanner = page.locator('section[aria-label="Momcozy 品牌使命横幅"]');
    const missionImage = page.getByRole('img', { name: 'Momcozy 品牌使命', exact: true });
    const brandRadar = page.getByRole('img', { name: 'Momcozy 品牌健康四维雷达', exact: true });
    const brandScoreSection = page.locator('section[aria-label="Momcozy 品牌健康度指数"]');
    const storySection = page.locator('[data-testid="dashboard-insight-story"]');
    const overallScore = await page.locator('[data-testid="brand-health-overall-score"]').getAttribute('data-score');
    const dimensionScores = await brandScoreSection.locator('[data-dimension-score]').evaluateAll((elements) => (
      elements.map((element) => Number(element.getAttribute('data-dimension-score')))
    ));
    const formulaExpectations = [
      ['品牌健康度指数', 'round_half_up(mean'],
      ['口碑健康', '50 + 50 ×'],
      ['产品体验', '100 × (1 -'],
      ['推荐信任', '50 + 50 ×'],
      ['风险韧性', '100 - 风险暴露'],
    ];
    const formulaStates = [];
    for (const [label, formulaFragment] of formulaExpectations) {
      const helpButton = brandScoreSection.getByRole('button', { name: `${label}指标说明`, exact: true });
      const dialog = brandScoreSection.getByRole('dialog', { name: `${label}计算口径`, exact: true });
      const helpButtonCount = await helpButton.count();
      if (helpButtonCount === 1) {
        await helpButton.click();
        await dialog.waitFor({ state: 'visible', timeout: 5_000 });
      }
      const dialogCount = await dialog.count();
      const dialogText = dialogCount === 1 ? await dialog.innerText() : '';
      formulaStates.push({ label, helpButtonCount, dialogCount, formulaVisible: dialogText.includes(formulaFragment) });
      if (dialogCount === 1) {
        await dialog.getByRole('button', { name: `关闭${label}指标说明`, exact: true }).click();
        try {
          await dialog.waitFor({ state: 'hidden', timeout: 1_000 });
        } catch {
          await helpButton.click();
          await dialog.waitFor({ state: 'hidden', timeout: 5_000 });
        }
      }
    }
    const evidenceButton = page.getByRole('button', { name: '查看数据证据', exact: true });
    await evidenceButton.click();
    const evidenceDialog = page.getByRole('dialog', { name: '数据证据与口径', exact: true });
    await evidenceDialog.waitFor({ state: 'visible', timeout: 5_000 });
    const groupedEvidenceCounts = await Promise.all(
      ['数据时间口径', '中心与页面投影', '覆盖证据', '结构覆盖与债务']
        .map((label) => evidenceDialog.getByText(label, { exact: true }).count()),
    );
    const dataEvidenceModalState = {
      dialogCount: await evidenceDialog.count(),
      backdropCount: await page.locator('[data-testid="data-evidence-backdrop"]').count(),
      bodyScrollLocked: await page.evaluate(() => document.body.style.overflow === 'hidden'),
      groupedEvidencePresent: groupedEvidenceCounts.every((count) => count === 1),
    };
    await evidenceDialog.getByRole('button', { name: '关闭数据证据', exact: true }).click();
    await evidenceDialog.waitFor({ state: 'hidden', timeout: 5_000 });
    dataEvidenceModalState.closed = await evidenceDialog.count() === 0;
    const rangeExpectations = [
      { label: '近1周', range: 'near1week', postVocCount: 27, totalVocCount: 142, window: 'rolling_7_days', bucketCount: 7 },
      { label: '近1月', range: 'near1month', postVocCount: 145, totalVocCount: 1275, window: 'rolling_30_days', bucketCount: 30 },
      { label: '近半年', range: 'near6months', postVocCount: 239, totalVocCount: 2099, window: 'rolling_183_days', bucketCount: 7 },
    ];
    const rangeStates = [];
    for (const expected of rangeExpectations) {
      const tab = page.getByRole('tab', { name: expected.label, exact: true });
      await tab.click();
      await page.waitForFunction(({ range, windowId }) => (
        new URL(window.location.href).searchParams.get('range') === range
        && document.querySelector('[data-testid="dashboard-range-summary"]')?.getAttribute('data-range') === range
        && document.querySelector('#trend-change')?.getAttribute('data-dashboard-window') === windowId
        && [...document.querySelectorAll('[role="tab"]')].some((element) => (
          element.textContent?.trim() === ({ near1week: '近1周', near1month: '近1月', near6months: '近半年' })[range]
          && element.getAttribute('aria-selected') === 'true'
        ))
      ), { range: expected.range, windowId: expected.window }, { timeout: 10_000 });
      const summary = page.locator('[data-testid="dashboard-range-summary"]');
      const trendSection = page.locator('#trend-change');
      const dualAxisChart = trendSection.locator('[data-testid="dual-axis-trend-chart"]');
      rangeStates.push({
        range: readQueryParam(page.url(), 'range'),
        selected: await tab.getAttribute('aria-selected'),
        summaryRange: await summary.getAttribute('data-range'),
        postVocCount: Number(await summary.locator('[data-kpi-label="Momcozy 相关帖子"]').getAttribute('data-kpi-value')),
        totalVocCount: Number(await summary.locator('[data-kpi-label="VOC 观察量"]').getAttribute('data-kpi-value')),
        competitorCount: Number(await summary.locator('[data-kpi-label="主要竞对语境"]').getAttribute('data-kpi-value')),
        window: await trendSection.getAttribute('data-dashboard-window'),
        bucketCount: Number(await trendSection.getAttribute('data-bucket-count')),
        dualAxisCount: await dualAxisChart.count(),
        dualAxisLabel: await dualAxisChart.getAttribute('aria-label'),
        barSeriesCount: await dualAxisChart.locator('.recharts-bar').count(),
        lineSeriesCount: await dualAxisChart.locator('.recharts-line').count(),
        lineLegendCount: await dualAxisChart.locator('.recharts-legend-item-text')
          .filter({ hasText: '负面 VOC 占比（%）' }).count(),
        expected,
      });
    }
    return {
      missionBannerCount: await missionBanner.count(),
      missionImageCount: await missionImage.count(),
      brandRadarCount: await brandRadar.count(),
      radarGridType: await brandRadar.getAttribute('data-radar-grid'),
      hiddenRadarGridType: await brandScoreSection.locator('[data-testid="brand-health-radar-grid"]').getAttribute('data-grid-type'),
      brandScoreSectionCount: await brandScoreSection.count(),
      brandScoreHeadingCount: await page.getByRole('heading', { name: '品牌健康度指数', exact: true }).count(),
      brandScoreText: await brandScoreSection.innerText(),
      overallScore: Number(overallScore),
      dimensionScores,
      formulaStates,
      dataEvidenceModalState,
      rangeStates,
      storyCount: await storySection.count(),
      storyText: await storySection.innerText(),
      releaseEvidenceCardCount: await page.locator('[data-governance-component="release-evidence-card"]').count(),
    };
  });

  if (dashboardContract) {
    assertContract(
      dashboardContract.missionBannerCount === 0
      && dashboardContract.missionImageCount === 0
      && dashboardContract.brandRadarCount === 1
      && dashboardContract.radarGridType === 'circle'
      && dashboardContract.hiddenRadarGridType === 'circle'
      && dashboardContract.brandScoreSectionCount === 1
      && dashboardContract.brandScoreHeadingCount === 1
      && Number.isFinite(dashboardContract.overallScore)
      && dashboardContract.dimensionScores.length === 4
      && dashboardContract.dimensionScores.every((score) => Number.isFinite(score))
      && dashboardContract.formulaStates.length === 5
      && dashboardContract.formulaStates.every((state) => state.helpButtonCount === 1 && state.dialogCount === 1 && state.formulaVisible)
      && dashboardContract.dataEvidenceModalState.dialogCount === 1
      && dashboardContract.dataEvidenceModalState.backdropCount === 1
      && dashboardContract.dataEvidenceModalState.bodyScrollLocked
      && dashboardContract.dataEvidenceModalState.groupedEvidencePresent
      && dashboardContract.dataEvidenceModalState.closed
      && dashboardContract.rangeStates.length === 3
      && dashboardContract.rangeStates.every((state) => (
        state.range === state.expected.range
        && state.selected === 'true'
        && state.summaryRange === state.expected.range
        && state.postVocCount === state.expected.postVocCount
        && state.totalVocCount === state.expected.totalVocCount
        && state.competitorCount > 0
        && state.window === state.expected.window
        && state.bucketCount === state.expected.bucketCount
        && state.dualAxisCount === 1
        && state.dualAxisLabel?.includes('双坐标趋势')
        && state.barSeriesCount === 2
        && state.lineLegendCount === 1
        && state.lineSeriesCount === 1
      ))
      && dashboardContract.brandScoreText.includes('满分 100')
      && ['口碑健康', '产品体验', '推荐信任', '风险韧性'].every((label) => dashboardContract.brandScoreText.includes(label))
      && dashboardContract.storyCount === 1
      && ['用户痛点', '舆情与内容合规', '新品机会', 'GEO 优化机会'].every((label) => dashboardContract.storyText.includes(label))
      && !dashboardContract.brandScoreText.includes('观察样本品牌健康度指数')
      && dashboardContract.releaseEvidenceCardCount === 0,
      `dashboard-ranges-circular-radar-five-formulas-dual-axis-and-management-story:${JSON.stringify(dashboardContract)}`,
    );
  }

  const workspaceContract = await captureContract('restored-real-data-workspaces', async () => {
    const expectations = [
      {
        route: '/dashboard/ugc-showcase',
        heading: 'Momcozy 高价值内容',
        sections: ['真实内容机会', '内容机会主题构成', '内容情感构成', '高价值内容池'],
      },
      {
        route: '/dashboard/messages',
        heading: 'Momcozy 舆情信号',
        sections: ['优先舆情信号', '风险主题分布', '行动队列口径', 'Momcozy VOC 预警与行动队列'],
      },
      {
        route: '/dashboard/settings',
        heading: '数据与指标口径',
        sections: ['当前真实数据范围', '指标口径词典', '帖子、评论与帖子+评论关系'],
      },
    ];
    const states = [];
    for (const expected of expectations) {
      await gotoRoute(expected.route);
      const bodyText = await page.locator('body').innerText();
      states.push({
        route: expected.route,
        headingCount: await page.getByRole('heading', { name: expected.heading, exact: true }).count(),
        requiredSectionsPresent: expected.sections.every((section) => bodyText.includes(section)),
        metricHelpCount: await page.locator('button[aria-label$="指标说明"]').count(),
        legacyGateAbsent: forbiddenLegacyGateTexts.every((text) => !bodyText.includes(text)),
      });
    }
    return states;
  });

  if (workspaceContract) {
    assertContract(
      workspaceContract.length === 3
      && workspaceContract.every((state) => (
        state.headingCount === 1
        && state.requiredSectionsPresent
        && state.metricHelpCount >= 4
        && state.legacyGateAbsent
      )),
      'restored-workspaces-use-real-data-and-no-legacy-gates',
    );
  }

  const insightsContract = await captureContract('quarter-insights-four-theme-dom', async () => {
    await page.setViewportSize(viewports[0]);
    await gotoRoute('/dashboard/insights');
    const initialBodyText = await page.locator('body').innerText();
    const scopeBar = page.locator('[data-governance-component="data-scope-bar"]');
    const personaSection = page.locator('section[aria-labelledby="aggregate-personas-title"]');
    const personaText = await personaSection.innerText();
    const avatarLocator = personaSection.locator('img');
    const personaCards = personaSection.locator('[data-testid="persona-cohort-card"]');
    const personaDistribution = personaSection.locator('[data-testid="persona-distribution-chart"]');
    const personaEvidenceHrefs = await personaCards.getByRole('link', { name: '查看证据', exact: true })
      .evaluateAll((elements) => elements.map((element) => element.getAttribute('href')));
    const baseDatasetVersion = releaseArtifacts?.release?.datasets?.base?.dataset_version;
    const basePostIds = await page.evaluate(async ({ origin, datasetVersion }) => {
      if (typeof datasetVersion !== 'string') return [];
      const response = await fetch(`${origin}/data/reddit-voc/${datasetVersion}/posts-public.json`, { cache: 'no-cache' });
      if (!response.ok) throw new Error(`base posts HTTP ${response.status}`);
      const posts = await response.json();
      return posts.flatMap((post) => [post.post_id, post.reddit_id]);
    }, { origin: baseUrl, datasetVersion: baseDatasetVersion });
    const personaEvidenceLinksResolvable = await page.evaluate(({ hrefs, origin, postIds }) => {
      const knownPostIds = new Set(postIds);
      return hrefs.every((href) => {
        if (typeof href !== 'string') return false;
        const target = new URL(href, origin);
        const queryPostId = target.searchParams.get('q');
        return target.pathname === '/dashboard/search'
          && queryPostId?.startsWith('t3_')
          && queryPostId === target.searchParams.get('post')
          && knownPostIds.has(queryPostId);
      });
    }, { hrefs: personaEvidenceHrefs, origin: baseUrl, postIds: basePostIds });
    const personaShares = await personaSection.locator('[data-testid="persona-distribution-bar"]').evaluateAll((elements) => (
      elements.map((element) => Number(element.getAttribute('data-share')))
    ));
    const avatarCount = await avatarLocator.count();
    if (avatarCount > 0) {
      await avatarLocator.first().scrollIntoViewIfNeeded();
      await page.waitForFunction(() => [...document.querySelectorAll(
        'section[aria-labelledby="aggregate-personas-title"] img',
      )].every((image) => image.complete && image.naturalWidth > 0), undefined, { timeout: 10_000 });
    }
    const avatars = await avatarLocator.evaluateAll((images) => images.map((image) => ({
      src: image.getAttribute('src'), alt: image.getAttribute('alt'), complete: image.complete, naturalWidth: image.naturalWidth,
    })));
    const themeExpectations = [
      { label: '用户痛点', theme: 'pain', keyValue: '1,865', historicalCase: false },
      { label: '舆情与内容合规', theme: 'reputation', keyValue: '344', historicalCase: true },
      { label: '新品机会', theme: 'new-product', keyValue: '482', historicalCase: false },
      { label: 'GEO 优化机会', theme: 'geo', keyValue: String(releaseArtifacts.quarterData.themes.geo.comparison_decision_posts), historicalCase: false },
    ];
    const themeStates = [];
    for (const expected of themeExpectations) {
      const tab = page.locator(`#insight-theme-tab-${expected.theme}`);
      if (await tab.count() !== 1) throw new Error(`missing quarter insight theme ${expected.label}`);
      await tab.click();
      await page.waitForFunction((theme) => (
        new URL(window.location.href).searchParams.get('theme') === theme
        && document.querySelector(`#insight-theme-tab-${theme}`)?.getAttribute('aria-selected') === 'true'
        && document.querySelector('#quarter-theme-panel')?.getAttribute('data-theme') === theme
      ), expected.theme, { timeout: 10_000 });
      const panel = page.locator('#quarter-theme-panel');
      const panelText = await panel.innerText();
      const evidenceHrefs = await panel.locator('a[role="listitem"]').evaluateAll((elements) => (
        elements.map((element) => element.getAttribute('href'))
      ));
      const evidenceLinksBound = evidenceHrefs.length > 0 && evidenceHrefs.every((href) => {
        if (typeof href !== 'string') return false;
        const relativeHref = href.startsWith(baseUrl) ? href.slice(baseUrl.length) : href;
        const queryPostId = readQueryParam(relativeHref, 'q');
        return relativeHref.split('?')[0] === '/dashboard/search'
          && queryPostId?.startsWith('t3_')
          && queryPostId === readQueryParam(relativeHref, 'post')
          && readQueryParam(relativeHref, 'release')
          && readQueryParam(relativeHref, 'snapshot')
          && readQueryParam(relativeHref, 'from') === 'insights';
      });
      themeStates.push({
        theme: readQueryParam(page.url(), 'theme'),
        selected: await tab.getAttribute('aria-selected'),
        panelTheme: await panel.getAttribute('data-theme'),
        storySectionCount: await panel.locator('[data-story-section]').count(),
        commonStoryPresent: ['核心信号', 'Reddit 证据', '业务解释', 'P0 / P1 / P2 建议', '案例方法参照']
          .every((label) => panelText.includes(label)),
        keyValuePresent: panelText.includes(expected.keyValue),
        evidenceLinksBound,
        caseBoundaryPresent: expected.historicalCase
          ? panelText.includes('历史案例不构成本季度信号证据，也不确认品牌机器人归属')
          : panelText.includes('案例广场候选内容独立浏览，不参与本模块排序、结论或成效证明'),
        automationBoundaryPresent: expected.theme !== 'reputation' || (
          panelText.includes('自动化评论')
          && panelText.includes('本季度自动化评论与管理员规则证据不支持确认 Momcozy 使用机器人、控制相关账号或存在商业关系')
          && await panel.locator('section[aria-label="内容合规归因边界"]').count() === 1
        ),
        expected,
      });
    }
    const storySteps = await page.locator('[data-insight-story-step]').evaluateAll((elements) => (
      elements.map((element) => element.getAttribute('data-insight-story-step'))
    ));
    return {
      pageHeading: await page.getByRole('heading', { name: 'Momcozy Reddit VOC 洞察', exact: true }).count(),
      initialBodyText,
      scopeBarText: await scopeBar.innerText(),
      personaText,
      avatars,
      personaCardCount: await personaCards.count(),
      personaDistributionCount: await personaDistribution.count(),
      personaShares,
      storySteps,
      personaBeforeThemes: storySteps.indexOf('personas') >= 0 && storySteps.indexOf('personas') < storySteps.indexOf('themes'),
      personaEvidenceLinkCount: await personaCards.getByRole('link', { name: '查看证据', exact: true }).count(),
      personaEvidenceLinksResolvable,
      themeStates,
      darkLegacyPanelCount: await page.locator('*').evaluateAll((elements) => elements.filter(
        (element) => typeof element.className === 'string' && element.className.includes('bg-[#17212B]'),
      ).length),
      personaErrorPresent: initialBodyText.includes('真实用户画像不可用，未回退 Mock'),
    };
  });

  if (insightsContract) {
    assertContract(insightsContract.pageHeading === 1, 'insights-heading-momcozy-voc');
    assertContract(
      insightsContract.scopeBarText.includes('2026-04-25 至 2026-07-23')
      && insightsContract.scopeBarText.includes('共 90 个自然日')
      && insightsContract.scopeBarText.includes('9,252')
      && insightsContract.scopeBarText.includes('1,865')
      && insightsContract.scopeBarText.includes('Reddit 观察样本 · Momcozy 为分析主干'),
      'insights-quarter-window-analysis-pool-and-momcozy-scope-exact',
    );
    assertContract(
      insightsContract.personaText.includes('用户画像')
      && insightsContract.personaText.includes('408 次 Momcozy 画像赋值')
      && insightsContract.personaText.includes('2,830 次母婴品类语境赋值')
      && insightsContract.personaText.includes('非用户人数或人口占比')
      && insightsContract.personaCardCount === 8
      && insightsContract.personaDistributionCount === 1
      && insightsContract.personaShares.length === 8
      && Math.abs(insightsContract.personaShares.reduce((total, share) => total + share, 0) - 100) < 0.001
      && insightsContract.personaBeforeThemes
      && insightsContract.storySteps.join('|') === 'scope|personas|themes'
      && insightsContract.personaEvidenceLinkCount === 8
      && insightsContract.personaEvidenceLinksResolvable
      && insightsContract.avatars.length === 8
      && insightsContract.avatars.every((avatar) => avatar.src?.startsWith('blob:') && avatar.alt?.includes('非真实用户') && avatar.complete && avatar.naturalWidth > 0)
      && !insightsContract.personaErrorPresent,
      'insights-quarter-personas-first-eight-groups-and-current-assignments',
    );
    assertContract(
      insightsContract.themeStates.length === 4
      && insightsContract.themeStates.every((state) => (
        state.theme === state.expected.theme
        && state.selected === 'true'
        && state.panelTheme === state.expected.theme
        && state.storySectionCount === 5
        && state.commonStoryPresent
        && state.keyValuePresent
        && state.evidenceLinksBound
        && state.caseBoundaryPresent
        && state.automationBoundaryPresent
      )),
      `insights-four-quarter-themes-evidence-actions-cases-and-attribution:${JSON.stringify(insightsContract.themeStates)}`,
    );
    assertContract(
      insightsContract.darkLegacyPanelCount === 0
      && !insightsContract.initialBodyText.includes('内容证据 cohort')
      && !insightsContract.initialBodyText.includes('证据画像'),
      'insights-light-tone-and-business-language',
    );
  }

  const reportStates = await captureContract('reports-latest-complete-dom', async () => {
    await page.setViewportSize(viewports[0]);
    await gotoRoute('/dashboard/reports');
    const headingCount = await page.getByRole('heading', { name: '舆情报告', exact: true }).count();
    const periodButtons = page.locator('[aria-label="报告周期"] button');
    const periodButtonText = await periodButtons.evaluateAll((buttons) => buttons.map(
      (button) => (button.textContent ?? '').replace(/\s+/g, ' ').trim(),
    ));
    const availablePeriodRegion = page.getByRole('region', { name: '报告可用周期', exact: true });
    if (await availablePeriodRegion.count() !== 1) throw new Error('expected one truthful available-period region');
    const states = [];
    for (const periodLabel of ['日报', '周报', '月报']) {
      const expectedIndicatorCount = periodLabel === '日报' ? 7 : 11;
      const periodButton = page.locator('[aria-label="报告周期"] button').filter({ hasText: periodLabel });
      if (await periodButton.count() !== 1) throw new Error(`missing period button ${periodLabel}`);
      await periodButton.click();
      await page.waitForFunction((label) => [...document.querySelectorAll('[aria-label="报告周期"] button')]
        .some((button) => button.textContent?.includes(label) && button.getAttribute('aria-pressed') === 'true'), periodLabel);
      const text = await page.locator('body').innerText();
      const availablePeriodText = (await availablePeriodRegion.innerText()).replace(/\s+/g, ' ').trim();
      const historicalPeriodSelect = page.getByRole('combobox', { name: '选择历史报告周期', exact: true });
      const historicalPeriodOptionCount = await historicalPeriodSelect.locator('option').count();
      const mindMap = page.locator('[data-testid="report-insight-mind-map"]');
      const mindMapText = await mindMap.innerText();
      const monitor = page.locator('section[aria-labelledby="report-monitor-title"]');
      const indicators = monitor.locator('[data-report-indicator]');
      const trendDirections = await indicators.locator('[data-report-trend]').evaluateAll((elements) => (
        elements.map((element) => element.getAttribute('data-report-trend'))
      ));
      const helpButtons = indicators.locator('[aria-label$="指标说明"]');
      const upStrokes = await indicators.locator('[data-report-trend="up"] polyline').evaluateAll((elements) => (
        elements.map((element) => element.getAttribute('stroke'))
      ));
      const downStrokes = await indicators.locator('[data-report-trend="down"] polyline').evaluateAll((elements) => (
        elements.map((element) => element.getAttribute('stroke'))
      ));
      const currentValues = await indicators.evaluateAll((elements) => elements.map((element) => (
        element.querySelector(':scope > p')?.textContent?.trim() ?? ''
      )));
      const monitorText = await monitor.innerText();
      states.push({
        collection: '最新完整周期',
        period: periodLabel,
        availablePeriodText,
        historicalPeriodOptionCount,
        expectedHistoricalPeriodOptionCount: periodLabel === '日报' ? 15 : 13,
        latestCompleteSelected: await historicalPeriodSelect.inputValue() === 'current',
        historyContractVisible: availablePeriodText.includes('环比与同比基期内置')
          && !availablePeriodText.includes('当前数据包未公开可独立浏览的历史报告'),
        completeness100: text.includes('历史采集完整性：数据所有者确认100%'),
        storyMapCount: await mindMap.count(),
        storyMapComplete: ['核心信号', '驱动诊断', '业务影响', '建议行动', '持续监测']
          .every((label) => mindMapText.includes(label)),
        operationalBody: ['声量趋势', '驱动与范围拆解', '真实帖子证据', '从洞察到行动']
          .every((label) => text.includes(label)),
        comparison: monitorText.includes('环比') && monitorText.includes('同比'),
        expectedIndicatorCount,
        indicatorCount: await indicators.count(),
        helpButtonCount: await helpButtons.count(),
        trendCount: trendDirections.length,
        upTrendCount: trendDirections.filter((direction) => direction === 'up').length,
        downTrendCount: trendDirections.filter((direction) => direction === 'down').length,
        flatTrendCount: trendDirections.filter((direction) => direction === 'flat').length,
        upTrendRed: upStrokes.every((stroke) => stroke === '#E95A76'),
        downTrendGreen: downStrokes.every((stroke) => stroke === '#00A86B'),
        unavailableAbsent: currentValues.length === expectedIndicatorCount
          && currentValues.every((value) => value !== '' && value !== '—')
          && !text.includes('v3-unavailable-appendix'),
        periodScopePresent: periodLabel === '日报'
          ? (
              text.includes('当日治理口径 Momcozy 新帖')
              && text.includes('新增评论')
            ) || text.includes('当日新发 Momcozy 相关帖子')
          : text.includes('品类'),
        legacyTermsAbsent: !text.includes('当前闭合期') && !text.includes('闭合归档'),
        dailyMidnightLabelAbsent: periodLabel !== '日报' || !text.includes('00:00'),
      });
    }
    const historyStates = [];
    for (const periodLabel of ['日报', '周报', '月报']) {
      const periodButton = page.locator('[aria-label="报告周期"] button').filter({ hasText: periodLabel });
      const historicalPeriodSelectBeforeClick = page.getByRole('combobox', { name: '选择历史报告周期', exact: true });
      const previousOptionSignature = await historicalPeriodSelectBeforeClick.locator('option').evaluateAll(
        (options) => options.map((option) => option.getAttribute('value') ?? '').join('|'),
      );
      const periodWasAlreadySelected = await periodButton.getAttribute('aria-pressed') === 'true';
      await periodButton.click();
      await page.waitForFunction(({ expectedOptionCount, previousSignature, requireChangedSignature }) => {
        const selector = document.querySelector('[aria-label="选择历史报告周期"]');
        return selector instanceof HTMLSelectElement
          && selector.options.length === expectedOptionCount
          && selector.value === 'current'
          && (!requireChangedSignature || [...selector.options]
            .map((option) => option.getAttribute('value') ?? '')
            .join('|') !== previousSignature);
      }, {
        expectedOptionCount: periodLabel === '日报' ? 15 : 13,
        previousSignature: previousOptionSignature,
        requireChangedSignature: !periodWasAlreadySelected,
      });
      const historicalPeriodSelect = page.getByRole('combobox', { name: '选择历史报告周期', exact: true });
      const optionValues = await historicalPeriodSelect.locator('option').evaluateAll((options) => options.map(
        (option) => ({ value: option.getAttribute('value') ?? '', label: option.textContent?.trim() ?? '' }),
      ));
      const historicalOption = optionValues.find((option) => option.value !== 'current');
      if (!historicalOption) throw new Error(`missing historical option for ${periodLabel}`);
      const historyRequests = [];
      const observeHistoryRequest = (request) => {
        const observedUrl = request.url();
        if (observedUrl.startsWith(baseUrl) && observedUrl.includes('/history/') && observedUrl.endsWith('.json')) {
          historyRequests.push(observedUrl);
        }
      };
      page.on('request', observeHistoryRequest);
      await historicalPeriodSelect.selectOption(historicalOption.value);
      await page.waitForFunction(({ expectedPeriodId }) => {
        const selector = document.querySelector('[aria-label="选择历史报告周期"]');
        const mindMap = document.querySelector('[data-testid="report-insight-mind-map"]');
        return selector?.value === expectedPeriodId
          && mindMap?.getAttribute('data-period-id') === expectedPeriodId;
      }, { expectedPeriodId: historicalOption.value });
      await page.waitForLoadState('networkidle', { timeout: 10_000 });
      page.off('request', observeHistoryRequest);
      const selectedText = await page.locator('body').innerText();
      historyStates.push({
        period: periodLabel,
        periodId: historicalOption.value,
        historyRequestCount: historyRequests.length,
        selectedLabelPresent: selectedText.includes(historicalOption.label),
        historicalEntryVisible: selectedText.includes('历史完整周期'),
        urlBound: readQueryParam(page.url(), 'period_id') === encodeURIComponent(historicalOption.value),
      });
      await historicalPeriodSelect.selectOption('current');
      await page.waitForFunction(({ previousPeriodId }) => {
        const selector = document.querySelector('[aria-label="选择历史报告周期"]');
        const mindMap = document.querySelector('[data-testid="report-insight-mind-map"]');
        return selector?.value === 'current'
          && mindMap?.getAttribute('data-period-id') !== previousPeriodId;
      }, { previousPeriodId: historicalOption.value });
    }

    const dailyHistory = historyStates.find((state) => state.period === '日报');
    if (!dailyHistory) throw new Error('daily history selection evidence is missing');
    const deepLinkHistoryRequests = [];
    const observeDeepLinkHistoryRequest = (request) => {
      const observedUrl = request.url();
      if (observedUrl.startsWith(baseUrl) && observedUrl.includes('/history/') && observedUrl.endsWith('.json')) {
        deepLinkHistoryRequests.push(observedUrl);
      }
    };
    page.on('request', observeDeepLinkHistoryRequest);
    await page.goto(`${baseUrl}/dashboard/reports?period=daily&period_id=${encodeURIComponent(dailyHistory.periodId)}`, {
      waitUntil: 'domcontentloaded',
      timeout: 20_000,
    });
    await page.waitForFunction(({ expectedPeriodId }) => {
      const selector = document.querySelector('[aria-label="选择历史报告周期"]');
      const mindMap = document.querySelector('[data-testid="report-insight-mind-map"]');
      return selector?.value === expectedPeriodId
        && mindMap?.getAttribute('data-period-id') === expectedPeriodId;
    }, { expectedPeriodId: dailyHistory.periodId });
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    page.off('request', observeDeepLinkHistoryRequest);
    const historyDeepLink = {
      periodId: dailyHistory.periodId,
      historyRequestCount: deepLinkHistoryRequests.length,
      selected: await page.getByRole('combobox', { name: '选择历史报告周期', exact: true }).inputValue(),
      urlBound: readQueryParam(page.url(), 'period_id') === encodeURIComponent(dailyHistory.periodId),
    };
    return {
      headingCount,
      periodButtonText,
      availablePeriodRegionCount: await availablePeriodRegion.count(),
      states,
      historyStates,
      historyDeepLink,
    };
  });

  if (reportStates) {
    assertContract(reportStates.headingCount >= 1, 'reports-heading');
    assertContract(
      ['日报', '周报', '月报'].every((label) => reportStates.periodButtonText.some(
        (text) => text.startsWith(label),
      )),
      'reports-three-booklets',
    );
    assertContract(
      reportStates.availablePeriodRegionCount === 1
      && reportStates.states.length === 3,
      'reports-truthful-current-period-three-states',
    );
    assertContract(
      reportStates.states.every((state) => state.completeness100
        && state.storyMapCount === 1
        && state.storyMapComplete
        && state.operationalBody
        && state.comparison
        && state.indicatorCount === state.expectedIndicatorCount
        && state.helpButtonCount === state.indicatorCount
        && state.trendCount > 0
        && state.upTrendRed
        && state.downTrendGreen
        && state.unavailableAbsent
        && state.periodScopePresent
        && state.historicalPeriodOptionCount === state.expectedHistoricalPeriodOptionCount
        && state.latestCompleteSelected
        && state.historyContractVisible
        && state.availablePeriodText.includes('数据锚点：')
        && state.legacyTermsAbsent
        && state.dailyMidnightLabelAbsent),
      `reports-operational-body-computable-pop-yoy-trend-and-spu:${JSON.stringify(reportStates.states)}`,
    );
    assertContract(
      reportStates.historyStates.length === 3
      && reportStates.historyStates.every((state) => state.historyRequestCount === 1
        && state.selectedLabelPresent
        && state.historicalEntryVisible
        && state.urlBound)
      && reportStates.historyDeepLink.selected === reportStates.historyDeepLink.periodId
      && reportStates.historyDeepLink.historyRequestCount === 1
      && reportStates.historyDeepLink.urlBound,
      `reports-history-select-and-deep-link:${JSON.stringify({ states: reportStates.historyStates, deepLink: reportStates.historyDeepLink })}`,
    );
  }

  async function captureSearchFilters() {
    // Run this contract before the route matrix on the freshly opened CLI page.
    // Network idle can precede the React data UI, so the exact accessible
    // combobox below is the business-readiness signal before assertions.
    const searchPage = page;
    await searchPage.setViewportSize(viewports[0]);
    const gotoSearch = async () => {
      const response = await searchPage.goto(`${baseUrl}/dashboard/search`, {
        waitUntil: 'domcontentloaded',
        timeout: 20_000,
      });
      await searchPage.waitForLoadState('networkidle', { timeout: 10_000 });
      await searchPage.locator('body').waitFor({ state: 'visible', timeout: 10_000 });
      return response;
    };
    await gotoSearch();
    const newFilterLabels = [
      '品牌筛选',
      '严重度筛选',
      '品类筛选',
      '产品族筛选',
      'SPU 筛选',
      '标签筛选',
      '最低 Score',
      '最低关联评论数',
    ];
    const brandFilter = searchPage.getByRole('combobox', { name: '品牌筛选', exact: true });
    await brandFilter.waitFor({ state: 'visible', timeout: 60_000 });
    const individualBrandOptionCount = await brandFilter.locator('option').evaluateAll((options) => (
      options.filter((option) => option.value.startsWith('brand:')).length
    ));
    const filterCounts = {};
    for (const label of newFilterLabels) {
      filterCounts[label] = await searchPage.getByRole('combobox', { name: label, exact: true }).count();
    }
    const optionCounts = {};
    for (const label of ['严重度筛选', '品类筛选', '产品族筛选', 'SPU 筛选', '标签筛选']) {
      optionCounts[label] = await searchPage.getByRole('combobox', { name: label, exact: true }).locator('option').count();
    }
    await brandFilter.selectOption('momcozy');
    await searchPage.getByRole('combobox', { name: '最低 Score', exact: true }).selectOption('5');
    await searchPage.getByRole('combobox', { name: '最低关联评论数', exact: true }).selectOption('1');
    const bodyText = await searchPage.locator('body').innerText();
    const resultMatch = bodyText.match(/找到\s+(\d+)\s+条真实帖子/);
    return {
      headingCount: await searchPage.getByRole('heading', { name: '真实帖子搜索', exact: true }).count(),
      filterCounts,
      optionCounts,
      individualBrandOptionCount,
      selectedBrand: await searchPage.getByRole('combobox', { name: '品牌筛选', exact: true }).inputValue(),
      selectedScore: await searchPage.getByRole('combobox', { name: '最低 Score', exact: true }).inputValue(),
      selectedComments: await searchPage.getByRole('combobox', { name: '最低关联评论数', exact: true }).inputValue(),
      resultCount: resultMatch ? Number(resultMatch[1]) : null,
      resultArticleCount: await searchPage.locator('article').count(),
      clearFiltersVisible: bodyText.includes('清除全部筛选'),
    };
  }

  async function captureUrlState() {
    await page.setViewportSize(viewports[0]);

    await gotoRoute('/dashboard/reports?period=weekly');
    await page.locator('[aria-label="报告周期"] button').filter({ hasText: '周报' }).waitFor({ state: 'visible' });
    await page.locator('[aria-label="报告周期"] button').filter({ hasText: '月报' }).click();
    await page.waitForFunction(() => new URL(window.location.href).searchParams.get('period') === 'monthly');
    await gotoRoute('/dashboard');
    await page.goBack({ waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    const restoredReportPeriod = readQueryParam(page.url(), 'period');
    const restoredReportPressed = await page.locator('[aria-label="报告周期"] button').filter({ hasText: '月报' }).getAttribute('aria-pressed');

    await gotoRoute('/dashboard?range=near1week');
    await page.getByRole('tab', { name: '近半年', exact: true }).click();
    await page.waitForFunction(() => new URL(window.location.href).searchParams.get('range') === 'near6months');
    await gotoRoute('/dashboard/insights');
    await page.goBack({ waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    const restoredDashboardRange = readQueryParam(page.url(), 'range');
    const restoredDashboardRangeSelected = await page.getByRole('tab', { name: '近半年', exact: true }).getAttribute('aria-selected');
    const restoredDashboardPostVocs = Number(await page.locator('[data-kpi-label="Momcozy 相关帖子"]').getAttribute('data-kpi-value'));
    const restoredDashboardTotalVocs = Number(await page.locator('[data-kpi-label="VOC 观察量"]').getAttribute('data-kpi-value'));

    await gotoRoute('/dashboard/insights?theme=pain');
    await page.locator('#insight-theme-tab-geo').click();
    await page.waitForFunction(() => new URL(window.location.href).searchParams.get('theme') === 'geo');
    await gotoRoute('/dashboard');
    await page.goBack({ waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    const restoredInsightTheme = readQueryParam(page.url(), 'theme');
    const restoredInsightSelected = await page.locator('#insight-theme-tab-geo').getAttribute('aria-selected');
    const restoredInsightPanelTheme = await page.locator('#quarter-theme-panel').getAttribute('data-theme');

    await gotoRoute('/dashboard/ugc-showcase?sentiment=negative');
    const contentSentiment = page.getByRole('combobox', { name: '内容情感筛选', exact: true });
    await contentSentiment.waitFor({ state: 'visible', timeout: 20_000 });
    await contentSentiment.selectOption('positive');
    await page.waitForFunction(() => new URL(window.location.href).searchParams.get('sentiment') === 'positive');
    await gotoRoute('/dashboard');
    await page.goBack({ waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    const restoredContentSentiment = await page.getByRole('combobox', { name: '内容情感筛选', exact: true }).inputValue();

    await gotoRoute('/dashboard/search?brand=momcozy&sentiment=negative&minScore=5&minComments=1&page=2');
    const brandFilter = page.getByRole('combobox', { name: '品牌筛选', exact: true });
    await brandFilter.waitFor({ state: 'visible', timeout: 60_000 });
    await gotoRoute('/dashboard');
    await page.goBack({ waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle', { timeout: 10_000 });
    await brandFilter.waitFor({ state: 'visible', timeout: 60_000 });
    const restoredSearchParams = Object.fromEntries(
      ['brand', 'sentiment', 'minScore', 'minComments', 'page'].map((key) => [key, readQueryParam(page.url(), key)]),
    );
    const restoredSearchInputs = {
      brand: await page.getByRole('combobox', { name: '品牌筛选', exact: true }).inputValue(),
      sentiment: await page.getByRole('combobox', { name: '情感筛选', exact: true }).inputValue(),
      minScore: await page.getByRole('combobox', { name: '最低 Score', exact: true }).inputValue(),
      minComments: await page.getByRole('combobox', { name: '最低关联评论数', exact: true }).inputValue(),
    };

    return {
      restoredReportPeriod,
      restoredReportPressed,
      restoredDashboardRange,
      restoredDashboardRangeSelected,
      restoredDashboardPostVocs,
      restoredDashboardTotalVocs,
      restoredInsightTheme,
      restoredInsightSelected,
      restoredInsightPanelTheme,
      restoredContentSentiment,
      restoredSearchParams,
      restoredSearchInputs,
    };
  }

  if (urlStateContract) {
    assertContract(
      urlStateContract.restoredReportPeriod === 'monthly'
      && urlStateContract.restoredReportPressed === 'true'
      && urlStateContract.restoredDashboardRange === 'near6months'
      && urlStateContract.restoredDashboardRangeSelected === 'true'
      && urlStateContract.restoredDashboardPostVocs === 239
      && urlStateContract.restoredDashboardTotalVocs === 2099
      && urlStateContract.restoredInsightTheme === 'geo'
      && urlStateContract.restoredInsightSelected === 'true'
      && urlStateContract.restoredInsightPanelTheme === 'geo'
      && urlStateContract.restoredContentSentiment === 'positive'
      && JSON.stringify(urlStateContract.restoredSearchParams) === JSON.stringify({
        brand: 'momcozy',
        sentiment: 'negative',
        minScore: '5',
        minComments: '1',
        page: '2',
      })
      && JSON.stringify(urlStateContract.restoredSearchInputs) === JSON.stringify({
        brand: 'momcozy',
        sentiment: 'negative',
        minScore: '5',
        minComments: '1',
      }),
      `url-state-restored-after-browser-back:${JSON.stringify(urlStateContract)}`,
    );
  }

  if (searchContract) {
    assertContract(
      searchContract.headingCount === 1
      && Object.values(searchContract.filterCounts).every((count) => count === 1)
      && Object.values(searchContract.optionCounts).every((count) => count > 1)
      && searchContract.individualBrandOptionCount > 0,
      'search-brand-severity-product-tag-interaction-filters-present',
    );
    assertContract(
      searchContract.selectedBrand === 'momcozy'
      && searchContract.selectedScore === '5'
      && searchContract.selectedComments === '1'
      && typeof searchContract.resultCount === 'number'
      && searchContract.resultCount > 0
      && searchContract.resultArticleCount > 0
      && searchContract.clearFiltersVisible,
      'search-real-filter-combination-returns-real-posts',
    );
  }

  const caseContract = await captureContract('cases-dom', async () => {
    await page.setViewportSize(viewports[0]);
    await gotoRoute('/cases');
    const referenceTab = page.getByRole('tab', { name: '参考案例', exact: true });
    const operationsTab = page.getByRole('tab', { name: '运营闭环', exact: true });
    const reviewTab = page.getByRole('tab', { name: '待复核', exact: true });
    await page.waitForFunction(() => /已加载\s+\d+\s+条案例/.test(document.body.innerText));
    const bodyText = await page.locator('body').innerText();
    const referenceCountMatch = bodyText.match(/已加载\s+(\d+)\s+条案例/);
    const referenceDefaultEligible = referenceCountMatch ? Number(referenceCountMatch[1]) : null;
    const referenceSelected = await referenceTab.getAttribute('aria-selected');
    const referenceExternalCards = await page.locator('a.card[target="_blank"]').count();
    const excludedApplePodcastSeed = !bodyText.includes('Vol.33 不只本土化和活人感');

    await reviewTab.click();
    await page.waitForFunction(() => document.body.innerText.includes('已加载 17 条案例'));
    const reviewText = await page.locator('body').innerText();
    const reviewOnlyMatch = reviewText.match(/已加载\s+(\d+)\s+条案例/);
    const reviewOnly = reviewOnlyMatch ? Number(reviewOnlyMatch[1]) : null;
    const reviewExternalCards = await page.locator('a.card[target="_blank"]').count();
    const reviewInternalCards = await page.locator('article[data-external-navigation="disabled"]').count();

    await operationsTab.click();
    const operationsTitle = page.getByText('Momcozy 社区信任与疑似非自然推广治理事件', { exact: true });
    await operationsTitle.waitFor({ state: 'visible' });
    const operationsDossiers = await operationsTitle.count();
    const operationsExternalLink = await operationsTitle.locator('xpath=ancestor::a').count();
    await page.getByRole('button', { name: '查看治理闭环', exact: true }).click();
    const drawer = page.getByRole('dialog', { name: 'Momcozy 社区信任与疑似非自然推广治理事件', exact: true });
    await drawer.waitFor({ state: 'visible' });
    const stageHeadings = [];
    for (const stage of ['洞察', '证据', '行动', '监测', '复盘']) {
      stageHeadings.push(await drawer.getByRole('heading', { name: stage, exact: true }).count());
    }
    const drawerText = await drawer.innerText();
    return {
      headingCount: await page.getByRole('heading', { name: 'Reddit 数据应用案例精选', exact: true }).count(),
      bodyText,
      autoDeltaCheck: bodyText.includes('自动检查增量') && bodyText.includes('检查增量'),
      tabCount: (await referenceTab.count()) + (await operationsTab.count()) + (await reviewTab.count()),
      referenceSelected,
      referenceDefaultEligible,
      referenceExternalCards,
      excludedApplePodcastSeed,
      reviewOnly,
      reviewExternalCards,
      reviewInternalCards,
      operationsDossiers,
      operationsExternalLink,
      stageHeadings,
      drawerLinkCount: await drawer.getByRole('link').count(),
      suggestionVisible: drawerText.includes('建议方案'),
      attributionBoundaryVisible: drawerText.includes('brand_control_confirmed=false')
        && !drawerText.includes('已确认品牌机器人项目'),
    };
  });

  if (caseContract && releaseArtifacts) {
    assertContract(caseContract.headingCount === 1, 'cases-curated-heading');
    assertContract(
      caseContract.tabCount === 3
      && caseContract.referenceSelected === 'true'
      && caseContract.referenceDefaultEligible === 33
      && caseContract.referenceExternalCards > 0
      && caseContract.excludedApplePodcastSeed,
      'cases-reference-default-high-quality-only',
    );
    assertContract(
      caseContract.reviewOnly === 17
      && caseContract.reviewExternalCards === 0
      && caseContract.reviewInternalCards > 0,
      'cases-review-only-no-external-navigation',
    );
    assertContract(
      caseContract.operationsDossiers === 1
      && caseContract.operationsExternalLink === 0
      && caseContract.stageHeadings.every((count) => count === 1)
      && caseContract.drawerLinkCount === 0
      && caseContract.suggestionVisible
      && caseContract.attributionBoundaryVisible,
      'cases-internal-five-stage-governance-drawer',
    );
    assertContract(caseContract.autoDeltaCheck, 'cases-increment-check-ui');
  }

  const collectorContract = await captureContract('collector-link', async () => {
    await page.setViewportSize(viewports[0]);
    await gotoRoute('/dashboard');
    const externalBeforeInspection = [...new Set(externalRequests)].length;
    const links = await page.locator('a[href="https://reddit.brand.lute-tlz-dddd.top/"]').evaluateAll(
      (elements) => elements.map((element) => ({
        href: element.getAttribute('href'),
        target: element.getAttribute('target'),
        rel: element.getAttribute('rel'),
        referrerPolicy: element.getAttribute('referrerpolicy'),
        ariaLabel: element.getAttribute('aria-label'),
      })),
    );
    const externalAfterInspection = [...new Set(externalRequests)].length;
    return {
      links,
      externalBeforeInspection,
      externalAfterInspection,
      clicked: false,
    };
  });

  if (collectorContract) {
    assertContract(collectorContract.links.length > 0, 'collector-link-present');
    assertContract(
      collectorContract.links.every((link) => {
        const relTokens = new Set((link.rel ?? '').split(/\s+/).filter(Boolean));
        return link.href === 'https://reddit.brand.lute-tlz-dddd.top/'
          && link.target === '_blank'
          && relTokens.has('noopener')
          && relTokens.has('noreferrer')
          && link.referrerPolicy === 'no-referrer'
          && link.ariaLabel === '采集后台';
      }),
      'collector-link-safe-attributes',
    );
    assertContract(
      collectorContract.externalBeforeInspection === 0
      && collectorContract.externalAfterInspection === 0
      && collectorContract.clicked === false,
      'collector-link-zero-external-request-before-click',
    );
  }

  const uniqueExternalRequests = [...new Set(externalRequests)];
  const uniqueBrowserErrors = [...new Set(browserErrors)];
  const uniqueHttpFailures = [...new Set(sameOriginHttpFailures)];
  const failedRoutes = results.filter((result) => (
    result.error
    || result.status !== 200
    || result.finalPath !== result.route
    || result.textLength < 100
    || result.requiredTextPresent === false
    || result.forbiddenLegacyGateTextPresent === true
    || result.horizontalOverflow === true
    || result.passwordInputs !== 0
    || result.loginControls?.length > 0
    || result.abnormalPromptIcons !== 0
  ));
  const failures = [
    ...failedRoutes.map((result) => `route:${result.viewport}:${result.route}:${JSON.stringify({
      error: result.error,
      status: result.status,
      finalPath: result.finalPath,
      textLength: result.textLength,
      requiredTextPresent: result.requiredTextPresent,
      forbiddenLegacyGateTextPresent: result.forbiddenLegacyGateTextPresent,
      horizontalOverflow: result.horizontalOverflow,
      overflowDiagnostics: result.overflowDiagnostics,
      passwordInputs: result.passwordInputs,
      loginControls: result.loginControls,
      abnormalPromptIcons: result.abnormalPromptIcons,
    })}`),
    ...contractFailures.map((failure) => `contract:${failure}`),
    ...uniqueBrowserErrors.map((failure) => `browser:${failure}`),
    ...uniqueHttpFailures.map((failure) => `http:${failure}`),
    ...uniqueExternalRequests.map((failure) => `external:${failure}`),
  ];
  if (failures.length > 0) {
    throw new Error(`Reddit VOC release E2E failed closed: ${JSON.stringify(failures.slice(0, 40))}`);
  }

  return {
    status: 'passed',
    evidenceLevel: 'browser_dom_network_acceptance',
    baseUrl,
    routes: results,
    release: releaseArtifacts ? {
      releaseSha256: releaseArtifacts.siteReleaseMarker?.release_sha256,
      releaseId: releaseArtifacts.release.release_id,
      releasePointerSha256: releaseArtifacts.releaseSha256,
      datasetVersions: Object.fromEntries(Object.entries(releaseArtifacts.release.datasets).map(
        ([key, binding]) => [key, binding.dataset_version],
      )),
      noLogin: releaseArtifacts.release.boundaries.login_required === false,
      collectorIsolation: releaseArtifacts.release.boundaries.collector_isolation_required === true,
    } : null,
    observedAtUtc: new Date().toISOString(),
    dashboard: {
      missionImageAbsent: true,
      circularRadarAndFiveClickableFormulas: true,
      threeUrlBackedRangesExact: true,
      dualAxisTrendExact: true,
      executiveDigestPresent: true,
    },
    insights: {
      quarterWindowAndCountsExact: true,
      eightPersonaGroupsAndQuarterAssignmentsExact: true,
      fourUrlBackedThemeTabsExact: true,
      geoAndAutomationCountsExact: true,
      automationAttributionBoundaryVisible: true,
      caseReferencesMethodOnly: true,
      controlledEvidence: true,
      legacyDarkPanelsAbsent: true,
    },
    reports: reportStates?.states ?? [],
    cases: releaseArtifacts ? {
      curatedSeed: releaseArtifacts.caseManifest.seed.count,
      legacyUnverified: releaseArtifacts.caseManifest.legacyUnverified.count,
      approvedDelta: releaseArtifacts.caseManifest.approvedDelta.count,
      stockPreserved: true,
      threeViews: caseContract?.tabCount === 3,
      referenceDefaultEligible: caseContract?.referenceDefaultEligible ?? null,
      reviewOnly: caseContract?.reviewOnly ?? null,
      operationsDossiers: caseContract?.operationsDossiers ?? null,
      internalFiveStageDrawer: caseContract?.stageHeadings.every((count) => count === 1) ?? false,
    } : null,
    casebook: releaseArtifacts ? {
      relativeRoot: casebookRoot.slice(1),
      manifestSha256: releaseArtifacts.casebookManifestSha256,
      dataSha256: releaseArtifacts.casebookDataSha256,
      dossierCount: releaseArtifacts.casebookData?.dossiers?.length ?? 0,
      externalNavigation: releaseArtifacts.casebookData?.boundaries?.external_navigation,
    } : null,
    collector: collectorContract,
    browserErrors: [],
    sameOriginHttpFailures: [],
    externalRequests: [],
    screenshots: false,
  };
})
