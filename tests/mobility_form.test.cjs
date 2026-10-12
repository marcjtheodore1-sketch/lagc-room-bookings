const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');
const source = fs.readFileSync('static/js/app.js', 'utf8');
const code = source.slice(source.indexOf('let mobilityAccess ='), source.indexOf('function resetAttendeeFields()'));

function form() {
    const nodes = new Map();
    const listeners = {};
    const windows = {};
    let now = 1000000;
    function node(id) {
        if (!nodes.has(id)) nodes.set(id, {
            value: '', checked: false, hidden: true, disabled: false, required: false,
            textContent: '', events: {},
            addEventListener(event, callback) { this.events[event] = callback; },
            checkValidity() { return this.value.includes('@'); },
            focus() {},
        });
        return nodes.get(id);
    }
    const radios = ['no', 'yes', 'reuse'].map(value => ({...node('radio-' + value), value}));
    const elements = {emailInput: node('email'), firstNameInput: node('first'), lastNameInput: node('last')};
    let reply = async (url, options) => ({ok: true, json: async () =>
        options?.method === 'POST' ? {verified: true, email: elements.emailInput.value,
            expires_at: 2000, previous: {details: 'Earlier support', date_display: 'Friday'}}
            : {verified: true, expires_at: 2000}});
    const context = vm.createContext({
        document: {
            getElementById: node,
            addEventListener(event, callback) { listeners[event] = callback; },
            querySelectorAll(selector) { return selector === 'input[name="mobility-needs"]' ? radios : []; },
            querySelector(selector) {
                if (selector.includes(':checked')) return radios.find(radio => radio.checked);
                return radios.find(radio => selector.includes(`[value="${radio.value}"]`));
            },
        },
        window: {addEventListener(event, callback) { windows[event] = callback; }},
        elements, Date: {now: () => now}, setInterval() {},
        fetch: (...args) => reply(...args), updateAttendeeFields() {}, addCompanion() {},
        alert() {}, confirm: () => true,
    });
    vm.runInContext(code, context);
    listeners.DOMContentLoaded();
    function identity(email = 'person@example.test', first = 'Test', last = 'Person') {
        for (const [input, value] of [[elements.emailInput, email], [elements.firstNameInput, first], [elements.lastNameInput, last]]) {
            input.value = value;
            input.events.input();
        }
    }
    function choose(value) {
        radios.forEach(radio => { radio.checked = radio.value === value; });
        context.updateMobilityFields();
    }
    return {context, node, radios, windows, elements, identity, choose,
        expire() { now = 3000000; context.renderMobilityHistory(); },
        respond(callback) { reply = callback; },
        async ready() { await context.loadMobilityHistory(); },
    };
}

test('loading a private session reveals no email or answer until explicitly requested', async () => {
    const f = form();
    await f.ready();
    assert.equal(f.elements.emailInput.value, '');
    assert.equal(f.node('mobility-history').hidden, true);
    assert.equal(f.node('mobility-reuse-option').hidden, true);
    assert.equal(f.radios[2].disabled, true);
    f.identity();
    await f.context.showMobilityHistory();
    assert.equal(f.node('mobility-history').hidden, false);
    assert.equal(f.node('mobility-reuse-option').hidden, false);
    assert.equal(f.node('mobility-history-details').textContent, 'Earlier support');
});

test('typed and edited drafts survive email corrections, choice changes and expiry', async () => {
    const f = form();
    await f.ready();
    f.identity();
    await f.context.showMobilityHistory();
    f.choose('yes');
    f.node('mobility-details').value = 'My own wording';
    f.node('mobility-details').events.input();
    f.choose('no');
    f.choose('yes');
    assert.equal(f.node('mobility-details').value, 'My own wording');
    f.identity('corrected@example.test');
    assert.equal(f.node('mobility-details').value, 'My own wording');
    f.expire();
    assert.equal(f.node('mobility-details').value, 'My own wording');
    assert.equal(f.node('mobility-history').hidden, true);
});

test('only an unedited history copy is cleared when changing person', async () => {
    for (const edited of [false, true]) {
        const f = form();
        await f.ready(); f.identity(); await f.context.showMobilityHistory();
        f.node('mobility-edit-history').events.click();
        assert.equal(f.node('mobility-details').value, 'Earlier support');
        if (edited) {
            f.node('mobility-details').value = 'Earlier support plus my changes';
            f.node('mobility-details').events.input();
        }
        f.identity('person@example.test', 'Other', 'Person');
        assert.equal(f.node('mobility-details').value, edited ? 'Earlier support plus my changes' : '');
        assert.equal(f.node('mobility-history').hidden, true);
        f.identity();
        assert.equal(f.node('mobility-history').hidden, true); // No automatic redisclosure.
    }
});

test('expiry preserves a copied draft but disables reuse and clears stale confirmation', async () => {
    const f = form();
    await f.ready(); f.identity(); await f.context.showMobilityHistory();
    f.node('mobility-edit-history').events.click();
    f.choose('reuse');
    f.node('mobility-change-confirmed').checked = true;
    f.expire();
    assert.equal(f.node('mobility-details').value, 'Earlier support');
    assert.equal(f.radios[2].checked, false);
    assert.equal(f.radios[2].disabled, true);
    assert.equal(f.node('mobility-change-confirmed').checked, false);
});

test('a delayed answer cannot reveal the previous person after identity changes', async () => {
    const f = form();
    await f.ready(); f.identity();
    let resolve;
    f.respond(() => new Promise(done => { resolve = done; }));
    const pending = f.context.showMobilityHistory();
    f.identity('other@example.test');
    resolve({ok:true, json:async()=>({verified:true, expires_at:2000, previous:{details:'Private'}})});
    await pending;
    assert.equal(f.node('mobility-history').hidden, true);
    assert.equal(f.node('mobility-history-details').textContent, '');
});

test('leaving the page clears private display and a copied draft before back navigation', async () => {
    const f = form();
    await f.ready(); f.identity(); await f.context.showMobilityHistory();
    f.node('mobility-edit-history').events.click();
    f.windows.pagehide();
    assert.equal(f.node('mobility-details').value, '');
    assert.equal(f.node('mobility-history-details').textContent, '');
    assert.equal(f.node('mobility-history').hidden, true);
    f.windows.pageshow({persisted:true});
    await f.ready();
    assert.equal(f.node('mobility-history').hidden, true);
});

test('ending access defeats a delayed session response and clears only unedited copies', async () => {
    const f = form();
    await f.ready(); f.identity(); await f.context.showMobilityHistory();
    f.node('mobility-edit-history').events.click();
    let resolve;
    f.respond((url, options) => options?.method === 'POST'
        ? Promise.resolve({ok:true}) : new Promise(done => { resolve = done; }));
    const pending = f.context.loadMobilityHistory();
    await f.context.endMobilityAccess();
    resolve({ok:true, json:async()=>({verified:true, expires_at:2000})});
    await pending;
    assert.equal(f.node('mobility-details').value, '');
    assert.equal(f.node('mobility-private-ready').hidden, true);
    assert.equal(f.node('mobility-history').hidden, true);
});
