// Run with Node.js and Playwright installed; BROWSER_EXECUTABLE is optional.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');

const payload = '<img src=x onerror="window.pwned=true"><svg onload="window.pwned=true"></svg>';
function pageTemplate(name) {
  return fs.readFileSync(`${process.env.TEMPLATE_ROOT || 'templates'}/${name}.html`, 'utf8')
    .replace(/\{%[\s\S]*?%\}/g, '')
    .replace(/\{\{[\s\S]*?\}\}/g, '1')
    .replace(/<script src=[\s\S]*?<\/script>/g, '')
    .replace(/<link[^>]*>/g, '');
}

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.BROWSER_EXECUTABLE ? {executablePath: process.env.BROWSER_EXECUTABLE} : {})});
  try {
    const chat = await browser.newPage();
    await chat.route('**/*', route => route.abort());
    await chat.setContent('<script>window.fetch = async () => ({ok: true, json: async () => ({messages: []})});</script>' + pageTemplate('chat'));
    await chat.evaluate(text => {
      appendMessage({text, datetime_sent: '2026-01-01'}, false);
      prependMessage({text, sender_id: '2', datetime_sent: '2026-01-01'});
    }, payload);
    await chat.waitForTimeout(100);
    assert.equal(await chat.locator('.chat-bubble img, .chat-bubble svg').count(), 0, 'Message text must never create HTML elements');
    assert.equal(await chat.locator('.chat-bubble').first().textContent().then(s => s.includes(payload)), true);
    assert.equal(await chat.evaluate(() => window.pwned), undefined);
    // A failed send must preserve the draft and must not display a sent bubble.
    await chat.evaluate(() => {window.fetch = async () => ({ok: false, status: 403, json: async () => ({error: 'Forbidden'})});});
    await chat.locator('#chat-input').fill('unsent draft');
    const before = await chat.locator('.chat-bubble').count();
    await chat.locator('#send-btn').click();
    await chat.waitForTimeout(100);
    assert.equal(await chat.locator('.chat-bubble').count(), before);
    assert.equal(await chat.locator('#chat-input').inputValue(), 'unsent draft');
    await chat.close();

    const map = await browser.newPage();
    await map.route('**/*', route => route.abort());
    const bootstrap = `<script>
      window.popups=[];
      window.L={map:()=>({setView(){return this},getBounds:()=>({getSouth:()=>0,getWest:()=>0,getNorth:()=>90,getEast:()=>180}),on(){}}),layerGroup:()=>({addTo(){return this},clearLayers(){},addLayer(){}}),tileLayer:()=>({addTo(){}}),marker:()=>({bindPopup(content){window.popups.push(content);return this}})};
      window.fetch=async()=>({ok:true,json:async()=>({alumni:[{id:2,name:${JSON.stringify(payload)},department:${JSON.stringify(payload)},job_title:${JSON.stringify(payload)},batch:2020,lat:10,lng:79}]})});
    </script>`;
    await map.setContent(bootstrap + pageTemplate('alumni_map'));
    await map.waitForFunction(() => document.querySelectorAll('#alumniTable tbody tr').length === 1);
    assert.equal(await map.locator('#alumniTable tbody img, #alumniTable tbody svg').count(), 0, 'Profile fields must never create HTML elements');
    assert.equal(await map.locator('#alumniTable tbody td').first().textContent(), payload);
    assert.equal(await map.evaluate(() => window.popups.every(p => p instanceof HTMLElement && !p.querySelector('img,svg'))), true, 'Leaflet must receive safe DOM nodes');
    assert.equal(await map.evaluate(() => window.pwned), undefined);
    await map.close();
    console.log('Browser security checks passed: messages, history, map/table/popups, failed sends.');
  } finally {await browser.close();}
})().catch(error => {console.error(error);process.exitCode=1;});
