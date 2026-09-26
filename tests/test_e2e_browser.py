"""Browser end-to-end test with a real Chromium: first setup, pairing a second PC through the screens,
login on the second PC, permissions, live changes, sync light, Devices & Sync, conflicts and logs.
Skipped when Playwright is not installed (it is only needed for testing, never at runtime)."""
import os
import time
import unittest

from harness import TcpProxy, Server, wait_until

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
            a.wait_for_selector('text=Break Area 01', timeout=30000)  # sample data loaded on the very first start
            self.shot(a, '01-admin-dashboard')
            self.assertTrue(a.locator('#syncInd').is_hidden(), 'no sync light while only one PC exists')
            # ---- Devices & Sync: add a PC
            a.goto(self.A.base + '/#/devices')
            a.wait_for_selector('text=Only this PC')
            a.get_by_role('button', name='Add a PC').click()
            code = a.locator('#modal .big-code').inner_text().strip()
            self.shot(a, '02-add-pc')
            a.keyboard.press('Escape')
            # ---- second PC: join
            b.goto(self.B.base)
            b.get_by_text('Join an existing system').click()
            b.fill('input[name=address]', self.A.sync_address)
            b.fill('input[name=code]', code)
            b.fill('input[name=name]', 'Store PC')
            b.get_by_role('button', name='Send Join Request').click()
            b.wait_for_selector('#joinCode')
            confirm = b.locator('#joinCode').inner_text().strip()
            self.shot(b, '03-join-waiting')
            # ---- approve on the administrator PC (same confirmation number)
            a.goto(self.A.base + '/#/devices')
            a.reload()
            a.wait_for_selector(f'text={confirm}', timeout=15000)
            self.shot(a, '04-approve')
            a.get_by_role('button', name='Approve').click()
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
            s.goto(self.B.base + '/#/devices')
            s.wait_for_selector('text=No access')
            code = s.evaluate("() => fetch('/api/devices').then(r => r.status)")
            self.assertEqual(code, 403, 'the monitoring API itself refuses ordinary users')
            self.shot(s, '06-viewer-no-access')
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
            self.errors.clear()
            # the conflict page, the logs with PC column
            a.goto(self.A.base + '/#/devices')
            a.get_by_role('button', name='Conflicts').click()
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
            self.B.stop()
            self.B.set_cfg(peer_addresses={}, sync_port=port)
            self.B.start()
            a.goto(self.A.base + '/#/devices')
            a.get_by_role('button', name='Conflicts').click()
            try:
                wait_until(lambda: (a.get_by_role('button', name='Conflicts').click(), a.wait_for_timeout(1500), a.locator('.card.conflict').count())[2], 60, 1, what='conflict shown')
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
