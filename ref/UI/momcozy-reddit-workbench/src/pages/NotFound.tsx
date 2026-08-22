import { Link } from 'react-router-dom';
import { ArrowLeft, Home } from 'lucide-react';

/** 404 页面 */
export default function NotFound() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-surface-tertiary p-6">
      <div className="card max-w-lg w-full text-center p-12">
        <div className="text-[80px] font-bold text-primary/10 leading-none mb-2">404</div>
        <h1 className="text-h1 text-foreground mb-3">页面未找到</h1>
        <p className="text-body text-foreground-secondary mb-8">
          你访问的页面不存在或已被移除。请检查链接是否正确，或返回首页继续浏览。
        </p>
        <div className="flex items-center justify-center gap-3">
          <button
            onClick={() => window.history.back()}
            className="btn-secondary inline-flex items-center gap-2"
          >
            <ArrowLeft className="w-4 h-4" strokeWidth={1.5} />
            返回上一页
          </button>
          <Link to="/" className="btn-primary inline-flex items-center gap-2">
            <Home className="w-4 h-4" strokeWidth={1.5} />
            返回首页
          </Link>
        </div>
      </div>
    </div>
  );
}
