// UGC 素材库 Mock 数据
// 用于 /dashboard/ugc-showcase 页面的正面内容自动归档展示

import type { UGCItem, UGCStats } from '../types';

export const ugcItems: UGCItem[] = [
  {
    id: 'ugc-001',
    title: 'Momcozy M5 使用三个月真实体验——比 Elvie 更适合背奶妈妈',
    content: '我已经使用 Momcozy M5 三个月了，每天背奶两次，必须说这个泵真的改变了我的职场生活。静音效果比之前的 Elvie 好太多，办公室隔间里几乎听不到声音。续航也很给力，一次充电可以用三天。最重要的是清洗方便，配件少，省了很多时间。',
    author: 'WorkingMom_Amy',
    subreddit: 'breastfeeding',
    upvotes: 342,
    comments: 56,
    sentiment: 'positive',
    intentScore: 92,
    createdAt: '2024-07-08T14:32:00Z',
    url: 'https://reddit.com/r/breastfeeding/comments/ugc001',
    category: 'experience',
    tags: ['M5', '背奶', '职场妈妈', '对比', 'Elvie'],
    isArchived: true,
    archivedAt: '2024-07-09T10:00:00Z',
    mediaType: 'text',
    engagementRate: 87,
    quotedBy: ['momcozy.com/blog', 'instagram.com/momcozy'],
    autoArchiveReason: '高情感分+产品对比+详细体验描述',
  },
  {
    id: 'ugc-002',
    title: 'Spectra vs Momcozy S12——新手妈妈的选购指南',
    content: '作为新手妈妈，我在 Spectra 和 Momcozy S12 之间纠结了很久。最后选择了 S12，原因有三：1) 价格只有 Spectra 的 1/3；2) 可穿戴设计，晚上不用起身；3) 社区口碑越来越好。使用两周后， suction 足够，没有漏奶问题。推荐给预算有限的妈妈。',
    author: 'FTM_Sarah2024',
    subreddit: 'NewParents',
    upvotes: 278,
    comments: 43,
    sentiment: 'positive',
    intentScore: 88,
    createdAt: '2024-07-06T09:15:00Z',
    url: 'https://reddit.com/r/NewParents/comments/ugc002',
    category: 'comparison',
    tags: ['S12', 'Spectra', '选购', '新手妈妈', '性价比'],
    isArchived: true,
    archivedAt: '2024-07-07T08:00:00Z',
    mediaType: 'text',
    engagementRate: 76,
    autoArchiveReason: '正面情感+竞品对比+购买意图明确',
  },
  {
    id: 'ugc-003',
    title: '我的 Momcozy 泵奶装备——办公室背奶 setup 分享',
    content: '分享一下我的办公室背奶 setup：Momcozy V2 + 便携 cooler bag + 消毒湿巾。这个组合让我每天背奶零压力。图片里是我的 setup，隔间里完全看不出来在泵奶。V2 的 app 可以记录每次的产量，方便追踪。',
    author: 'WorkingMom_Amy',
    subreddit: 'workingmoms',
    upvotes: 189,
    comments: 31,
    sentiment: 'positive',
    intentScore: 85,
    createdAt: '2024-07-05T11:20:00Z',
    url: 'https://reddit.com/r/workingmoms/comments/ugc003',
    category: 'lifestyle',
    tags: ['V2', '办公室', '背奶', 'setup', 'app'],
    isArchived: true,
    archivedAt: '2024-07-06T09:00:00Z',
    mediaType: 'image',
    engagementRate: 68,
    autoArchiveReason: '高互动+场景展示+生活方式',
  },
  {
    id: 'ugc-004',
    title: 'Momcozy 的 customer service 让我感动了',
    content: '我的 M5 用了一个月后 flange 有点松，联系了客服。没想到他们直接寄了一个新的，还附送了一套清洗刷。这种售后态度真的让我觉得很值得推荐给其他妈妈。品牌不只是卖产品，还在建立信任。',
    author: 'BreastfeedingAdvocate',
    subreddit: 'breastfeeding',
    upvotes: 456,
    comments: 72,
    sentiment: 'positive',
    intentScore: 95,
    createdAt: '2024-07-09T16:45:00Z',
    url: 'https://reddit.com/r/breastfeeding/comments/ugc004',
    category: 'experience',
    tags: ['M5', '售后', '客服', '感动', '推荐'],
    isArchived: true,
    archivedAt: '2024-07-10T08:00:00Z',
    mediaType: 'text',
    engagementRate: 92,
    quotedBy: ['momcozy.com/testimonials'],
    autoArchiveReason: '情感高峰+售后体验+品牌忠诚',
  },
  {
    id: 'ugc-005',
    title: '二胎妈妈对比三款 wearable pump：Momcozy / Willow / Elvie',
    content: '二胎后重新研究 wearable pump，用了 Momcozy M5、Willow 3.0 和 Elvie Stride。结论：Momcozy 性价比最高，Willow 最隐形但太贵，Elvie app 最好用。详细对比在评论里。',
    author: 'LactationConsultant_Mary',
    subreddit: 'breastpumps',
    upvotes: 512,
    comments: 89,
    sentiment: 'positive',
    intentScore: 90,
    createdAt: '2024-07-07T08:10:00Z',
    url: 'https://reddit.com/r/breastpumps/comments/ugc005',
    category: 'comparison',
    tags: ['M5', 'Willow', 'Elvie', 'wearable', '二胎', '对比'],
    isArchived: true,
    archivedAt: '2024-07-08T10:00:00Z',
    mediaType: 'text',
    engagementRate: 94,
    quotedBy: ['momcozy.com/comparison-guide'],
    autoArchiveReason: '专家背书+多竞品对比+高互动',
  },
  {
    id: 'ugc-006',
    title: '如何在 insurance 里 cover Momcozy pump——我的成功经验',
    content: '很多妈妈不知道，Momcozy 的泵可以通过保险报销。我通过 Aeroflow 成功报销了 M5，只需要医生的处方。流程分享：1) 找 OB 开处方；2) 在 Aeroflow 选择 Momcozy；3) 等保险审批；4) 免费寄到家。省下了 $200+。',
    author: 'NewMom_Jessica',
    subreddit: 'babybumps',
    upvotes: 623,
    comments: 105,
    sentiment: 'positive',
    intentScore: 89,
    createdAt: '2024-07-04T13:00:00Z',
    url: 'https://reddit.com/r/babybumps/comments/ugc006',
    category: 'tip',
    tags: ['M5', '保险', '报销', 'Aeroflow', '省钱', '攻略'],
    isArchived: true,
    archivedAt: '2024-07-05T08:00:00Z',
    mediaType: 'text',
    engagementRate: 88,
    autoArchiveReason: '实用攻略+省钱+高收藏率',
  },
  {
    id: 'ugc-007',
    title: 'Momcozy S12 的 night mode 真的是救星',
    content: '作为一个夜奶频繁的妈妈，S12 的夜 mode 太实用了。LED 灯很柔和，不会吵醒宝宝，声音也很轻。我可以躺在床上泵奶，然后直接继续睡。比坐起来用传统泵舒服太多。',
    author: 'FTM_Sarah2024',
    subreddit: 'NewParents',
    upvotes: 198,
    comments: 28,
    sentiment: 'positive',
    intentScore: 86,
    createdAt: '2024-07-10T02:30:00Z',
    url: 'https://reddit.com/r/NewParents/comments/ugc007',
    category: 'experience',
    tags: ['S12', '夜奶', 'LED', '静音', '新手妈妈'],
    isArchived: true,
    archivedAt: '2024-07-10T12:00:00Z',
    mediaType: 'text',
    engagementRate: 71,
    autoArchiveReason: '场景痛点+情感共鸣+使用细节',
  },
  {
    id: 'ugc-008',
    title: '视频：Momcozy M5 开箱 + 首次使用教程',
    content: '录了一个 M5 的开箱和首次使用视频，包括如何组装、清洗、以及不同模式的介绍。希望对新买的妈妈有帮助。视频链接在评论里。',
    author: 'PumpReview_Guru',
    subreddit: 'breastpumps',
    upvotes: 267,
    comments: 34,
    sentiment: 'positive',
    intentScore: 84,
    createdAt: '2024-07-03T18:00:00Z',
    url: 'https://reddit.com/r/breastpumps/comments/ugc008',
    category: 'product',
    tags: ['M5', '开箱', '视频', '教程', '评测'],
    isArchived: true,
    archivedAt: '2024-07-04T08:00:00Z',
    mediaType: 'video',
    engagementRate: 74,
    autoArchiveReason: '多媒体内容+教程+评测',
  },
  {
    id: 'ugc-009',
    title: '旅行必备：Momcozy pump 的便携性测试',
    content: '上周末出差带了 M5，测试了一下便携性。总结：重量比一瓶水还轻，充电器通用，清洗后晾干快。在酒店房间里泵了三次，完全没压力。对于经常出差的妈妈来说，这是必备品。',
    author: 'WorkingMom_Amy',
    subreddit: 'breastfeeding',
    upvotes: 312,
    comments: 47,
    sentiment: 'positive',
    intentScore: 87,
    createdAt: '2024-07-02T10:00:00Z',
    url: 'https://reddit.com/r/breastfeeding/comments/ugc009',
    category: 'lifestyle',
    tags: ['M5', '旅行', '便携', '出差', '酒店'],
    isArchived: true,
    archivedAt: '2024-07-03T08:00:00Z',
    mediaType: 'image',
    engagementRate: 81,
    autoArchiveReason: '场景扩展+旅行+生活方式',
  },
  {
    id: 'ugc-010',
    title: '从 Medela 转到 Momcozy 的一周感受——为什么后悔没早转',
    content: '用了 Medela 两年，最近因为配件太贵转到 Momcozy S12。一周感受：suction 差不多，但方便太多了。不需要插电，可以边做饭边泵。后悔没早转，省了两年的束缚。',
    author: 'BreastfeedingAdvocate',
    subreddit: 'breastfeeding',
    upvotes: 445,
    comments: 68,
    sentiment: 'positive',
    intentScore: 91,
    createdAt: '2024-07-01T15:00:00Z',
    url: 'https://reddit.com/r/breastfeeding/comments/ugc010',
    category: 'comparison',
    tags: ['S12', 'Medela', '转换', '便携', '后悔'],
    isArchived: true,
    archivedAt: '2024-07-02T08:00:00Z',
    mediaType: 'text',
    engagementRate: 89,
    quotedBy: ['momcozy.com/switch-stories'],
    autoArchiveReason: '竞品转换+后悔叙事+高情感分',
  },
  {
    id: 'ugc-011',
    title: 'Momcozy 的新配件——flange 尺寸终于有 19mm 了',
    content: '好消息！Momcozy 终于推出了 19mm 的 flange。之前因为尺寸不合适一直在凑合，现在终于有合适的选择。质量也很好，和原装的一样。',
    author: 'NewMom_Jessica',
    subreddit: 'breastpumps',
    upvotes: 156,
    comments: 22,
    sentiment: 'positive',
    intentScore: 82,
    createdAt: '2024-06-28T11:00:00Z',
    url: 'https://reddit.com/r/breastpumps/comments/ugc011',
    category: 'product',
    tags: ['配件', 'flange', '19mm', '新品', '尺寸'],
    isArchived: true,
    archivedAt: '2024-06-29T08:00:00Z',
    mediaType: 'text',
    engagementRate: 65,
    autoArchiveReason: '产品更新+配件+用户痛点解决',
  },
  {
    id: 'ugc-012',
    title: '妈妈群里被问最多的问题：Momcozy 哪个型号适合我？',
    content: '整理了一个简单的型号选择指南：M5 适合背奶/职场妈妈，S12 适合家用/预算有限，V2 适合 tech-savvy 妈妈。每个型号的具体优缺点在评论里。',
    author: 'LactationConsultant_Mary',
    subreddit: 'babybumps',
    upvotes: 389,
    comments: 52,
    sentiment: 'positive',
    intentScore: 88,
    createdAt: '2024-06-25T14:00:00Z',
    url: 'https://reddit.com/r/babybumps/comments/ugc012',
    category: 'tip',
    tags: ['选购', 'M5', 'S12', 'V2', '型号对比', '指南'],
    isArchived: true,
    archivedAt: '2024-06-26T08:00:00Z',
    mediaType: 'text',
    engagementRate: 83,
    autoArchiveReason: '选购指南+专家背书+多产品',
  },
];

export function getUGCStats(): UGCStats {
  const total = ugcItems.length;
  const positive = ugcItems.filter((i) => i.sentiment === 'positive').length;
  const avgEngagement = Math.round(ugcItems.reduce((sum, i) => sum + i.engagementRate, 0) / total);
  const categoryCounts: Record<string, number> = {};
  ugcItems.forEach((i) => {
    categoryCounts[i.category] = (categoryCounts[i.category] || 0) + 1;
  });
  const topCategory = (Object.entries(categoryCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || 'experience') as UGCStats['topCategory'];

  return {
    totalArchived: total,
    thisWeek: ugcItems.filter((i) => {
      const d = new Date(i.createdAt);
      const now = new Date();
      const diff = (now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24);
      return diff <= 7;
    }).length,
    positiveRate: Math.round((positive / total) * 100),
    avgEngagement,
    topCategory,
  };
}

export function getUGCItemsByTimeRange(timeRange: '7d' | '30d' | '90d'): UGCItem[] {
  const days = timeRange === '7d' ? 7 : timeRange === '30d' ? 30 : 90;
  const now = new Date();
  return ugcItems.filter((i) => {
    const d = new Date(i.createdAt);
    const diff = (now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24);
    return diff <= days;
  });
}

export function filterUGCItems(
  items: UGCItem[],
  filters: {
    category?: string;
    mediaType?: string;
    sentiment?: string;
    searchQuery?: string;
    minEngagement?: number;
  }
): UGCItem[] {
  return items.filter((i) => {
    if (filters.category && filters.category !== 'all' && i.category !== filters.category) return false;
    if (filters.mediaType && filters.mediaType !== 'all' && i.mediaType !== filters.mediaType) return false;
    if (filters.sentiment && filters.sentiment !== 'all' && i.sentiment !== filters.sentiment) return false;
    if (filters.minEngagement && i.engagementRate < filters.minEngagement) return false;
    if (filters.searchQuery) {
      const q = filters.searchQuery.toLowerCase();
      const match =
        i.title.toLowerCase().includes(q) ||
        i.content.toLowerCase().includes(q) ||
        i.tags.some((t) => t.toLowerCase().includes(q)) ||
        i.author.toLowerCase().includes(q) ||
        i.subreddit.toLowerCase().includes(q);
      if (!match) return false;
    }
    return true;
  });
}
