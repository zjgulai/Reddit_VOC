import { useState } from 'react';
import { Search, Plus, SlidersHorizontal } from 'lucide-react';

export default function SearchPanel() {
  const [subreddit, setSubreddit] = useState('');
  const [keyword, setKeyword] = useState('');

  const handleAnalyze = () => {
    // Mock analysis action
    console.log('Analyzing:', { subreddit, keyword });
  };

  return (
    <div className="card">
      <div className="flex items-center gap-2 mb-5">
        <div className="w-8 h-8 rounded-lg bg-[#C44A5E]/10 flex items-center justify-center">
          <Search className="w-4 h-4 text-[#C44A5E]" />
        </div>
        <h3 className="text-lg font-semibold text-[#35141A]">搜索配置</h3>
      </div>

      <div className="grid sm:grid-cols-2 gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-[#7C5C62] mb-2">
            Subreddit
          </label>
          <div className="relative">
            <span className="absolute left-4 top-1/2 -translate-y-1/2 text-[#A89094] text-sm font-medium">r/</span>
            <input
              type="text"
              value={subreddit}
              onChange={(e) => setSubreddit(e.target.value)}
              placeholder="SaaS"
              className="input-field pl-8"
            />
          </div>
          <p className="text-xs text-[#A89094] mt-1.5">输入你想监测的 subreddit 名称</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-[#7C5C62] mb-2">
            关键词
          </label>
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            placeholder="breast pump, wearable, Momcozy..."
            className="input-field"
          />
          <p className="text-xs text-[#A89094] mt-1.5">用逗号分隔多个关键词</p>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          onClick={handleAnalyze}
          className="btn-primary px-6 py-2.5"
        >
          <Search className="w-4 h-4 mr-2" />
          分析
        </button>
        <button className="btn-secondary px-4 py-2.5">
          <Plus className="w-4 h-4 mr-2" />
          添加监测
        </button>
        <button className="ml-auto p-2.5 rounded-xl border border-[#E8D5D5] text-[#7C5C62] hover:bg-[#F5EBE6] transition-colors">
          <SlidersHorizontal className="w-4 h-4" />
        </button>
      </div>

      {/* Active monitors */}
      <div className="mt-5 pt-5 border-t border-[#E8D5D5]">
        <p className="text-sm font-medium text-[#35141A] mb-3">当前监测</p>
        <div className="flex flex-wrap gap-2">
          {['r/SaaS', 'r/mommit', 'r/breastfeeding', 'r/Momcozy'].map((item) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg bg-[#F5EBE6] text-sm text-[#35141A]"
            >
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              {item}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
