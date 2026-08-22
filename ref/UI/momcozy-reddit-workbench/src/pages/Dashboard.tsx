import { useState } from 'react';
import Sidebar from '../components/Sidebar';
import StatCard from '../components/StatCard';
import PostCard from '../components/PostCard';
import SearchPanel from '../components/SearchPanel';
import InsightCard from '../components/InsightCard';
import {
  Monitor,
  FileText,
  UserCheck,
  TrendingUp,
  Search,
  Bell,
  User,
  Filter,
  LayoutGrid,
  List,
  AlertCircle,
  Lightbulb,
} from 'lucide-react';

const mockPosts = [
  {
    id: '1',
    subreddit: 'SaaS',
    title: 'Looking for an affordable alternative to HubSpot for my small business. Any recommendations?',
    intentScore: 92,
    status: 'new' as const,
    author: 'u/startup_guy_92',
    createdAt: '2 小时前',
  },
  {
    id: '2',
    subreddit: 'startups',
    title: 'How do you track customer feedback across Reddit, Twitter, and other social channels?',
    intentScore: 78,
    status: 'saved' as const,
    author: 'u/tech_entrepreneur',
    createdAt: '5 小时前',
  },
  {
    id: '3',
    subreddit: 'marketing',
    title: 'What tools are you using for Reddit monitoring and engagement? Need something reliable.',
    intentScore: 85,
    status: 'viewed' as const,
    author: 'u/growth_hacker_x',
    createdAt: '8 小时前',
  },
  {
    id: '4',
    subreddit: 'ecommerce',
    title: 'Struggling to find where my potential customers hang out online. Reddit seems promising.',
    intentScore: 88,
    status: 'new' as const,
    author: 'u/shop_owner_2024',
    createdAt: '12 小时前',
  },
  {
    id: '5',
    subreddit: 'ProductManagement',
    title: 'Best practices for gathering user feedback from Reddit communities?',
    intentScore: 72,
    status: 'replied' as const,
    author: 'u/pm_daily',
    createdAt: '1 天前',
  },
  {
    id: '6',
    subreddit: 'AskMarketing',
    title: 'Has anyone successfully used Reddit for B2B lead generation? Would love to hear your experience.',
    intentScore: 95,
    status: 'saved' as const,
    author: 'u/b2b_marketer',
    createdAt: '1 天前',
  },
];

const insights = [
  {
    icon: TrendingUp,
    title: '高意向话题趋势',
    description: '本周 "寻找替代品" 和 "工具推荐" 类 post 数量增长 34%，主要集中在 SaaS 和营销 subreddit。',
    highlight: '34% 增长',
  },
  {
    icon: AlertCircle,
    title: '品牌提及预警',
    description: 'r/SaaS 中有用户在对比竞品，建议主动介入提供价值，当前未回复的高意向 post 有 3 个。',
    highlight: '3 个待回复',
  },
  {
    icon: Lightbulb,
    title: '优化建议',
    description: '监测到 r/startups 中关于 "客户反馈工具" 的讨论频率较高，建议在该社区增加品牌曝光。',
    highlight: '新机会',
  },
];

export default function Dashboard() {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('list');
  const [searchQuery, setSearchQuery] = useState('');

  return (
    <div className="min-h-screen bg-[#FCF5F2] flex">
      <Sidebar />

      <div className="flex-1 min-w-0">
        {/* Top bar */}
        <header className="bg-white border-b border-[#E8D5D5] px-6 py-4">
          <div className="flex items-center justify-between gap-4">
            <div className="flex-1 max-w-md">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A89094]" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="搜索 post、关键词..."
                  className="input-field pl-10 text-sm"
                />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button className="relative w-10 h-10 rounded-xl flex items-center justify-center text-[#7C5C62] hover:bg-[#F5EBE6] transition-all">
                <Bell className="w-5 h-5" />
                <span className="absolute top-1 right-1 w-2 h-2 bg-[#C44A5E] rounded-full" />
              </button>
              <button className="w-10 h-10 rounded-xl bg-[#F5EBE6] flex items-center justify-center text-[#C44A5E] hover:bg-[#C44A5E] hover:text-white transition-all">
                <User className="w-5 h-5" />
              </button>
            </div>
          </div>
        </header>

        <div className="p-6 space-y-6">
          {/* Stats */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              icon={Monitor}
              label="监测 subreddit 数"
              value="12"
              change="+2"
              positive
            />
            <StatCard
              icon={FileText}
              label="本周发现帖子数"
              value="348"
              change="+18%"
              positive
            />
            <StatCard
              icon={UserCheck}
              label="高意向线索数"
              value="56"
              change="+8"
              positive
            />
            <StatCard
              icon={TrendingUp}
              label="转化率"
              value="23.5%"
              change="+2.3%"
              positive
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Main content */}
            <div className="lg:col-span-2 space-y-6">
              <SearchPanel />

              {/* Post list */}
              <div className="card">
                <div className="flex items-center justify-between mb-6">
                  <h3 className="text-lg font-semibold text-[#35141A]">
                    最新监测结果
                  </h3>
                  <div className="flex items-center gap-2">
                    <button className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-[#7C5C62] hover:bg-[#F5EBE6] transition-all">
                      <Filter className="w-4 h-4" />
                      筛选
                    </button>
                    <div className="flex bg-[#F5EBE6] rounded-lg p-1">
                      <button
                        onClick={() => setViewMode('list')}
                        className={`p-1.5 rounded-md transition-all ${
                          viewMode === 'list' ? 'bg-white text-[#C44A5E] shadow-sm' : 'text-[#7C5C62]'
                        }`}
                      >
                        <List className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => setViewMode('grid')}
                        className={`p-1.5 rounded-md transition-all ${
                          viewMode === 'grid' ? 'bg-white text-[#C44A5E] shadow-sm' : 'text-[#7C5C62]'
                        }`}
                      >
                        <LayoutGrid className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>

                <div className="space-y-3">
                  {mockPosts.map((post) => (
                    <PostCard key={post.id} post={post} />
                  ))}
                </div>
              </div>
            </div>

            {/* Sidebar */}
            <div className="space-y-6">
              <div className="card">
                <h3 className="text-lg font-semibold text-[#35141A] mb-4">
                  智能洞察
                </h3>
                <div className="space-y-4">
                  {insights.map((insight, index) => (
                    <InsightCard key={index} {...insight} />
                  ))}
                </div>
              </div>

              <div className="card">
                <h3 className="text-lg font-semibold text-[#35141A] mb-4">
                  快速操作
                </h3>
                <div className="space-y-2">
                  <button className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-[#35141A] hover:bg-[#F5EBE6] transition-all text-left">
                    <div className="w-8 h-8 rounded-lg bg-[#C44A5E]/10 flex items-center justify-center">
                      <Search className="w-4 h-4 text-[#C44A5E]" />
                    </div>
                    新建搜索任务
                  </button>
                  <button className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-[#35141A] hover:bg-[#F5EBE6] transition-all text-left">
                    <div className="w-8 h-8 rounded-lg bg-[#C44A5E]/10 flex items-center justify-center">
                      <TrendingUp className="w-4 h-4 text-[#C44A5E]" />
                    </div>
                    查看分析报告
                  </button>
                  <button className="w-full flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-[#35141A] hover:bg-[#F5EBE6] transition-all text-left">
                    <div className="w-8 h-8 rounded-lg bg-[#C44A5E]/10 flex items-center justify-center">
                      <Bell className="w-4 h-4 text-[#C44A5E]" />
                    </div>
                    设置通知规则
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
