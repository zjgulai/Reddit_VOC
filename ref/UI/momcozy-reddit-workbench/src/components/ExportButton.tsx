import { useState, useCallback, useRef, useMemo, useEffect } from 'react';
import { Download, FileSpreadsheet, FileText, FileType2, Presentation, Loader2, Check, X } from 'lucide-react';
import { EXPORT_COLORS, EXPORT_BRAND_HEX } from '../constants/colors';

export type ExportFormat = 'csv' | 'pdf' | 'pptx' | 'docx';

export interface ExportSection {
  title: string;
  subtitle?: string;
  headers: string[];
  rows: (string | number)[][];
}

export interface ExportButtonProps {
  /** 导出数据（用于 CSV） */
  data?: Record<string, string | number>[];
  /** 导出文件名前缀 */
  filename?: string;
  /** 自定义 CSV 内容生成 */
  csvContent?: string;
  /** 自定义导出处理 */
  onCustomExport?: (format: ExportFormat) => void;
  /** 尺寸 */
  size?: 'sm' | 'md';
  /** 报告标题（用于 PDF/PPT/Word） */
  title?: string;
  /** 报告副标题 */
  subtitle?: string;
  /** 结构化报告分节（用于 PDF/PPT/Word） */
  sections?: ExportSection[];
}

/** 将对象数组转为 CSV 字符串 */
function toCSV(rows: Record<string, string | number>[]): string {
  if (!rows.length) return '';
  const headers = Object.keys(rows[0]);
  const escape = (val: string | number) => {
    const s = String(val).replace(/"/g, '""');
    return s.includes(',') || s.includes('\n') || s.includes('"') ? `"${s}"` : s;
  };
  const lines = [
    headers.join(','),
    ...rows.map((row) => headers.map((h) => escape(row[h])).join(',')),
  ];
  return '\uFEFF' + lines.join('\n'); // BOM for Excel UTF-8
}

/** 触发文件下载 */
function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** 生成 PDF（html2canvas + jsPDF，确保中文正常渲染） */
async function exportPDF(filename: string, title: string, subtitle: string | undefined, sections: ExportSection[]) {
  const [{ default: html2canvas }, { default: jsPDF }] = await Promise.all([
    import('html2canvas'),
    import('jspdf'),
  ]);

  const container = document.createElement('div');
  container.style.position = 'fixed';
  container.style.left = '-9999px';
  container.style.top = '0';
  container.style.width = '794px'; // A4 width at 96dpi
  container.style.padding = '40px';
  container.style.background = '#ffffff';
  container.style.fontFamily = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif';
  container.style.color = EXPORT_COLORS.title;
  container.style.lineHeight = '1.6';
  container.style.boxSizing = 'border-box';
  container.style.wordBreak = 'break-all';

  let html = '';
  html += `<h1 style="font-size:24px;font-weight:600;color:${EXPORT_COLORS.title};margin:0 0 8px 0;">${escapeHtml(title)}</h1>`;
  if (subtitle) {
    html += `<p style="font-size:14px;color:${EXPORT_COLORS.subtitle};margin:0 0 24px 0;">${escapeHtml(subtitle)}</p>`;
  }
  html += `<p style="font-size:12px;color:${EXPORT_COLORS.meta};margin:0 0 24px 0;">生成时间：${new Date().toLocaleString('zh-CN')}</p>`;

  sections.forEach((section) => {
    html += `<h2 style="font-size:18px;font-weight:600;color:${EXPORT_COLORS.title};margin:24px 0 12px 0;">${escapeHtml(section.title)}</h2>`;
    if (section.subtitle) {
      html += `<p style="font-size:13px;color:${EXPORT_COLORS.subtitle};margin:0 0 12px 0;">${escapeHtml(section.subtitle)}</p>`;
    }
    html += `<table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:16px;table-layout:fixed;">`;
    html += `<thead><tr style="background:${EXPORT_COLORS.headerBg};">`;
    section.headers.forEach((h) => {
      html += `<th style="padding:10px 12px;text-align:left;border-bottom:2px solid ${EXPORT_COLORS.tableBorder};font-weight:600;color:${EXPORT_COLORS.title};font-size:13px;word-break:break-all;">${escapeHtml(h)}</th>`;
    });
    html += `</tr></thead><tbody>`;
    section.rows.forEach((row, i) => {
      html += `<tr style="background:${i % 2 === 0 ? EXPORT_COLORS.white : EXPORT_COLORS.rowAlt};">`;
      row.forEach((cell) => {
        html += `<td style="padding:8px 12px;border-bottom:1px solid ${EXPORT_COLORS.border};color:${EXPORT_COLORS.title};font-size:13px;word-break:break-all;">${escapeHtml(String(cell))}</td>`;
      });
      html += `</tr>`;
    });
    html += `</tbody></table>`;
  });

  container.innerHTML = html;
  document.body.appendChild(container);

  // 强制布局，触发浏览器字体加载
  container.getBoundingClientRect();

  try {
    // 等待字体加载完成，确保中文正确渲染
    await document.fonts.ready;

    const canvas = await html2canvas(container, {
      scale: 2,
      useCORS: true,
      logging: false,
      backgroundColor: '#ffffff',
      width: 794,
      windowWidth: 794,
    });
    const imgData = canvas.toDataURL('image/png');

    const pdf = new jsPDF({ orientation: 'portrait', unit: 'px', format: 'a4' });
    const pdfWidth = pdf.internal.pageSize.getWidth();
    const pdfHeight = pdf.internal.pageSize.getHeight();
    const imgWidth = pdfWidth;
    const imgHeight = (canvas.height * imgWidth) / canvas.width;

    let heightLeft = imgHeight;
    let position = 0;

    pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
    heightLeft -= pdfHeight;

    while (heightLeft > 0) {
      position -= pdfHeight;
      pdf.addPage();
      pdf.addImage(imgData, 'PNG', 0, position, imgWidth, imgHeight);
      heightLeft -= pdfHeight;
    }

    pdf.save(`${filename}.pdf`);
  } finally {
    if (container.parentNode) {
      document.body.removeChild(container);
    }
  }
}

/** 生成 PPTX */
async function exportPPTX(filename: string, title: string, subtitle: string | undefined, sections: ExportSection[]) {
  const { default: PptxGenJS } = await import('pptxgenjs');
  const pptx = new PptxGenJS();
  pptx.layout = 'LAYOUT_16x9';
  pptx.title = title;

  // Title slide
  const slide1 = pptx.addSlide();
  slide1.background = { color: 'FFFFFF' };
  slide1.addText(title, {
    x: 0.5, y: 1.8, w: 9, h: 1,
    fontSize: 32, bold: true, color: EXPORT_BRAND_HEX,
    fontFace: 'Microsoft YaHei',
    align: 'center',
  });
  if (subtitle) {
    slide1.addText(subtitle, {
      x: 0.5, y: 2.8, w: 9, h: 0.5,
      fontSize: 16, color: '6B6B6B',
      fontFace: 'Microsoft YaHei',
      align: 'center',
    });
  }
  slide1.addText(`生成时间：${new Date().toLocaleString('zh-CN')}`, {
    x: 0.5, y: 3.6, w: 9, h: 0.3,
    fontSize: 11, color: '9A9A9A',
    fontFace: 'Microsoft YaHei',
    align: 'center',
  });

  sections.forEach((section) => {
    const slide = pptx.addSlide();
    slide.background = { color: 'FFFFFF' };
    slide.addText(section.title, {
      x: 0.5, y: 0.4, w: 9, h: 0.5,
      fontSize: 20, bold: true, color: '1A1A1A',
      fontFace: 'Microsoft YaHei',
    });
    if (section.subtitle) {
      slide.addText(section.subtitle, {
        x: 0.5, y: 0.9, w: 9, h: 0.3,
        fontSize: 12, color: '6B6B6B',
        fontFace: 'Microsoft YaHei',
      });
    }

    const rows = [
      section.headers.map((h) => ({ text: h })),
      ...section.rows.map((r) => r.map((c) => ({ text: String(c) }))),
    ];
    const colW = section.headers.map(() => 9 / section.headers.length);

    slide.addTable(rows, {
      x: 0.5, y: 1.3, w: 9,
      fontSize: 11,
      color: '1A1A1A',
      fontFace: 'Microsoft YaHei',
      border: { pt: 0.5, color: 'EDEDED' },
      fill: { color: 'FDF0F2' },
      colW,
    });
  });

  pptx.writeFile({ fileName: `${filename}.pptx` });
}

/** 生成 DOCX */
async function exportDOCX(filename: string, title: string, subtitle: string | undefined, sections: ExportSection[]) {
  const {
    Document, Packer, Paragraph, Table, TableCell, TableRow,
    TextRun, HeadingLevel, WidthType, BorderStyle,
  } = await import('docx');

  const children = [];

  children.push(
    new Paragraph({
      children: [new TextRun({ text: title, bold: true, size: 32, color: EXPORT_BRAND_HEX })],
      heading: HeadingLevel.TITLE,
      spacing: { after: 200 },
    })
  );

  if (subtitle) {
    children.push(
      new Paragraph({
        children: [new TextRun({ text: subtitle, size: 24 })],
        spacing: { after: 400 },
      })
    );
  }

  children.push(
    new Paragraph({
      children: [new TextRun({ text: `生成时间：${new Date().toLocaleString('zh-CN')}`, size: 22, color: '#9A9A9A' })],
      spacing: { after: 400 },
    })
  );

  sections.forEach((section) => {
    children.push(
      new Paragraph({
        children: [new TextRun({ text: section.title, bold: true, size: 26 })],
        heading: HeadingLevel.HEADING_2,
        spacing: { before: 300, after: 100 },
      })
    );
    if (section.subtitle) {
      children.push(
        new Paragraph({
          children: [new TextRun({ text: section.subtitle, size: 22, color: '6B6B6B' })],
          spacing: { after: 200 },
        })
      );
    }

    children.push(
      new Table({
        width: { size: 100, type: WidthType.PERCENTAGE },
        rows: [
          new TableRow({
            children: section.headers.map((h) =>
              new TableCell({
                children: [new Paragraph({ children: [new TextRun({ text: h, bold: true })] })],
                shading: { fill: 'FDF0F2', color: 'auto' },
                borders: {
                  top: { color: EXPORT_BRAND_HEX, size: 8, style: BorderStyle.SINGLE },
                  bottom: { color: EXPORT_BRAND_HEX, size: 8, style: BorderStyle.SINGLE },
                  left: { style: BorderStyle.NONE },
                  right: { style: BorderStyle.NONE },
                },
              })
            ),
          }),
          ...section.rows.map((row) =>
            new TableRow({
              children: row.map((cell) =>
                new TableCell({
                  children: [new Paragraph({ children: [new TextRun({ text: String(cell) })] })],
                  borders: {
                    top: { style: BorderStyle.NONE },
                    bottom: { color: 'EDEDED', size: 4, style: BorderStyle.SINGLE },
                    left: { style: BorderStyle.NONE },
                    right: { style: BorderStyle.NONE },
                  },
                })
              ),
            })
          ),
        ],
      })
    );
  });

  const doc = new Document({
    sections: [{
      properties: {},
      children,
    }],
  });

  const blob = await Packer.toBlob(doc);
  downloadBlob(blob, `${filename}.docx`);
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 从扁平 data 生成 sections */
function deriveSections(data: Record<string, string | number>[], title?: string, subtitle?: string): ExportSection[] {
  if (!data.length) return [];
  const headers = Object.keys(data[0]);
  return [{
    title: title || '导出数据',
    subtitle: subtitle,
    headers,
    rows: data.map((row) => headers.map((h) => row[h])),
  }];
}

export default function ExportButton({
  data,
  filename = 'export',
  csvContent,
  onCustomExport,
  size = 'md',
  title,
  subtitle,
  sections: propSections,
}: ExportButtonProps) {
  const [showMenu, setShowMenu] = useState(false);
  const [exporting, setExporting] = useState<ExportFormat | null>(null);
  const [done, setDone] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<ExportFormat | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const menuRef = useRef<HTMLDivElement>(null);
  const timerRefs = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

  // 清理所有定时器，防止组件卸载后 setState
  useEffect(() => {
    return () => {
      timerRefs.current.forEach((id) => clearTimeout(id));
      timerRefs.current.clear();
    };
  }, []);

  const sections = useMemo(() => propSections ?? (data ? deriveSections(data, title, subtitle) : []), [propSections, data, title, subtitle]);
  const reportTitle = title || filename;
  const reportSubtitle = subtitle || `生成日期：${new Date().toLocaleDateString('zh-CN')}`;

  const handleExport = useCallback(
    async (format: ExportFormat) => {
      setShowMenu(false);
      setExporting(format);
      setDone(null);
      setError(null);
      setErrorMessage('');

      try {
        if (onCustomExport) {
          onCustomExport(format);
        } else if (format === 'csv') {
          const content = csvContent || (data ? toCSV(data) : '');
          if (!content) {
            throw new Error('暂无数据可导出');
          }
          const dateStr = new Date().toISOString().slice(0, 10);
          const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
          downloadBlob(blob, `${filename}_${dateStr}.csv`);
        } else if (format === 'pdf') {
          if (sections.length === 0) {
            throw new Error('暂无数据可导出');
          }
          await exportPDF(filename, reportTitle, reportSubtitle, sections);
        } else if (format === 'pptx') {
          if (sections.length === 0) {
            throw new Error('暂无数据可导出');
          }
          await exportPPTX(filename, reportTitle, reportSubtitle, sections);
        } else if (format === 'docx') {
          if (sections.length === 0) {
            throw new Error('暂无数据可导出');
          }
          await exportDOCX(filename, reportTitle, reportSubtitle, sections);
        }

        setDone(format);
        const doneTimer = setTimeout(() => setDone(null), 2000);
        timerRefs.current.add(doneTimer);
      } catch (err) {
        setError(format);
        setErrorMessage(err instanceof Error ? err.message : '导出失败，请重试');
        const errorTimer = setTimeout(() => {
          setError(null);
          setErrorMessage('');
        }, 3000);
        timerRefs.current.add(errorTimer);
      } finally {
        setExporting(null);
      }
    },
    [csvContent, data, filename, onCustomExport, reportTitle, reportSubtitle, sections]
  );

  const btnClass =
    size === 'sm'
      ? 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-button text-tiny font-medium transition-all'
      : 'inline-flex items-center gap-2 px-4 py-2 rounded-button text-body-sm font-medium transition-all';

  const iconSize = size === 'sm' ? 'w-3.5 h-3.5' : 'w-4 h-4';

  const formatItems: { format: ExportFormat; label: string; icon: typeof FileSpreadsheet }[] = [
    { format: 'csv', label: 'CSV', icon: FileSpreadsheet },
    { format: 'pdf', label: 'PDF', icon: FileText },
    { format: 'pptx', label: 'PPT', icon: Presentation },
    { format: 'docx', label: 'Word', icon: FileType2 },
  ];

  useEffect(() => {
    if (!showMenu) return;
    function handleClickOutside(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setShowMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showMenu]);

  useEffect(() => {
    if (!showMenu) return;
    function handleEsc(e: KeyboardEvent) {
      if (e.key === 'Escape') setShowMenu(false);
    }
    document.addEventListener('keydown', handleEsc);
    return () => document.removeEventListener('keydown', handleEsc);
  }, [showMenu]);

  return (
    <div className="relative" ref={menuRef}>
      <button
        className={`${btnClass} bg-surface-tertiary text-foreground-secondary hover:bg-surface-warm hover:text-foreground border border-border-divider`}
        onClick={() => setShowMenu(!showMenu)}
        aria-haspopup="true"
        aria-expanded={showMenu}
      >
        <Download className={iconSize} strokeWidth={1.5} />
        导出
      </button>

      {showMenu && (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setShowMenu(false)}
          />
          <div className="absolute right-0 top-full mt-2 w-52 bg-white rounded-card shadow-card-hover border border-border-divider z-50 py-1.5">
            {formatItems.map((item) => {
              const isExporting = exporting === item.format;
              const isDone = done === item.format;
              const isError = error === item.format;
              const Icon = item.icon;
              return (
                <button
                  key={item.format}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-body-sm text-foreground-secondary hover:bg-surface-tertiary hover:text-foreground transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  onClick={() => handleExport(item.format)}
                  disabled={exporting !== null}
                  title={isError ? errorMessage : undefined}
                  data-ui-severity={isError ? 'error' : undefined}
                >
                  {isExporting ? (
                    <Loader2 className="w-4 h-4 animate-spin text-primary" strokeWidth={1.5} />
                  ) : isDone ? (
                    <Check className="w-4 h-4 text-status-success" strokeWidth={1.5} />
                  ) : isError ? (
                    <X className="w-4 h-4 text-status-error" strokeWidth={1.5} />
                  ) : (
                    <Icon className="w-4 h-4" strokeWidth={1.5} />
                  )}
                  <span className="flex-1 text-left">
                    {isExporting ? '导出中…' : isDone ? '导出成功' : isError ? '导出失败' : `导出 ${item.label}`}
                  </span>
                </button>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}
