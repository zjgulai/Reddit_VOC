import { Boxes, Layers3, PackageSearch } from 'lucide-react';
import type { ProductAnalysis, ProductScope } from '../../features/redditSnapshot/types';

function percent(value: number | null): string {
  return value === null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function ScopeList({ title, rows, icon }: { title: string; rows: ProductScope[]; icon: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-card border border-border-divider p-4">
      <div className="mb-3 flex min-w-0 items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {icon}
          <h3 className="text-body-sm font-semibold text-foreground">{title}</h3>
        </div>
        <span className="shrink-0 text-tiny text-foreground-muted">{rows.length} 项</span>
      </div>
      {rows.length ? (
        <div className="space-y-2.5">
          {rows.slice(0, 8).map((row) => (
            <article key={row.scope_id} className="min-w-0 rounded-icon bg-surface-tertiary px-3 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-caption font-medium text-foreground">{row.scope_name_cn || row.scope_name_en}</p>
                  <p className="mt-0.5 truncate font-mono text-tiny text-foreground-muted">{row.scope_id}</p>
                </div>
                <span className="rounded-badge bg-white px-2 py-0.5 text-tiny text-foreground-muted">{row.binding_level}</span>
              </div>
              <div className="mt-2 grid gap-2 text-tiny sm:grid-cols-2">
                <div className="min-w-0 rounded-icon bg-white px-2.5 py-2 text-foreground-secondary">
                  帖子负面 <strong className="float-right text-foreground">{percent(row.metrics.post.value)}</strong>
                  <p className="mt-0.5 text-foreground-muted">{row.metrics.post.numerator ?? '—'}/{row.metrics.post.denominator ?? '—'}</p>
                </div>
                <div className="min-w-0 rounded-icon bg-white px-2.5 py-2 text-foreground-secondary">
                  评论负面 <strong className="float-right text-foreground">{percent(row.metrics.comment.value)}</strong>
                  <p className="mt-0.5 text-foreground-muted">{row.metrics.comment.numerator ?? '—'}/{row.metrics.comment.denominator ?? '—'}</p>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="rounded-icon bg-surface-tertiary p-3 text-caption text-foreground-muted">当前窗口没有该层级的受控绑定。</p>
      )}
    </section>
  );
}

export default function ProductAnalysisPanel({ analysis }: { analysis: ProductAnalysis }) {
  const bindingRate = typeof analysis.coverage.binding_rate === 'number'
    ? `${(analysis.coverage.binding_rate * 100).toFixed(1)}%`
    : '—';
  return (
    <section className="min-w-0 card p-5 sm:p-6" aria-labelledby="product-analysis-title">
      <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-icon bg-primary-light">
            <PackageSearch className="h-[18px] w-[18px] text-primary" strokeWidth={1.5} />
          </div>
          <div>
            <h2 id="product-analysis-title" className="text-h3 text-foreground">Momcozy 产品三层分析</h2>
            <p className="mt-0.5 text-caption text-foreground-muted">品类 → 产品族 → 受控 SPU；帖子与评论分别计算</p>
          </div>
        </div>
        <span className="rounded-badge bg-primary-light px-2.5 py-1 text-tiny font-medium text-primary">产品绑定率 {bindingRate}</span>
      </div>
      <div className="grid min-w-0 gap-4 xl:grid-cols-3">
        <ScopeList title="品类" rows={analysis.category} icon={<Layers3 className="h-4 w-4 text-primary" strokeWidth={1.5} />} />
        <ScopeList title="产品族" rows={analysis.product_family} icon={<Boxes className="h-4 w-4 text-primary" strokeWidth={1.5} />} />
        <ScopeList title="SPU" rows={analysis.spu_exact} icon={<PackageSearch className="h-4 w-4 text-primary" strokeWidth={1.5} />} />
      </div>
      <p className="mt-4 rounded-icon bg-surface-tertiary px-3 py-2 text-tiny leading-relaxed text-foreground-muted">
        多产品内容可进入多个范围，但在单一范围内按内容实体去重；SPU 只展示 exact_spu_approved。
      </p>
    </section>
  );
}
