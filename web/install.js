// The page a browser tab shows instead of the app: what BGU cats is for,
// how it is used, and how to install it on the device in hand — in Hebrew,
// English, Russian and Arabic.
//
// The app runs only installed. A tab can be closed with photos still in its
// outbox, its storage can be evicted, and on iPhone a tab and the installed
// app do not even share it; an installed app keeps all three. This is a
// front door, not a lock — the API checks every sign-in on every call.
//
// "?browser" opens the app in a tab anyway, for the rare case the installed
// app cannot sign in on some phone. It lasts until the tab is closed.

const LANG_KEY = "bgucats.lang"; // the same key the landing page uses
const BROWSER_KEY = "bgucats.browser";
const LANGS = ["he", "en", "ru", "ar"];
const RTL = new Set(["he", "ar"]);

// **…** marks the app's own button names, which stay in English: they are
// what people will see on screen. {share} is the share icon.
const T = {
  en: {
    name: "English",
    short: "EN",
    langLabel: "Language",
    tagline: "Photograph the campus cats, and give them names",
    lede:
      "The app for the people who photograph the cats of Ben-Gurion University. " +
      "Every photo helps tell the cats apart, and builds the catalogue that will one day " +
      "recognise each cat by its face.",
    jump: "Install the app",
    whatTitle: "What it's for",
    what: [
      "Photograph a cat when you meet one — photos and short videos.",
      "The place is saved too, rounded to about 100 m. Cats keep to their own corner of campus, and that helps tell them apart.",
      "Browse every cat already in the catalogue.",
    ],
    howTitle: "How to use it",
    how: [
      "Met a cat? Tap **Start an encounter**.",
      "Photograph just that cat from different sides — face, side, back — or film a slow 5–10 second video around it.",
      "Tap **Done — next cat**. One encounter is one cat.",
      "No signal? Keep going. Photos wait on your phone and upload by themselves.",
    ],
    installTitle: "Install the app",
    installLede:
      "BGU cats works only as an app on your home screen, so photos are never lost when a browser tab closes.",
    button: "Install BGU cats",
    installed: "Installed. Open BGU cats from your home screen.",
    platforms: { ios: "iPhone and iPad", android: "Android", desktop: "Computer" },
    steps: {
      ios: [
        "Open this page in Safari (or Chrome).",
        "Tap Share {share} — at the bottom in Safari, at the top in Chrome.",
        "Choose **Add to Home Screen**, then **Add**.",
        "Open BGU cats from your home screen and sign in.",
      ],
      android: [
        "Open this page in Chrome.",
        "Tap the menu ⋮, then **Install app** (or **Add to Home screen**).",
        "Open BGU cats from your home screen and sign in.",
      ],
      desktop: [
        "In Chrome or Edge, click the install icon at the end of the address bar — or the button above.",
        "In Safari on a Mac: **File → Add to Dock**.",
        "Firefox can't install apps; use Chrome or Edge.",
      ],
    },
    inApp:
      "Opened from Telegram, WhatsApp or Instagram? Apps can't be installed from there. Open this page in Safari or Chrome first: tap ⋯ and choose Open in browser.",
    copy: "Copy the link",
    copied: "Link copied",
    other: "Other phones and computers",
    invite: "By invitation only: sign in with the Google account you were invited with.",
  },

  he: {
    name: "עברית",
    short: "עב",
    langLabel: "שפה",
    tagline: "מצלמים את חתולי הקמפוס ונותנים להם שם",
    lede:
      "האפליקציה של מי שמצלם את החתולים של אוניברסיטת בן־גוריון. " +
      "כל תמונה עוזרת להבחין בין החתולים ובונה את הקטלוג, שיום אחד יזהה כל חתול לפי הפנים שלו.",
    jump: "התקנת האפליקציה",
    whatTitle: "בשביל מה זה",
    what: [
      "מצלמים חתול כשפוגשים אותו — תמונות וסרטונים קצרים.",
      "גם המקום נשמר, בעיגול של כ־100 מטר. לכל חתול יש פינה משלו בקמפוס, וזה עוזר להבדיל ביניהם.",
      "אפשר לדפדף בכל החתולים שכבר בקטלוג.",
    ],
    howTitle: "איך משתמשים",
    how: [
      "פגשתם חתול? הקישו על **Start an encounter**.",
      "צלמו רק את החתול הזה מכמה צדדים — פנים, צד, גב — או צלמו סרטון איטי של 5 עד 10 שניות מסביבו.",
      "הקישו על **Done — next cat**. מפגש אחד = חתול אחד.",
      "אין קליטה? ממשיכים לצלם. התמונות מחכות בטלפון ועולות לבד.",
    ],
    installTitle: "התקנת האפליקציה",
    installLede:
      "BGU cats עובדת רק כאפליקציה במסך הבית, כדי שתמונות לא ילכו לאיבוד כשסוגרים לשונית בדפדפן.",
    button: "התקנת BGU cats",
    installed: "הותקנה. פתחו את BGU cats ממסך הבית.",
    platforms: { ios: "iPhone ו־iPad", android: "אנדרואיד", desktop: "מחשב" },
    steps: {
      ios: [
        "פתחו את הדף הזה ב־Safari (או ב־Chrome).",
        "הקישו על שיתוף {share} — למטה ב־Safari, למעלה ב־Chrome.",
        "בחרו **הוספה למסך הבית** ואז **הוסף**.",
        "פתחו את BGU cats ממסך הבית והתחברו.",
      ],
      android: [
        "פתחו את הדף הזה ב־Chrome.",
        "הקישו על התפריט ⋮ ואז על **התקנת אפליקציה** (או **הוספה למסך הבית**).",
        "פתחו את BGU cats ממסך הבית והתחברו.",
      ],
      desktop: [
        "ב־Chrome או ב־Edge: לחצו על סמל ההתקנה בקצה שורת הכתובת — או על הכפתור למעלה.",
        "ב־Safari במק: **File ← Add to Dock**.",
        "ב־Firefox אי אפשר להתקין אפליקציות; השתמשו ב־Chrome או ב־Edge.",
      ],
    },
    inApp:
      "פתחתם מטלגרם, מוואטסאפ או מאינסטגרם? משם אי אפשר להתקין אפליקציות. פתחו קודם את הדף ב־Safari או ב־Chrome: הקישו על ⋯ ובחרו „פתיחה בדפדפן”.",
    copy: "העתקת הקישור",
    copied: "הקישור הועתק",
    other: "טלפונים ומחשבים אחרים",
    invite: "בהזמנה בלבד: מתחברים עם חשבון ה־Google שאליו נשלחה ההזמנה.",
  },

  ru: {
    name: "Русский",
    short: "RU",
    langLabel: "Язык",
    tagline: "Фотографируем котов кампуса и даём им имена",
    lede:
      "Приложение для тех, кто фотографирует котов Университета имени Бен-Гуриона. " +
      "Каждое фото помогает различать котов и пополняет каталог, который однажды будет узнавать каждого кота в лицо.",
    jump: "Установить приложение",
    whatTitle: "Зачем это",
    what: [
      "Фотографируйте кота, когда встретите его, — фото и короткие видео.",
      "Место тоже сохраняется, с точностью около 100 м. У каждого кота свой уголок кампуса, и это помогает их различать.",
      "Можно посмотреть всех котов, которые уже есть в каталоге.",
    ],
    howTitle: "Как пользоваться",
    how: [
      "Встретили кота? Нажмите **Start an encounter**.",
      "Снимите только этого кота с разных сторон — морду, бок, спину — или снимите медленное видео на 5–10 секунд, обходя его.",
      "Нажмите **Done — next cat**. Одна встреча — один кот.",
      "Нет сигнала? Продолжайте. Фото ждут в телефоне и загрузятся сами.",
    ],
    installTitle: "Установка приложения",
    installLede:
      "BGU cats работает только как приложение на главном экране — так фото не пропадут, если закрыть вкладку браузера.",
    button: "Установить BGU cats",
    installed: "Установлено. Откройте BGU cats с главного экрана.",
    platforms: { ios: "iPhone и iPad", android: "Android", desktop: "Компьютер" },
    steps: {
      ios: [
        "Откройте эту страницу в Safari (или в Chrome).",
        "Нажмите «Поделиться» {share} — внизу в Safari, вверху в Chrome.",
        "Выберите **На экран «Домой»**, затем **Добавить**.",
        "Откройте BGU cats с главного экрана и войдите.",
      ],
      android: [
        "Откройте эту страницу в Chrome.",
        "Нажмите меню ⋮, затем **Установить приложение** (или **Добавить на главный экран**).",
        "Откройте BGU cats с главного экрана и войдите.",
      ],
      desktop: [
        "В Chrome или Edge нажмите значок установки в конце адресной строки — или кнопку выше.",
        "В Safari на Mac: **Файл → Добавить в Dock**.",
        "Firefox не умеет устанавливать приложения — используйте Chrome или Edge.",
      ],
    },
    inApp:
      "Открыли из Telegram, WhatsApp или Instagram? Оттуда приложение не установить. Сначала откройте страницу в Safari или Chrome: нажмите ⋯ и выберите «Открыть в браузере».",
    copy: "Скопировать ссылку",
    copied: "Ссылка скопирована",
    other: "Другие телефоны и компьютеры",
    invite: "Только по приглашению: входите через аккаунт Google, на который пришло приглашение.",
  },

  ar: {
    name: "العربية",
    short: "ع",
    langLabel: "اللغة",
    tagline: "نصوّر قطط الحرم الجامعي ونمنحها أسماء",
    lede:
      "تطبيق لمن يصوّرون قطط جامعة بن غوريون. " +
      "كل صورة تساعد على التمييز بين القطط، وتبني الدليل الذي سيتعرّف يومًا ما على كل قطة من وجهها.",
    jump: "تثبيت التطبيق",
    whatTitle: "ما فائدته",
    what: [
      "صوّر القطة عندما تلتقي بها — صورًا ومقاطع فيديو قصيرة.",
      "يُحفظ المكان أيضًا، مقرّبًا إلى نحو 100 متر. لكل قطة ركنها الخاص في الحرم الجامعي، وهذا يساعد على التمييز بينها.",
      "تصفّح كل القطط الموجودة في الدليل.",
    ],
    howTitle: "طريقة الاستخدام",
    how: [
      "التقيت بقطة؟ اضغط **Start an encounter**.",
      "صوّر هذه القطة وحدها من جهات مختلفة — الوجه والجانب والظهر — أو صوّر فيديو بطيئًا مدته من 5 إلى 10 ثوانٍ وأنت تدور حولها.",
      "اضغط **Done — next cat**. لقاء واحد = قطة واحدة.",
      "لا توجد تغطية؟ تابع التصوير. تنتظر الصور في هاتفك وتُرفع تلقائيًا.",
    ],
    installTitle: "تثبيت التطبيق",
    installLede:
      "يعمل BGU cats فقط كتطبيق على الشاشة الرئيسية، حتى لا تضيع الصور عند إغلاق علامة تبويب في المتصفح.",
    button: "تثبيت BGU cats",
    installed: "تم التثبيت. افتح BGU cats من الشاشة الرئيسية.",
    platforms: { ios: "iPhone وiPad", android: "Android", desktop: "حاسوب" },
    steps: {
      ios: [
        "افتح هذه الصفحة في Safari (أو في Chrome).",
        "اضغط زر المشاركة {share} — في الأسفل في Safari، وفي الأعلى في Chrome.",
        "اختر **إضافة إلى الشاشة الرئيسية** ثم **إضافة**.",
        "افتح BGU cats من الشاشة الرئيسية وسجّل الدخول.",
      ],
      android: [
        "افتح هذه الصفحة في Chrome.",
        "اضغط على القائمة ⋮ ثم **تثبيت التطبيق** (أو **إضافة إلى الشاشة الرئيسية**).",
        "افتح BGU cats من الشاشة الرئيسية وسجّل الدخول.",
      ],
      desktop: [
        "في Chrome أو Edge: انقر رمز التثبيت في طرف شريط العنوان — أو الزر أعلاه.",
        "في Safari على Mac: **File ← Add to Dock**.",
        "لا يدعم Firefox تثبيت التطبيقات؛ استخدم Chrome أو Edge.",
      ],
    },
    inApp:
      "فتحت الصفحة من Telegram أو WhatsApp أو Instagram؟ لا يمكن تثبيت التطبيقات من هناك. افتح الصفحة أولًا في Safari أو Chrome: اضغط ⋯ واختر «فتح في المتصفح».",
    copy: "نسخ الرابط",
    copied: "تم نسخ الرابط",
    other: "هواتف وحواسيب أخرى",
    invite: "بالدعوة فقط: سجّل الدخول بحساب Google الذي وصلتك عليه الدعوة.",
  },
};

// --------------------------------------------------------------------------
// Installed or not
// --------------------------------------------------------------------------

export function isInstalled() {
  const modes = ["standalone", "fullscreen", "minimal-ui", "window-controls-overlay"];
  if (modes.some((mode) => matchMedia(`(display-mode: ${mode})`).matches)) return true;
  if (navigator.standalone === true) return true; // iOS before display-mode support
  return browserOverride();
}

function browserOverride() {
  try {
    if (new URLSearchParams(location.search).has("browser")) sessionStorage.setItem(BROWSER_KEY, "1");
    return sessionStorage.getItem(BROWSER_KEY) === "1";
  } catch {
    return false;
  }
}

// Chrome and Edge offer their own install prompt; it is kept for the button
// rather than shown as Chrome's bottom bar. Safari has no such event.
let installPrompt = null;
let justInstalled = false;
let redraw = null;
addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  redraw?.();
});
addEventListener("appinstalled", () => {
  installPrompt = null;
  justInstalled = true;
  redraw?.();
});

function platform() {
  const ua = navigator.userAgent;
  if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "ios";
  if (/Android/.test(ua)) return "android";
  return "desktop";
}

// The in-app browsers of chat and social apps cannot install anything.
const inAppBrowser = () => /FBAN|FBAV|FB_IAB|Instagram|Line\/|Telegram|WhatsApp|; wv\)/.test(navigator.userAgent);

function pickLang() {
  const pick = (code) => {
    code = (code || "").toLowerCase();
    if (code.startsWith("iw")) return "he";
    return LANGS.find((lang) => code.startsWith(lang));
  };
  let saved = null;
  try {
    saved = localStorage.getItem(LANG_KEY);
  } catch {
    /* private mode — fall through to the browser's languages */
  }
  return pick(saved) || (navigator.languages || [navigator.language]).map(pick).find(Boolean) || "he";
}

// --------------------------------------------------------------------------
// The page
// --------------------------------------------------------------------------

const el = (tag, props = {}, kids = []) => {
  const { attrs, ...rest } = props;
  const node = Object.assign(document.createElement(tag), rest);
  for (const [name, value] of Object.entries(attrs || {})) node.setAttribute(name, value);
  for (const kid of [].concat(kids)) if (kid != null && kid !== false) node.append(kid);
  return node;
};

const SVG_NS = "http://www.w3.org/2000/svg";
function svg(symbolOrPath, className, viewBox) {
  const node = document.createElementNS(SVG_NS, "svg");
  node.setAttribute("class", className);
  node.setAttribute("aria-hidden", "true");
  if (viewBox) {
    node.setAttribute("viewBox", viewBox);
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", symbolOrPath);
    node.append(path);
  } else {
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", `#${symbolOrPath}`);
    node.append(use);
  }
  return node;
}

// iOS's share glyph: a box with an arrow out of the top.
const shareIcon = () => svg("M12 3v12M8 7l4-4 4 4M7 11H5v10h14V11h-2", "share-icon", "0 0 24 24");

// "**bold**" and "{share}" in a translated string, as DOM nodes — never as
// HTML, so a translation can't inject markup.
function rich(text) {
  const nodes = [];
  for (const [i, part] of text.split("**").entries()) {
    const pieces = part.split("{share}");
    pieces.forEach((piece, j) => {
      // dir="auto" isolates a bold run, so an English button name inside a
      // Hebrew or Arabic sentence keeps its full stop where it belongs.
      if (piece) nodes.push(i % 2 ? el("b", { textContent: piece, dir: "auto" }) : piece);
      if (j < pieces.length - 1) nodes.push(shareIcon());
    });
  }
  return nodes;
}

export function showInstallPage() {
  const root = document.querySelector("#install");
  let lang = pickLang();

  function draw() {
    const t = T[lang];
    root.lang = lang;
    root.dir = RTL.has(lang) ? "rtl" : "ltr";
    document.documentElement.lang = lang;
    document.title = "BGU cats";

    const langs = el(
      "div",
      { className: "langs", attrs: { role: "group", "aria-label": t.langLabel } },
      LANGS.map((code) => {
        const b = el("button", {
          type: "button",
          lang: code,
          title: T[code].name,
          textContent: T[code].short,
          attrs: { "aria-pressed": String(code === lang) },
        });
        b.onclick = () => {
          lang = code;
          try {
            localStorage.setItem(LANG_KEY, code);
          } catch {
            /* not remembered — fine */
          }
          draw();
        };
        return b;
      }),
    );

    const here = platform();
    const others = ["ios", "android", "desktop"].filter((p) => p !== here);
    const steps = (p) =>
      el("div", { className: "install-platform" }, [
        el("h4", { textContent: t.platforms[p] }),
        el("ol", { className: "install-steps" }, t.steps[p].map((s) => el("li", {}, rich(s)))),
      ]);

    const action = justInstalled
      ? el("p", { className: "install-done", textContent: t.installed })
      : installPrompt
        ? el("button", {
            type: "button",
            className: "btn btn-primary btn-lg",
            textContent: t.button,
            onclick: async () => {
              const prompt = installPrompt;
              installPrompt = null;
              await prompt.prompt();
              const { outcome } = await prompt.userChoice;
              if (outcome === "accepted") justInstalled = true;
              draw();
            },
          })
        : null;

    const copy = el("button", { type: "button", className: "btn btn-sm", textContent: t.copy });
    copy.onclick = async () => {
      try {
        await navigator.clipboard.writeText(location.origin + "/");
        copy.textContent = t.copied;
      } catch {
        /* the address bar still has it */
      }
    };

    root.replaceChildren(
      el("div", { className: "install-wrap" }, [
        el("header", { className: "install-top" }, [
          el("div", { className: "brand", attrs: { dir: "ltr" } }, [
            svg("cat-midnight", "doodle brand-mark"),
            el("span", { textContent: "BGU cats" }),
          ]),
          langs,
        ]),

        el("section", { className: "install-hero" }, [
          el("div", { className: "lineup", attrs: { "aria-hidden": "true" } }, [
            svg("cat-ginger", "doodle"),
            svg("cat-tuxedo", "doodle"),
            svg("cat-calico", "doodle"),
            svg("cat-grump", "doodle"),
          ]),
          el("h1", { textContent: t.tagline }),
          el("p", { className: "install-lede", textContent: t.lede }),
          el("a", { className: "btn btn-primary btn-lg", href: "#install-now", textContent: t.jump }),
        ]),

        el("div", { className: "install-grid" }, [
          el("section", { className: "card install-card" }, [
            el("h2", { textContent: t.whatTitle }),
            el("ul", { className: "install-what" }, t.what.map((s) => el("li", {}, rich(s)))),
          ]),
          el("section", { className: "card install-card" }, [
            el("h2", { textContent: t.howTitle }),
            el("ol", { className: "install-how" }, t.how.map((s) => el("li", {}, rich(s)))),
          ]),
        ]),

        el("section", { className: "card install-card install-now", id: "install-now" }, [
          el("h2", { textContent: t.installTitle }),
          el("p", { className: "install-lede", textContent: t.installLede }),
          inAppBrowser() ? el("p", { className: "callout" }, [t.inApp, " ", copy]) : null,
          action,
          steps(here),
          el("details", { className: "install-other" }, [
            el("summary", { textContent: t.other }),
            ...others.map(steps),
          ]),
        ]),

        el("p", { className: "install-invite", textContent: t.invite }),
      ]),
    );
  }

  redraw = draw;
  draw();
  root.hidden = false;
  document.querySelector("#login").hidden = true;
  document.querySelector("#app").hidden = true;
}
