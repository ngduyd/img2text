import { motion, useReducedMotion } from "motion/react";
import { Link } from "react-router-dom";
import Badge from "../components/ui/Badge";
import { buttonClasses } from "../components/ui/Button";
import { useT } from "../i18n";

/** Client leaf (Vite SPA, no RSC): one reveal helper for the hero image. */
function Reveal({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduce ? false : { opacity: 0, y: 24 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.3 }}
      transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.div>
  );
}

/** Ảnh sản phẩm thật (web/public/shots, chụp bằng scripts/landing-shots.mjs). */
function Shot({
  name,
  alt,
  testid,
  className,
}: {
  name: string;
  alt: string;
  testid: string;
  className?: string;
}) {
  return (
    <img
      src={`/shots/${name}.jpg`}
      alt={alt}
      data-testid={testid}
      loading="lazy"
      decoding="async"
      width={1280}
      height={800}
      className={`w-full rounded-card border border-border bg-surface shadow-card ${className ?? ""}`}
    />
  );
}

const HOW_STEPS = [
  {
    labelKey: "landing.how.s1.label",
    bodyKey: "landing.how.s1.body",
  },
  {
    labelKey: "landing.how.s2.label",
    bodyKey: "landing.how.s2.body",
  },
  {
    labelKey: "landing.how.s3.label",
    bodyKey: "landing.how.s3.body",
  },
];

/** "Sắp có" — gộp nội dung trang /features cũ vào Landing (roadmap). */
const ROADMAP = ["features.workers", "features.storage", "features.members"] as const;

const INPUT_FORMATS = ["JPG", "PNG", "WebP", "PDF"];

export default function Landing() {
  const reduce = useReducedMotion();
  const { t } = useT();
  return (
    <main id="main" data-testid="landing" className="mx-auto max-w-6xl px-4 pb-0">
      {/* Hero: split, clamp typography, motion entry. */}
      <section
        data-testid="landing-hero"
        className="grid items-center gap-10 pt-16 pb-16 md:grid-cols-[3fr_2fr] md:pt-24"
      >
        <motion.div
          initial={reduce ? false : { opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
        >
          <h1 className="text-[clamp(2rem,5vw,3.5rem)] font-bold leading-[1.15] tracking-tight">
            {t("landing.hero.title")}
          </h1>
          <p className="mt-5 max-w-[45ch] text-muted">
            {t("landing.hero.sub")}
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-4">
            <Link to="/signin" data-testid="landing-cta" className={buttonClasses("primary", "md")}>
              {t("landing.cta")}
            </Link>
            <a href="#how" className="text-accent-text hover:underline">
              {t("landing.howLink")}
            </a>
          </div>
        </motion.div>
        <Reveal>
          <Shot name="editor" testid="landing-mock" alt={t("landing.shot.editor")} />
        </Reveal>
      </section>

      {/* Ảnh thật: danh sách job + trang Văn bản (đối chiếu ảnh gốc / sửa lỗi OCR). */}
      <section data-testid="landing-preview" className="border-t border-border py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("landing.previewTitle")}
        </h2>
        <div className="mt-8 grid gap-6 md:grid-cols-2">
          <figure className="flex flex-col gap-2">
            <Shot name="jobs" testid="landing-shot-jobs" alt={t("landing.shot.jobs")} />
            <figcaption className="text-sm text-muted">{t("landing.shot.jobsCaption")}</figcaption>
          </figure>
          <figure className="flex flex-col gap-2">
            <Shot name="text" testid="landing-shot-text" alt={t("landing.shot.text")} />
            <figcaption className="text-sm text-muted">{t("landing.shot.textCaption")}</figcaption>
          </figure>
        </div>
      </section>

      {/* #how: pipeline OCR → IR → Layout, so numbered list, verb-noun labels. */}
      <section data-testid="landing-how" id="how" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">{t("landing.howTitle")}</h2>
        <ol className="mt-8 divide-y divide-border">
          {HOW_STEPS.map((step, i) => (
            <li key={step.labelKey} className="flex items-baseline gap-6 py-6">
              <span aria-hidden="true" className="text-3xl font-bold text-muted">
                {i + 1}
              </span>
              <div>
                <h3 className="text-lg font-semibold">{t(step.labelKey)}</h3>
                <p className="mt-1 max-w-[65ch] text-muted">{t(step.bodyKey)}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Roadmap "Sắp có": 3 hạng mục đang làm + dải định dạng hỗ trợ. */}
      <section data-testid="landing-roadmap" id="roadmap" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">{t("landing.roadmapTitle")}</h2>
        <ul className="mt-8 grid gap-4 md:grid-cols-3">
          {ROADMAP.map((key) => (
            <li
              key={key}
              data-testid="roadmap-item"
              className="rounded-card border border-border bg-surface p-5"
            >
              <h3 className="text-lg font-semibold">{t(`${key}.title`)}</h3>
              <p className="mt-1 text-muted">{t(`${key}.desc`)}</p>
            </li>
          ))}
        </ul>
        <div data-testid="landing-formats" className="mt-10 space-y-4">
          <h3 className="text-lg font-semibold">{t("landing.formatsTitle")}</h3>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{t("landing.inputLabel")}</span>
            {INPUT_FORMATS.map((fmt) => (
              <Badge key={fmt} tone="neutral">
                {fmt}
              </Badge>
            ))}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">{t("landing.outputLabel")}</span>
            {["MD", "HTML", "DOCX", "PDF"].map((fmt) => (
              <Badge key={fmt} tone="info">
                {fmt}
              </Badge>
            ))}
          </div>
          <p className="text-muted">{t("landing.colab")}</p>
        </div>
      </section>

      {/* Final CTA: same label "Bắt đầu" (one signup intent, one label). */}
      <section className="py-16 text-center md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {t("landing.finalTitle")}
        </h2>
        <div className="mt-8">
          <Link to="/signin" className={buttonClasses("primary", "md")}>
            {t("landing.cta")}
          </Link>
        </div>
      </section>

    </main>
  );
}
