# Ideas Book – reusable ideas from this project (bilingual / نسخة عربي وإنجليزي)

Owner: Mohamed Fawzy. This file keeps the **ideas, tricks and technologies** of this project in plain words, so they
can be reused in any other project. It is not a manual of this program (see `README.md`) and not its history (see
`DEVELOPMENT_HISTORY.md`).

بالعربي: الملف ده مجموعة أفكار المشروع مكتوبة ببساطة، علشان تتنقل لأي مشروع تاني. مش دليل استخدام البرنامج (ده في
`README.md`) ومش تاريخه (ده في `DEVELOPMENT_HISTORY.md`).

Every idea follows the same shape / كل فكرة بنفس الشكل:
**Problem** (what hurt / المشكلة) → **Idea** (one sentence / الفكرة في جملة) → **How** (simple steps / إزاي اشتغلت) →
**Where** (files here / مكانها في الكود) → **Reuse when / watch out** (تنفع فين / خد بالك من إيه).

Kept up to date with every change (rule in `CLAUDE.md`). New idea → new card in the right chapter.
بالعربي: الملف ده بيتحدّث أوتوماتيك مع كل تعديل في المشروع.

---

## Chapter 1 – Several PCs that work alone and share (offline-first)
## الفصل ١ – أجهزة كتير تشتغل لوحدها وتتشارك (بدون سيرفر مركزي)

### 1.1 Every PC has everything, PCs share *changes*, never database files
- **Problem:** one server PC = when it is off, nobody works. Sharing one database file over the network breaks it.
- **Idea:** every PC keeps the complete data and works alone; PCs send each other small "change packets".
- **How:** each save becomes one *changeset* (who, when, what changed). PCs ask each other "what do you have that I
  don't?" and exchange only the missing changesets. Each PC applies them to its own database.
- **Where:** `server/journal.py` (changesets), `server/sync.py` (exchange), `server/replica.py` (apply).
- **Reuse when:** shops, branches, field teams, factories with weak network. **Watch out:** never copy or share the
  database file itself (SQLite over a network drive corrupts).
- 🇪🇬 **بالعربي:** كل جهاز عنده نسخة كاملة من البيانات ويشتغل لوحده حتى لو النت وقع. الأجهزة بتتبادل "رسايل تغيير"
  صغيرة بس (مين غيّر إيه وإمتى)، مش بتنسخ ملف الداتابيز نفسه أبداً. تنفع في أي فرع أو محل أو مصنع نتّه ضعيف.

### 1.2 Same result on every PC, whatever the order (deterministic merge)
- **Problem:** PC A and PC B change things at the same time without seeing each other. Who wins?
- **Idea:** fixed rules that give the same answer on every PC, no matter which change arrives first.
- **How (the rules):**
  - A text field: the newest change wins, "newest" = (clock, PC id, number) – a tie is impossible.
  - A quantity (stock): store **movements** (+5, −2), not the final number → both changes count (+3).
  - A delete stays a delete; the record is kept hidden, never erased.
  - When a person should decide (two different values, delete vs. edit) → show both in a "To decide" list.
- **Where:** `server/replica.py`, `Journal._fold_roster` (PC list), conflict screen in `js/devices.js`.
- **Watch out:** when a *second* author can write something that had only one author before, check that its merge
  still does not depend on arrival order (lesson of version 2.3.1). When you add a "version" column later, rebuild
  the old rows from the history.
- 🇪🇬 **بالعربي:** لو جهازين غيّروا نفس الحاجة في نفس الوقت، فيه قاعدة ثابتة تديهم نفس النتيجة مهما كان الترتيب.
  التغيير الأحدث بياخد الأولوية، والكميات (زي المخزون) بتتجمع بدل ما تتحل محل بعض، والحذف بيفضل حذف.

### 1.3 A clock that never goes backwards (hybrid logical clock) + "what I have" lists
- **Problem:** PC clocks are wrong or change; "newest" by wall time is unreliable.
- **Idea:** a clock that is the wall time, but always a bit bigger than anything already seen.
- **How:** every change carries this clock. Each PC also keeps a short list "from PC X I have changes up to number N"
  (version vector) → the exchange asks only for what is missing.
- **Where:** `HLC` in `server/journal.py`.
- 🇪🇬 **بالعربي:** ساعة الجهاز ممكن تكون غلط، فبنستخدم "ساعة منطقية" بتفضل تزيد وما بترجعش لورا، وقايمة صغيرة بتقول
  كل جهاز واصل لحد فين، علشان التبادل ما يبعتش حاجة اتبعتت قبل كده.

### 1.4 Tamper-evident history (hash chain + signatures)
- **Problem:** somebody edits or deletes old records directly in the database.
- **Idea:** chain the changes like a blockchain-lite and sign them.
- **How:** each change contains the fingerprint (hash) of the previous change of the same PC and is signed with that
  PC's key (Ed25519). Changing an old one breaks the chain → detected. Every PC keeps a copy of all chains.
- **Where:** `server/journal.py`, `server/ed25519.py`; "Check Records" button.
- 🇪🇬 **بالعربي:** كل تغيير بياخد بصمة التغيير اللي قبله ويتوقّع بمفتاح الجهاز، زي سلسلة صغيرة من البلوك تشين. أي
  تلاعب في القديم بيكسر السلسلة ويتكشف على طول.

### 1.5 Wait for a newer program instead of losing data
- **Problem:** an updated PC sends new fields that an old PC does not know; the old PC would drop them.
- **Idea:** a data "schema number" in every change; an old PC keeps such changes aside until it is updated.
- **Where:** `journal.SCHEMA`, `sync.SCHEMA_VERSION`. **Watch out:** raise it with every new field.
- 🇪🇬 **بالعربي:** كل تغيير معاه رقم "شكل البيانات". الجهاز اللي لسه ما اتحدّثش بيحتفظ بالتغيير ده جنب لحد ما
  يتحدّث، بدل ما يرميه.

### 1.6 When the network blocks sharing: a "thin" PC that opens the main PC like a link
- **Problem:** in one company network the PCs could not reach each other's sharing port (only the web address worked, so personal links
  worked but "Join" never connected). The full-copy design was right, but the network did not allow it.
- **Idea:** give the program a second, very simple mode: the PC keeps no data and only sends the browser to the main PC – the one
  path that is known to work. Same login, same screens, nothing to keep in step.
- **How:** the first screen offers it first; the address is found by scanning the local network on the web port (or typed and checked
  live); one setting (`office_url`) is saved; from then on the program is a tiny page on 127.0.0.1 that checks the main PC and redirects,
  or says in plain words that it is off ("Try again", new address). Old open browser connections are closed after the switch.
- **Where:** `server/office.py`, `server/bams_main.py`, `/api/office/*` and `/api/node/office` in `server/app.py`, `showOffice` in `js/devices.js`.
- **Reuse when / watch out:** any "local server" app in a locked-down network – always keep one path that needs nothing but a browser
  address. Test a real switch with a real browser: keep-alive connections and cached pages can show the old screen. A page on 127.0.0.1
  must check the Host header (DNS rebinding), not only the caller's IP.
- 🇪🇬 **بالعربي:** لو شبكة الشركة قافلة "باب" المشاركة بين الأجهزة، خلّي الجهاز التاني ما يشيلش داتا خالص ويفتح الجهاز الرئيسي زي
  اللينك بالظبط. نفس الدخول ونفس الشاشات، ومفيش حاجة تتلخبط.

---

## Chapter 2 – Trust and security between PCs
## الفصل ٢ – الثقة والأمان بين الأجهزة

### 2.1 One "authority key" for the dangerous changes
- **Problem:** any PC could pretend to give itself administrator rights.
- **Idea:** user, permission and PC changes must be signed with a special key that only the administrator PC has.
- **How:** every PC knows the public half; it refuses such changes without a valid signature.
- **Where:** `server/node.py`, `Journal._check`.
- 🇪🇬 **بالعربي:** أي تغيير خطير (مستخدمين، صلاحيات، أجهزة) لازم يتوقّع بمفتاح خاص موجود بس على جهاز الأدمن. أي
  جهاز تاني يحاول يعمل الحاجة دي، البرنامج بيرفضها.

### 2.2 Delegation: a backup administrator PC
- **Problem:** the administrator is on holiday or their PC is off → nobody can add people.
- **Idea:** give a copy of the authority key to one trusted PC, and take it back later.
- **How:** the administrator marks a PC "backup"; that PC fetches the key over the encrypted, pinned connection.
  When the role ends – or the PC is removed, even while it was off – it deletes the key. A backup PC may not export
  the key and may not remove the main administrator PC.
- **Where:** `set_backup`, `/sync/authority`, `Node.drop_backup_key`, `check_backup_role` in `server/sync.py`.
- **Watch out:** a removed PC never receives the message "you are removed" (everyone refuses it) → react to the
  refusal itself and check again at every start. Full revocation needs a new key (key rotation).
- 🇪🇬 **بالعربي:** لو الأدمن مسافر أو جهازه مقفول، ممكن تدي نسخة من مفتاحه لجهاز تاني تثق فيه، وترجع تسحبها منه في
  أي وقت. الجهاز اللي اتشال بيمسح نسخته أول ما يرجع للشبكة، حتى لو كان مقفول وقت الشيل.

### 2.3 Adding a new PC: two levels of safety
- **Problem:** how does a new PC join without IT knowledge?
- **Idea A – safe (2.0–2.3):** a one-time code (15 minutes) + the same 6-digit number shown on both screens, the
  administrator approves only if equal – like Bluetooth pairing.
- **Idea B – easiest (2.4, used now, small trusted team):** the new PC searches the network for the administrator PC
  (asks every address of its network "are you the administrator PC?" on the sync port, 64 at a time) and joins
  with the address only; the administrator PC adds it at once. The first connection remembers the certificate
  fingerprint, so later connections are still pinned ("trust on first use").
- **Where:** `discover`, `join_open`, `_open_join`, `/sync/hello` in `server/sync.py`; the code method
  (`create_invite`, `decide`) is kept in the code but not shown in the screens.
- **Watch out:** B lets any PC with the program in the network join – choose A again for bigger or open networks.
- 🇪🇬 **بالعربي:** طريقتين لإضافة جهاز: الآمنة (كود + رقم من 6 أرقام وموافقة الأدمن، زي البلوتوث)، والأسهل
  (المستخدمة دلوقتي لفريق صغير): الجهاز الجديد يدوّر على جهاز الأدمن في الشبكة لوحده وينضم على طول من غير كود ولا
  موافقة. الأسهل تنفع لفريق صغير موثوق بس.

### 2.4 Encrypted connections with "pinned" certificates
- **Idea:** each PC makes its own certificate; the others remember its fingerprint when it joins and accept only that one
  (no certificate authority needed, a fake PC in the middle is refused).
- **Where:** `server/tlscert.py`, `server/sync.py`.
- 🇪🇬 **بالعربي:** كل جهاز بيعمل شهادة أمان لنفسه، والباقي بيحفظوا بصمتها مرة واحدة عند الإقران. أي جهاز مزيف
  يحاول يقف في النص بيتكشف على طول.

### 2.5 Clone detection
- **Problem:** someone copies the data folder to a second PC → two PCs with the same identity.
- **Idea:** remember a machine fingerprint; if it changed, ask "same computer or a copy?".
- **Where:** `machine_fingerprint` in `server/node.py`.
- 🇪🇬 **بالعربي:** لو حد نسخ فولدر البيانات لجهاز تاني، البرنامج بيحس إن بصمة الجهاز اتغيّرت ويسأل "ده نفس الجهاز
  ولا نسخة على جهاز جديد؟".

---

## Chapter 3 – People, logins and permissions
## الفصل ٣ – الموظفين وتسجيل الدخول والصلاحيات

### 3.1 Personal link instead of user name and password
- **Problem:** factory staff forget passwords; installing software for everyone is heavy.
- **Idea:** every person gets a fixed secret link that logs them in under their own name.
- **How:** token = HMAC(secret key, person + random number); the PCs store only a hash of it. Opening the link shows a
  small page that logs in by itself from inside the page (a POST), so chat previews and virus scanners that only
  *read* the link never log anybody in. "New link" kills the old one at once on the administrator PC, and on
  every other PC as soon as it has shared changes with it (a PC that is off keeps the old link until then).
- **Where:** `server/auth.py` (links), `js/quick.js`.
- **Watch out:** a link never carries administrator rights (checked on every request, not only in the screen).
- 🇪🇬 **بالعربي:** بدل يوزر نيم وباسورد، كل موظف بياخد لينك ثابت بيدخّله باسمه على طول. اللينك ما بيدّيش صلاحيات
  أدمن أبداً، ولو ضاع تعمل لينك جديد يلغي القديم فوراً على جهاز الأدمن، وعلى باقي الأجهزة أول ما تتواصل معاه.

### 3.2 Tick boxes + profiles
- **Idea:** one tick per page and per action, grouped; ready-made profiles (Viewer, Data Entry…) tick them for you;
  dangerous rights in their own orange group that "Select all" never ticks.
- **Where:** `PERMISSIONS`, `ADMIN_PERMS` in `server/auth.py`; `permPicker` in `js/app.js`.
- **Watch out:** the server checks every request; hiding a button is only comfort.
- 🇪🇬 **بالعربي:** الصلاحيات علامات صح بسيطة لكل صفحة وكل حاجة، والبروفايلات الجاهزة بتعلّمها لوحدها. صلاحيات
  الأدمن الخطيرة في مجموعة منفصلة ما بتتعلّمش تلقائي أبداً.

### 3.3 Password and login safety kit
- Passwords stored only as salted PBKDF2 hashes; rules: length, letters + number, not the name.
- 5 wrong passwords → locked 15 minutes; max 10 failures per minute per address.
- Before login only small requests (64 kB) are read.
- Automatic logout after 30 minutes idle – but **not while the person is typing** (a long form is never lost).
- Tokens, passwords and keys never written into logs.
- **Where:** `server/auth.py`, `too_many_failures` in `server/app.py`.
- 🇪🇬 **بالعربي:** مجموعة أمان جاهزة لأي نظام: كلمات السر متشفرة، قفل الحساب بعد محاولات غلط، خروج تلقائي بعد
  عدم نشاط (بس مش وإنت بتكتب)، ومفيش باسورد أو مفتاح بيتسجّل في اللوجات أبداً.

### 3.4 Actions that only work on the PC itself
- **Idea:** first administrator, saving the key, choosing the backup folder: accepted only from `127.0.0.1`.
  Nobody on the network can do them, even with a stolen password.
- 🇪🇬 **بالعربي:** الحاجات الخطيرة جداً (أول حساب أدمن، تصدير المفتاح) بتشتغل بس من على الجهاز نفسه، حتى لو حد
  عنده الباسورد ومحاول من جهاز تاني.

---

## Chapter 4 – Data safety
## الفصل ٤ – أمان البيانات

### 4.1 Never erase, never roll back
- **Idea:** deletes only hide (Recycle Bin); "restore a backup" is saved as a **new** change that puts old values
  back – history and logs are never rolled back, and other PCs follow.
- **Where:** `Backups.restore` in `server/backup.py`, `Store.restore_from` / `Store.restore_txn` in `server/store.py`.
- 🇪🇬 **بالعربي:** عمرنا ما بنمسح حاجة فعلياً، بس بنخفيها (سلة المهملات). واسترجاع نسخة قديمة بيتسجّل كتغيير جديد،
  والتاريخ والسجلات ما بترجعش لورا أبداً.

### 4.2 Backups done right
- Automatic at start, every 6 hours when something changed, and before every risky action.
- Every backup is checked (`PRAGMA integrity_check`) before it counts.
- A second copy on another disk or USB drive (not a network folder: it contains password hashes).
- A warning card while backups exist on one disk only.
- 🇪🇬 **بالعربي:** نسخ احتياطية تلقائية بانتظام وقبل أي خطوة خطيرة، وكل نسخة بيتم فحصها إنها سليمة، ونسخة تانية
  على قرص خارجي علشان لو القرص الأساسي باظ.

### 4.3 Random ids, never "count + 1"
- **Problem:** two PCs offline both create "area 23" → they merge into one.
- **Idea:** random ids for everything created.
- 🇪🇬 **بالعربي:** أي حاجة جديدة بتاخد رقم عشوائي، مش رقم متسلسل، علشان جهازين ما ينشئوش نفس الرقم في نفس الوقت
  وهما أوفلاين.

### 4.4 One program per data folder
- **Idea:** a lock file; a second copy (autostart + double click) refuses to start instead of damaging data.
- **Where:** `lock_data` in `server/system.py`.
- 🇪🇬 **بالعربي:** ملف قفل بسيط يمنع نسختين من البرنامج يشتغلوا على نفس البيانات في نفس الوقت.

### 4.5 Upgrade in place
- **Idea:** on the first start of a new version: backup, check, convert, continue – the user sees nothing.
- 🇪🇬 **بالعربي:** أول تشغيل لإصدار جديد بياخد نسخة احتياطية ويفحص ويحوّل البيانات لوحده، من غير ما المستخدم
  يحس بأي حاجة.

### 4.5b Serial numbers: one record per piece, the count stays a counter
- **Problem:** the stock is a number (30 chairs); the customer wants the serial number of every piece. A list of
  serial numbers inside one record would lose pieces when two PCs add at the same time (last writer wins).
- **Idea:** every piece is its own small record (item, serial number, break area). Two PCs adding pieces keep both;
  a transfer only changes the break area of the record. The quantity stays the counter it was.
- **How:** new entity `pieces`; the inventory window asks the serial numbers when adding (one per line, a barcode
  scanner types them), asks *which* pieces when removing or transferring, and old → new serial when replacing.
  Duplicates are refused with the place where the number already is.
- **Where:** `server/store.py` (`pieces`), `js/app.js` (`invModal`, `serialModal`, `serialList`).
- 🇪🇬 **بالعربي:** كل قطعة ليها سجل لوحدها بالسيريال بتاعها، والعدد يفضل رقم زي ما هو. كده جهازين يضيفوا قطع في
  نفس الوقت محدش يمسح التاني، والنقل بيغيّر مكان القطعة بس. والباركود سكانر بيكتب السيريال لوحده.

### 4.6 Files by fingerprint
- **Idea:** photos and documents are named by their SHA-256; copying between PCs is resumable and a damaged copy is
  detected.
- 🇪🇬 **بالعربي:** الصور والملفات بتتسمى ببصمتها (SHA-256)، فنسخها بين الأجهزة يقدر يكمّل من نص الطريق، وأي نسخة
  تالفة بتتكشف.

---

## Chapter 5 – Delivery: installer, protection, releases
## الفصل ٥ – التسطيب وحماية الكود والإصدارات

### 5.1 One installer that installs *and* updates
- **Idea:** program in `C:\Program Files\BAMS`, data in `C:\ProgramData\BAMS`; the same `Setup.exe` replaces only
  the program, the data is never touched (not even by uninstall).
- **Tools:** Inno Setup (`installer/bams.iss`): stops the program, firewall rule, start with Windows.
- 🇪🇬 **بالعربي:** ملف تسطيب واحد بيسطّب أو يحدّث حسب الحالة، والبرنامج منفصل تماماً عن البيانات، فالتحديث عمره
  ما يلمس بيانات المستخدم.

### 5.2 No readable source code on the customer PC
- **Idea:** compile Python to machine code (Nuitka) and pack the web pages *inside* the `.exe`.
- **Where:** `tools/make_assets.py`, `tools/build_windows.py` (refuses to ship a `.py` file).
- 🇪🇬 **بالعربي:** بايثون بيتحوّل لملف تنفيذي واحد، وكل صفحات الويب بتتحط جواه، فمفيش كود مقروء على جهاز العميل.

### 5.3 Releases without any tools on your own PC
- **Idea:** GitHub Actions tests, builds the Windows installer and publishes it under Releases for every new
  version merged into `main` – nothing to install on your PC.
- **Where:** `.github/workflows/build.yml`, `docs/BUILD_AND_RELEASE.md`.
- 🇪🇬 **بالعربي:** GitHub بيعمل الاختبارات وبناء ملف التسطيب ونشره تلقائي مع كل نسخة جديدة، من غير ما تحتاج
  تنزّل أي أداة على جهازك.

### 5.4 Standard library only
- **Idea:** Python standard library + SQLite + plain JavaScript: nothing to install, nothing that breaks with updates.
- 🇪🇬 **بالعربي:** استخدام مكتبات بايثون الأساسية بس + SQLite + جافاسكريبت عادي، من غير أي مكتبات خارجية ممكن
  تتعطل مع الوقت.

---

## Chapter 6 – Simple screens for non-technical people
## الفصل ٦ – شاشات بسيطة لناس مش تقنيين

- One sentence per message, plain English, one clear action per screen.
- Technical details (sync light, warnings) only for administrators; others see "Please tell the administrator".
- First start asks: "empty system" or "try with sample data"; sample data is deleted in one step and only the
  sample records are deleted.
- A failed save keeps the form open with the text.
- A **Help page** of questions and answers with a search box, with extra topics for administrators.
- Buttons that cannot work on this PC are greyed out with the reason.
- 🇪🇬 **بالعربي:** جملة واحدة بسيطة لكل رسالة، فعل واحد واضح في كل شاشة. التفاصيل الفنية للأدمن بس. أول تشغيل
  بيسأل تبدأ فاضي ولا بعينة تجريبية. الحفظ اللي بيفشل ما بيضيّعش اللي كتبته. وفيه صفحة مساعدة بحث بسيط.

### 6.1 Recognise sample records by their fixed ids, not by their names
- **Problem:** people start real use by *renaming* the sample records ("Break Area 03" → "Main Canteen"). A check by
  name then says "no sample data left" – the delete button disappears and the fake issues, photos and surveys stay.
- **Idea:** give every sample record a short fixed id (`ba03`, `is12`, `ba03s81`) and every real record a random
  8-letter id. Delete by id: untouched sample areas completely, renamed ones keep the area, its inventory and
  everything added by hand, only their sample records go.
- **Where:** `js/app.js` (`SAMPLE_REC`, `sampleLeft`, `clearAll`), `js/data.js` (ids).
- **Reuse when:** any demo data that people may start to use for real.
- 🇪🇬 **بالعربي:** الناس بتبدأ الشغل الحقيقي بإنها تغيّر اسم البيانات التجريبية. متعرفش التجريبي من اسمه، اعرفه من
  رقمه الثابت. كده تمسح التجريبي بس وتسيب اللي الناس ضافته بإيديها.

### 1.5 Updates must never lose data (snapshot, verify, refuse newer)
- **Problem:** people keep working for months; an update must show exactly their data, and a wrong install (older program on newer data) must not damage anything.
- **Idea:** a small marker file says which program version and data model wrote the data. At start: newer data → refuse, touch nothing; version changed → verified snapshot of the databases,
  fingerprint of every table; after the update compare (old columns of old rows identical, no row lost, integrity ok, history append-only); only then go on. Changes that rewrite data
  must be registered migration steps that declare what they touch. The best test runs the REAL previous release on a data folder, then the new one.
- **Where:** `server/upgrade.py`, `T41_UpgradeKeepsData`, Settings → Data Safety.
- 🇪🇬 **بالعربي:** قبل أي تحديث البرنامج بيعمل نسخة متأكد منها، وبعد التحديث بيقارن كل سجل قديم بالجديد، وبيرفض يشتغل لو الداتا من نسخة أحدث. والاختبار الحقيقي بيشغّل النسخة القديمة بجد وبعدين الجديدة على نفس الملفات.

### 6.5 Import from Excel that cannot hurt
- **Problem:** people already have lists in Excel; typing them again is slow and a bad import can overwrite good data.
- **Idea:** find the columns by their names in any order, show a preview (what is new, what is left out and why), never change what exists (so the same file twice adds nothing), one saved change after a backup.
- **Where:** `server/excel_import.py`, `server/xlsx_read.py`, `importExcelModal` in `js/app.js`.
- 🇪🇬 **بالعربي:** استيراد من إكسل بيوريك المعاينة الأول، مابيغيّرش أي حاجة موجودة، فلو استوردت نفس الملف مرتين مفيش حاجة بتتكرر.

### 6.6 "Needs attention" and Ctrl K
- Put the few things a person must look at on the first screen (late work, urgent issues, warranties ending, a piece repaired 3 times); one keyboard shortcut searches everything.
- 🇪🇬 **بالعربي:** أهم الحاجات اللي محتاجة انتباه على أول شاشة، وCtrl K يدوّر في كل حاجة.

### 6.3 One time line per place: notes + work + issues + inspections
- **Problem:** "was this room painted? when was the last repair?" – the answer was spread over issues, maintenance, inspections and photos.
- **Idea:** one *Area Log*: free notes with a type (painting, renovation…) plus everything else merged into one list, newest first, printable.
  Work can be recorded after the fact ("record finished work") because people do not plan everything in advance.
- **Where:** `js/app.js` (`areaTimeline`, `areaLogCard`, `doneWorkModal`), reports *Area History* / *Maintenance & Work Done*.
- 🇪🇬 **بالعربي:** سجل واحد لكل مكان: ملاحظات (دهان، تجديد…) + كل الصيانة والأعطال والتفتيش في خط زمني واحد، وتقدر تسجّل شغل خلص من غير ما تجدوله الأول.

### 6.4 Hide a value everywhere, not only on screen (cost by permission)
- **Problem:** costs should not be seen by everybody; hiding a column in the screen still leaves them in the API, the change log and the Excel export.
- **Idea:** the server removes the value from every output for people without the right, and when such a person saves the record it puts the stored
  value back – so they can neither read, change nor erase it.
- **Where:** `server/app.py` (`hide_costs`, commit), `server/store.py` (`state(cost=)`, `strip_cost`, `export_sheets(cost=)`).
- 🇪🇬 **بالعربي:** إخفاء الرقم من الشاشة مش كفاية: لازم يتشال من الـ API وسجل التغييرات والإكسل، ولما حد ماله صلاحية يحفظ السجل الرقم القديم بيتحط تاني مكانه.

### 6.2 A window must never save "old" records
- **Problem:** a save fails ("someone else changed it"), the data is loaded again, the window stays open so nothing
  typed is lost – but the window still points at the *old* records. Pressing Save again said "saved" and saved nothing.
- **Idea:** every window remembers which data it was opened on and which button opened it. If the data was loaded
  again in between, the window is opened again on the new data and everything typed is put back.
- **Where:** `js/app.js` (`modal`, `reopenFresh`, `OPENER`).
- **Reuse when:** any app that keeps a form open after a failed save and reloads its data.
- 🇪🇬 **بالعربي:** لو الحفظ فشل والبيانات اتحدّثت، الشباك لازم يتفتح تاني على البيانات الجديدة ومعاه اللي كتبته،
  عشان مايقولش "اتحفظ" وهو ماحفظش حاجة.

### 6.7 A chart that stays readable with 5 or 80 categories (ranked list instead of columns)
- **Problem:** a column chart with one column per item type looked fine with 7 types; the real factory has 60, and the labels became
  10 px text on top of each other.
- **Idea:** show a ranked list – one row per category with icon, name, a short "why it matters" line, a bar and the number – largest first,
  the first 8 visible and the rest behind a **Show all** button.
- **How:** sort, slice, render rows; the hidden rows sit right before the button so "Show fewer" ends up at the bottom; the button has
  `aria-expanded`.
- **Where:** `rankList`, `equipmentReview`, `ACT.rankMore` in `js/app.js`.
- **Reuse when:** any "per category" overview whose number of categories the users decide. Watch out: test with the real number of categories.
- 🇪🇬 **بالعربي:** بدل أعمدة كتير مش مقروءة، قائمة مترتبة من الأكبر للأصغر، أول ٨ ظاهرين والباقي بزرار "Show all".

### 6.8 KPI cards that explain themselves
- **Problem:** five bare numbers; a manager still had to dig for "is something wrong?".
- **Idea:** every card = icon + title + number + one line of context ("2 with high priority", "in 22 break areas"); problem cards turn green
  when there is nothing to do; a click opens the page with the details. Cards a person may not see are replaced by others, so the row stays full.
- **Where:** `dashKpis`, `kpiCard`, `pageHref` in `js/app.js`.
- 🇪🇬 **بالعربي:** كل كارت فيه سطر صغير بيشرح الرقم، ولونه أخضر لو مفيش مشكلة، ولو دوست عليه يفتح الصفحة اللي فيها التفاصيل.

### 6.10 A web program that feels like a desktop app (Edge app mode)
- **Problem:** people asked for "a separate app", not a browser tab; a real desktop framework would mean another runtime to ship and secure.
- **Idea:** start the browser that every Windows PC has in *app mode*: `msedge --app=http://localhost:8080/ --user-data-dir=<own folder>`.
- **How:** own window without tabs or address bar, own taskbar entry with the page icon (a PNG file – an inline SVG is ignored there), own profile
  so it never mixes with the person's tabs; fall back to the normal browser.
- **Where:** `server/appwindow.py`. **Watch out:** the session lives in that own profile (log in once there).
- 🇪🇬 **بالعربي:** البرنامج يفتح في شباك لوحده زي أي برنامج، باستخدام Edge في وضع "App" من غير تابات ولا شريط عنوان.

### 6.11 One drawing for every icon (desktop, taskbar, screens, print)
- **Idea:** describe the logo once as simple shapes; render it to `.ico`/PNG in pure Python and use the same shapes as inline SVG; a test
  compares them. **Where:** `tools/make_icon.py`, `APP_MARK`.
- 🇪🇬 **بالعربي:** اللوجو مرسوم مرة واحدة ويطلع منه أيقونة الويندوز والصورة والـ SVG، والاختبار يتأكد إنهم شبه بعض.

### 6.12 A command bar: "+ New" from anywhere, menu as icons
- **Idea:** the everyday jobs in one menu on every page, filtered by permission; jobs for one place use the open place or ask which one. A
  sidebar that collapses to icons (with tool tips) gives room on small screens; the choice is remembered before the page is drawn.
- **Where:** `quickItems`, `quickNew`, `popMenu`, `toggleNav` in `js/app.js`, `js/boot.js`.
- 🇪🇬 **بالعربي:** زرار "New" فيه كل الشغل اليومي من أي صفحة، والقائمة الجانبية ممكن تبقى أيقونات بس.

### 6.9 A big icon set that people can actually search (names never change)
- **Problem:** 600 icons are useless if you have to scroll through them; and an item type stores the icon *name*, so renaming breaks old data.
- **Idea:** generate the pack from an open icon set with its search words (tags); suggest icons from the name the person types; keep every
  name that was ever shipped.
- **How:** `tools/make_icons.py` reads Lucide's SVGs and `tags.json`, writes `ICON_PACK`, `ICON_GROUPS`, `ICON_TAGS`; a unit test fails if an old
  name disappears. The picker scores icons by name and tag words (plural → singular) and picks the best one until the person clicks.
- **Where:** `tools/make_icons.py`, `js/icons.js`, `iconSuggestions` / `iconMatches` in `js/app.js`, `IconPackTest`.
- 🇪🇬 **بالعربي:** ٦٠٠ أيقونة ومعاها كلمات بحث، والبرنامج بيقترح الأيقونة من اسم الصنف، وأسماء الأيقونات القديمة عمرها ما تتغير.

---

## Chapter 7 – How we work (the method)
## الفصل ٧ – طريقة الشغل

- **Project memory in the repo:** `CLAUDE.md` (rules), a project skill (`.claude/skills/…/SKILL.md`: how the program
  works, pitfalls), `DEVELOPMENT_HISTORY.md` (what, why, mistakes, lessons), this `IDEAS.md`.
- **Tests on three levels:** fast unit tests; real multi-PC tests (several programs, a network cable that can be
  "unplugged" by a proxy); a real browser test (Playwright). A regression test for every bug.
- **Review loop:** independent reviewer + automatic PR reviews (Codex/Claude) → verify each finding → fix → test →
  write the lesson. Wait for the automatic reviews before merging, not only for green checks.
- **Branch → pull request → merge only when the owner says so.** Never force-push, never rewrite history.
- 🇪🇬 **بالعربي:** ذاكرة المشروع محفوظة جوه الريبو نفسه (قواعد، مهارة، تاريخ، أفكار). اختبارات على 3 مستويات.
  مراجعة مستقلة + مراجعات تلقائية قبل أي دمج. فرع → Pull Request → دمج بس لما صاحب المشروع يوافق.

---

## Technologies used (quick list) / التكنولوجيات المستخدمة

| Technology | Used for / بتُستخدم في |
|---|---|
| Python 3 (standard library only) | server, sync, security |
| SQLite | data, history (journal), accounts |
| Plain JavaScript + HTML + CSS | all screens (no framework) |
| Ed25519 signatures, SHA-256, HMAC, PBKDF2 | signing changes, file fingerprints, links, passwords |
| TLS 1.3 with pinned certificates | PC-to-PC connections |
| Hybrid logical clock, version vectors | ordering and exchanging changes |
| Nuitka | compiling Python to a protected `.exe` |
| Inno Setup | Windows installer |
| GitHub Actions | tests, Windows build, automatic releases |
| Playwright + Chromium | browser tests |
