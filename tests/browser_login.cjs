// Exercise the production login form with real browser submit events.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');

const html = fs.readFileSync(`${process.env.TEMPLATE_ROOT || 'templates'}/login.html`, 'utf8')
  .replace(/\{%[\s\S]*?%\}/g, '');

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.BROWSER_EXECUTABLE ? {executablePath: process.env.BROWSER_EXECUTABLE} : {})});
  try {
    for (const method of ['click', 'enter', 'requestSubmit']) {
      const page = await browser.newPage();
      await page.setContent(html);
      await page.getByLabel('Enter Your Email ID').fill('test@example.invalid');
      await page.getByLabel('Enter Your Password').fill('TestPassword!7392');
      // Observe submissions after production listeners, then stop navigation so
      // we can exercise more input while the first submission is pending.
      await page.locator('form').evaluate(form => {
        window.acceptedSubmissions = 0;
        form.addEventListener('submit', event => {
          if (!event.defaultPrevented) window.acceptedSubmissions++;
          event.preventDefault();
        });
      });
      await page.getByRole('button', {name: 'Sign In'}).click();
      assert.equal(await page.locator('button[type=submit]').isDisabled(), true,
        'Sign In must be disabled while the first submission is pending');
      if (method === 'click') {
        await page.locator('button[type=submit]').evaluate(button => button.click());
      } else if (method === 'enter') {
        await page.getByLabel('Enter Your Password').press('Enter');
      } else {
        await page.locator('form').evaluate(form => form.requestSubmit());
      }
      assert.equal(await page.evaluate(() => window.acceptedSubmissions), 1,
        `${method} must allow exactly one login submission`);
      // A bfcache restoration must reset both the disabled button and guard.
      await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true})));
      assert.equal(await page.getByRole('button', {name: 'Sign In'}).isEnabled(), true,
        'A restored login page must allow a new submission');
      await page.getByRole('button', {name: 'Sign In'}).click();
      assert.equal(await page.evaluate(() => window.acceptedSubmissions), 2,
        'Restoration must reset the submission guard');
      await page.close();
    }
    console.log('Login browser checks passed: duplicate clicks, Enter, submit events, page restoration.');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode = 1;});
