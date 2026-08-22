import { createHash } from 'node:crypto';
import { lstat, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { relative, resolve, sep } from 'node:path';

const [
  distArg,
  outputArg,
  baseImage,
  deployArg,
  projectArg,
  nodeVersion,
  npmVersion,
  baseVersion,
  insightsVersion,
  reportsVersion,
  personasVersion,
  currentReleaseRelativePath,
  latestCollectionIntegratedArg,
  latestCollectionFullyHydratedArg,
  packageLockArg,
  dockerignoreArg,
  frontendSourceManifestArg,
  frontendSourceReceiptArg,
] = process.argv.slice(2);

if (
  !distArg || !outputArg || !baseImage || !deployArg || !projectArg
  || !nodeVersion || !npmVersion || !baseVersion || !insightsVersion
  || !reportsVersion || !personasVersion || !currentReleaseRelativePath
) {
  throw new Error('usage: build-release.mjs <dist-dir> <output-dir> <digest-pinned-base-image> <deploy-dir> <project-dir> <node-version> <npm-version> <base-version> <insights-version> <reports-version> <personas-version> <current-release-relative-path> [latest-collection-integrated] [latest-collection-fully-hydrated] [package-lock-path] [dockerignore-path] [frontend-source-manifest-path] [frontend-source-receipt-path]');
}
if (Boolean(frontendSourceManifestArg) !== Boolean(frontendSourceReceiptArg)) {
  throw new Error('frontend source manifest and receipt must be supplied together');
}

function parseOptionalBoolean(value, label) {
  if (value === undefined) {
    return false;
  }
  if (value !== 'true' && value !== 'false') {
    throw new Error(`${label} must be true or false`);
  }
  return value === 'true';
}

const latestCollectionIntegrated = parseOptionalBoolean(
  latestCollectionIntegratedArg,
  'latest collection integrated',
);
const latestCollectionFullyHydrated = parseOptionalBoolean(
  latestCollectionFullyHydratedArg,
  'latest collection fully hydrated',
);
if (latestCollectionFullyHydrated && !latestCollectionIntegrated) {
  throw new Error('latest collection cannot be fully hydrated before it is integrated');
}
const collectionStatus = {
  latest_collection_integrated: latestCollectionIntegrated,
  latest_collection_fully_hydrated: latestCollectionFullyHydrated,
};

if (!baseImage.includes('@sha256:')) {
  throw new Error('base image must be pinned by sha256 digest');
}

const distRoot = resolve(distArg);
const outputRoot = resolve(outputArg);
const deployRoot = resolve(deployArg);
const projectRoot = resolve(projectArg);
const targetPlatform = 'linux/amd64';
const buildContractVersion = 'reddit_voc_insights_container_v6';
const dataRuntime = {
  contract_version: 'reddit_voc_data_mount_v1',
  mode: 'read_only_versioned_mount',
  host_root_environment: 'REDDIT_VOC_DATA_ROOT',
  container_root: '/srv/reddit-voc-data',
  current_pointer: 'current',
  public_alias: '/srv/reddit-voc-data/current/public/data/reddit-voc/',
  web_path: '/data/reddit-voc/',
  expected_mount_count: 1,
  read_only: true,
  atomic_pointer_switch_without_container_restart: true,
};
const dataRoot = 'data/reddit-voc';
const versionContract = {
  base: { version: baseVersion, prefix: 'reddit_voc_site_snapshot_', manifest: `${dataRoot}/${baseVersion}/manifest-public.json` },
  insights: { version: insightsVersion, prefix: 'reddit_voc_insights_', manifest: `${dataRoot}/${insightsVersion}/public/manifest.json` },
  reports: { version: reportsVersion, prefix: 'reddit_voc_reports_', manifest: `${dataRoot}/${reportsVersion}/public/manifest.json` },
  personas: { version: personasVersion, prefix: 'reddit_voc_personas_', manifest: `${dataRoot}/${personasVersion}/manifest.json` },
};
const safeIdentifierPattern = /^[a-z0-9][a-z0-9_-]{0,127}$/;
const sha256Pattern = /^[a-f0-9]{64}$/;
for (const [key, contract] of Object.entries(versionContract)) {
  if (!safeIdentifierPattern.test(contract.version) || !contract.version.startsWith(contract.prefix)) {
    throw new Error(`unsafe ${key} dataset version`);
  }
}
if (currentReleaseRelativePath !== `${dataRoot}/current-release.json`) {
  throw new Error('current-release must use the reviewed runtime path');
}

async function walk(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  const compareCodePoints = (left, right) => (
    left.name < right.name ? -1 : left.name > right.name ? 1 : 0
  );
  for (const entry of entries.sort(compareCodePoints)) {
    const path = resolve(directory, entry.name);
    if (entry.isSymbolicLink()) {
      throw new Error(`release input must not contain symlinks: ${path}`);
    }
    if (entry.isDirectory()) {
      files.push(...await walk(path));
    } else if (entry.isFile()) {
      files.push(path);
    } else {
      throw new Error(`unsupported release input: ${path}`);
    }
  }
  return files;
}

function sha256(bytes) {
  return createHash('sha256').update(bytes).digest('hex');
}

function assertExactKeys(value, expected, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new Error(`${label} field contract mismatch`);
  }
}

const rootStat = await lstat(distRoot);
if (!rootStat.isDirectory()) {
  throw new Error(`dist directory is missing: ${distRoot}`);
}

const paths = await walk(distRoot);
const files = [];
for (const path of paths) {
  const bytes = await readFile(path);
  const releasePath = relative(distRoot, path).split(sep).join('/');
  files.push({
    path: releasePath,
    bytes: bytes.length,
    sha256: sha256(bytes),
  });
}

const deploymentInputs = [];
for (const filename of ['Dockerfile', 'nginx.conf', 'compose.yaml', 'build-release.mjs']) {
  const path = resolve(deployRoot, filename);
  const stat = await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`deployment input must be a regular file: ${path}`);
  }
  const bytes = await readFile(path);
  deploymentInputs.push({ path: `deploy/insights/${filename}`, bytes: bytes.length, sha256: sha256(bytes) });
}
const packageLockPath = packageLockArg
  ? resolve(packageLockArg)
  : resolve(distRoot, '..', 'package-lock.json');
const packageLockStat = await lstat(packageLockPath);
if (!packageLockStat.isFile() || packageLockStat.isSymbolicLink()) {
  throw new Error(`package lock must be a regular file: ${packageLockPath}`);
}
const packageLockBytes = await readFile(packageLockPath);
const buildInputs = [{
  path: 'package-lock.json',
  bytes: packageLockBytes.length,
  sha256: sha256(packageLockBytes),
}];
const dockerignorePath = dockerignoreArg
  ? resolve(dockerignoreArg)
  : resolve(distRoot, '..', '.dockerignore');
for (const [releasePath, sourcePath] of [
  ['scripts/build_public_tag_dictionary.py', resolve(projectRoot, 'scripts', 'build_public_tag_dictionary.py')],
  ['scripts/build_public_site_projection.py', resolve(projectRoot, 'scripts', 'build_public_site_projection.py')],
  ['scripts/build_insights_release.sh', resolve(projectRoot, 'scripts', 'build_insights_release.sh')],
  ['scripts/audit_insights_dist.py', resolve(projectRoot, 'scripts', 'audit_insights_dist.py')],
  ['ref/UI/momcozy-reddit-workbench/.dockerignore', dockerignorePath],
]) {
  const builderPath = sourcePath;
  const builderStat = await lstat(builderPath);
  if (!builderStat.isFile() || builderStat.isSymbolicLink()) {
    throw new Error(`public projection builder must be a regular file: ${builderPath}`);
  }
  const builderBytes = await readFile(builderPath);
  buildInputs.push({
    path: releasePath,
    bytes: builderBytes.length,
    sha256: sha256(builderBytes),
  });
}
const toolchain = { node: nodeVersion, npm: npmVersion };

async function readFrontendSourceContract(manifestArg, receiptArg) {
  if (!manifestArg || !receiptArg) {
    return null;
  }
  const manifestPath = resolve(manifestArg);
  const receiptPath = resolve(receiptArg);
  const manifestStat = await lstat(manifestPath);
  if (!manifestStat.isFile() || manifestStat.isSymbolicLink()) {
    throw new Error('frontend source manifest must be a regular file');
  }
  const receiptStat = await lstat(receiptPath);
  if (!receiptStat.isFile() || receiptStat.isSymbolicLink()) {
    throw new Error('frontend source receipt must be a regular file');
  }
  const manifestBytes = await readFile(manifestPath);
  const receiptBytes = await readFile(receiptPath);
  const sourceManifest = JSON.parse(manifestBytes.toString('utf8'));
  const sourceReceipt = JSON.parse(receiptBytes.toString('utf8'));
  const isV3Source = sourceManifest.schema_version === 'reddit_voc_frontend_source_manifest_v2';
  if (
    !['reddit_voc_frontend_source_manifest_v1', 'reddit_voc_frontend_source_manifest_v2']
      .includes(sourceManifest.schema_version)
    || sourceManifest.status !== 'frontend_source_frozen_local'
    || !sha256Pattern.test(sourceManifest.frontend_candidate_input_sha256)
  ) {
    throw new Error('frontend source manifest contract mismatch');
  }
  const inventory = sourceManifest.source?.inventory;
  if (
    !inventory || typeof inventory !== 'object' || Array.isArray(inventory)
    || !Number.isInteger(inventory.file_count) || inventory.file_count <= 0
    || inventory.file_count > 50000
    || !Number.isInteger(inventory.total_bytes) || inventory.total_bytes < 0
    || !sha256Pattern.test(inventory.inventory_sha256)
  ) {
    throw new Error('frontend source inventory contract mismatch');
  }
  const sourceInventory = {
    file_count: inventory.file_count,
    inventory_sha256: inventory.inventory_sha256,
    total_bytes: inventory.total_bytes,
  };
  const manifestSha = sha256(manifestBytes);
  const expectedReceiptSchema = isV3Source
    ? 'reddit_voc_candidate_ui_source_validation_receipt_v2'
    : 'reddit_voc_candidate_ui_source_validation_receipt_v1';
  if (
    sourceReceipt.schema_version !== expectedReceiptSchema
    || sourceReceipt.status !== 'passed_local_source_validation'
    || sourceReceipt.frontend_candidate_input_sha256
      !== sourceManifest.frontend_candidate_input_sha256
    || sourceReceipt.frontend_source_manifest_sha256 !== manifestSha
    || JSON.stringify(sourceReceipt.source_inventory) !== JSON.stringify(sourceInventory)
  ) {
    throw new Error('frontend source lineage mismatch');
  }
  let v3Lineage = null;
  let periodicReportPublication = null;
  if (isV3Source) {
    const upstream = sourceManifest.upstream;
    const upstreamKeys = upstream && typeof upstream === 'object' && !Array.isArray(upstream)
      ? Object.keys(upstream).sort()
      : [];
    const allowedUpstreamKeys = upstream?.periodic_report_publication
      ? ['periodic_report_publication', 'v3_lineage']
      : ['v3_lineage'];
    if (
      !upstream || typeof upstream !== 'object' || Array.isArray(upstream)
      || JSON.stringify(upstreamKeys) !== JSON.stringify(allowedUpstreamKeys)
      || !upstream.v3_lineage || typeof upstream.v3_lineage !== 'object'
      || Array.isArray(upstream.v3_lineage)
    ) {
      throw new Error('V3 frontend source lineage is missing');
    }
    v3Lineage = upstream.v3_lineage;
    const datasets = v3Lineage.datasets;
    if (
      ![
        'reddit_voc_v3_four_dataset_frontend_lineage_v1',
        'reddit_voc_v3_seven_dataset_frontend_lineage_v2',
      ].includes(v3Lineage.contract)
      || !sha256Pattern.test(v3Lineage.current_release_pointer_sha256)
      || typeof v3Lineage.source_snapshot_id !== 'string'
      || !v3Lineage.source_snapshot_id
      || !datasets || typeof datasets !== 'object' || Array.isArray(datasets)
      || JSON.stringify(Object.keys(datasets).sort())
        !== JSON.stringify(['base', 'insights', 'personas', 'reports'])
    ) {
      throw new Error('V3 frontend source lineage contract mismatch');
    }
    for (const [name, binding] of Object.entries(datasets)) {
      if (
        !binding || typeof binding !== 'object' || Array.isArray(binding)
        || typeof binding.dataset_version !== 'string' || !binding.dataset_version
        || !sha256Pattern.test(binding.public_manifest_sha256)
        || !sha256Pattern.test(binding.lineage_manifest_sha256)
        || !sha256Pattern.test(binding.validation_receipt_sha256)
        || typeof binding.public_manifest_relative_path !== 'string'
        || !binding.public_manifest_relative_path.startsWith('public/data/reddit-voc/')
        || typeof binding.validation_receipt_schema !== 'string'
        || !binding.validation_receipt_schema.startsWith('reddit_voc_')
      ) {
        throw new Error(`V3 frontend ${name} lineage binding mismatch`);
      }
    }
    if (JSON.stringify(sourceReceipt.v3_lineage) !== JSON.stringify(v3Lineage)) {
      throw new Error('V3 frontend source receipt lineage mismatch');
    }
    if (JSON.stringify(sourceReceipt.upstream) !== JSON.stringify(upstream)) {
      throw new Error('V3 frontend source receipt upstream mismatch');
    }
    periodicReportPublication = upstream.periodic_report_publication ?? null;
    if (periodicReportPublication !== null) {
      const assets = periodicReportPublication.assets;
      if (
        typeof periodicReportPublication !== 'object'
        || Array.isArray(periodicReportPublication)
        || periodicReportPublication.contract
          !== 'reddit_voc_periodic_report_frontend_publication_v1'
        || !sha256Pattern.test(periodicReportPublication.manifest_sha256)
        || !sha256Pattern.test(periodicReportPublication.source_bundle_manifest_sha256)
        || typeof periodicReportPublication.manifest_relative_path !== 'string'
        || !periodicReportPublication.manifest_relative_path
          .startsWith('public/periodic-report-assets/')
        || !Array.isArray(assets)
        || assets.length !== 3
        || JSON.stringify(assets.map((asset) => asset.grain).sort())
          !== JSON.stringify(['daily', 'monthly', 'weekly'])
        || JSON.stringify(sourceReceipt.periodic_report_publication)
          !== JSON.stringify(periodicReportPublication)
      ) {
        throw new Error('V3 periodic report publication lineage mismatch');
      }
      for (const asset of assets) {
        if (
          !asset || typeof asset !== 'object' || Array.isArray(asset)
          || typeof asset.relative_path !== 'string'
          || !asset.relative_path.startsWith('public/periodic-report-assets/')
          || !Number.isInteger(asset.bytes) || asset.bytes <= 0
          || !sha256Pattern.test(asset.sha256)
        ) {
          throw new Error('V3 periodic report publication asset mismatch');
        }
      }
    } else if ('periodic_report_publication' in sourceReceipt) {
      throw new Error('V3 periodic report publication receipt is unexpected');
    }
  }
  const contract = {
    frontend_candidate_input_sha256: sourceManifest.frontend_candidate_input_sha256,
    manifest: {
      path: 'frontend/source/frontend-source-manifest.json',
      bytes: manifestBytes.length,
      sha256: manifestSha,
    },
    validation_receipt: {
      path: 'frontend/source/candidate-ui-source-validation-receipt.json',
      bytes: receiptBytes.length,
      sha256: sha256(receiptBytes),
    },
    source_inventory: sourceInventory,
  };
  if (isV3Source) {
    contract.contract_schema_version = sourceManifest.schema_version;
    contract.validation_receipt_schema_version = sourceReceipt.schema_version;
    contract.v3_lineage = v3Lineage;
    if (periodicReportPublication !== null) {
      contract.periodic_report_publication = periodicReportPublication;
    }
  }
  return contract;
}

const frontendSource = await readFrontendSourceContract(
  frontendSourceManifestArg,
  frontendSourceReceiptArg,
);

const currentReleaseBytes = await readFile(resolve(distRoot, currentReleaseRelativePath));
const currentRelease = JSON.parse(currentReleaseBytes.toString('utf8'));
const currentReleaseV2 = currentRelease.schema_version === 'reddit_voc_current_release_v2';
assertExactKeys(
  currentRelease,
  [
    'schema_version',
    'release_id',
    'generated_at_utc',
    'datasets',
    ...(currentReleaseV2 ? ['freshness'] : []),
    'cases',
    'boundaries',
  ],
  'current-release',
);
if (
  !['reddit_voc_current_release_v1', 'reddit_voc_current_release_v2']
    .includes(currentRelease.schema_version)
  || typeof currentRelease.release_id !== 'string'
  || !safeIdentifierPattern.test(currentRelease.release_id)
  || !currentRelease.release_id.startsWith('reddit_voc_release_')
) {
  throw new Error('current-release identity contract mismatch');
}
const auxiliaryVersionContract = {
  brand_health: { prefix: 'reddit_voc_brand_health_' },
  quarter_insights: { prefix: 'reddit_voc_quarter_insights_' },
  casebook: { prefix: 'reddit_voc_casebook_' },
};
assertExactKeys(
  currentRelease.datasets,
  [
    ...Object.keys(versionContract),
    ...(currentReleaseV2 ? Object.keys(auxiliaryVersionContract) : []),
  ],
  'current-release datasets',
);
if (currentReleaseV2) {
  if (
    !currentRelease.freshness || typeof currentRelease.freshness !== 'object'
    || !['complete', 'partial'].includes(currentRelease.freshness.status)
    || currentRelease.freshness.timezone !== 'Asia/Shanghai'
    || typeof currentRelease.freshness.center_snapshot_id !== 'string'
    || !currentRelease.freshness.center_snapshot_id
  ) {
    throw new Error('current-release freshness contract mismatch');
  }
}
assertExactKeys(
  currentRelease.boundaries,
  ['case_gallery_stock_preserved', 'collector_isolation_required', 'login_required'],
  'current-release boundaries',
);
if (
  currentRelease.boundaries.case_gallery_stock_preserved !== true
  || currentRelease.boundaries.collector_isolation_required !== true
  || currentRelease.boundaries.login_required !== false
) {
  throw new Error('current-release access/isolation boundaries are unsafe');
}
if (
  !currentRelease.cases || typeof currentRelease.cases !== 'object'
  || currentRelease.cases.stock_content_preserved !== true
) {
  throw new Error('current-release case preservation boundary is unsafe');
}

const datasetVersions = {};
const datasetManifests = {};
for (const [key, contract] of Object.entries(versionContract)) {
  const binding = currentRelease.datasets[key];
  assertExactKeys(
    binding,
    ['dataset_version', 'manifest_path', 'public_manifest_sha256', 'lineage_manifest_sha256'],
    `current-release datasets.${key}`,
  );
  if (
    binding.dataset_version !== contract.version
    || binding.manifest_path !== contract.manifest
    || !sha256Pattern.test(binding.public_manifest_sha256)
    || !sha256Pattern.test(binding.lineage_manifest_sha256)
  ) {
    throw new Error(`current-release ${key} binding mismatch`);
  }
  const manifestBytes = await readFile(resolve(distRoot, contract.manifest));
  if (sha256(manifestBytes) !== binding.public_manifest_sha256) {
    throw new Error(`current-release ${key} public manifest SHA-256 mismatch`);
  }
  const manifest = JSON.parse(manifestBytes.toString('utf8'));
  const observedManifestVersion = (
    key === 'personas' && manifest.schema_version === 'reddit_voc_personas_manifest_v3'
      ? manifest.snapshot_id
      : manifest.dataset_version
  );
  if (observedManifestVersion !== contract.version) {
    throw new Error(`${key} public manifest dataset_version mismatch`);
  }
  datasetVersions[key] = contract.version;
  datasetManifests[key] = {
    manifest_path: contract.manifest,
    public_manifest_sha256: binding.public_manifest_sha256,
    lineage_manifest_sha256: binding.lineage_manifest_sha256,
  };
}
if (currentReleaseV2) {
  for (const [key, contract] of Object.entries(auxiliaryVersionContract)) {
    const binding = currentRelease.datasets[key];
    assertExactKeys(
      binding,
      ['dataset_version', 'manifest_path', 'public_manifest_sha256', 'lineage_manifest_sha256'],
      `current-release datasets.${key}`,
    );
    const expectedManifest = `${dataRoot}/${binding.dataset_version}/manifest.json`;
    if (
      typeof binding.dataset_version !== 'string'
      || !safeIdentifierPattern.test(binding.dataset_version)
      || !binding.dataset_version.startsWith(contract.prefix)
      || binding.manifest_path !== expectedManifest
      || !sha256Pattern.test(binding.public_manifest_sha256)
      || binding.lineage_manifest_sha256 !== binding.public_manifest_sha256
    ) {
      throw new Error(`current-release ${key} binding mismatch`);
    }
    const manifestBytes = await readFile(resolve(distRoot, expectedManifest));
    if (sha256(manifestBytes) !== binding.public_manifest_sha256) {
      throw new Error(`current-release ${key} public manifest SHA-256 mismatch`);
    }
    const publicManifest = JSON.parse(manifestBytes.toString('utf8'));
    const observedVersion = publicManifest.dataset_version ?? publicManifest.projection_id;
    if (observedVersion !== binding.dataset_version) {
      throw new Error(`${key} public manifest dataset identity mismatch`);
    }
    datasetVersions[key] = binding.dataset_version;
    datasetManifests[key] = {
      manifest_path: expectedManifest,
      public_manifest_sha256: binding.public_manifest_sha256,
      lineage_manifest_sha256: binding.lineage_manifest_sha256,
    };
  }
}

const currentReleaseContract = {
  path: currentReleaseRelativePath,
  release_id: currentRelease.release_id,
  sha256: sha256(currentReleaseBytes),
};

if (frontendSource?.v3_lineage) {
  if (frontendSource.v3_lineage.current_release_pointer_sha256 !== currentReleaseContract.sha256) {
    throw new Error('V3 frontend source pointer does not match release dist');
  }
  for (const key of Object.keys(versionContract)) {
    const sourceBinding = frontendSource.v3_lineage.datasets[key];
    const releaseBinding = datasetManifests[key];
    if (
      sourceBinding.dataset_version !== datasetVersions[key]
      || sourceBinding.public_manifest_sha256 !== releaseBinding.public_manifest_sha256
      || sourceBinding.lineage_manifest_sha256 !== releaseBinding.lineage_manifest_sha256
      || sourceBinding.public_manifest_relative_path
        !== `public/${releaseBinding.manifest_path}`
    ) {
      throw new Error(`V3 frontend source ${key} does not match release dist`);
    }
  }
  if (currentReleaseV2) {
    const auxiliaryByPath = Object.fromEntries(
      (frontendSource.v3_lineage.auxiliary_public_manifests ?? [])
        .map((binding) => [binding.relative_path, binding.sha256]),
    );
    for (const key of Object.keys(auxiliaryVersionContract)) {
      const releaseBinding = datasetManifests[key];
      if (
        auxiliaryByPath[`public/${releaseBinding.manifest_path}`]
        !== releaseBinding.public_manifest_sha256
      ) {
        throw new Error(`V3 frontend source ${key} does not match release dist`);
      }
    }
  }
}

if (frontendSource?.periodic_report_publication) {
  const periodic = frontendSource.periodic_report_publication;
  if (periodic.data_release_id !== currentReleaseContract.release_id) {
    throw new Error('periodic report publication release identity mismatch');
  }
  const manifestRelative = periodic.manifest_relative_path.replace(/^public\//, '');
  const manifestBytes = await readFile(resolve(distRoot, manifestRelative));
  if (sha256(manifestBytes) !== periodic.manifest_sha256) {
    throw new Error('periodic report publication manifest SHA-256 mismatch');
  }
  for (const asset of periodic.assets) {
    const relative = asset.relative_path.replace(/^public\//, '');
    const payload = await readFile(resolve(distRoot, relative));
    if (payload.length !== asset.bytes || sha256(payload) !== asset.sha256) {
      throw new Error(`periodic report publication ${asset.grain} asset mismatch`);
    }
  }
}

const contentDescriptor = Buffer.from(JSON.stringify({
  build_contract_version: buildContractVersion,
  target_platform: targetPlatform,
  nginx_base_image: baseImage,
  files,
  deployment_inputs: deploymentInputs,
  build_inputs: buildInputs,
  toolchain,
  dataset_versions: datasetVersions,
  dataset_manifests: datasetManifests,
  current_release: currentReleaseContract,
  collection_status: collectionStatus,
  data_runtime: dataRuntime,
  ...(frontendSource ? { frontend_source: frontendSource } : {}),
}));
const releaseSha = sha256(contentDescriptor);

const manifest = {
  schema_version: 'reddit_voc_insights_site_release_v2',
  release_sha256: releaseSha,
  generated_at_utc: new Date().toISOString(),
  delivery_mode: 'immutable_static_container',
  public_access: true,
  authentication_enabled: false,
  ...collectionStatus,
  nginx_base_image: baseImage,
  target_platform: targetPlatform,
  build_contract_version: buildContractVersion,
  deployment_inputs: deploymentInputs,
  build_inputs: buildInputs,
  toolchain,
  dataset_versions: datasetVersions,
  dataset_manifests: datasetManifests,
  current_release: currentReleaseContract,
  data_runtime: dataRuntime,
  ...(frontendSource ? { frontend_source: frontendSource } : {}),
  file_count: files.length,
  files,
  boundaries: {
    provider_call: false,
    database_write: false,
    live_send: false,
    webhook_send: false,
    schedule_change: false,
    collector_restart: false,
    collector_isolation_required: true,
    case_gallery_stock_preserved: true,
    login_required: false,
  },
};

await mkdir(outputRoot, { recursive: true });
await writeFile(
  resolve(outputRoot, 'release-manifest.json'),
  `${JSON.stringify(manifest, null, 2)}\n`,
  { mode: 0o644 },
);
await writeFile(
  resolve(outputRoot, 'dist-SHA256SUMS'),
  `${files.map((file) => `${file.sha256}  dist/${file.path}`).join('\n')}\n`,
  { mode: 0o644 },
);
process.stdout.write(`${releaseSha}\n`);
