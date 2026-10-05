import { motion, useReducedMotion } from "motion/react";
import { Link } from "react-router-dom";
import Badge from "../components/ui/Badge";
import Card from "../components/ui/Card";
import { buttonClasses } from "../components/ui/Button";

/** Client leaf (Vite SPA, no RSC): one animation helper reused by all sections. */
function Reveal({
  children,
  className,
  delay = 0,
  as = "div",
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
  /** "li" keeps <ol> → <li> semantics valid (P2: no div between list and items). */
  as?: "div" | "li";
}) {
  const reduce = useReducedMotion();
  const MotionTag = as === "li" ? motion.li : motion.div;
  return (
    <MotionTag
      className={className}
      initial={reduce ? false : { opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6, delay, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </MotionTag>
  );
}

/**
 * Real-component mini-preview: JobRow is coupled to api/queryClient/toast, so this
 * uses the actual ui/Badge + ui/Card primitives with JobRow-like row layout.
 */
function JobsMiniPreview() {
  return (
    <Card title="Công việc">
      <ul className="divide-y divide-border">
        <li className="flex items-center justify-between gap-3 py-2 text-sm">
          <span>#47 · PDF · 6 trang</span>
          <Badge tone="success">Hoàn tất</Badge>
        </li>
        <li className="flex items-center justify-between gap-3 py-2 text-sm">
          <span>#48 · Ảnh · 2 trang</span>
          <Badge tone="info">Đang xử lý</Badge>
        </li>
        <li className="flex items-center justify-between gap-3 py-2 text-sm">
          <span>#49 · PDF · 1 trang</span>
          <Badge tone="neutral">Chờ xử lý</Badge>
        </li>
      </ul>
    </Card>
  );
}

const HOW_STEPS = [
  {
    label: "Tải lên",
    body: "Chụp ảnh hoặc chọn file PDF từ máy bạn.",
  },
  {
    label: "Chỉnh sửa",
    body: "Chọn trang, xoay, cắt vùng, sửa từng vùng lỗi.",
  },
  {
    label: "Xuất file",
    body: "Tải kết quả về MD, HTML, DOCX hoặc PDF.",
  },
];

type Feature = {
  title: string;
  body: string;
  className?: string;
  visual?: React.ReactNode;
};

const FEATURES: Feature[] = [
  {
    title: "Wizard chọn trang và xoay",
    body: "Bỏ trang thừa, xoay trang nghiêng trước khi chạy OCR.",
    className: "md:col-span-2",
    visual: (
      <img
        src="https://picsum.photos/seed/exam-paper-desk/1200/520"
        alt="Ảnh chụp đề thi trên bàn học"
        className="h-44 w-full rounded-lg object-cover"
        loading="lazy"
      />
    ),
  },
  {
    title: "Crop ảnh trước khi gửi",
    body: "Cắt đúng vùng chứa chữ, giảm nhiễu nền.",
    visual: (
      <img
        src="https://picsum.photos/seed/scissor-crop-photo/600/520"
        alt="Cắt xén ảnh trên bàn làm việc"
        className="h-44 w-full rounded-lg object-cover"
        loading="lazy"
      />
    ),
  },
  {
    title: "Xem trước MD, PDF, DOCX",
    body: "Đổi định dạng xem trước ngay trong trình duyệt.",
    className: "bg-accent/10 border-accent/30",
  },
  {
    title: "Chỉnh sửa từng vùng",
    body: "Sửa vùng lỗi OCR mà không làm hỏng phần còn lại.",
  },
  {
    title: "Xuất DOCX, PDF, HTML",
    body: "Một tệp kết quả, nhiều định dạng.",
  },
];

const INPUT_FORMATS = ["JPG", "PNG", "WebP", "PDF"];
const OUTPUT_FORMATS = ["MD", "HTML", "DOCX", "PDF"];

export default function Landing() {
  const reduce = useReducedMotion();
  return (
    <div data-testid="landing" className="mx-auto max-w-6xl px-4 pb-24">
      {/* Hero: asymmetric split, motion entry. */}
      <section
        data-testid="landing-hero"
        className="grid items-center gap-10 pt-20 pb-16 md:grid-cols-[1.2fr_1fr] md:pt-24"
      >
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        >
          <h1 className="text-4xl font-bold leading-tight tracking-tight md:text-5xl lg:text-6xl">
            Biến ảnh và PDF thành văn bản sửa được
          </h1>
          <p className="mt-4 max-w-[45ch] text-muted">
            Tải lên, chọn trang, cắt vùng, xuất MD, DOCX, PDF. Chạy trên Colab miễn phí.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            <Link to="/login" data-testid="landing-cta" className={buttonClasses("primary", "md")}>
              Bắt đầu
            </Link>
            <a href="#how" className="text-accent hover:underline">
              Xem cách hoạt động
            </a>
          </div>
        </motion.div>
        <Reveal delay={0.15}>
          <JobsMiniPreview />
        </Reveal>
      </section>

      {/* #how: stacked numbered list, verb-noun labels, no equal cards. */}
      <section data-testid="landing-how" id="how" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold md:text-3xl">Cách hoạt động</h2>
        <ol className="mt-8 divide-y divide-border">
          {HOW_STEPS.map((step, i) => (
            <Reveal
              as="li"
              key={step.label}
              delay={i * 0.06}
              className="flex items-baseline gap-6 py-6"
            >
              <span aria-hidden="true" className="text-3xl font-bold text-muted">
                {i + 1}
              </span>
              <div>
                <h3 className="text-lg font-semibold">{step.label}</h3>
                <p className="mt-1 text-muted">{step.body}</p>
              </div>
            </Reveal>
          ))}
        </ol>
      </section>

      {/* Features: bento, exactly 5 cells, 2 image cells + 1 tinted cell. */}
      <section data-testid="landing-features" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold md:text-3xl">Tính năng</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {FEATURES.map((f, i) => (
            <Reveal
              key={f.title}
              delay={(i % 3) * 0.06}
              className={`rounded-card border border-border bg-surface p-4 ${f.className ?? ""}`}
            >
              <div data-testid="feature-cell">
                {f.visual}
                <h3 className="mt-3 text-lg font-semibold">{f.title}</h3>
                <p className="mt-1 text-muted">{f.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* Formats + Colab strip. */}
      <section data-testid="landing-formats" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold md:text-3xl">Định dạng</h2>
        <Reveal className="mt-8 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">Nhận vào:</span>
            {INPUT_FORMATS.map((fmt) => (
              <Badge key={fmt} tone="neutral">
                {fmt}
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">Xuất ra:</span>
            {OUTPUT_FORMATS.map((fmt) => (
              <Badge key={fmt} tone="info">
                {fmt}
              </Badge>
            ))}
          </div>
          <p className="text-muted">Chạy miễn phí trên Google Colab.</p>
        </Reveal>
      </section>

      {/* Final CTA: same label "Bắt đầu". */}
      <section className="py-16 text-center md:py-24">
        <Reveal>
          <h2 className="text-2xl font-semibold md:text-3xl">Tải ảnh đầu tiên của bạn</h2>
          <div className="mt-8">
            <Link to="/login" className={buttonClasses("primary", "md")}>
              Bắt đầu
            </Link>
          </div>
        </Reveal>
      </section>
    </div>
  );
}
