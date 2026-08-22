(async (page) => {
  const browserErrors = [];
  const requestFailures = [];
  const httpFailures = [];
  const externalRequests = [];
  const originMatch = page.url().match(/^(https?:\/\/[^/]+)/);
  if (!originMatch) throw new Error(`capture-origin-invalid:${page.url()}`);
  const origin = originMatch[1];

  page.on('pageerror', (error) => browserErrors.push(`pageerror:${error.message}`));
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'assert') {
      browserErrors.push(`console-${message.type()}:${message.text()}`);
    }
  });
  page.on('requestfailed', (request) => {
    requestFailures.push(`${request.method()}:${request.url()}:${request.failure()?.errorText ?? 'unknown'}`);
  });
  page.on('response', (response) => {
    if (response.url().startsWith(origin) && response.status() >= 400) {
      httpFailures.push(`${response.status()}:${response.url()}`);
    }
  });
  page.on('request', (request) => {
    const url = request.url();
    if (!url.startsWith(origin) && !url.startsWith('blob:') && !url.startsWith('data:')) {
      externalRequests.push(url);
    }
  });

  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30_000 });
  await page.waitForLoadState('networkidle', { timeout: 20_000 });

  const ready = page.locator('[data-report-capture-root][data-report-ready="true"]');
  const captureError = page.locator('[data-report-capture-error]');
  await Promise.race([
    ready.waitFor({ state: 'visible', timeout: 20_000 }),
    captureError.waitFor({ state: 'visible', timeout: 20_000 }).then(async () => {
      throw new Error(`capture-error:${await captureError.innerText()}`);
    }),
  ]);
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });

  const stableBoxes = [];
  for (let index = 0; index < 3; index += 1) {
    const box = await ready.boundingBox();
    if (!box) throw new Error('capture-root-missing-bounding-box');
    stableBoxes.push({
      x: Math.round(box.x),
      y: Math.round(box.y),
      width: Math.round(box.width),
      height: Math.round(box.height),
    });
    await page.waitForTimeout(120);
  }

  const contract = await ready.evaluate((root) => {
    const attributes = Object.fromEntries(
      [...root.attributes]
        .filter((attribute) => attribute.name.startsWith('data-report-'))
        .map((attribute) => [attribute.name, attribute.value]),
    );
    const rootRectangle = root.getBoundingClientRect();
    const footer = root.querySelector('footer');
    const body = root.querySelector('[data-report-poster-body]');
    const footerRectangle = footer?.getBoundingClientRect() ?? null;
    const bodyRectangle = body?.getBoundingClientRect() ?? null;
    const visibleTooltips = [...root.querySelectorAll('.recharts-tooltip-wrapper,[role="tooltip"]')]
      .filter((element) => {
        const style = getComputedStyle(element);
        const rectangle = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rectangle.width > 0 && rectangle.height > 0;
      }).length;
    const text = (root.textContent ?? '').replace(/\s+/g, ' ').trim();
    const textBlocks = [...root.querySelectorAll('h1,h2,h3,p,li,dd')]
      .map((element) => (element.textContent ?? '').replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    const chartCount = root.querySelectorAll('svg.recharts-surface').length;
    const cardCount = root.querySelectorAll('.card,.rounded-card').length;
    return {
      attributes,
      root: {
        clientWidth: root.clientWidth,
        clientHeight: root.clientHeight,
        scrollWidth: root.scrollWidth,
        scrollHeight: root.scrollHeight,
        rectangleWidth: Math.round(rootRectangle.width),
        rectangleHeight: Math.round(rootRectangle.height),
      },
      footerOverlap: Boolean(
        footerRectangle
        && bodyRectangle
        && bodyRectangle.bottom > footerRectangle.top - 8
      ),
      fontsStatus: document.fonts.status,
      visibleTooltips,
      textLength: text.length,
      chineseCharacterCount: (text.match(/[\u3400-\u9fff]/g) ?? []).length,
      maxTextBlockLength: Math.max(0, ...textBlocks.map((value) => value.length)),
      containsExtremePercent: /(?:\+|-)?\d{4,}(?:\.\d+)?%/.test(text),
      chartCount,
      cardCount,
      hasLoadingText: /正在加载|加载真实数据|重新加载中|骨架/.test(text),
      hasCaptureError: Boolean(root.querySelector('[data-report-capture-error]')),
    };
  });

  return {
    status: 'observed',
    url: page.url(),
    stableBoxes,
    contract,
    browserErrors,
    requestFailures,
    httpFailures,
    externalRequests,
  };
})
