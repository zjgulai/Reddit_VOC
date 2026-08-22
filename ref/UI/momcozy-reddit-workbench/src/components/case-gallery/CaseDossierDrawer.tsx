import { X } from 'lucide-react';
import type { PublicCaseDossier } from '../../features/redditSnapshot/casebook';

interface CaseDossierDrawerProps {
  dossier: PublicCaseDossier | null;
  onClose: () => void;
}

const stageStatusLabel = {
  evidence_backed: '证据支持',
  review_required: '待复核',
  suggestion_only: '仅建议',
} as const;

export default function CaseDossierDrawer({ dossier, onClose }: CaseDossierDrawerProps) {
  if (!dossier) return null;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/30" role="presentation" onMouseDown={onClose}>
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="case-dossier-title"
        className="h-full w-full max-w-3xl overflow-y-auto bg-white shadow-2xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-border-divider bg-white/95 px-6 py-5 backdrop-blur">
          <div>
            <p className="text-caption font-medium text-primary">只读治理事件 · {dossier.lifecycle_status}</p>
            <h2 id="case-dossier-title" className="mt-1 text-h2 font-semibold text-foreground">{dossier.title}</h2>
          </div>
          <button type="button" onClick={onClose} className="rounded-icon p-2 text-foreground-muted hover:bg-surface-tertiary" aria-label="关闭事件详情">
            <X className="h-5 w-5" strokeWidth={1.5} />
          </button>
        </div>

        <div className="space-y-6 p-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div className="rounded-card bg-surface-tertiary p-3"><p className="text-tiny text-foreground-muted">商业关系</p><p className="mt-1 font-semibold">C2</p></div>
            <div className="rounded-card bg-surface-tertiary p-3"><p className="text-tiny text-foreground-muted">完整性风险</p><p className="mt-1 font-semibold">I3</p></div>
            <div className="rounded-card bg-surface-tertiary p-3"><p className="text-tiny text-foreground-muted">品牌控制</p><p className="mt-1 font-semibold">未确认</p></div>
            <div className="rounded-card bg-surface-tertiary p-3"><p className="text-tiny text-foreground-muted">证据边界</p><p className="mt-1 font-semibold">风险观察</p></div>
          </div>

          <div className="rounded-card border border-status-warning/20 bg-status-warningBg p-4 text-caption leading-relaxed text-foreground-secondary">
            社区管理员公开指控属于风险信号；brand_control_confirmed=false。当前不确认品牌控制、机器人归属或责任主体。
          </div>

          <div>
            <p className="text-caption text-foreground-muted">业务问题</p>
            <p className="mt-1 text-body font-medium text-foreground">{dossier.business_question}</p>
          </div>

          <ol className="space-y-4" aria-label="治理闭环阶段">
            {dossier.stages.map((stage, index) => (
              <li key={stage.id} className="rounded-card border border-border-divider p-5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3">
                    <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary-light text-caption font-semibold text-primary">{index + 1}</span>
                    <h3 className="text-body font-semibold text-foreground">{stage.label}</h3>
                  </div>
                  <span className="rounded-badge bg-surface-tertiary px-2 py-1 text-tiny text-foreground-muted">{stageStatusLabel[stage.status]}</span>
                </div>
                <p className="mt-3 text-caption leading-relaxed text-foreground-secondary">{stage.summary}</p>
                <ul className="mt-3 space-y-2">
                  {stage.items.map((item) => <li key={item} className="text-caption text-foreground-secondary">• {item}</li>)}
                </ul>
              </li>
            ))}
          </ol>

          <div className="rounded-card bg-surface-tertiary p-4 text-caption text-foreground-secondary">
            证据范围：{dossier.evidence.canonical_post_ids.length} 条已归并帖子、{dossier.evidence.evidence_comment_ids.length} 条证据评论、{dossier.evidence.external_reference_ids.length} 条外部公开参考。此抽屉不提供外部跳转。
          </div>
        </div>
      </section>
    </div>
  );
}
