import { type ChangeEvent } from 'react';
import { FileSpreadsheet, RefreshCw, UploadCloud, X } from 'lucide-react';

interface QuoteRecognitionPanelProps {
  selectedFiles: File[];
  isRecognizing: boolean;
  onFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onRemoveFile: (index: number) => void;
  onClearFiles: () => void;
  onRecognize: () => void;
}

/** 识别报价表步骤的上传区：文件选择、已选文件列表与识别操作。 */
const QuoteRecognitionPanel = ({
  selectedFiles,
  isRecognizing,
  onFileChange,
  onRemoveFile,
  onClearFiles,
  onRecognize,
}: QuoteRecognitionPanelProps) => (
  <section className="section-panel flex flex-col gap-3 p-4">
    <input
      type="file"
      accept=".xlsx,.xlsm,.xls,.csv"
      multiple
      onChange={onFileChange}
      className="sr-only [&:focus-visible+label]:outline-2 [&:focus-visible+label]:outline-offset-2 [&:focus-visible+label]:outline-[var(--focus-ring)]"
      aria-label="选择报价表文件"
      id="rate-book-file"
    />
    <label
      htmlFor="rate-book-file"
      className="flex cursor-pointer items-center gap-3.5 rounded-lg border-[1.5px] border-dashed border-[var(--border-strong)] bg-[var(--surface-subtle)] p-4 transition-colors duration-150 hover:border-[color:color-mix(in_srgb,var(--brand)_55%,var(--border-strong))] hover:bg-[var(--surface-hover)] motion-reduce:transition-none"
    >
      <span className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-[var(--brand-soft)] text-[var(--brand-text)]">
        <UploadCloud className="h-[22px] w-[22px]" aria-hidden="true" />
      </span>
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="text-sm font-bold text-[var(--text)]">选择报价表文件</span>
        <span className="text-xs text-[var(--text-muted)]">
          支持 .xlsx / .xlsm / .xls / .csv，可一次选择多个文件
        </span>
      </span>
      <span className="ios-btn-secondary flex shrink-0 items-center justify-center rounded-md px-4 py-2 text-sm">
        浏览文件
      </span>
    </label>

    {selectedFiles.length > 0 && (
      <div className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-end sm:justify-between">
        <ul className="flex min-w-0 flex-1 flex-wrap gap-2" aria-label="已选择的文件">
          {selectedFiles.map((file, index) => (
            <li
              className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-[var(--border)] bg-[var(--surface)] py-1 pl-3 pr-1.5 text-[13px] leading-snug text-[var(--text-muted)]"
              key={`${file.name}-${index}`}
            >
              <FileSpreadsheet className="h-[15px] w-[15px] shrink-0 text-[var(--text-soft)]" aria-hidden="true" />
              <span className="min-w-0 max-w-[160px] truncate sm:max-w-[240px]" title={file.name}>{file.name}</span>
              <button
                type="button"
                className="relative inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[var(--text-soft)] transition-colors duration-150 after:absolute after:-inset-2.5 after:content-[''] hover:bg-[var(--danger-soft)] hover:text-[var(--danger)] motion-reduce:transition-none"
                onClick={() => onRemoveFile(index)}
                aria-label={`移除 ${file.name}`}
              >
                <X className="h-3.5 w-3.5" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            className="ios-btn-secondary flex flex-1 items-center justify-center rounded-md px-4 py-2 text-sm sm:flex-none"
            onClick={onClearFiles}
          >
            全部清除
          </button>
          <button
            type="button"
            className="ios-btn-primary flex flex-1 items-center justify-center gap-2 rounded-md px-4 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-45 sm:flex-none"
            disabled={isRecognizing}
            onClick={onRecognize}
          >
            {isRecognizing ? <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" /> : <FileSpreadsheet className="h-4 w-4" aria-hidden="true" />}
            <span>{isRecognizing ? '识别中' : '开始识别'}</span>
          </button>
        </div>
      </div>
    )}
  </section>
);

export default QuoteRecognitionPanel;
