import { Component, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/** 全局错误边界 - 捕获渲染异常，防止整站白屏 */
class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    if (import.meta.env.DEV) {
      console.error('ErrorBoundary caught:', error, errorInfo);
    }
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div
          className="min-h-screen flex items-center justify-center bg-surface-tertiary p-6"
          data-ui-severity="error"
        >
          <div className="card max-w-md w-full text-center p-8">
            <div className="w-14 h-14 rounded-icon bg-status-errorBg flex items-center justify-center mx-auto mb-5">
              <AlertTriangle className="w-7 h-7 text-status-error" strokeWidth={1.5} />
            </div>
            <h2 className="text-h2 font-semibold text-foreground mb-2">页面出错了</h2>
            <p className="text-body text-foreground-secondary mb-6">
              很抱歉，页面遇到了一些问题。请尝试刷新页面，或返回首页。
            </p>
            {this.state.error && (
              <p className="text-caption text-foreground-muted bg-surface-tertiary rounded-input p-3 mb-6 text-left break-all">
                {this.state.error.message}
              </p>
            )}
            <div className="flex items-center justify-center gap-3">
              <button
                onClick={this.handleReset}
                className="btn-primary inline-flex items-center gap-2"
              >
                <RefreshCw className="w-4 h-4" strokeWidth={1.5} />
                重试
              </button>
              <a href="/" className="btn-secondary">
                返回首页
              </a>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
