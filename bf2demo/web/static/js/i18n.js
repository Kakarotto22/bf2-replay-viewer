// English / Arabic UI strings. `T(key)` falls back to English, then to the key.
import { $ } from "./util.js";

const STRINGS = {
  en: {
    search_demos: "Search recordings (map, server, name)...", only_humans: "Players only (no bots)", sort_date: "Newest first", sort_players: "Most players",
    sort_kills: "Most kills", sort_duration: "Longest", upload: "Upload .bf2demo", all_maps: "All maps", demos: "recordings",
    ready: "Ready", parsing: "Parsing...", new: "Not parsed yet", error: "Error", empty: "Nothing here.",
    parsing_long: "Reading the recording... a long round with many players can take a few minutes the first time", loading: "Loading...",
    donate_short: "Support", unofficial: "Unofficial fan project, not affiliated with EA or DICE. MIT license.", source_code: "Source code on GitHub", donate_title: "Support this project", donate_telegram: "Telegram", donate_copy: "Copy username", donate_copied: "Copied", donate_more: "Ways to donate", donate_warn: "Send on the network written next to the address: funds sent on a wrong network are lost. Copy the address with the button instead of typing it.", donate_open: "Open", donate_qr: "QR code", donate_hide_qr: "Hide QR", donate_scan: "Scan with your wallet or phone camera", donate_copy_addr: "Copy",
    donate_text: "A free fan-made replay viewer, built by reverse engineering the game. If it is useful to you, a donation keeps the server running and the work going. Contact me on Telegram.",
    humans: "Players", bots: "bots", kills: "Kills", deaths: "Deaths", score: "Score", kd: "K/D", name: "Name", team: "Team", back: "Library",
    filters: "Filters", legend: "Legend", log: "Log", scoreboard: "Scoreboard", player: "Player", info: "Round",
    teams: "Teams", show: "Show", kits: "Kits", squad: "Squad", color_by: "Colour by", layers: "On the map",
    c_team: "Team", c_squad: "Squad", c_kit: "Kit", any_squad: "All squads", no_squad: "No squad",
    soldiers: "Soldiers", vehicles: "Vehicles with a crew", empty_vehicles: "Empty vehicles", air: "Parachutes and UAV",
    l_names: "Player names", l_cps: "Control points", l_lines: "Kill lines", l_heat: "Death heatmap", l_trail: "Trail of the selected player", l_corpses: "Death marks",
    search_log: "Filter the log...", find_player: "Find a player...", pick_player: "Click a player on the map or in the list.",
    duration: "Duration", map: "Map", mode: "Mode", server: "Server", recorded: "Recorded", tickets: "Tickets", at_end: "at the end", engine: "Engine",
    undecodable: "Undecodable packets", distance: "Distance", vehicles_used: "Vehicles used", follow: "Follow", unfollow: "Stop following",
    joined: "Joined", left_: "Left", events: "Events", kicked: "Kicked", no_backdrop: "The game is not installed here, so the map is a plain grid. Set BF2_GAME_ROOT to get the real map image.",
    lg_soldier: "Soldier (the selected one also shows the direction he looks)", lg_leader: "Squad leader (the squad number disc above the soldier)", lg_squadmate: "Colour = team, squad or kit", lg_vehicle: "Vehicle with a crew (icon = vehicle class)", lg_empty: "Empty vehicle (black with a light outline)",
    lg_flag: "Control point (flag = owner)", lg_dead: "Death mark", lg_gap: "Faded = no position update for a while", lg_uav: "UAV / parachute",
    seated_in: "in",
    moments: "Moments", m_killer: "Who killed (in what)", m_victim: "Who died (in what)", m_anyone: "Anyone", m_text: "Name of a vehicle, weapon or player", m_search: "e.g. Cobra, Lightning, M1A2...",
    m_count: "moments", m_prev: "Previous", m_next: "Next", m_clear: "Reset",
    cls_foot: "On foot", cls_tank: "Tank", cls_apc: "APC", cls_jeep: "Car", cls_heli: "Helicopter", cls_jet: "Jet", cls_boat: "Boat", cls_aa: "AA / gun", cls_other: "Other",
    died: "died", clip: "Clip", clip_help: "Cut a scene as a .bf2demo to open in the game. Go to the moment and press the buttons.", clip_set_start: "Start here", clip_set_end: "End here",
    clip_lead: "Normal playback before the start (seconds)", clip_sign: "Add the BF2Demo Analyzer welcome message (shown by the game as the server message; not tested in the game yet)", clip_download: "Download .bf2demo",
    clip_warning: "A cut that only has an END is a plain shortened recording. A START cut squashes the earlier packets so the game applies them at once: experimental, test it in the game first.", l_rate: "Playback rate (1 = real time, calibration)", l_rate_tip: "If the game replays slightly faster or slower than 30 ticks per second, correct it here", l_persp: "Team colours", c_blue: "blue", c_red: "red", l_iconsize: "Icon size", l_hd: "Detailed map (terrain tiles / your own HD map)", more: "More options", f_soldiers: "Soldiers", f_vehicles: "Vehicles", f_flags: "Flags", f_uav: "UAV", f_names: "Names", f_empty: "Empty vehicles", f_strikes: "Strikes", lg_strike: "Artillery / air strike (circle = blast area)",
    k_kill: "Kill", k_teamkill: "Team kill", k_death: "Death", k_suicide: "Suicide", k_join: "Joined", k_leave: "Left", k_spawn: "Spawn", k_capture: "Capture",
    "k_capture-initial": "Start", k_neutralize: "Neutralised", k_tickets: "Tickets", k_squad: "Squad", k_commander: "Commander", k_vote: "Vote", k_round: "Round",
    k_vehicle: "Vehicle", k_spot: "Spotted", k_call: "Call", k_uav: "UAV", k_assist: "Assist", k_medal: "Medal", k_kick: "Kick", k_team: "Team change",
 kit_n: "Kit", l_hudsize: "HUD size (auto = the game's own fit of its 800 x 600 layout)", auto: "Auto", weapon: "Weapon", in_vehicle: "Inside", no_weapon: "none", no_hp_ammo: "Health and ammo are not in the recorded data. Several weapon names = the default weapon and its unlocks (the chosen one is not recorded).", free_look: "Drag to pan, wheel to zoom", stat_alive: "alive",
  },
  ar: {
    search_demos: "ابحث في التسجيلات (خريطة، خادم، اسم)...", only_humans: "اللاعبون فقط (بدون بوتات)", sort_date: "الأحدث أولاً", sort_players: "الأكثر لاعبين",
    sort_kills: "الأكثر قتلاً", sort_duration: "الأطول", upload: "رفع ملف bf2demo", all_maps: "كل الخرائط", demos: "تسجيل",
    ready: "جاهز", parsing: "جارٍ القراءة...", new: "لم يُقرأ بعد", error: "خطأ", empty: "لا يوجد شيء.",
    parsing_long: "جارٍ قراءة التسجيل... الجولة الطويلة بلاعبين كثيرين قد تستغرق دقائق في المرة الأولى", loading: "جارٍ التحميل...",
    donate_short: "ادعم", unofficial: "مشروع معجبين غير رسمي، غير تابع لـ EA أو DICE. ترخيص MIT.", source_code: "الكود المصدري على GitHub", donate_title: "ادعم هذا المشروع", donate_telegram: "تيليجرام", donate_copy: "نسخ المعرّف", donate_copied: "تم النسخ", donate_more: "طرق التبرع", donate_warn: "أرسل على الشبكة المكتوبة بجانب العنوان: ما يُرسل على شبكة خاطئة يضيع. انسخ العنوان بالزر ولا تكتبه يدوياً.", donate_open: "فتح", donate_qr: "رمز QR", donate_hide_qr: "إخفاء QR", donate_scan: "امسحه بمحفظتك أو بكاميرا الهاتف", donate_copy_addr: "نسخ",
    donate_text: "عارض تسجيلات مجاني صنعه معجب باللعبة عبر الهندسة العكسية. إن أفادك، فتبرعك يبقي الخادم يعمل ويدعم استمرار العمل. تواصل معي عبر تيليجرام.",
    humans: "لاعبون", bots: "بوتات", kills: "القتلى", deaths: "الوفيات", score: "النقاط", kd: "ق/و", name: "الاسم", team: "الفريق", back: "المكتبة",
    filters: "التصفية", legend: "المفتاح", log: "السجل", scoreboard: "النتائج", player: "اللاعب", info: "الجولة",
    teams: "الفرق", show: "إظهار", kits: "الأدوار", squad: "الفرقة", color_by: "التلوين حسب", layers: "على الخريطة",
    c_team: "الفريق", c_squad: "الفرقة", c_kit: "الدور", any_squad: "كل الفرق الصغيرة", no_squad: "بلا فرقة",
    soldiers: "الجنود", vehicles: "المركبات التي بها طاقم", empty_vehicles: "المركبات الفارغة", air: "المظلّات والطائرة المسيّرة",
    l_names: "أسماء اللاعبين", l_cps: "نقاط السيطرة", l_lines: "خطوط القتل", l_heat: "خريطة حرارية للوفيات", l_trail: "مسار اللاعب المحدد", l_corpses: "علامات الموت",
    search_log: "تصفية السجل...", find_player: "ابحث عن لاعب...", pick_player: "اضغط على لاعب في الخريطة أو في القائمة.",
    duration: "المدة", map: "الخريطة", mode: "النمط", server: "الخادم", recorded: "وقت التسجيل", tickets: "التذاكر", at_end: "في النهاية", engine: "المحرك",
    undecodable: "حزم غير مفكوكة", distance: "المسافة", vehicles_used: "المركبات المستخدمة", follow: "تتبّع", unfollow: "إيقاف التتبّع",
    joined: "انضم", left_: "غادر", events: "الأحداث", kicked: "طُرد", no_backdrop: "اللعبة غير مثبّتة هنا فتظهر شبكة عادية بدل الخريطة. اضبط BF2_GAME_ROOT للحصول على صورة الخريطة.",
    lg_soldier: "جندي (المحدد فقط يظهر اتجاه نظره)", lg_leader: "قائد فرقة (قرص برقم الفرقة فوق الجندي)", lg_squadmate: "اللون = الفريق أو الفرقة أو الدور", lg_vehicle: "مركبة بها طاقم (الأيقونة = صنف المركبة)", lg_empty: "مركبة فارغة (سوداء بحافة فاتحة)",
    lg_flag: "نقطة سيطرة (العلم = المالك)", lg_dead: "علامة موت", lg_gap: "باهت = لا يصل تحديث للموقع منذ فترة", lg_uav: "طائرة مسيّرة / مظلّة",
    seated_in: "في",
    moments: "اللقطات", m_killer: "من قتل (وهو في ماذا)", m_victim: "من قُتل (وهو في ماذا)", m_anyone: "أي لاعب", m_text: "اسم مركبة أو سلاح أو لاعب", m_search: "مثلاً Cobra أو Lightning أو M1A2...",
    m_count: "لقطة", m_prev: "السابقة", m_next: "التالية", m_clear: "إعادة ضبط",
    cls_foot: "مشياً", cls_tank: "دبابة", cls_apc: "مدرّعة", cls_jeep: "سيارة", cls_heli: "هليكوبتر", cls_jet: "طائرة", cls_boat: "قارب", cls_aa: "مضاد / مدفع", cls_other: "أخرى",
    died: "مات", clip: "اقتطاع", clip_help: "اقتطع مشهداً كملف .bf2demo لفتحه في اللعبة. اذهب إلى اللحظة واضغط الأزرار.", clip_set_start: "البداية هنا", clip_set_end: "النهاية هنا",
    clip_lead: "ثوانٍ تُعرض عادياً قبل البداية", clip_sign: "إضافة رسالة ترحيب BF2Demo Analyzer (تظهر في اللعبة كرسالة الخادم؛ لم تُجرَّب في اللعبة بعد)", clip_download: "تنزيل .bf2demo",
    clip_warning: "الاقتطاع بنهاية فقط هو تسجيل مقصوص عادي. أما البداية فتضغط الحزم السابقة لتُطبَّق دفعة واحدة: ميزة تجريبية، جرّبها في اللعبة أولاً.", l_rate: "معامل سرعة التشغيل (1 = زمن حقيقي، للمعايرة)", l_rate_tip: "إن كانت اللعبة تعيد التسجيل أسرع أو أبطأ قليلاً من 30 تيك بالثانية فصحّحها هنا", l_persp: "ألوان الفرق", c_blue: "أزرق", c_red: "أحمر", l_iconsize: "حجم الأيقونات", l_hd: "خريطة مفصّلة (قطع التضاريس أو خريطتك عالية الدقة)", more: "خيارات أكثر", f_soldiers: "الجنود", f_vehicles: "المركبات", f_flags: "الأعلام", f_uav: "المسيّرة", f_names: "الأسماء", f_empty: "مركبات فارغة", f_strikes: "القصف", lg_strike: "قصف مدفعي أو جوي (الدائرة = منطقة الانفجار)",
    k_kill: "قتل", k_teamkill: "قتل زميل", k_death: "وفاة", k_suicide: "انتحار", k_join: "انضمام", k_leave: "مغادرة", k_spawn: "ظهور", k_capture: "استيلاء",
    "k_capture-initial": "البداية", k_neutralize: "تحييد", k_tickets: "التذاكر", k_squad: "الفرقة", k_commander: "القائد", k_vote: "تصويت", k_round: "الجولة",
    k_vehicle: "مركبة", k_spot: "رصد", k_call: "نداء", k_uav: "طائرة مسيّرة", k_assist: "مساعدة", k_medal: "وسام", k_kick: "طرد", k_team: "تغيير فريق",
 kit_n: "الدور", l_hudsize: "حجم الواجهة (تلقائي = كما تلائم اللعبة تخطيطها 800×600)", auto: "تلقائي", weapon: "السلاح", in_vehicle: "داخل", no_weapon: "لا شيء", no_hp_ammo: "الصحة والذخيرة غير موجودتين في البيانات المسجّلة. عدة أسماء للسلاح = السلاح الأساسي وبدائله المفتوحة (والمختار منها غير مسجّل).", free_look: "اسحب للتحريك والعجلة للتكبير", stat_alive: "أحياء",
  },
};

export let lang = new URLSearchParams(location.search).get("lang") || localStorage.getItem("lang") || "en";
export const T = (k) => (STRINGS[lang] && STRINGS[lang][k]) || STRINGS.en[k] || k.replace(/^k_/, "");

export function setLang(next) { lang = next; localStorage.setItem("lang", lang); applyLang(); }
export function applyLang() {
  document.documentElement.lang = lang;
  document.documentElement.dir = lang === "ar" ? "rtl" : "ltr";
  document.querySelectorAll("[data-t]").forEach((e) => { e.textContent = T(e.dataset.t); });
  document.querySelectorAll("[data-ph]").forEach((e) => { e.placeholder = T(e.dataset.ph); });
  $("langBtn").textContent = lang === "ar" ? "English" : "العربية";
}
