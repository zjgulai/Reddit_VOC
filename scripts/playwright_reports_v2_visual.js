(async (page) => {
  const outputDir = '/Users/pray/project/Reddit_VOC/tmp/ui-v2-reports-visual-20260722';
  const modes = [
    { name: 'desktop', width: 1440, height: 1000, reducedMotion: 'no-preference' },
    { name: 'tablet', width: 1024, height: 1366, reducedMotion: 'no-preference' },
    { name: 'mobile-390', width: 390, height: 844, reducedMotion: 'no-preference' },
    { name: 'mobile-390-reduced', width: 390, height: 844, reducedMotion: 'reduce' },
  ];
  const periods = [
    { id: 'daily', label: '日报', story: '昨日发生了什么，今天先处理什么' },
    { id: 'weekly', label: '周报', story: '本周结构如何变化，下周资源放在哪里' },
    { id: 'monthly', label: '月报', story: '本月品牌发生了什么，下一阶段如何取舍' },
  ];
  const originMatch = page.url().match(/^(https?:\/\/[^/]+)/);
  if (!originMatch) throw new Error(`cannot determine origin from ${page.url()}`);
  const origin = originMatch[1];
  const browserErrors = [];
  const rows = [];

  page.on('pageerror', (error) => browserErrors.push(`pageerror:${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'assert') {
      browserErrors.push(`console-${message.type()}:${message.text()}`);
    }
  });
  page.on('requestfailed', (request) => {
    browserErrors.push(`requestfailed:${request.method()}:${request.url()}`);
  });

  for (const mode of modes) {
    await page.setViewportSize({ width: mode.width, height: mode.height });
    await page.emulateMedia({ reducedMotion: mode.reducedMotion });
    for (const period of periods) {
      const response = await page.goto(`${origin}/dashboard/reports?period=${period.id}`, {
        waitUntil: 'domcontentloaded',
        timeout: 30_000,
      });
      await page.getByRole('heading', { name: period.story, exact: true }).waitFor({
        state: 'visible',
        timeout: 60_000,
      });
      const availablePeriod = page.getByRole('region', { name: '报告可用周期', exact: true });
      const storyPath = page.getByRole('list', { name: `${period.label}叙事路径`, exact: true });
      const fakeSelectorCount = await page.getByRole('button', { name: '最新完整周期', exact: true }).count();
      const geometry = await page.evaluate(() => ({
        clientWidth: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
      }));
      const screenshot = `${outputDir}/${mode.name}-${period.id}.png`;
      await page.screenshot({ path: screenshot, fullPage: true });
      rows.push({
        mode: mode.name,
        period: period.id,
        status: response?.status() ?? null,
        horizontalOverflow: geometry.scrollWidth > geometry.clientWidth + 1,
        availablePeriodCount: await availablePeriod.count(),
        archiveBoundaryPresent: (await availablePeriod.innerText()).includes('当前数据包未公开可独立浏览的历史报告'),
        storyPathCount: await storyPath.count(),
        fakeSelectorCount,
        screenshot,
      });
    }
  }

  const passed = browserErrors.length === 0 && rows.every((row) => (
    row.status === 200
    && row.horizontalOverflow === false
    && row.availablePeriodCount === 1
    && row.archiveBoundaryPresent === true
    && row.storyPathCount === 1
    && row.fakeSelectorCount === 0
  ));
  return { status: passed ? 'passed' : 'failed', browserErrors, rows };
})
