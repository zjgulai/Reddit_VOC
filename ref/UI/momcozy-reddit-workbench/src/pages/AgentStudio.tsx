import { useEffect, useState } from 'react';
import { Film, Wrench, RefreshCw } from 'lucide-react';
import { SnapshotPageLayout } from '../features/redditSnapshot/SnapshotPageLayout';

interface ContentIdea {
  topic_id: string;
  target_platform: string;
  target_audience: string;
  core_pain_point: string;
  hook_3s: string;
  story_conflict: string;
  solution_angle: string;
  call_to_action: string;
  visual_scene_script: Array<{ scene_num?: string; visual?: string; audio?: string; text_overlay?: string }>;
  hashtags: string[];
}

interface ContentIdeasDoc {
  run_id: string;
  total_topics: number;
  results: Array<{ source_post_id: string; source_title: string; ideas: ContentIdea[]; reasoning_summary: string }>;
}

interface RndTicket {
  defect_id: string;
  category: string;
  component: string;
  severity: string;
  symptom: string;
  root_cause_hypothesis: string;
  suggested_action: string;
  user_quote: string;
}

interface RndDoc {
  run_id: string;
  total_defects: number;
  results: Array<{ source_post_id: string; source_title: string; defects: RndTicket[] }>;
}

const AGENT_BASE = '/data/reddit-voc/agent-studio';

export default function AgentStudio() {
  const [ideas, setIdeas] = useState<ContentIdeasDoc | null>(null);
  const [rnd, setRnd] = useState<RndDoc | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'ideas' | 'rnd'>('ideas');

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch(`${AGENT_BASE}/latest-content-ideas.json`, { cache: 'no-cache' }).then(r => (r.ok ? r.json() : Promise.reject(new Error(`ideas ${r.status}`)))),
      fetch(`${AGENT_BASE}/latest-rnd-tickets.json`, { cache: 'no-cache' }).then(r => (r.ok ? r.json() : Promise.reject(new Error(`rnd ${r.status}`)))),
    ])
      .then(([ideasDoc, rndDoc]) => {
        if (!active) return;
        setIdeas(ideasDoc);
        setRnd(rndDoc);
        setIsLoading(false);
      })
      .catch((err: Error) => {
        if (!active) return;
        setError(err.message);
        setIsLoading(false);
      });
    return () => { active = false; };
  }, []);

  if (isLoading) {
    return (
      <SnapshotPageLayout title="Agent 创意工作室" description="每日自动产出的爆款选题与研发改款池" icon={Film}>
        <div className="flex flex-col items-center justify-center py-20 text-foreground-muted">
          <RefreshCw className="h-8 w-8 animate-spin mb-4 opacity-50" />
          <p>正在加载每日 Agent 产出...</p>
        </div>
      </SnapshotPageLayout>
    );
  }

  if (error || !ideas || !rnd) {
    return (
      <SnapshotPageLayout title="Agent 创意工作室" description="每日自动产出的爆款选题与研发改款池" icon={Film}>
        <div className="rounded-xl border border-status-warning/30 bg-status-warningBg p-6 text-status-warning">
          <p className="font-medium mb-1">Agent 产出尚未生成</p>
          <p className="text-sm opacity-80">
            每日 07:05 流水线运行后会自动发布选题与改款建议；当前错误：{error ?? '未知'}
          </p>
        </div>
      </SnapshotPageLayout>
    );
  }

  const allIdeas = ideas.results.flatMap(r => r.ideas.map(idea => ({ ...idea, source_title: r.source_title })));
  const allDefects = rnd.results.flatMap(r => r.defects.map(d => ({ ...d, source_title: r.source_title })));

  return (
    <SnapshotPageLayout title="Agent 创意工作室" description="每日自动产出的爆款选题与研发改款池" icon={Film}>
      <div className="space-y-5">
        <div className="rounded-card border border-border-divider bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-h3 text-foreground">每日 Agent 自动产出</h2>
              <p className="mt-1 text-caption text-foreground-muted">
                由每日 07:05 自动流水线生成 · Run: <span className="font-mono">{ideas.run_id}</span> · 选题 {ideas.total_topics} · 改款 {rnd.total_defects}
              </p>
            </div>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="btn-secondary inline-flex items-center gap-2"
            >
              <RefreshCw className="h-4 w-4" /> 刷新
            </button>
          </div>
          <div className="mt-4 flex gap-2">
            <button
              type="button"
              onClick={() => setTab('ideas')}
              className={`inline-flex items-center gap-2 rounded-badge px-4 py-2 text-body-sm font-medium transition-colors ${tab === 'ideas' ? 'bg-primary text-white' : 'bg-surface-tertiary text-foreground-secondary hover:bg-primary-light hover:text-primary'}`}
            >
              <Film className="h-4 w-4" /> 爆款选题库 ({allIdeas.length})
            </button>
            <button
              type="button"
              onClick={() => setTab('rnd')}
              className={`inline-flex items-center gap-2 rounded-badge px-4 py-2 text-body-sm font-medium transition-colors ${tab === 'rnd' ? 'bg-primary text-white' : 'bg-surface-tertiary text-foreground-secondary hover:bg-primary-light hover:text-primary'}`}
            >
              <Wrench className="h-4 w-4" /> 研发改款池 ({allDefects.length})
            </button>
          </div>
        </div>

        {tab === 'ideas' && (
          <div className="grid gap-4 xl:grid-cols-2">
            {allIdeas.map(idea => (
              <article key={idea.topic_id} className="card p-5 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-badge bg-primary-light px-2.5 py-1 text-tiny font-medium text-primary">
                    <Film className="mr-1 inline h-3 w-3" />{idea.target_platform}
                  </span>
                  <span className="rounded-badge bg-surface-tertiary px-2.5 py-1 text-tiny text-foreground-secondary">
                    {idea.target_audience}
                  </span>
                </div>
                <h3 className="text-body font-semibold text-foreground">{idea.core_pain_point}</h3>
                <div className="rounded-card bg-indigo-50/60 border border-indigo-100 p-3">
                  <p className="text-tiny font-medium text-indigo-700 mb-1">🎬 黄金前 3 秒 Hook</p>
                  <p className="text-body-sm text-indigo-950 italic">"{idea.hook_3s}"</p>
                </div>
                <dl className="space-y-1.5 text-caption text-foreground-secondary">
                  <div><dt className="inline text-foreground-muted">冲突： </dt><dd className="inline">{idea.story_conflict}</dd></div>
                  <div><dt className="inline text-foreground-muted">解法： </dt><dd className="inline">{idea.solution_angle}</dd></div>
                  <div><dt className="inline text-foreground-muted">CTA： </dt><dd className="inline">{idea.call_to_action}</dd></div>
                </dl>
                {idea.visual_scene_script.length > 0 && (
                  <details className="rounded-card border border-border-divider p-3">
                    <summary className="cursor-pointer text-tiny font-medium text-foreground-secondary">分镜脚本（{idea.visual_scene_script.length} 镜）</summary>
                    <ol className="mt-2 space-y-2 text-caption">
                      {idea.visual_scene_script.map((scene, i) => (
                        <li key={i} className="rounded-icon bg-surface-tertiary p-2.5">
                          <p className="font-medium text-foreground">镜头 {scene.scene_num ?? i + 1}</p>
                          <p className="mt-1 text-foreground-secondary">画面：{scene.visual}</p>
                          <p className="text-foreground-muted">音频：{scene.audio}</p>
                          <p className="text-primary">花字：{scene.text_overlay}</p>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}
                <div className="flex flex-wrap gap-1.5">
                  {idea.hashtags.map(tag => (
                    <span key={tag} className="rounded-badge bg-surface-tertiary px-2 py-0.5 text-tiny text-foreground-muted">{tag}</span>
                  ))}
                </div>
              </article>
            ))}
          </div>
        )}

        {tab === 'rnd' && (
          <div className="space-y-4">
            {allDefects.map(d => (
              <article key={d.defect_id} className="card p-5 space-y-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`rounded-badge px-2.5 py-1 text-tiny font-medium ${d.severity === 'critical' ? 'bg-status-errorBg text-status-error' : d.severity === 'major' ? 'bg-status-warningBg text-status-warning' : 'bg-surface-tertiary text-foreground-secondary'}`}>
                    <Wrench className="mr-1 inline h-3 w-3" />{d.severity.toUpperCase()}
                  </span>
                  <span className="rounded-badge bg-surface-tertiary px-2.5 py-1 text-tiny text-foreground-secondary">{d.category}</span>
                  <span className="rounded-badge bg-primary-light px-2.5 py-1 text-tiny text-primary">{d.component}</span>
                </div>
                <h3 className="text-body font-semibold text-foreground">{d.symptom}</h3>
                <div className="grid gap-3 md:grid-cols-2">
                  <div className="rounded-card bg-surface-tertiary p-3">
                    <p className="text-tiny font-medium text-foreground-muted mb-1">根因假设</p>
                    <p className="text-caption text-foreground-secondary">{d.root_cause_hypothesis}</p>
                  </div>
                  <div className="rounded-card bg-emerald-50/60 border border-emerald-100 p-3">
                    <p className="text-tiny font-medium text-emerald-700 mb-1">建议工程整改 (CAPA)</p>
                    <p className="text-caption text-emerald-950">{d.suggested_action}</p>
                  </div>
                </div>
                {d.user_quote && (
                  <blockquote className="border-l-2 border-border-divider pl-3 text-caption italic text-foreground-muted">
                    用户原声："{d.user_quote}"
                  </blockquote>
                )}
              </article>
            ))}
          </div>
        )}
      </div>
    </SnapshotPageLayout>
  );
}
