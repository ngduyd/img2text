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

type Feature = {
  titleKey: string;
  bodyKey: string;
  className?: string;
};

const FEATURES: Feature[] = [
  {
    titleKey: "landing.features.f1.title",
    bodyKey: "landing.features.f1.body",
    className: "md:col-span-2",
  },
  {
    titleKey: "landing.features.f2.title",
    bodyKey: "landing.features.f2.body",
    className: "bg-accent/10 border-accent/30",
  },
  {
    titleKey: "landing.features.f3.title",
    bodyKey: "landing.features.f3.body",
  },
  {
    titleKey: "landing.features.f4.title",
    bodyKey: "landing.features.f4.body",
  },
  {
    titleKey: "landing.features.f5.title",
    bodyKey: "landing.features.f5.body",
  },
];

const INPUT_FORMATS = ["JPG", "PNG", "WebP", "PDF"];

/**
 * 6 slot ảnh thật (spec §User-facing #8): hero, login, jobdetail 2 section,
 * layout preview, export, admin. File chưa capture → onError placeholder.
 */
const GALLERY = [
  {
    src: "/screenshots/landing-hero.png",
    altKey: "landing.gallery.g1.alt",
    captionKey: "landing.gallery.g1.caption",
  },
  {
    src: "/screenshots/login.png",
    altKey: "landing.gallery.g2.alt",
    captionKey: "landing.gallery.g2.caption",
  },
  {
    src: "/screenshots/jobdetail.png",
    altKey: "landing.gallery.g3.alt",
    captionKey: "landing.gallery.g3.caption",
  },
  {
    src: "/screenshots/layout-preview.png",
    altKey: "landing.gallery.g4.alt",
    captionKey: "landing.gallery.g4.caption",
  },
  {
    src: "/screenshots/export-menu.png",
    altKey: "landing.gallery.g5.alt",
    captionKey: "landing.gallery.g5.caption",
  },
  {
    src: "/screenshots/admin-users.png",
    altKey: "landing.gallery.g6.alt",
    captionKey: "landing.gallery.g6.caption",
  },
];

export default function Landing() {
  const reduce = useReducedMotion();
  const { t } = useT();
  return (
    <main id="main" data-testid="landing" className="mx-auto max-w-6xl px-4 pb-0">
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
          <Shot
            src="/screenshots/landing-hero.png"
            alt={t("landing.hero.alt")}
            caption={t("landing.hero.caption")}
          />
        </Reveal>
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

      {/* Features: bento, exactly 5 cells, 2-span + tinted cell for rhythm. */}
      <section data-testid="landing-features" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">{t("landing.featuresTitle")}</h2>
        <div className="mt-8 grid gap-4 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div
              key={f.titleKey}
              data-testid="feature-cell"
              className={`rounded-card border border-border bg-surface p-5 ${f.className ?? ""}`}
            >
              <h3 className="text-lg font-semibold">{t(f.titleKey)}</h3>
              <p className="mt-1 text-muted">{t(f.bodyKey)}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Formats strip: nhận vào / xuất ra + Colab. */}
      <section data-testid="landing-formats" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">{t("landing.formatsTitle")}</h2>
        <div className="mt-8 space-y-4">
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

      {/* Gallery: real screenshots (placeholder-friendly khi anh chua chup). */}
      <section data-testid="landing-gallery" className="py-16 md:py-24">
        <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">{t("landing.galleryTitle")}</h2>
        <div className="mt-8 grid gap-6 sm:grid-cols-2">
          {GALLERY.map((shot) => (
            <Shot key={shot.src} src={shot.src} alt={t(shot.altKey)} caption={t(shot.captionKey)} />
          ))}
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
