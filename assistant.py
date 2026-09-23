"""What a message means, and what to do about it — with no model at all.

The chat used to answer every sentence that was not a slash command with
a template: *"Happy to help! I received your request."* That is a
placeholder wearing a greeting. This module is the replacement's floor:
a rules-based understander that turns a sentence in English or Arabic
into one of a small, typed set of actions, and an executor for the
actions that need nothing but the Agent itself.

The contract is one dict, an **intent**:

    {"action": "remember", "arguments": {"information": "…"},
     "reply": None, "source": "rules"}

`server/assistant.py` produces the same dict from a language model when
one is configured, and runs the actions that need the run engine. Both
paths meet at the same executor, so what an action *does* never depends
on who understood the sentence.

Standard library only, because the command-line interface uses it too.
"""

import re

# The whole vocabulary. An action the model names that is not here is
# refused, not improvised; an argument it names that is not listed is
# dropped. Small on purpose: a person can read this and know exactly
# what a sentence can cause.
ACTIONS = {
    "chat": (),
    "help": (),
    "remember": ("information", "category"),
    "recall": ("query",),
    "forget": ("key",),
    "clear_history": (),
    "set_preference": ("key", "value"),
    "start_run": ("goal", "dataset"),
    "run_status": ("run_id",),
    "explain_report": ("section", "run_id"),
}
# These delete something. Whoever understood the sentence — rules or
# model — the system asks first, and only a "yes" in the next message
# executes. The UI's own controls confirm too; the chat is not a way
# around that.
DESTRUCTIVE = {"forget", "clear_history"}
# These need the run engine, which the command-line interface does not have.
SERVER_ONLY = {"start_run", "run_status", "explain_report"}
PREFERENCE_KEYS = ("tone", "language", "user_name", "save_history")
TONES = ("friendly", "concise", "formal")
SECTIONS = ("descriptive", "diagnostic", "experiment", "predictive", "prescriptive")

YES_WORDS = {
    "yes", "y", "yeah", "yep", "yup", "sure", "confirm", "confirmed", "do it",
    "go ahead", "ok", "okay", "please do", "proceed", "affirmative",
    "نعم", "أيوه", "ايوه", "أيوة", "ايوة", "اه", "آه", "أكيد", "اكيد", "تمام",
    "موافق", "موافقة", "نفذ", "نفّذ", "اعمل", "أكد", "أؤكد", "طبعا", "طبعًا",
}
NO_WORDS = {
    "no", "n", "nope", "cancel", "don't", "dont", "do not", "stop", "never mind",
    "nevermind", "leave it", "forget it", "negative",
    "لا", "لأ", "لاء", "إلغاء", "الغاء", "بلاش", "خلاص", "مش عايز", "لا تفعل",
    "توقف", "الغي", "ألغِ", "ألغي", "اتركه", "سيبه",
}

TONE_WORDS = {
    "concise": ("concise", "brief", "briefer", "short", "shorter", "terse",
                "مختصر", "مختصرة", "موجز", "موجزة", "باختصار", "قصير", "قصيرة"),
    "formal": ("formal", "formally", "professional",
               "رسمي", "رسمية", "رسميا", "رسميًا", "بشكل رسمي"),
    "friendly": ("friendly", "casual", "warm", "relaxed", "informal",
                 "ودود", "ودي", "ودية", "لطيف", "لطيفة", "بشكل ودي"),
}
LANGUAGE_WORDS = {
    "Arabic": ("arabic", "بالعربي", "بالعربية", "العربية", "عربي", "عربى"),
    "English": ("english", "بالإنجليزي", "بالانجليزي", "بالإنجليزية",
                "بالانجليزية", "الإنجليزية", "الانجليزية", "انجليزي", "إنجليزي"),
}

# The assistant's own sentences. The Agent's catalogue (agent.py) covers
# the slash commands; these cover understanding, confirmation and the
# actions only the assistant can take. Same rule as everywhere: the
# reply is in the language the person chose, and English is the fallback.
REPLIES = {
    "en": {
        "fallback_friendly":
            "Happy to help! I'm not sure what you'd like me to do with "
            "“{request}”. I can analyse a dataset, remember something, show "
            "what I remember, change how I reply, or explain the latest "
            "report — for example: “analyse the sample sales data” or "
            "“remember that the Q4 review is on Monday”.",
        "fallback_concise":
            "Not sure what to do with “{request}”. Try: analyse the sample "
            "sales data · remember that … · what do you remember? · explain "
            "the latest report.",
        "fallback_formal":
            "Your request “{request}” was not understood. The following are "
            "supported: analysing a dataset, saving and recalling "
            "information, changing reply preferences, and explaining the "
            "latest report.",
        "capabilities":
            "Here is what I can do:\n"
            "• Analyse a dataset — “analyse the sample sales data”, or name "
            "a dataset you have uploaded\n"
            "• Remember things — “remember that the Q4 review is on Monday”\n"
            "• Show what I remember — “what do you remember?”\n"
            "• Explain the latest report — “why did revenue move?”, “what "
            "should we do?”\n"
            "• Change how I reply — “be concise”, “reply in Arabic”, “call "
            "me Ahmad”\n"
            "Slash commands still work; /help lists them.",
        "confirm_forget_all":
            "This will permanently delete everything I remember. Reply "
            "“yes” to confirm or “no” to keep it.",
        "confirm_forget_key":
            "This will permanently delete {key}: “{text}”. Reply “yes” to "
            "confirm or “no” to keep it.",
        "confirm_clear_history":
            "This will clear this session's conversation history (saved "
            "memory is not affected). Reply “yes” to confirm or “no” to "
            "keep it.",
        "cancelled": "Nothing was changed.",
        "recall_none_match": "Nothing I remember mentions “{query}”.",
        "bad_tone":
            "I can reply in a friendly, concise, or formal tone — which "
            "would you like?",
        "unknown_preference":
            "I can change the tone, the language, your name, or whether "
            "history is recorded.",
        "cli_needs_web":
            "Analytics runs need the web interface: start it with "
            "`python scripts/serve.py` and ask there.",
        "run_started":
            "Started analysis {run_id} on {dataset}: “{goal}”. It is open in "
            "Runs — the pipeline advances while that view is open, and "
            "publishing waits for your approval.",
        "run_status":
            "Analysis {run_id} (“{goal}”) is {state}: {done} of {total} "
            "steps done{approval}.",
        "run_status_approval": " — waiting for your approval to publish",
        "no_runs":
            "There is no analysis yet. Say “analyse the sample sales data” "
            "to start one.",
        "no_report_yet":
            "Analysis {run_id} has not produced a report yet — it is "
            "{state}.",
        "report_intro": "From analysis {run_id} (“{goal}”):",
        "report_outro": "The full report, with every calculation, is in Runs.",
        "dataset_sample": "the sample sales dataset",
    },
    "ar": {
        "fallback_friendly":
            "يسعدني المساعدة! لم أفهم ما تريده من «{request}». أستطيع تحليل "
            "مجموعة بيانات، أو حفظ معلومة، أو عرض ما أتذكره، أو تغيير طريقة "
            "ردي، أو شرح آخر تقرير — مثلًا: «حلّل بيانات المبيعات النموذجية» "
            "أو «تذكّر أن مراجعة الربع الرابع يوم الاثنين».",
        "fallback_concise":
            "لم أفهم «{request}». جرّب: حلّل بيانات المبيعات النموذجية · "
            "تذكّر أن … · ماذا تتذكر؟ · اشرح آخر تقرير.",
        "fallback_formal":
            "لم يُفهم طلبك «{request}». المدعوم: تحليل مجموعة بيانات، وحفظ "
            "المعلومات واستدعاؤها، وتغيير تفضيلات الرد، وشرح آخر تقرير.",
        "capabilities":
            "هذا ما أستطيع فعله:\n"
            "• تحليل مجموعة بيانات — «حلّل بيانات المبيعات النموذجية»، أو "
            "اذكر اسم مجموعة رفعتها\n"
            "• حفظ المعلومات — «تذكّر أن مراجعة الربع الرابع يوم الاثنين»\n"
            "• عرض ما أتذكره — «ماذا تتذكر؟»\n"
            "• شرح آخر تقرير — «لماذا تغيّرت الإيرادات؟»، «ماذا ينبغي أن "
            "نفعل؟»\n"
            "• تغيير طريقة ردي — «خليك مختصر»، «رد بالإنجليزي»، «ناديني أحمد»\n"
            "أوامر الشرطة المائلة ما زالت تعمل؛ ‎/help يعرضها.",
        "confirm_forget_all":
            "سيُحذف كل ما أتذكره نهائيًا. أجب بـ«نعم» للتأكيد أو «لا» للإبقاء "
            "عليه.",
        "confirm_forget_key":
            "سيُحذف {key} نهائيًا: «{text}». أجب بـ«نعم» للتأكيد أو «لا» "
            "للإبقاء عليه.",
        "confirm_clear_history":
            "سيُمسح سجل محادثة هذه الجلسة (لن تتأثر الذاكرة المحفوظة). أجب "
            "بـ«نعم» للتأكيد أو «لا» للإبقاء عليه.",
        "cancelled": "لم يتغيّر شيء.",
        "recall_none_match": "لا شيء مما أتذكره يذكر «{query}».",
        "bad_tone": "أستطيع الرد بأسلوب ودود أو موجز أو رسمي — أيها تفضّل؟",
        "unknown_preference":
            "أستطيع تغيير الأسلوب، أو اللغة، أو اسمك، أو تسجيل السجل.",
        "cli_needs_web":
            "عمليات التحليل تحتاج واجهة الويب: شغّلها بـ "
            "`python scripts/serve.py` واطلب منها هناك.",
        "run_started":
            "بدأت التحليل {run_id} على {dataset}: «{goal}». مفتوح في "
            "التحليلات — يتقدّم خط المعالجة أثناء فتح تلك الشاشة، والنشر "
            "ينتظر موافقتك.",
        "run_status":
            "التحليل {run_id} («{goal}») {state}: اكتملت {done} من {total} "
            "خطوات{approval}.",
        "run_status_approval": " — بانتظار موافقتك على النشر",
        "no_runs":
            "لا يوجد تحليل بعد. قل «حلّل بيانات المبيعات النموذجية» لبدء "
            "واحد.",
        "no_report_yet": "التحليل {run_id} لم يُنتج تقريرًا بعد — حالته {state}.",
        "report_intro": "من التحليل {run_id} («{goal}»):",
        "report_outro": "التقرير الكامل، بكل حساباته، في التحليلات.",
        "dataset_sample": "مجموعة بيانات المبيعات النموذجية",
    },
}

RUN_STATES = {
    "en": {"queued": "queued", "running": "running",
           "awaiting_approval": "waiting for approval", "completed": "completed",
           "partially_completed": "partially completed", "failed": "failed",
           "cancelled": "cancelled"},
    "ar": {"queued": "في الانتظار", "running": "قيد التنفيذ",
           "awaiting_approval": "بانتظار الموافقة", "completed": "مكتمل",
           "partially_completed": "مكتمل جزئيًا", "failed": "فشل",
           "cancelled": "أُلغي"},
}

SECTION_QUESTIONS = {
    "en": {"descriptive": "What happened?", "diagnostic": "Why did it happen?",
           "experiment": "Can we claim a cause?", "predictive": "What will happen?",
           "prescriptive": "What should I do?"},
    "ar": {"descriptive": "ماذا حدث؟", "diagnostic": "لماذا حدث؟",
           "experiment": "هل يمكننا ادعاء سبب؟", "predictive": "ماذا سيحدث؟",
           "prescriptive": "ماذا ينبغي أن أفعل؟"},
}


def reply(language, message, /, **values):
    """A sentence of the assistant's own, in the person's language.

    `message` is positional-only because one of the placeholders a
    caller fills is named `key`."""
    catalogue = REPLIES.get(language) or REPLIES["en"]
    template = catalogue.get(message) or REPLIES["en"][message]
    return template.format(**values)


def intent(action, arguments=None, text=None, source="rules", why=None):
    return {"action": action, "arguments": dict(arguments or {}),
            "reply": text, "source": source, "why": why}


_PUNCTUATION = " \t\r\n!.,;:؟?،؛\"'«»“”"


def is_yes(text):
    return str(text).strip(_PUNCTUATION).lower() in YES_WORDS


def is_no(text):
    return str(text).strip(_PUNCTUATION).lower() in NO_WORDS


# ---------------------------------------------------------------------------
# Rules. Order is the priority: a sentence matching two rules gets the
# first. Anchored patterns (^) are for verbs that open a request;
# unanchored ones are for questions that can be phrased many ways.
# ---------------------------------------------------------------------------

_HELP = re.compile(
    r"^\W*(help|commands|capabilities)\W*$"
    r"|\b(what can you do|what do you do|what are you able to do|"
    r"what can i (ask|do)|what commands|which commands|list (the |your )?commands)\b"
    r"|^\W*(مساعدة|ساعدني|ماذا تستطيع|ماذا يمكنك|إيه اللي تقدر|ايه اللي تقدر|"
    r"تقدر تعمل|ما الذي تستطيع|ما الذي يمكنك|الأوامر)", re.I)
_CLEAR_HISTORY = re.compile(
    r"\b(clear|delete|erase|wipe|reset)\b.*\b(history|conversation)\b"
    r"|(امسح|احذف|امح|صفّر|صفر)\b.*(السجل|سجل المحادثة|المحادثة|التاريخ)", re.I)
_FORGET_ALL = re.compile(
    r"\b(forget|delete|clear|erase|wipe|remove)\b.*"
    r"\b(everything|all memory|all memories|all of it|the memory|my memory|"
    r"your memory|all)\b"
    r"|(انس|انسى|انسَ|امسح|احذف|امح)\b.*(كل|الكل|كل الذاكرة|الذاكرة كلها|"
    r"كل حاجة|كل شيء|الذاكرة)", re.I)
_FORGET_KEY = re.compile(
    r"\b(forget|delete|remove|erase)\b.*\b(?P<key>memory_\d+)\b"
    r"|(انس|انسى|انسَ|احذف|امسح|امح)\b.*(?P<key_ar>memory_\d+)", re.I)
_REMEMBER = re.compile(
    r"^\W*(?:please\s+)?(?:remember|note|save|keep in mind|don'?t forget|"
    r"dont forget)(?:\s+that)?\s*[:,\-–—]?\s*(?P<info>.+?)\s*$"
    r"|^\W*(?:من فضلك\s+|لو سمحت\s+)?(?:تذكر|تذكّر|افتكر|إفتكر|احفظ|إحفظ|سجل|"
    r"سجّل|لا تنس|لا تنسى|ما تنساش|متنساش|خلي بالك)"
    r"(?:\s+(?:أن|ان|إن|انه|أنه|إنه|ان\s))?\s*[:،,\-–—]?\s*(?P<info_ar>.+?)\s*$",
    re.I | re.S)
_REMEMBER_BARE = re.compile(
    r"^\W*(remember|note|save|تذكر|تذكّر|افتكر|احفظ|سجل|سجّل)\W*$", re.I)
_RECALL = re.compile(
    r"\b(what do you (remember|know)|what have (i|you) (saved|remembered|told)|"
    r"show (me )?(my |the )?(memory|memories|notes)|list (my |the )?(memory|"
    r"memories|notes)|what did i (tell|say|ask)( you)?|what('s| is) in "
    r"(your|my) memory|what do you remember about|^\W*recall\b|"
    r"^\W*(do|can) you remember)"
    r"|(إيه اللي فاكره|ايه اللي فاكره|إيه اللي حفظته|ايه اللي حفظته|ماذا تتذكر|"
    r"ما الذي تتذكره|ماذا حفظت|ما الذي حفظته|اعرض الذاكرة|أعرض الذاكرة|"
    r"اعرض ما حفظت|ماذا تعرف عني|ما هي ذاكرتك|فاكر إيه|فاكر ايه|فاكر حاجة|"
    r"هل تتذكر|تفتكر|بتفتكر)", re.I)
_RECALL_QUERY = re.compile(r"\babout\s+(?P<q>.+?)\s*[?؟.]*\s*$|\bعن\s+(?P<q_ar>.+?)\s*[?؟.]*\s*$", re.I)
_NAME = re.compile(
    r"\b(?:call me|my name is|my name's|i am called|i'm called|you can call me)"
    r"\s+(?P<name>[^\s.,!?؟،]{1,40}(?:\s+[^\s.,!?؟،]{1,40})?)"
    r"|(?:اسمي|إسمي|ناديني|نادني|سمّني|سميني|أنا اسمي|انا اسمي)"
    r"\s+(?P<name_ar>[^\s.,!?؟،]{1,40}(?:\s+[^\s.,!?؟،]{1,40})?)", re.I)
_TONE_VERB = re.compile(
    r"\b(be|reply|answer|respond|keep|make|switch|use|talk|speak|go|stay|"
    r"sound|please)\b"
    r"|(خليك|خلّيك|كن|كوني|رد|ردّ|ردودك|اجعل|اجعلي|خلي|خلّي|تكلم|اتكلم|"
    r"كلمني|لو سمحت|من فضلك)", re.I)
_LANGUAGE_VERB = re.compile(
    r"\b(reply|answer|speak|talk|switch|change|respond|write|use)\b"
    r"|\b(in|to|into)\s+(arabic|english)\b"
    r"|(رد|ردّ|تكلم|اتكلم|كلمني|غير|غيّر|حوّل|حول|اللغة|بال)", re.I)
_RUN_STATUS = re.compile(
    r"\b(status|progress)\b|\bhow('s| is| far)( along)?( is)? (the |my |that )?"
    r"(run|analysis|report)|\bis (the |my |it |that )?(run |analysis |report )?"
    r"(done|finished|ready|complete)|\bwhere (are we|is it|did (we|it) get)"
    r"|(الحالة|حالة التحليل|وصل فين|وصلنا فين|خلص|خلصت|خلّص|انتهى|انتهت|"
    r"جاهز|جاهزة|فين التحليل|أين التحليل|ايه وضع|إيه وضع|ما وضع|وضع التحليل)",
    re.I)
_EXPLAIN = re.compile(
    r"\b(explain|summari[sz]e|walk me through|what did (it|the analysis|the "
    r"report|you) find|what (does|did) the report (say|show)|tell me about "
    r"the (report|results|findings|analysis)|(key|main) (findings|results|"
    r"takeaways)|what happened|why did .*(move|change|rise|fall|drop|grow|"
    r"increase|decrease|go (up|down))|what will happen|what('s| is) the "
    r"forecast|what should (i|we) do|what do you recommend|can we claim a "
    r"cause|is (it|this) causal|what caused)\b"
    r"|(اشرح|إشرح|اشرحلي|اشرح لي|لخص|لخّص|لخصلي|ايه النتائج|إيه النتائج|"
    r"ما النتائج|ما هي النتائج|ماذا وجد|ماذا وجدت|النتائج الرئيسية|أهم النتائج|"
    r"ماذا حدث|ايه اللي حصل|إيه اللي حصل|لماذا تغير|لماذا تغيّر|ليه اتغير|"
    r"ليه زاد|ليه نقص|لماذا زاد|لماذا انخفض|ماذا سيحدث|ايه اللي هيحصل|"
    r"إيه اللي هيحصل|التوقع|التوقعات|ماذا ينبغي|ايه اللي المفروض|"
    r"إيه اللي المفروض|ماذا تنصح|بماذا توصي|ما توصيتك|هل السبب|"
    r"هل يمكننا ادعاء سبب|ما سبب)", re.I)
_SECTION_HINTS = (
    ("diagnostic", re.compile(r"\b(why|cause of the change)\b|لماذا|ليه", re.I)),
    ("predictive", re.compile(r"\b(forecast|will happen|predict|next (month|quarter|"
                              r"period|year)|outlook)\b|سيحدث|هيحصل|التوقع|توقع|"
                              r"الشهر القادم|الربع القادم", re.I)),
    ("prescriptive", re.compile(r"\b(should|recommend|recommendation|advice|"
                                r"what to do)\b|ينبغي|المفروض|تنصح|توصي|توصية|"
                                r"نعمل ايه|نعمل إيه", re.I)),
    ("experiment", re.compile(r"\b(causal|cause|caused|experiment)\b|سبب|سببي|"
                              r"تجربة", re.I)),
    ("descriptive", re.compile(r"\b(what happened|overview|summary|summari[sz]e)\b"
                               r"|ماذا حدث|اللي حصل|لخص|لخّص|ملخص", re.I)),
)
_START_RUN = re.compile(
    r"\b(analy[sz]e|analysis|run (an? |the )?(analysis|report|pipeline)|"
    r"(generate|produce|create|make|build|prepare|write|give me) (a |an |the )?"
    r"(report|analysis)|examine|study|explore|dig into|look into|crunch)\b"
    r"|(حلل|حلّل|حلّلي|حللي|تحليل|اعمل تحليل|إعمل تحليل|اعمل تقرير|اعملي تقرير|"
    r"أعد تقرير|أعدّ تقرير|جهز تقرير|جهّز تقرير|ابدأ تحليل|ابدأ التحليل|"
    r"إبدأ تحليل|شغل تحليل|شغّل تحليل|شغل التحليل|ادرس|إدرس|افحص|إفحص)", re.I)
_SAMPLE_DATASET = re.compile(r"\bsample\b|النموذجي|النموذجية|التجريبي|التجريبية|العينة", re.I)


def _language_named(text):
    lowered = text.lower()
    for language, words in LANGUAGE_WORDS.items():
        if any(word in lowered for word in words):
            return language
    return None


def _tone_named(text):
    lowered = text.lower()
    for tone, words in TONE_WORDS.items():
        if any(re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", lowered)
               for word in words):
            return tone
    return None


def section_for(text):
    """Which report section a question is about; "all" when it is general."""
    for section, pattern in _SECTION_HINTS:
        if pattern.search(text):
            return section
    return "all"


def understand(text):
    """A sentence → an intent, by rules.

    Returns the `chat` intent when nothing matches; the executor then
    answers honestly that it did not understand, and says what it can do.
    """
    text = str(text or "").strip()
    if not text:
        return intent("chat")
    words = len(text.split())

    if _HELP.search(text):
        return intent("help")
    # "Remember to delete all the old files" is a note, not a deletion:
    # the anchored remember rule decides before any forget rule can.
    if _REMEMBER_BARE.match(text):
        return intent("remember", {"information": ""})
    match = _REMEMBER.match(text)
    if match:
        info = match.group("info") or match.group("info_ar") or ""
        return intent("remember", {"information": info.strip(), "category": None})
    if _CLEAR_HISTORY.search(text):
        return intent("clear_history")
    match = _FORGET_KEY.search(text)
    if match:
        return intent("forget", {"key": match.group("key") or match.group("key_ar")})
    if _FORGET_ALL.search(text):
        return intent("forget", {"key": "all"})
    if _RECALL.search(text):
        query = None
        found = _RECALL_QUERY.search(text)
        if found:
            query = (found.group("q") or found.group("q_ar") or "").strip() or None
        return intent("recall", {"query": query})
    match = _NAME.search(text)
    if match:
        name = match.group("name") or match.group("name_ar")
        return intent("set_preference", {"key": "user_name", "value": name.strip()})
    # A language or tone word on its own ("arabic", "concise please") is a
    # request; inside a longer sentence it needs a verb of address, or "I
    # like Arabic coffee" would switch the interface.
    language = _language_named(text)
    if language and (words <= 2 or _LANGUAGE_VERB.search(text)):
        return intent("set_preference", {"key": "language", "value": language})
    tone = _tone_named(text)
    if tone and (words <= 2 or _TONE_VERB.search(text)):
        return intent("set_preference", {"key": "tone", "value": tone})
    # "Is the analysis done?" names the analysis and asks about it; the
    # question wins over the noun.
    if _RUN_STATUS.search(text):
        return intent("run_status")
    if _START_RUN.search(text):
        dataset = "sample" if _SAMPLE_DATASET.search(text) else None
        return intent("start_run", {"goal": text, "dataset": dataset})
    if _EXPLAIN.search(text):
        return intent("explain_report", {"section": section_for(text)})
    return intent("chat")


# ---------------------------------------------------------------------------
# Execution of the actions that need only the Agent. The server adds the
# three that need the run engine.
# ---------------------------------------------------------------------------

def fallback(agent, text):
    """The honest "I did not understand", in the agent's tone and language."""
    tone = agent.preferences.get("tone", "friendly")
    if tone not in TONES:
        tone = "friendly"
    return reply(agent.language(), f"fallback_{tone}", request=text)


def execute_local(action, arguments, agent, text, model_reply=None):
    """Run one non-server action against the Agent and return the reply.

    Every confirmation here is the Agent's own sentence — the same one the
    slash command would produce — so a reply can never claim a save that
    did not happen. Only `chat` shows text a model wrote.
    """
    language = agent.language()
    arguments = arguments or {}
    if action == "help":
        return reply(language, "capabilities")
    if action == "remember":
        return agent.add_memory(str(arguments.get("information") or ""),
                                arguments.get("category"))
    if action == "recall":
        query = str(arguments.get("query") or "").strip().lower()
        entries = agent.memory_entries()
        if query:
            entries = [e for e in entries if query in e["text"].lower()]
            if not entries:
                return reply(language, "recall_none_match", query=query)
        if not entries:
            return agent.text("nothing_saved")
        return agent.text("saved_heading") + "\n" + "\n".join(
            f"{e['key']}: {e['text']}" for e in entries)
    if action == "forget":
        key = str(arguments.get("key") or "").strip()
        if key.lower() == "all":
            return agent.clear_all_memory()
        return agent.remove_memory(key)
    if action == "clear_history":
        agent.history.clear()
        return agent.text("history_cleared")
    if action == "set_preference":
        key = str(arguments.get("key") or "").strip().lower()
        value = arguments.get("value")
        if key not in PREFERENCE_KEYS:
            return reply(language, "unknown_preference")
        if key == "tone" and str(value).lower() not in TONES:
            return reply(language, "bad_tone")
        if key == "save_history" and isinstance(value, bool):
            value = "true" if value else "false"
        return agent.set_preference(key, str(value).strip())
    if action in SERVER_ONLY:
        return reply(language, "cli_needs_web")
    # chat: a model's phrasing if one answered, else the honest fallback.
    return (model_reply or "").strip() or fallback(agent, text)


def confirmation_prompt(action, arguments, agent):
    """The question asked before a destructive action runs."""
    language = agent.language()
    if action == "clear_history":
        return reply(language, "confirm_clear_history")
    key = str((arguments or {}).get("key") or "").strip()
    if key.lower() == "all":
        return reply(language, "confirm_forget_all")
    text = agent.memory.get(key)
    if text is None:
        # Nothing to confirm: the executor will say the key does not exist.
        return None
    return reply(language, "confirm_forget_key", key=key, text=text)
