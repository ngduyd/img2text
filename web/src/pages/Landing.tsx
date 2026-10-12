import { motion, useReducedMotion } from "motion/react";
import { Link } from "react-router-dom";
import Badge from "../components/ui/Badge";
import { buttonClasses } from "../components/ui/Button";

/** Client leaf (Vite SPA, no RSC): one reveal helper reused by all sections. */
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
 * Product screenshot. File may not exist yet (capture script chua chay):
 * onError anh hien tai, chuoi caption van doc duoc (khong lo an, khong vo build).
 */
function Shot({ src, alt, caption }: { src: string; alt: string; caption: string }) {
  return (
    <figure data-testid="gallery-shot" className="overflow-hidden">
      <img
        src={src}
        alt={alt}
        loading="lazy"
        onError={(e) => {
          e.currentTarget.style.visibility = "hidden";
          e.currentTarget.style.aspectRatio = "16 / 10";
          e.currentTarget.style.width = "100%";
        }}
        className="aspect-[16/10] w-full rounded-md border border-border bg-surface object-cover object-top"
      />
      <figcaption className="mt-2 text-sm text-muted">{caption}</figcaption>
    </figure>
  );
}

const HOW_STEPS = [
  {
    label: "OCR đọc chữ",
    body: "Máy đọc ảnh và PDF, ra văn bản thô. Hỗ trợ tiếng Việt có dấu.",
  },
  {
    label: "IR giữ cấu trúc",
    body: "Văn bản được tổ chức thành đoạn, tiêu đề, bảng, danh sách. Bạn sửa từng vùng nghi lỗi.",
  },
  {
    label: "Layout dựng trang",
    body: "Trình dựng layout ghép phần đã sửa lại thành trang có-format, giữ cột và canh lề gốc.",
  },
];

type Feature = {
  title: string;
  body: string;
  className?: string;
};

const FEATURES: Feature[] = [
  {
    title: "Soạn hai khung, undo mọi bước",
    body: "Văn bản và Layout mở song song. Mỗi thao tác lưu vào lịch sử, Ctrl+Z hoàn tác được về bước trước.",
    className: "md:col-span-2",
  },
  {
    title: "Sửa lỗi proofread bằng cách bấm",
    body: "Bấm vào vùng sai trong bản xem trước, chữ tương ứng trong ảnh được tô sáng. Sửa đúng chỗ, không ảnh hưởng phần còn lại.",
    className: "bg-accent/10 border-accent/30",
  },
  {
    title: "Năm định dạng xuất",
    body: "Markdown, DOCX, PDF, cộng bản giữ nguyên layout cho Markdown và DOCX.",
  },
  {
    title: "Quota minh bạch",
    body: "Số trang còn lại của tháng hiển thị ngay trên thanh điều hướng. Không phát sinh chi phí ẩn.",
  },
  {
    title: "Chuẩn bị trang trước khi chạy",
    body: "Chọn trang cần lấy, xoay trang nghiêng, cắt vùng chứa chữ trong wizard trước khi gửi đi.",
  },
];

const INPUT_FORMATS = ["JPG", "PNG", "WebP", "PDF"];

const GALLERY = [
  {
    src: "/screenshots/jobs-list.png",
    alt: "Danh sách công việc img2text kèm quota badge",
    caption: "Danh sách công việc, quota hiển thị trên nav.",
  },
  {
    src: "/screenshots/jobdetail-vanban.png",
    alt: "Bản xem trước văn bản proofread, bấm vào vùng lỗi để sửa",
    caption: "Khung văn bản: sửa từng vùng lỗi bằng cách bấm.",
  },
  {
    src: "/screenshots/jobdetail-layout.png",
    alt: "Bản xem trước layout dựng trang giữ cột và canh lề gốc",
    caption: "Khung layout: trang có-format ghép lại từ phần đã sửa.",
  },
  {
    src: "/screenshots/extraction.png",
    alt: "Màn hình trích xuất ảnh và PDF thành văn bản có cấu trúc",
    caption: "Màn hình trích xuất: ảnh và kết quả so song.",
  },
];

export default function Landing() {
  const reduce = useReducedMotion();
  return (
    <div data-testid="landing" className="mx-auto max-w-6xl px-4 pb-0">
      {/* Hero: split, clamp typography, motion entry. */}
      <section
        data-testid="landing-hero"
        className="grid items-center gap-10 pt-16 pb-16 md:grid-cols-[1.1fr_1fr] md:pt-24"
      >
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        >
          <h1 className="text-[clamp(2rem,5vw,3.5rem)] font-bold leading-[1.15] tracking-tight">
            Biến ảnh và PDF thành văn bản sửa được
          </h1>
          <p className="mt-5 max-w-[45ch] text-muted">
            Ảnh chụp đề thi, sách, tài liệu scan thành văn bản có cấu trúc. Sửa từng vùng lỗi, xuất file bạn cần.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            <Link to="/signin" data-testid="landing-cta" className={buttonClasses("primary", "md")}>
              Bắt đầu
            </Link>
            <a href="#how" className="text-accent-text hover:underline">
              Xem cách hoạt động
            </a>
          </div>
        </motion.div>
        <Reveal delay={0.15}>
          <Shot
            src="/screenshots/landing.png"
            alt="Giao diện img2text trên nền tối"
            caption="Toàn bộ trang trên nền tối."
          />
        </Reveal>
      </section>

      {/* #how: pipeline OCR → IR → Layout, so numbered list, verb-noun labels. */}
      <section data-testid="landing-how" id="how" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">Cách hoạt động</h2>
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
                <p className="mt-1 max-w-[65ch] text-muted">{step.body}</p>
              </div>
            </Reveal>
          ))}
        </ol>
      </section>

      {/* Features: bento, exactly 5 cells, 2-span + tinted cell for rhythm. */}
      <section data-testid="landing-features" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">Tính năng</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {FEATURES.map((f, i) => (
            <Reveal
              key={f.title}
              delay={(i % 3) * 0.06}
              className={`rounded-card border border-border bg-surface p-5 ${f.className ?? ""}`}
            >
              <div data-testid="feature-cell">
                <h3 className="text-lg font-semibold">{f.title}</h3>
                <p className="mt-1 text-muted">{f.body}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* Formats strip: nhận vào / xuất ra + Colab. */}
      <section data-testid="landing-formats" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">Định dạng</h2>
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
            {["MD", "HTML", "DOCX", "PDF"].map((fmt) => (
              <Badge key={fmt} tone="info">
                {fmt}
              </Badge>
            ))}
          </div>
          <p className="text-muted">Chạy miễn phí trên Google Colab.</p>
        </Reveal>
      </section>

      {/* Gallery: real screenshots (placeholder-friendly khi anh chua chup). */}
      <section data-testid="landing-gallery" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">Xem trước</h2>
        <div className="mt-8 grid gap-6 sm:grid-cols-2">
          {GALLERY.map((shot, i) => (
            <Reveal key={shot.src} delay={(i % 2) * 0.06}>
              <Shot {...shot} />
            </Reveal>
          ))}
        </div>
      </section>

      {/* Final CTA: same label "Bắt đầu" (one signup intent, one label). */}
      <section className="py-16 text-center md:py-24">
        <Reveal>
          <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
            Tải ảnh đầu tiên của bạn
          </h2>
          <div className="mt-8">
            <Link to="/signin" className={buttonClasses("primary", "md")}>
              Bắt đầu
            </Link>
          </div>
        </Reveal>
      </section>

      {/* Footer: brand + 2 auth links, muted, hairline top. */}
      <footer data-testid="landing-footer" className="border-t border-border py-8">
        <div className="flex flex-wrap items-center justify-between gap-4 text-sm text-muted">
          <span className="font-semibold text-text">img2text</span>
          <nav className="flex gap-4" aria-label="Liên kết chân trang">
            <Link to="/signin" className="hover:text-text">
              Đăng nhập
            </Link>
            <Link to="/signup" className="hover:text-text">
              Đăng ký
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
