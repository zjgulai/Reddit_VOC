import { useState, useCallback } from 'react';
import { Target, Plus, Trash2, X } from 'lucide-react';
import { CHART_PALETTE } from '../constants/colors';
import { useCompetitorStore } from '../stores';

const MAX_BRANDS = 9;

const PRESET_COLORS: string[] = [
  CHART_PALETTE[0], CHART_PALETTE[1], CHART_PALETTE[2], CHART_PALETTE[3], CHART_PALETTE[6],
  CHART_PALETTE[12], CHART_PALETTE[13], CHART_PALETTE[14], CHART_PALETTE[15],
];

interface TagListEditorProps {
  label: string;
  tags: string[];
  placeholder: string;
  onChange: (tags: string[]) => void;
}

function TagListEditor({ label, tags, placeholder, onChange }: TagListEditorProps) {
  const [input, setInput] = useState('');

  const addTag = () => {
    const trimmed = input.trim();
    if (!trimmed) return;
    if (tags.includes(trimmed)) {
      setInput('');
      return;
    }
    onChange([...tags, trimmed]);
    setInput('');
  };

  const removeTag = (tag: string) => {
    onChange(tags.filter((t) => t !== tag));
  };

  return (
    <div className="mt-2">
      <label className="text-tiny text-foreground-muted block mb-1">{label}</label>
      <div className="flex items-center gap-1.5 mb-1.5">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              addTag();
            }
          }}
          placeholder={placeholder}
          className="input-field text-body-sm py-1.5 px-2 flex-1 min-w-0"
        />
        <button
          type="button"
          onClick={addTag}
          disabled={!input.trim()}
          aria-label={`添加 ${label}`}
          className="btn-primary px-2.5 py-1.5 text-body-sm disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Plus className="w-3.5 h-3.5" strokeWidth={1.5} />
        </button>
      </div>
      <div className="flex flex-wrap gap-1">
        {tags.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-0.5 px-2 py-0.5 rounded-badge text-tiny bg-surface-tertiary text-foreground-secondary"
          >
            {tag}
            <button
              type="button"
              onClick={() => removeTag(tag)}
              className="ml-0.5 hover:text-status-error transition-colors"
              aria-label={`删除 ${tag}`}
            >
              <X className="w-3 h-3" strokeWidth={1.5} />
            </button>
          </span>
        ))}
        {tags.length === 0 && (
          <span className="text-tiny text-foreground-muted">暂无</span>
        )}
      </div>
    </div>
  );
}

export default function CompetitorBrandConfig() {
  const { brands, addBrand, removeBrand, updateBrand, toggleBrand } = useCompetitorStore();
  const [newName, setNewName] = useState('');
  const [newColor, setNewColor] = useState(PRESET_COLORS[0]);
  const [error, setError] = useState('');

  const addNewBrand = useCallback(() => {
    const trimmed = newName.trim();
    if (!trimmed) {
      setError('请输入品牌名称');
      return;
    }
    if (brands.length >= MAX_BRANDS) {
      setError(`最多支持 ${MAX_BRANDS} 个品牌`);
      return;
    }
    if (brands.some((b) => b.name.toLowerCase() === trimmed.toLowerCase())) {
      setError('该品牌已存在');
      return;
    }
    const brand = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      name: trimmed,
      color: newColor,
      subreddits: [] as string[],
      keywords: [] as string[],
      enabled: true,
    };
    addBrand(brand);
    setNewName('');
    setError('');
  }, [newName, newColor, brands, addBrand]);

  const updateSubreddits = useCallback((id: string, subreddits: string[]) => {
    updateBrand(id, { subreddits });
  }, [updateBrand]);

  const updateKeywords = useCallback((id: string, keywords: string[]) => {
    updateBrand(id, { keywords });
  }, [updateBrand]);

  const updateName = useCallback((id: string, name: string) => {
    updateBrand(id, { name: name.trimStart() });
  }, [updateBrand]);

  const updateColor = useCallback((id: string, color: string) => {
    updateBrand(id, { color });
  }, [updateBrand]);

  return (
    <div className="card p-6">
      <div className="flex items-center gap-2 mb-5">
        <Target className="w-5 h-5 text-primary" strokeWidth={1.5} />
        <h2 className="text-h2 text-foreground">竞品品牌配置</h2>
      </div>

      <div className="space-y-4">
        {/* Add new row */}
        <div className="flex flex-col sm:flex-row items-start sm:items-end gap-3">
          <div className="flex-1 w-full">
            <label className="text-caption text-foreground-muted mb-1.5 block">品牌名称</label>
            <input
              type="text"
              value={newName}
              onChange={(e) => {
                setNewName(e.target.value);
                if (error) setError('');
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter') addNewBrand();
              }}
              placeholder="输入竞品品牌名称，如 Elvie"
              className="input-field"
              maxLength={30}
            />
          </div>
          <div className="w-full sm:w-auto">
            <label className="text-caption text-foreground-muted mb-1.5 block">标识颜色</label>
            <div className="flex items-center gap-2">
              <div className="flex flex-wrap gap-1.5">
                {PRESET_COLORS.map((c, index) => (
                  <button
                    key={`${c}-${index}`}
                    type="button"
                    onClick={() => setNewColor(c)}
                    className={`w-7 h-7 rounded-full border-2 transition-transform ${
                      newColor === c ? 'border-foreground scale-110' : 'border-transparent'
                    }`}
                    style={{ backgroundColor: c }}
                    aria-label={`选择颜色 ${c}`}
                  />
                ))}
                <div className="relative w-7 h-7 rounded-full overflow-hidden border-2 border-transparent">
                  <div className="absolute inset-0" style={{ backgroundColor: newColor }} />
                  <input
                    type="color"
                    value={newColor}
                    onChange={(e) => setNewColor(e.target.value)}
                    className="absolute inset-0 opacity-0 cursor-pointer"
                    aria-label="自定义颜色"
                  />
                </div>
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={addNewBrand}
            disabled={brands.length >= MAX_BRANDS}
            className="btn-primary px-4 py-2.5 text-body-sm w-full sm:w-auto inline-flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Plus className="w-4 h-4" strokeWidth={1.5} />
            添加
          </button>
        </div>

        {error && (
          <div className="text-caption text-status-error bg-status-errorBg rounded-input px-3 py-2">
            {error}
          </div>
        )}

        <div className="text-tiny text-foreground-muted">
          已配置 {brands.length} / {MAX_BRANDS} 个品牌
        </div>

        {/* Brand list */}
        {brands.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 rounded-icon bg-surface-tertiary">
            <Target className="w-8 h-8 text-foreground-muted mb-2" strokeWidth={1.5} />
            <p className="text-body-sm text-foreground-secondary">尚未配置竞品品牌</p>
            <p className="text-caption text-foreground-muted">添加品牌以在竞品对比中使用</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {brands.map((brand) => (
              <div
                key={brand.id}
                className="flex flex-col p-3 rounded-icon bg-surface-tertiary transition-all"
              >
                <div className="flex items-center gap-3">
                  <div
                    className="w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-white text-xs font-semibold"
                    style={{ backgroundColor: brand.color }}
                  >
                    {brand.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <input
                      type="text"
                      value={brand.name}
                      onChange={(e) => updateName(brand.id, e.target.value)}
                      className="w-full bg-transparent border-0 p-0 text-body-sm font-medium text-foreground focus:outline-none focus:ring-0"
                      maxLength={30}
                    />
                    <div className="flex items-center gap-1.5 mt-1">
                      <div className="relative w-4 h-4 rounded-full overflow-hidden flex-shrink-0">
                        <div className="absolute inset-0" style={{ backgroundColor: brand.color }} />
                        <input
                          type="color"
                          value={brand.color}
                          onChange={(e) => updateColor(brand.id, e.target.value)}
                          className="absolute inset-0 opacity-0 cursor-pointer"
                          aria-label="修改颜色"
                        />
                      </div>
                      <span className="text-tiny text-foreground-muted font-mono">{brand.color}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => toggleBrand(brand.id)}
                      className={`relative w-9 h-5 rounded-full transition-all duration-200 ${
                        brand.enabled ? 'bg-primary' : 'bg-foreground-muted/30'
                      }`}
                      aria-label={brand.enabled ? '禁用' : '启用'}
                      title={brand.enabled ? '禁用' : '启用'}
                    >
                      <span
                        className={`absolute top-1 w-3 h-3 bg-white rounded-full shadow-sm transition-all duration-200 ${
                          brand.enabled ? 'left-5' : 'left-1'
                        }`}
                      />
                    </button>
                    <button
                      type="button"
                      onClick={() => removeBrand(brand.id)}
                      className="w-7 h-7 rounded-icon flex items-center justify-center text-foreground-muted hover:text-status-error hover:bg-status-errorBg transition-colors"
                      aria-label="删除"
                      title="删除"
                    >
                      <Trash2 className="w-4 h-4" strokeWidth={1.5} />
                    </button>
                  </div>
                </div>
                <TagListEditor
                  label="Subreddits"
                  tags={brand.subreddits}
                  placeholder="输入 subreddit 名称..."
                  onChange={(tags) => updateSubreddits(brand.id, tags)}
                />
                <TagListEditor
                  label="Keywords"
                  tags={brand.keywords}
                  placeholder="输入关键词..."
                  onChange={(tags) => updateKeywords(brand.id, tags)}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
