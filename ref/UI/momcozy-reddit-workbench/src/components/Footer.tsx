import { Link } from 'react-router-dom';
import { MessageSquare } from 'lucide-react';
import { getCurrentYear } from '../utils/date';

export default function Footer() {
  return (
    <footer className="bg-surface-secondary border-t border-border-divider">
      <div className="max-w-container mx-auto px-6 lg:px-16 py-16">
        <div className="grid grid-cols-1 md:grid-cols-12 gap-12">
          {/* Brand — 占据更多空间 */}
          <div className="md:col-span-5">
            <div className="flex items-center gap-2.5 mb-4">
              <div className="w-7 h-7 rounded-icon bg-primary flex items-center justify-center">
                <MessageSquare className="w-4 h-4 text-white" strokeWidth={1.5} />
              </div>
              <span className="text-base font-semibold text-foreground tracking-tight">
                Momcozy & Reddit
              </span>
            </div>
            <p className="text-body-sm text-foreground-muted leading-relaxed max-w-sm">
              基于版本化 Reddit 公开内容快照，提供可回溯的 VOC 聚合、报告与证据检索。
            </p>
          </div>

          {/* Links */}
          <div className="md:col-span-3 md:col-start-7">
            <h4 className="text-caption font-semibold text-foreground uppercase tracking-wider mb-4">产品</h4>
            <ul className="space-y-3">
              <li><Link to="/features" className="text-body-sm text-foreground-secondary hover:text-primary transition-colors duration-200">功能介绍</Link></li>
              <li><Link to="/how-it-works" className="text-body-sm text-foreground-secondary hover:text-primary transition-colors duration-200">使用流程</Link></li>
              <li><Link to="/dashboard" className="text-body-sm text-foreground-secondary hover:text-primary transition-colors duration-200">工作台</Link></li>
            </ul>
          </div>

          <div className="md:col-span-3">
            <h4 className="text-caption font-semibold text-foreground uppercase tracking-wider mb-4">支持</h4>
            <ul className="space-y-3">
              <li><Link to="/faq" className="text-body-sm text-foreground-secondary hover:text-primary transition-colors duration-200">常见问题</Link></li>
              <li><span className="text-body-sm text-foreground-secondary">隐私政策</span></li>
              <li><span className="text-body-sm text-foreground-secondary">服务条款</span></li>
            </ul>
          </div>
        </div>

        <div className="mt-16 pt-8 border-t border-border-divider">
          <p className="text-caption text-foreground-muted">
            © {getCurrentYear()} Momcozy & Reddit 舆情工作台. 保留所有权利.
          </p>
        </div>
      </div>
    </footer>
  );
}
