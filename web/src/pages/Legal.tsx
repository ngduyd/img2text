import Card from "../components/ui/Card";
import PageHeader from "../components/PageHeader";
import PageShell from "../components/PageShell";
import { useT } from "../i18n";

/** Spec 2026-11-04 (A1/A5): /legal — route CÔNG KHAI (không cần đăng nhập,
 *  ngoài VerifyGate) để user đọc trước khi tick đồng ý ở signup. */
const SECTIONS = ["service", "data", "responsibilities", "rights"] as const;

export default function Legal() {
  const { t } = useT();
  return (
    <PageShell width="form">
      <PageHeader title={t("legal.title")} subtitle={t("legal.subtitle")} />
      <Card testid="card-legal">
        <div className="flex flex-col gap-6">
          {SECTIONS.map((key) => (
            <section key={key} data-testid={`legal-${key}`} className="flex flex-col gap-2">
              <h2 className="text-lg font-semibold">{t(`legal.${key}.title`)}</h2>
              <p className="text-sm leading-relaxed text-muted">{t(`legal.${key}.body`)}</p>
            </section>
          ))}
        </div>
      </Card>
    </PageShell>
  );
}
