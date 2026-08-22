import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  MessageSquare,
  Mail,
  Lock,
  ArrowLeft,
  Eye,
  EyeOff,
  Globe,
} from 'lucide-react';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    // Mock login
    setTimeout(() => setIsLoading(false), 1500);
  };

  return (
    <div className="min-h-screen bg-[#FCF5F2] flex items-center justify-center p-4">
      {/* Background decoration */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute top-20 left-10 w-96 h-96 bg-[#C44A5E]/5 rounded-full blur-3xl" />
        <div className="absolute bottom-20 right-10 w-72 h-72 bg-[#C44A5E]/5 rounded-full blur-3xl" />
      </div>

      <div className="relative w-full max-w-md">
        {/* Back to home */}
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-[#7C5C62] hover:text-[#C44A5E] transition-colors mb-8"
        >
          <ArrowLeft className="w-4 h-4" />
          返回首页
        </Link>

        <div className="card">
          {/* Logo */}
          <div className="text-center mb-8">
            <div className="w-12 h-12 rounded-xl bg-[#C44A5E] flex items-center justify-center mx-auto mb-4">
              <MessageSquare className="w-7 h-7 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-[#35141A] mb-2">
              登录 Momcozy & Reddit 舆情工作台
            </h1>
            <p className="text-sm text-[#A89094]">
              开始监测 Reddit 上的品牌声量
            </p>
          </div>

          {/* Google Login */}
          <button className="w-full flex items-center justify-center gap-3 px-4 py-3 rounded-xl border border-[#E8D5D5] bg-white text-[#35141A] font-medium text-sm hover:bg-[#F5EBE6] transition-colors mb-6">
            <Globe className="w-5 h-5" />
            使用 Google 账号登录
          </button>

          <div className="relative mb-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-[#E8D5D5]" />
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-4 bg-white text-[#A89094]">或使用邮箱登录</span>
            </div>
          </div>

          {/* Email/Password Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-[#7C5C62] mb-2">
                邮箱地址
              </label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A89094]" />
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="your@email.com"
                  className="input-field pl-10"
                  required
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-[#7C5C62] mb-2">
                密码
              </label>
              <div className="relative">
                <Lock className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A89094]" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="input-field pl-10 pr-10"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-[#A89094] hover:text-[#7C5C62] transition-colors"
                >
                  {showPassword ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>

            <div className="flex items-center justify-between">
              <label className="flex items-center gap-2 text-sm text-[#7C5C62]">
                <input type="checkbox" className="w-4 h-4 rounded border-[#E8D5D5] text-[#C44A5E] focus:ring-[#C44A5E]" />
                记住我
              </label>
              <a href="#" className="text-sm text-[#C44A5E] hover:text-[#B03A4E] transition-colors">
                忘记密码？
              </a>
            </div>

            <button
              type="submit"
              disabled={isLoading}
              className="w-full btn-primary py-3 disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {isLoading ? '登录中...' : '登录'}
            </button>
          </form>

          <div className="text-center mt-6">
            <p className="text-sm text-[#7C5C62]">
              还没有账号？
              <a href="#" className="text-[#C44A5E] hover:text-[#B03A4E] font-medium transition-colors">
                立即注册
              </a>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
