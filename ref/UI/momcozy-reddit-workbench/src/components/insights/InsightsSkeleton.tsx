/** Insights 页面骨架屏 */
export default function InsightsSkeleton() {
  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div className="shimmer h-6 w-48" />
        <div className="shimmer h-4 w-72" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="card p-5 space-y-3">
            <div className="flex items-center gap-2">
              <div className="shimmer h-4 w-16" />
              <div className="shimmer h-4 w-20" />
            </div>
            <div className="shimmer h-5 w-3/4" />
            <div className="shimmer h-16 w-full" />
            <div className="shimmer h-3 w-full" />
            <div className="shimmer h-3 w-2/3" />
          </div>
        ))}
      </div>
      <div className="card p-5 space-y-3">
        <div className="shimmer h-5 w-32" />
        <div className="shimmer h-4 w-full" />
        <div className="shimmer h-4 w-full" />
        <div className="shimmer h-4 w-full" />
      </div>
    </div>
  );
}
