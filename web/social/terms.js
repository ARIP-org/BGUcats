// The terms come before anything a person writes for others to read: a
// post, a new cat, a name. Asked once, where the first such write happens.

import { post } from "../lib/api.js";
import { t } from "./i18n.js";
import { get, set } from "./store.js";
import { confirm } from "./ui.js";

// -> true once the current terms are accepted; false if the person said no.
export async function termsFirst() {
  const me = get().me;
  if (!me?.terms?.required) return true;
  const yes = await confirm({
    title: t("terms.title"),
    body: t("terms.body"),
    button: t("terms.accept"),
  });
  if (!yes) return false;
  const answer = await post("/v1/me/terms", { version: me.terms.current });
  set({ me: { ...me, ...answer } });
  return true;
}
