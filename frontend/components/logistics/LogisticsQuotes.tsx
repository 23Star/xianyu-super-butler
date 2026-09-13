import { Calculator, Sparkles } from 'lucide-react';

const LogisticsQuotes = () => {
  return (
    <div className="page-stack mx-auto w-full max-w-[1080px] animate-fade-in">
      <div className="section-panel flex min-h-[420px] flex-col items-center justify-center p-8 text-center">
        <div className="mb-5 flex h-20 w-20 items-center justify-center rounded-3xl bg-[#fff4b8] text-[#8c7900] shadow-sm">
          <Calculator className="h-10 w-10" aria-hidden="true" />
        </div>
        <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-[#f0d84a] bg-[#fffbea] px-3 py-1 text-xs font-semibold text-[#8c7900]">
          <Sparkles className="h-3.5 w-3.5" /> 持续优化中
        </div>
        <h1 className="text-xl font-bold text-gray-900">物流报价</h1>
        <p className="mt-3 max-w-md text-sm leading-6 text-gray-500">物流报价功能正在持续优化，完成后将重新开放。感谢你的耐心等待。</p>
      </div>
    </div>
  );
};

export default LogisticsQuotes;
