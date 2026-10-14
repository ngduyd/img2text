import { ApiError } from "../api/client";
import { translate } from "../i18n";

/** R59: deterministic error→message mapping for every mutation toast + inline error.
 *  Spec S2: server {code, params} (S1/S5) → dict key errors.<code>; fallback = raw detail. */
export function mapApiError(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.code && translate(`errors.${e.code}`) !== `errors.${e.code}`)
      return translate(`errors.${e.code}`, e.params);
    return e.detail;
  }
  if (e instanceof TypeError || String(e).includes("fetch failed"))
    return translate("errors.network");
  return String(e instanceof Error ? e.message : e);
}
