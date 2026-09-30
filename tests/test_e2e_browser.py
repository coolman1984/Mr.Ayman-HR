"""Browser end-to-end test with a real Chromium: first setup, pairing a second PC through the screens,
login on the second PC, permissions, live changes, sync light, Devices & Sync, conflicts and logs.
Skipped when Playwright is not installed (it is only needed for testing, never at runtime)."""
import os
import unittest

from harness import ADMIN, Server, make_authority, wait_until

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

CHROME = next((p for p in ('/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell',) if os.path.exists(p)), None)
SHOTS = os.environ.get('BAMS_SCREENSHOTS')


@unittest.skipIf(sync_playwright is None, 'playwright not installed')
class BrowserFlow(unittest.TestCase):
    def setUp(self):
        self.A = Server('Admin-PC').start()
        self.B = Server('Store-PC').start()
        self.errors = []

    def tearDown(self):
        for s in (self.A, self.B):
            s.cleanup()

    def page(self, browser, name):
        ctx = browser.new_context(viewport={'width': 1400, 'height': 900})
        p = ctx.new_page()
        p.on('console', lambda m: m.type == 'error' and self.errors.append(f'{name}: {m.text}'))
        p.on('pageerror', lambda e: self.errors.append(f'{name}: {e}'))
        p.on('dialog', lambda d: d.accept())
        return p

    def shot(self, p, name):
        if SHOTS:
            os.makedirs(SHOTS, exist_ok=True)
            p.screenshot(path=os.path.join(SHOTS, name + '.png'), full_page=True)

    def test_two_pcs_through_the_screens(self):
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME) if CHROME else pw.chromium.launch()
            a = self.page(browser, 'A')
            b = self.page(browser, 'B')
            # ---- first PC: create the administrator
            a.goto(self.A.base)
            a.get_by_text('This is the first (or only) PC').click()
            a.fill('input[name=full_name]', 'Ayman Essam')
            a.fill('input[name=username]', 'ayman')
            a.fill('input[name=password]', 'Strong-pass1')
            a.fill('input[name=password2]', 'Strong-pass1')
            a.get_by_role('button', name='Create Administrator').click()
            # first start: the administrator chooses empty or sample data (sample data is never loaded by itself)
            a.get_by_text('Try it with sample data first').click()
            a.wait_for_selector('text=Break Area 01', timeout=30000)
            self.shot(a, '01-admin-dashboard')
            # ---- Help & User Guide: from Settings, admin answers included, search works
            a.goto(self.A.base + '/#/settings')
            a.wait_for_selector('text=Delete Sample Data')
            a.locator('a.help-card').click()
            a.wait_for_selector('text=How do I add a person?')
            a.wait_for_selector('text=How do I give someone administrator rights (a deputy)?')
            a.fill('#helpQ', 'sample data')
            a.wait_for_selector('text=How do I delete the sample data?')
            self.assertEqual(a.locator('text=How do I add a person?').count(), 0, 'search filters the answers')
            self.shot(a, '01b-help')
            self.assertTrue(a.locator('#syncInd').is_hidden(), 'no sync light while only one PC exists')
            # ---- Devices & Sync: no "Add a PC" any more (joining needs nothing on the administrator PC)
            a.goto(self.A.base + '/#/devices')
            a.wait_for_selector('text=Only this PC')
            self.assertEqual(a.get_by_role('button', name='Add a PC').count(), 0)
            self.shot(a, '02-devices-single')
            # ---- second PC: join with the administrator PC's address only (the search cannot find test servers on
            # their random ports, so the address is typed; in an office the search fills it in)
            b.goto(self.B.base)
            b.get_by_text('Join an existing system').click()
            b.fill('input[name=name]', 'Store PC')
            b.fill('input[name=address]', self.A.sync_address)
            self.shot(b, '03-join')
            b.get_by_role('button', name='Join').click()
            b.wait_for_selector('#loginForm', timeout=60000)
            b.fill('input[name=username]', 'ayman')
            b.fill('input[name=password]', 'Strong-pass1')
            b.get_by_role('button', name='Log In').click()
            b.wait_for_selector('text=Break Area 01', timeout=30000)
            self.shot(b, '05-store-pc-dashboard')
            # ---- a normal user created on the administrator PC can log in on the second PC
            r = a.evaluate("""() => fetch('/api/users/save', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({
                username: 'sara', full_name: 'Sara Mostafa', password: 'Blue-sky551', must_change: false, role: 'Viewer',
                perms: ['dashboard.view', 'areas.view', 'reports.view'], areas: null})}).then(r => r.json())""")
            self.assertEqual(r.get('username'), 'sara', r)
            wait_until(lambda: self._login_ok(self.B, 'sara', 'Blue-sky551'), 30, what='sara on store pc')
            s = self.page(browser, 'Sara')
            s.goto(self.B.base)
            s.fill('input[name=username]', 'sara')
            s.fill('input[name=password]', 'Blue-sky551')
            s.get_by_role('button', name='Log In').click()
            s.wait_for_selector('text=Break Area 01', timeout=20000)
            nav = s.locator('#sidebar').inner_text()
            self.assertNotIn('Users', nav)
            self.assertNotIn('Devices', nav)
            self.assertTrue(s.locator('#syncInd').is_hidden(), 'ordinary users are not shown the sync light')
            s.goto(self.B.base + '/#/devices')
            s.wait_for_selector('text=No access')
            code = s.evaluate("() => fetch('/api/devices').then(r => r.status)")
            self.assertEqual(code, 403, 'the monitoring API itself refuses ordinary users')
            self.shot(s, '06-viewer-no-access')
            s.close()  # (a page left open would log "connection refused" while the test switches PCs off)
            # ---- a change on the second PC appears on the first; both lights green
            b.evaluate("""() => fetch('/api/commit', {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({label: 'Add break area', ops: [{e: 'areas', id: 'e2e1', op: 'put', row: {name: 'Canteen East', location: 'Admin', status: 'Good'}}]})})""")
            a.goto(self.A.base + '/#/areas')
            a.wait_for_selector('text=Canteen East', timeout=30000)
            wait_until(lambda: 'All PCs up to date' in a.locator('#syncInd').inner_text(), 30, what='green light on A')
            wait_until(lambda: 'All PCs up to date' in b.locator('#syncInd').inner_text(), 30, what='green light on B')
            self.shot(a, '07-synced-areas')
            a.goto(self.A.base + '/#/devices')
            a.wait_for_selector('text=Same data', timeout=20000)
            self.shot(a, '08-devices-ok')
            # ---- the second PC is switched off: calm "working on this PC" message, never red
            self.B.kill()
            a.reload()
            wait_until(lambda: 'Working on this PC' in a.locator('#syncInd').inner_text(), 60, what='offline light')
            self.shot(a, '09-other-pc-off')
            # ---- conflict: same field changed on both PCs while they cannot reach each other
            self.B.start()
            for p in (a, b):
                pass
            b2 = self.page(browser, 'B2')
            b2.goto(self.B.base)
            b2.fill('input[name=username]', 'ayman')
            b2.fill('input[name=password]', 'Strong-pass1')
            b2.get_by_role('button', name='Log In').click()
            b2.wait_for_selector('text=Break Area 01', timeout=30000)
            wait_until(lambda: 'All PCs up to date' in a.evaluate("() => fetch('/api/version').then(r => r.json()).then(v => SYNC_TEXT[v.sync.state][0])"), 60,
                       what='reconnected')
            b.close()
            b2.close()  # (pages on the store PC would log "connection refused" while it is switched off below)
            self.errors.clear()
            # the conflict page, the logs with PC column
            a.goto(self.A.base + '/#/devices')
            a.get_by_role('button', name='To decide').click()
            a.wait_for_selector('text=No conflicts')
            a.goto(self.A.base + '/#/logs')
            a.wait_for_selector('.log-tbl td:has-text("Canteen East")', timeout=20000)
            self.assertIn('Store PC', a.locator('.log-tbl').inner_text())
            self.shot(a, '10-logs-with-pc')
            a.get_by_role('button', name='Logins & Security').click()
            a.wait_for_selector('.log-tbl span:has-text("PC added")', timeout=20000)
            self.shot(a, '11-security-log')
            # ---- a real conflict: both PCs change the same field while they cannot reach each other
            a_id = a.evaluate("() => fetch('/api/me').then(r => r.json()).then(m => m.node.id)")
            port = self.B.sync_port
            self.B.stop()
            self.B.set_cfg(peer_addresses={a_id: '127.0.0.1:9'}, sync_port=port + 1 if port < 65000 else port - 1)
            self.B.start()
            edit = """desc => fetch('/api/state').then(r => r.json()).then(s => { const x = s.areas.find(y => y.id === 'e2e1');
                const row = Object.fromEntries(Object.entries(x).filter(([k, v]) => !Array.isArray(v) && k !== 'ver'));
                return fetch('/api/commit', {method: 'POST', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({label: 'Edit break area', ops: [{e: 'areas', id: 'e2e1', op: 'put', ver: x.ver, row: {...row, description: desc}}]})}).then(r => r.status); })"""
            self.assertEqual(a.evaluate(edit, 'Opened on Monday'), 200)
            b3 = self.page(browser, 'B3')
            b3.goto(self.B.base)
            b3.fill('input[name=username]', 'ayman')
            b3.fill('input[name=password]', 'Strong-pass1')
            b3.get_by_role('button', name='Log In').click()
            b3.wait_for_selector('text=Break Area 01', timeout=30000)
            self.assertEqual(b3.evaluate(edit, 'Opened on Tuesday'), 200)
            b3.close()
            self.B.stop()
            self.B.set_cfg(peer_addresses={}, sync_port=port)
            self.B.start()
            a.goto(self.A.base + '/#/devices')
            a.get_by_role('button', name='To decide').click()
            try:
                wait_until(lambda: (a.get_by_role('button', name='To decide').click(), a.wait_for_timeout(1500), a.locator('.card.conflict').count())[2], 60, 1, what='conflict shown')
            except AssertionError:
                self.shot(a, '12-conflict-missing')
                raise AssertionError(f'conflict not shown; console: {self.errors}; api: ' + str(a.evaluate("() => fetch('/api/conflicts').then(r => r.text())")))
            self.shot(a, '12-conflict')
            text = a.locator('.card.conflict').inner_text()
            self.assertIn('Opened on Monday', text)
            self.assertIn('Opened on Tuesday', text)
            a.locator('.card.conflict tr:has-text("Opened on Tuesday") button').click()
            a.wait_for_selector('text=No conflicts', timeout=20000)
            wait_until(lambda: self._desc(self.B) == 'Opened on Tuesday', 30, what='resolution reached the store PC')
            browser.close()
        self.assertEqual(self.errors, [], 'browser console errors')

    def test_serial_numbers_and_renamed_sample_area(self):
        """Customer reports of 2.4: (1) after renaming a sample break area the Delete Sample Data button disappeared and the
        sample records stayed; (2) every piece should carry its serial number."""
        make_authority(self.A)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME) if CHROME else pw.chromium.launch()
            a = self.page(browser, 'A')
            a.goto(self.A.base)
            a.fill('input[name=username]', ADMIN[0])
            a.fill('input[name=password]', ADMIN[1])
            a.get_by_role('button', name='Log In').click()
            a.get_by_text('Try it with sample data first').click()
            a.wait_for_selector('text=Break Area 01', timeout=30000)
            submit = lambda: a.click('#modal .modal-f .primary')
            closed = lambda: a.wait_for_selector('#modal.open', state='detached', timeout=15000)
            # every sample break area renamed: the button stays, the renamed break areas stay, their sample records go
            a.evaluate("async () => { DB.areas.forEach(x => (x.name = 'Canteen ' + x.id)); await save('rename all', { force: true }); }")
            a.goto(self.A.base + '/#/area/ba03')
            a.wait_for_selector('text=Canteen ba03')
            # serial numbers: two TV screens with their serial numbers; the quantity follows the list
            a.click('.page-head button[data-act=invModal]')
            a.select_option('#modal select[name=item]', 'tv')
            a.fill('#modal textarea[name=serials]', 'TV-7001\nTV-7002')
            self.assertEqual(a.input_value('#modal input[name=qty]'), '2')
            submit()
            closed()
            a.wait_for_selector('.serial-chips >> text=TV-7002')
            # removing fewer pieces than have a serial number asks which one goes
            a.click('.page-head button[data-act=invModal]')
            a.select_option('#modal select[name=item]', 'tv')
            a.select_option('#modal select[name=action]', 'Removed')
            a.fill('#modal input[name=qty]', '2')  # 3 TV screens, 2 with a serial number: 1 of them must go
            submit()
            a.wait_for_selector('#toast.error')
            a.check('#modal input[name=pick] >> nth=0')
            submit()
            closed()
            self.assertEqual(a.evaluate("area('ba03').pieces.map(p => p.serial)"), ['TV-7002'])
            a.goto(self.A.base + '/#/equipment')
            a.fill('input[data-f="serial.q"]', '7002')
            a.wait_for_selector('tbody[data-results=serial] >> text=Canteen ba03')
            # a real record of the very first program version with a short id like the sample ones (review of 2.5) stays
            a.evaluate("async () => { DB.history.push({ id: 'h121', seq: 121, areaId: 'ba03', date: '2026-01-05', item: 'tv', action: 'Added', prev: 0, next: 1, details: 'Real work', by: 'Ayman' }); await save('old real record'); }")
            a.goto(self.A.base + '/#/settings')
            a.evaluate("window.prompt = () => 'DELETE'")  # the confirmation asks to type DELETE
            a.click('button[data-act=clearAll]')
            a.wait_for_selector('text=Sample data deleted')
            left = a.evaluate("({ n: DB.areas.length, recs: DB.areas.reduce((s, x) => s + x.photos.length + x.issues.length + x.surveys.length + x.inspections.length + x.maintenance.length, 0), pieces: area('ba03').pieces.length, hist: DB.history.filter(h => /^h\\d+$/.test(h.id)).map(h => h.id) })")
            self.assertEqual(left, {'n': 22, 'recs': 0, 'pieces': 1, 'hist': ['h121']})
            a.goto(self.A.base + '/#/settings')
            a.wait_for_selector('text=Server & Database')
            self.assertEqual(a.locator('button[data-act=clearAll]').count(), 0, 'nothing of the sample data is left')
            self.assertEqual(self.errors, [])
            browser.close()

    def test_save_again_after_a_conflict(self):
        """Review of 2.4: after "changed by another user" the window stayed open on the old records; pressing Save again
        said "Inventory updated" but saved nothing (only a wrong transaction line). Now it opens again on the new data."""
        make_authority(self.A)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME) if CHROME else pw.chromium.launch()
            a = self.page(browser, 'A')
            a.goto(self.A.base)
            a.fill('input[name=username]', ADMIN[0])
            a.fill('input[name=password]', ADMIN[1])
            a.get_by_role('button', name='Log In').click()
            a.get_by_text('Try it with sample data first').click()
            a.wait_for_selector('text=Break Area 01', timeout=30000)
            a.goto(self.A.base + '/#/area/ba01')
            a.click('.page-head button[data-act=invModal]')
            a.fill('#modal input[name=qty]', '5')
            a.fill('#modal textarea[name=details]', 'From supplier X')
            # meanwhile somebody else changes the chairs of this break area
            other = self.A.client()
            other.login(*ADMIN)
            inv = next(x for x in next(x for x in other.get('/api/state')['areas'] if x['id'] == 'ba01')['inventory'] if x['item'] == 'chairs')
            other.post('/api/commit', {'label': 'other', 'ops': [{'e': 'inventory', 'id': inv['id'], 'op': 'put', 'ver': inv['ver'],
                                                                   'row': {**{k: v for k, v in inv.items() if k != 'ver'}, 'areaId': 'ba01', 'qty': inv['qty'] + 1}}]})
            a.click('#modal .modal-f .primary')
            a.wait_for_selector('#toast.error >> text=Not saved')
            a.click('#modal .modal-f .primary')
            a.wait_for_selector('#toast.error >> text=window shows the new data')
            self.assertEqual(a.input_value('#modal input[name=qty]'), '5', 'what was typed is kept')
            self.assertEqual(a.input_value('#modal textarea[name=details]'), 'From supplier X')
            a.click('#modal .modal-f .primary')
            a.wait_for_selector('#modal.open', state='detached', timeout=15000)
            self.assertEqual(a.evaluate("qty(area('ba01'), 'chairs')"), inv['qty'] + 6)
            # closing an issue records its closed date (review of 2.5: the date was lost)
            iid = a.evaluate("area('ba03').issues.find(i => i.status !== 'Closed').id")
            a.goto(self.A.base + '/#/area/ba03')
            a.click(f'button[data-act=issueView][data-iid="{iid}"]')
            a.select_option('#modal select[name=status]', 'Closed')
            a.click('#modal .modal-f .primary')
            a.wait_for_selector('#modal.open', state='detached', timeout=15000)
            self.assertEqual(a.evaluate(f"area('ba03').issues.find(i => i.id === '{iid}').closedDate"), a.evaluate('today()'))
            # the record is deleted by someone else while the window is open: a clear message, no silent crash
            a.click('.page-head button[data-act=editArea]')
            a.fill('#modal input[name=name]', 'Canteen Three')
            other.post('/api/commit', {'label': 'gone', 'ops': [{'e': 'areas', 'id': 'ba03', 'op': 'del', 'ver': next(x for x in other.get('/api/state')['areas'] if x['id'] == 'ba03')['ver']}]})
            a.click('#modal .modal-f .primary')
            a.wait_for_selector('#toast.error >> text=Not saved')
            a.click('#modal .modal-f .primary')
            a.wait_for_selector('#toast.error >> text=deleted this in the meantime')
            self.assertEqual([e for e in self.errors if '409 (Conflict)' not in e], [])
            browser.close()

    def test_area_log_finished_work_and_repeats(self):
        """2.6 (customer's request): notes for a break area, finished work with cost / warranty / related issue, cancel instead of
        delete, repeating work, piece history by serial number, the Area History report."""
        make_authority(self.A)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME) if CHROME else pw.chromium.launch()
            a = self.page(browser, 'A')
            a.goto(self.A.base)
            a.fill('input[name=username]', ADMIN[0])
            a.fill('input[name=password]', ADMIN[1])
            a.get_by_role('button', name='Log In').click()
            a.get_by_text('Try it with sample data first').click()
            a.wait_for_selector('text=Break Area 01', timeout=30000)
            submit = lambda: (a.click('#modal .modal-f .primary'), a.wait_for_selector('#modal.open', state='detached', timeout=15000))
            a.goto(self.A.base + '/#/area/ba03')
            a.wait_for_selector('h3:text-is("Area Log")')
            # a note: add, edit, delete
            a.click('button[data-act=noteModal]:not([data-nid])')
            a.select_option('#modal select[name=kind]', 'Painting')
            a.fill('#modal textarea[name=text]', 'Walls painted grey')
            submit()
            a.wait_for_selector('.tl-text >> text=Walls painted grey')
            a.click('.tl-row:has-text("Walls painted grey") button[data-act=noteModal]')
            a.fill('#modal textarea[name=text]', 'Walls painted light grey')
            submit()
            a.wait_for_selector('.tl-text >> text=light grey')
            a.click('.tl-row:has-text("light grey") button[data-act=noteDelete]')
            a.wait_for_selector('.tl-text >> text=light grey', state='detached')
            # finished work with cost and warranty, solving an open issue (the issue closes with it)
            open_before = a.evaluate("area('ba03').issues.filter(i => i.status !== 'Closed').length")
            a.click('button[data-act=workModal]')
            a.fill('#modal textarea[name=details]', 'Replaced the chair cushions')
            a.fill('#modal input[name=cost]', '4500')
            a.fill('#modal input[name=warrantyUntil]', '2030-01-01')
            a.select_option('#modal select[name=issueId]', index=1)
            submit()
            got = a.evaluate("(() => { const m = area('ba03').maintenance.find(x => x.details === 'Replaced the chair cushions'); return [m.status, m.cost, m.kind, area('ba03').issues.filter(i => i.status !== 'Closed').length]; })()")
            self.assertEqual(got, ['Done', 4500, 'Repair', open_before - 1])
            # repeating work: completing it plans the next one, 31 January + 1 month is the end of February
            self.assertEqual(a.evaluate("addMonths('2026-01-31', 1)"), '2026-02-28')
            a.click('.card-h button[data-act=maintModal]')
            a.fill('#modal textarea[name=details]', 'Clean the air filters')
            a.select_option('#modal select[name=repeatMonths]', '3')
            submit()
            mid = a.evaluate("area('ba03').maintenance.find(x => x.details === 'Clean the air filters').id")
            a.click(f'.tbl button[data-act=maintDone][data-mid="{mid}"]')
            submit()
            self.assertEqual(a.evaluate("area('ba03').maintenance.filter(x => x.details === 'Clean the air filters').map(x => x.status).sort()"), ['Done', 'Scheduled'])
            # cancel keeps the work in the history
            nid = a.evaluate("area('ba03').maintenance.find(x => x.details === 'Clean the air filters' && x.status === 'Scheduled').id")
            a.click(f'button[data-act=maintCancel][data-mid="{nid}"]')
            a.fill('#modal textarea[name=reason]', 'not needed')
            submit()
            self.assertEqual(a.evaluate(f"area('ba03').maintenance.find(x => x.id === '{nid}').status"), 'Cancelled')
            # piece history by serial number
            a.goto(self.A.base + '/#/area/ba01')
            a.click('button[data-act=serialModal][data-item=tv]')
            a.fill('#modal textarea[name=serials]', 'TV-55-1')
            submit()
            a.click('button[data-act=workModal]')
            a.select_option('#modal select[name=item]', 'tv')
            a.select_option('#modal select[name=serial]', 'TV-55-1')
            a.fill('#modal textarea[name=details]', 'Power board replaced')
            submit()
            a.click('button[data-act=pieceHistory]')
            a.wait_for_selector('#modal .tl-text >> text=Power board replaced')
            self.assertIn('Repairs so far', a.inner_text('#modal'))
            a.click('#modal .modal-f button[data-act=closeModal]')
            # the Area History report has the entries
            self.assertGreaterEqual(a.evaluate("REPORTS.areahistory.rows('', '', 'ba03').length"), 5)
            a.goto(self.A.base + '/#/maintenance')
            a.wait_for_selector('text=Work Due Soon or Late')
            self.assertEqual(self.errors, [])
            browser.close()

    def test_plans_search_icons_import_and_data_safety(self):
        """2.6: future plans (schedule it, complete the work, the plan is done), Ctrl K search, the icon picker, the Excel import
        with its preview, the Needs Attention card and the Data Safety card."""
        import excel_import
        import xlsx
        make_authority(self.A)
        xlsx_path = os.path.join(self.A.root, 'import.xlsx')
        with open(xlsx_path, 'wb') as f:
            f.write(xlsx.build([(n, h, r) for n, (h, r) in excel_import.TEMPLATE.items()]))
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME) if CHROME else pw.chromium.launch()
            a = self.page(browser, 'A')
            a.goto(self.A.base)
            a.fill('input[name=username]', ADMIN[0])
            a.fill('input[name=password]', ADMIN[1])
            a.get_by_role('button', name='Log In').click()
            a.get_by_text('Try it with sample data first').click()
            a.wait_for_selector('text=Break Area 01', timeout=30000)
            submit = lambda: (a.click('#modal .modal-f .primary'), a.wait_for_selector('#modal.open', state='detached', timeout=15000))
            # the dashboard: attention card; the search button is there
            a.wait_for_selector('h3:text-is("Needs Attention")')
            self.assertTrue(a.locator('#searchBtn').is_visible())
            # future plans: add, schedule it (the dialog is filled in), complete the work -> the plan is done
            a.goto(self.A.base + '/#/area/ba02')
            a.click('button[data-act=planModal]:not([data-pid])')
            a.fill('#modal input[name=title]', 'Repaint the walls')
            a.fill('#modal input[name=targetDate]', '2030-03-01')
            submit()
            a.wait_for_selector('.plan-row >> text=Repaint the walls')
            a.click('.plan-row:has-text("Repaint the walls") button[data-act=planSchedule]')
            self.assertEqual(a.input_value('#modal textarea[name=details]'), 'Repaint the walls')
            self.assertEqual(a.input_value('#modal input[name=date]'), '2030-03-01')
            submit()
            pid = a.evaluate("area('ba02').plans.find(p => p.title === 'Repaint the walls').maintId")
            self.assertTrue(pid)
            a.click(f'.card button[data-act=maintDone][data-mid="{pid}"]')
            submit()
            self.assertEqual(a.evaluate("area('ba02').plans.find(p => p.title === 'Repaint the walls').status"), 'Done')
            self.assertEqual(a.evaluate("[stableHash('x'.repeat(300)).length, stableHash('a') === stableHash('a'), stableHash('a') === stableHash('b')]"), [12, True, False])
            # search everything: Ctrl K does not open behind a window; Esc closes only the search
            a.goto(self.A.base + '/#/area/ba02')
            a.click('button[data-act=noteModal]:not([data-nid])')
            a.keyboard.press('Control+k')
            self.assertEqual(a.locator('#palQ').count(), 0)
            a.click('#modal .modal-f button[data-act=closeModal]')
            a.goto(self.A.base + '/#/dashboard')
            a.keyboard.press('Control+k')
            a.wait_for_selector('#palQ')
            a.fill('#palQ', 'break area 07')
            a.keyboard.press('Enter')
            a.wait_for_url('**/#/area/ba07')
            # the icon picker: search, choose, saved
            a.goto(self.A.base + '/#/equipment')
            a.click('button[data-act=itemTypeModal]:not([data-tid])')
            a.fill('#modal input[name=name]', 'Kettles')
            a.fill('#modal .ico-search', 'kettle')
            a.click('#modal .ico-pick[data-ico=kettle]')
            submit()
            self.assertEqual(a.evaluate("itemType('kettles').icon"), 'kettle')
            # the Excel import: preview then import; a second import adds nothing
            a.goto(self.A.base + '/#/areas')
            a.click('button[data-act=importExcel]')
            a.set_input_files('#modal input[type=file]', xlsx_path)
            a.wait_for_selector('text=What the import would add')
            self.assertIn('Canteen East', a.inner_text('#modal'))
            submit()
            self.assertEqual(a.evaluate("area(DB.areas.find(x => x.name === 'Canteen East').id).pieces.map(p => p.serial).sort()"), ['TV-55-0142', 'TV-55-0143'])
            a.click('button[data-act=importExcel]')
            a.set_input_files('#modal input[type=file]', xlsx_path)
            a.wait_for_selector('text=Nothing new to import')
            # data safety
            a.goto(self.A.base + '/#/settings')
            a.wait_for_selector('h3:text-is("Data Safety")')
            a.click('button[data-act=dataCheck]')
            a.wait_for_selector('#toast >> text=All good')
            self.assertEqual(self.errors, [])
            browser.close()

    def test_font_and_text_size_choice(self):
        """2.6: Settings -> Appearance: six bundled fonts, six text sizes, kept on this PC (also after a reload), the Aa button, fonts served by the program."""
        make_authority(self.A)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME) if CHROME else pw.chromium.launch()
            a = self.page(browser, 'A')
            a.goto(self.A.base)
            a.fill('input[name=username]', ADMIN[0])
            a.fill('input[name=password]', ADMIN[1])
            a.get_by_role('button', name='Log In').click()
            a.get_by_text('Start with my real data').click()
            a.wait_for_selector('#modal.open', state='detached', timeout=30000)  # the start sets the page itself when it is finished
            body = lambda prop: a.evaluate("p => getComputedStyle(document.body)[p]", prop)
            self.assertEqual(body('fontSize'), '13px')
            a.goto(self.A.base + '/#/settings')
            a.wait_for_selector('h3:text-is("Appearance")')
            a.click('.font-card.f-inter')
            self.assertIn('Inter', body('fontFamily'))
            self.assertTrue(a.evaluate("document.fonts.load('16px \"Inter\"').then(f => f.length > 0)"), 'the font file is loaded from the program')
            a.click('button[data-act=lookSize][data-step="1"]')
            a.click('button[data-act=lookSize][data-step="1"]')
            self.assertEqual(body('fontSize'), '15.6px')
            self.assertIn('Large', a.inner_text('.look-now'))
            a.reload()
            a.wait_for_selector('h3:text-is("Appearance")')
            self.assertEqual((body('fontSize'), 'Inter' in body('fontFamily')), ('15.6px', True), 'kept after a reload, before the page is drawn')
            a.click('.font-card.f-serif')
            self.assertIn('Merriweather', body('fontFamily'))
            a.click('#fontBtn')
            a.wait_for_selector('h2:text-is("My Account")')
            a.wait_for_selector('h3:text-is("Appearance")')
            a.click('button[data-act=lookReset]')
            self.assertEqual(body('fontSize'), '13px')
            self.assertNotIn('Merriweather', body('fontFamily'))
            # served like the rest of the program: known folder, right type, nothing outside it
            ok = a.evaluate("fetch('/fonts/inter-latin-wght-normal.woff2').then(r => [r.status, r.headers.get('content-type')])")
            self.assertEqual(ok, [200, 'font/woff2'])
            self.assertEqual(a.evaluate("fetch('/fonts/../config.json').then(r => r.status)"), 404)
            self.assertEqual(a.evaluate("fetch('/fonts/nothing.woff2').then(r => r.status)"), 404)
            self.assertEqual([e for e in self.errors if '404' not in e], [])  # the two 404 above are the point of the test
            browser.close()

    def test_new_pc_screens_and_instructions(self):
        """The field report (no data on the new user's PC): join comes first and says who it is for, choosing "first PC" asks to make sure,
        the address is checked while typing, the administrator gets honest instructions for a person with a user name and password,
        and a PC set up alone by mistake can move into the company system."""
        make_authority(self.A)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME) if CHROME else pw.chromium.launch()
            # --- the new PC
            b = browser.new_context(viewport={'width': 1300, 'height': 850}).new_page()
            asked = []
            b.on('dialog', lambda d: (asked.append(d.message), d.dismiss()))
            b.goto(self.B.base)
            b.wait_for_selector('.choice')
            titles = b.eval_on_selector_all('.choice > b', 'els => els.map(e => e.textContent)')
            self.assertEqual(titles, ['Join an existing system', 'This is the first (or only) PC'], 'joining is the first choice')
            self.assertIn('already used in your company', b.inner_text('#auth'))
            b.get_by_text('This is the first (or only) PC').click()
            self.assertEqual(len(asked), 1)
            self.assertIn('really the very first PC', asked[0])
            self.assertEqual(b.locator('input[name=full_name]').count(), 0, 'cancelled: still on the first screen')
            b.get_by_text('Join an existing system').click()
            b.fill('input[name=address]', '127.0.0.1:1')
            b.wait_for_selector('#joinCheck.bad-txt', timeout=20000)
            b.fill('input[name=address]', self.A.sync_address)
            b.wait_for_selector('#joinCheck.ok-txt', timeout=20000)
            self.assertIn('Found the administrator PC', b.inner_text('#joinCheck'))
            # --- the administrator PC: adding a person with a user name and password
            a = self.page(browser, 'A')
            a.goto(self.A.base)
            a.fill('input[name=username]', ADMIN[0])
            a.fill('input[name=password]', ADMIN[1])
            a.get_by_role('button', name='Log In').click()
            a.get_by_text('Start with my real data').click()
            a.wait_for_selector('#modal.open', state='detached', timeout=30000)  # the start is finished (it sets the page itself)
            a.goto(self.A.base + '/#/users')
            a.wait_for_selector('text=How do people start?')
            a.get_by_role('button', name='Add Person').click()
            a.fill('#modal input[name=full_name]', 'Sara Mostafa')
            a.check('#modal input[name=login][value=password]')
            a.fill('#modal input[name=username]', 'sara.m')
            a.fill('#modal input[name=password]', 'Desk-lamp-5531')
            # a background refresh that finishes while a window is open must not replace the data under it (it made "Save" say "someone else changed this")
            self.assertTrue(a.evaluate("(async () => { const before = DB; const r = await load(true); return r === false && DB === before; })()"))
            a.click('#modal .modal-f .primary')
            a.wait_for_selector('text=can start in one of two ways')
            text = a.inner_text('#modal')
            self.assertIn('Join an existing system', text)
            self.assertIn('does not know this user', text)
            self.assertIn('sara.m', text)
            a.click('#modal .modal-f button[data-act=closeModal]')
            # --- a PC that is on its own offers the way into the company system
            a.goto(self.A.base + '/#/devices')
            a.wait_for_selector('text=Was this PC set up by mistake?')
            a.click('button[data-act=devLeave]')
            a.wait_for_selector('#modal >> text=Please restart this PC')
            self.assertIn('Join an existing system', a.inner_text('#modal'))
            self.assertEqual([e for e in self.errors if '403' not in e], [])
            browser.close()

    def test_personal_link(self):
        """The administrator adds a person with only a name (personal link is the default) and a profile; the link is shown
        at once; opening it in another browser logs that person in under their own name. The link list in Devices & Sync
        shows when it was used."""
        make_authority(self.A)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=CHROME) if CHROME else pw.chromium.launch()
            a = self.page(browser, 'A')
            a.goto(self.A.base)
            a.fill('input[name=username]', ADMIN[0])
            a.fill('input[name=password]', ADMIN[1])
            a.get_by_role('button', name='Log In').click()
            a.get_by_text('Start with my real data').click()  # first start: empty system, no sample data
            a.wait_for_selector('#modal.open', state='detached', timeout=30000)  # the start sets the page itself when it is finished
            a.goto(self.A.base + '/#/users')
            a.get_by_role('button', name='Add Person').click()
            a.wait_for_selector('#modal.open input[name=full_name]')
            self.assertTrue(a.locator('#modal input[name=login][value=link]').is_checked(), 'personal link is the default')
            self.assertTrue(a.locator('#modal .pw-fields').is_hidden(), 'no user name / password fields for a link')
            self.assertEqual(a.locator('#modal select[name=role]').input_value(), 'Full access')
            self.assertTrue(a.locator('#modal input[name=perm][value="users.manage"]').is_disabled())
            a.fill('#modal input[name=full_name]', 'Mona Adel')
            a.select_option('#modal select[name=role]', 'Visitor')
            self.assertEqual(sorted(a.eval_on_selector_all('#modal input[name=perm]:checked', 'els => els.map(e => e.value)')),
                             ['areas.view', 'dashboard.view'])
            a.get_by_role('button', name='Clear all').click()
            self.assertEqual(a.locator('#modal select[name=role]').input_value(), 'Custom')
            a.get_by_role('button', name='Select all').click()
            self.assertEqual(a.locator('#modal select[name=role]').input_value(), 'Full access')
            a.select_option('#modal select[name=role]', 'Visitor')
            self.shot(a, '13-add-person')
            a.locator('#modal .modal-f button.primary').click()
            a.wait_for_selector('#modal.open input[data-select-all]', timeout=20000)
            self.assertIn('Mona Adel is ready', a.locator('#modal h3').inner_text())
            url = a.locator('#modal.open input[data-select-all]').input_value()
            self.assertRegex(url, r'^http://[^/]+/k/[A-Za-z0-9_-]{25,}$')
            self.assertEqual(a.locator('#modal.open .qr-box svg').count(), 1, 'QR code shown')
            self.shot(a, '14-person-link')
            m = self.page(browser, 'Mona')
            m.goto(self.A.base + url[url.index('/k/'):])
            m.wait_for_url(self.A.base + '/', timeout=20000)
            wait_until(lambda: 'Mona Adel' in m.locator('body').inner_text(), 30, what='logged in as Mona')
            self.assertEqual(m.evaluate("() => fetch('/api/me').then(r => r.json()).then(x => [x.username, x.perms.join()])"),
                             ['mona.adel', 'areas.view,dashboard.view'])
            self.shot(m, '15-opened-with-link')
            a.locator('#modal .modal-f button:has-text("Close")').click()
            # profiles: make one of our own
            a.get_by_role('button', name='Profiles').click()
            a.get_by_role('button', name='New Profile').click()
            a.fill('#modal input[name=name]', 'Night Shift')
            a.get_by_role('button', name='Select all').click()
            a.locator('#modal .modal-f button.primary').click()
            a.wait_for_selector('#modal.open td:has-text("Night Shift")', timeout=20000)
            self.shot(a, '16-profiles')
            a.locator('#modal .modal-f button:has-text("Close")').click()
            # the overview in Devices & Sync
            a.goto(self.A.base + '/#/devices')
            a.get_by_role('button', name='Personal links').click()
            a.wait_for_selector('tr:has-text("Mona Adel") td:has-text("on ")', timeout=20000)  # last used, on which PC
            browser.close()
        self.assertEqual(self.errors, [], 'browser console errors')

    @staticmethod
    def _desc(srv):
        c = srv.client()
        c.login('ayman', 'Strong-pass1')
        return next(x for x in c.get('/api/state')['areas'] if x['id'] == 'e2e1').get('description')

    @staticmethod
    def _login_ok(srv, u, p):
        try:
            srv.client().login(u, p)
            return True
        except Exception:
            return False


if __name__ == '__main__':
    unittest.main()
