import {
  operationInsights,
  teamWorkloads,
  bestPractices,
  sentimentTrendHistory,
  warningHistory,
  negativeSpreads,
  crisisReviews,
  brandVoiceInsights,
  brandPositioning,
  mindShareTrends,
  productOpportunities,
  userPainPoints,
  productFeedbacks,
  marketGaps,
  sentimentSankeyNodes,
  sentimentSankeyLinks,
  sentimentWordCloudData,
  categoryFunnelData,
} from '../data/insightsMock';
import api from '../lib/api';

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true';

export interface InsightsData {
  operationInsights: typeof operationInsights;
  teamWorkloads: typeof teamWorkloads;
  bestPractices: typeof bestPractices;
  sentimentTrendHistory: typeof sentimentTrendHistory;
  warningHistory: typeof warningHistory;
  negativeSpreads: typeof negativeSpreads;
  crisisReviews: typeof crisisReviews;
  brandVoiceInsights: typeof brandVoiceInsights;
  brandPositioning: typeof brandPositioning;
  mindShareTrends: typeof mindShareTrends;
  productOpportunities: typeof productOpportunities;
  userPainPoints: typeof userPainPoints;
  productFeedbacks: typeof productFeedbacks;
  marketGaps: typeof marketGaps;
  sentimentSankeyNodes: typeof sentimentSankeyNodes;
  sentimentSankeyLinks: typeof sentimentSankeyLinks;
  sentimentWordCloudData: typeof sentimentWordCloudData;
  categoryFunnelData: typeof categoryFunnelData;
}

export async function getInsights(): Promise<InsightsData> {
  if (USE_MOCK) {
    return {
      operationInsights,
      teamWorkloads,
      bestPractices,
      sentimentTrendHistory,
      warningHistory,
      negativeSpreads,
      crisisReviews,
      brandVoiceInsights,
      brandPositioning,
      mindShareTrends,
      productOpportunities,
      userPainPoints,
      productFeedbacks,
      marketGaps,
      sentimentSankeyNodes,
      sentimentSankeyLinks,
      sentimentWordCloudData,
      categoryFunnelData,
    };
  }
  return api.insights.list() as Promise<InsightsData>;
}
