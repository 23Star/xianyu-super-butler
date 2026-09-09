import { type ChangeEvent, useCallback, useEffect, useState } from 'react';
import { Calculator, FileSpreadsheet } from 'lucide-react';
import {
  createQuoteBook,
  deleteQuoteBook,
  listQuoteBooks,
  type LogisticsQuoteBook,
} from '../../services/api';
import {
  extractParseError,
  supportedQuoteFilePattern,
} from '../../services/logisticsQuote';
import { confirmLeaveUnsaved } from '../../services/unsavedChanges';
import { EmptyState, PageHeader } from '../ui';
import QuoteAgentPanel from './agent/QuoteAgentPanel';
import QuoteAutoReply from './QuoteAutoReply';
import QuoteBookList from './QuoteBookList';
import QuoteDiagnostics from './QuoteDiagnostics';
import QuoteRecognitionPanel from './QuoteRecognitionPanel';
import QuoteSettings from './QuoteSettings';
import { StepCard, workflowSteps, type StepId } from './QuoteWorkflowSteps';

const LogisticsQuotes = () => {
  const [activeStep, setActiveStep] = useState<StepId>('recognition');
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [books, setBooks] = useState<LogisticsQuoteBook[]>([]);
  const [isRecognizing, setIsRecognizing] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isDeletingId, setIsDeletingId] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [infoMessage, setInfoMessage] = useState('');

  const refreshBooks = useCallback(async () => {
    try {
      const response = await listQuoteBooks();
      setBooks(response.books);
    } catch {
      setBooks([]);
    }
  }, []);

  useEffect(() => {
    void refreshBooks();
  }, [refreshBooks]);

  const handleRefreshBooks = async () => {
    if (isRefreshing) return;
    setIsRefreshing(true);
    await refreshBooks();
    setIsRefreshing(false);
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const files: File[] = event.target.files ? Array.from(event.target.files) : [];
    event.target.value = '';
    if (!files.length) return;
    const unsupported = files.filter((file) => !supportedQuoteFilePattern.test(file.name));
    if (unsupported.length) {
      setSelectedFiles([]);
      setErrorMessage(`仅支持 .xlsx、.xlsm、.xls 或 .csv 格式的报价表：${unsupported.map((file) => file.name).join('、')}`);
      return;
    }
    setSelectedFiles(files);
    setErrorMessage('');
  };

  const removeSelectedFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, position) => position !== index));
  };

  const clearSelection = () => {
    setSelectedFiles([]);
  };

  const handleRecognize = async () => {
    if (!selectedFiles.length || isRecognizing) return;
    setIsRecognizing(true);
    setErrorMessage('');
    setInfoMessage('');
    const failures: string[] = [];
    const synced: string[] = [];
    try {
      for (const file of selectedFiles) {
        try {
          const response = await createQuoteBook(file);
          setBooks((prev) => [response.book, ...prev.filter((book) => book.id !== response.book.id)]);
          if (response.route_import) {
            synced.push(`「${file.name}」已同步 ${response.route_import.route_count} 条线路明细到第五步物流 Agent`);
          } else if (response.route_warning) {
            synced.push(`「${file.name}」${response.route_warning}`);
          }
        } catch (error) {
          failures.push(`「${file.name}」${extractParseError(error)}`);
        }
      }
      if (failures.length) setErrorMessage(failures.join('；'));
      if (synced.length) setInfoMessage(synced.join('；'));
    } finally {
      setIsRecognizing(false);
      clearSelection();
      void refreshBooks();
    }
  };

  const handleDelete = async (bookId: number) => {
    if (isDeletingId !== null) return;
    setIsDeletingId(bookId);
    try {
      await deleteQuoteBook(bookId);
      setBooks((prev) => prev.filter((book) => book.id !== bookId));
    } catch (error) {
      setErrorMessage(extractParseError(error));
    } finally {
      setIsDeletingId(null);
    }
  };

  const activeWorkflowStep = workflowSteps.find((step) => step.id === activeStep) ?? workflowSteps[0];

  const handleSelectStep = async (id: StepId) => {
    if (id === activeStep) return;
    if (!(await confirmLeaveUnsaved())) return;
    setActiveStep(id);
  };

  return (
    <div className="page-stack mx-auto w-full max-w-[1080px] animate-fade-in">
      <PageHeader
        icon={Calculator}
        title="物流报价"
        description="维护承运商报价数据：先识别报价表，再配置报价设置与消息模板，最后在物流 Agent 按账号启用自动报价。识别报价表时线路明细会自动同步到第五步。"
      />

      <ol className="grid gap-3 sm:grid-cols-3 lg:grid-cols-5" aria-label="物流报价流程">
        {workflowSteps.map((step, index) => (
          <li key={step.id} aria-current={activeStep === step.id ? 'step' : undefined}>
            <StepCard
              step={step}
              index={index}
              active={activeStep === step.id}
              onSelect={handleSelectStep}
            />
          </li>
        ))}
      </ol>

      {activeStep === 'settings' ? (
        <QuoteSettings />
      ) : activeStep === 'apply' ? (
        <QuoteAutoReply />
      ) : activeStep === 'diagnose' ? (
        <QuoteDiagnostics />
      ) : activeStep === 'agent' ? (
        <QuoteAgentPanel onNavigateStep={(step) => void handleSelectStep(step)} />
      ) : activeStep === 'recognition' ? (
        <>
          <QuoteRecognitionPanel
            selectedFiles={selectedFiles}
            isRecognizing={isRecognizing}
            onFileChange={handleFileChange}
            onRemoveFile={removeSelectedFile}
            onClearFiles={clearSelection}
            onRecognize={() => void handleRecognize()}
          />

          {errorMessage && (
            <p
              className="rounded-md border border-[color:color-mix(in_srgb,var(--danger)_34%,var(--border))] bg-[var(--danger-soft)] px-3 py-2.5 text-[13px] leading-normal text-[var(--danger-ink)]"
              role="alert"
            >
              {errorMessage}
            </p>
          )}

          {infoMessage && (
            <p
              className="rounded-md border border-[color:color-mix(in_srgb,var(--brand)_34%,var(--border))] bg-[var(--brand-soft)] px-3 py-2.5 text-[13px] leading-normal text-[var(--brand-text)]"
              role="status"
            >
              {infoMessage}
            </p>
          )}

          <QuoteBookList
            books={books}
            isRefreshing={isRefreshing}
            isDeletingId={isDeletingId}
            onRefresh={() => void handleRefreshBooks()}
            onDelete={(bookId) => void handleDelete(bookId)}
          />
        </>
      ) : (
        <EmptyState
          title="该功能正在准备中"
          description={activeWorkflowStep.description}
          icon={activeWorkflowStep.icon}
        />
      )}
    </div>
  );
};

export default LogisticsQuotes;
