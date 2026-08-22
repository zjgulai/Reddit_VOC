# 本地、GitHub 与生产版本一致性

## 单一事实源

`main` 保存可审阅源码，`config/production-version-lock.json` 保存当前生产
release 身份，两个不可变 manifest 保存生产制品清单。生产环境不从未提交的
工作树发布；每次发布必须先让候选源码通过测试并进入 GitHub，再用精确 release
manifest 激活生产，最后更新 version lock 并提交。

这里的“一致”指可验证的版本闭包，不是把数据库、报表、浏览器记录、`.env`、
私钥、构建目录或生产数据快照提交到 Git。

## 当前证据边界

- 日报 runtime：本地源码可精确重建生产 release
  `7b177962a7fa36bcc6f873e115f363c53de4d5b7922b8316f21303bc7c5ec181`。
  校验器会重建全部 62 个受控文件并核对 release、manifest、launcher SHA。
- 公开洞察站：生产仍运行 2026-08-10 的 site release
  `da9b94b5e0a6e39941765779164303e54b92a338b1754d035dd3fea798052acc`
  和 data release `reddit_voc_release_20260810_observed_translation_v1`。
  Git 只保存其不可变 artifact manifest；当前较新的 UI 源码不能被表述为该旧
  production dist 的逐字节来源。下一次公开站发布后才能把这一项提升为
  `exact_rebuild`。

## 校验命令

本地源码与锁：

```bash
python3 scripts/verify_version_consistency.py
```

本地 `main`、GitHub `origin/main` 与生产只读元数据三方核验：

```bash
python3 scripts/verify_version_consistency.py \
  --check-github \
  --production-host ubuntu@101.34.52.232 \
  --identity-file DDDD.pem \
  --known-hosts /Users/pray/.ssh/known_hosts
```

生产观察器只读取 current symlink、release manifest、cron SHA 和
`reddit-voc-report.env` 的 `lstat` 元数据；不读取 credential 内容，不访问数据库，
不启动容器，也不写远端。

## 后续发布顺序

1. 从干净的 `main` 建候选，执行 backend 与 UI 全门禁。
2. 构建不可变 release；把 manifest 放入 `config/production/` 并更新 version lock。
3. 提交并推送，确认本地 `HEAD == origin/main`。
4. 以精确 manifest 和 GitHub commit 作为生产激活输入；生产失败则保持旧 current。
5. 激活后只读执行三方校验；若生产身份不同，立即失败，不补写锁掩盖漂移。
6. 生产回滚时同步回滚 version lock，并提交新的事实状态。

## 明确禁止

- 禁止提交 `.env`、`*.pem`、webhook、API key、生产数据库、报表私有导出和
  `public/data` 生成快照。
- 禁止用 `git add .` 绕过边界审计。
- 禁止把 manifest 通过当成真实发送、Provider 调用或页面验收证据。
- 禁止在公开站源码尚不能重建旧 production dist 时声称三端逐字节一致。
