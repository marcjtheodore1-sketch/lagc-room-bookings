/* Confirmation flow checks with a fake browser and no network access. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/room_requests.js'), 'utf8');

function setup(mode) {
    const elements = new Map();
    const events = new Map();
    let focused;
    const document = {getElementById(id) {
        if (!elements.has(id)) elements.set(id, {
            open: false, hidden: false, disabled: false, textContent: '', innerHTML: '',
            showModal() {this.open = true;}, close() {this.open = false;},
            focus() {focused = id;}, addEventListener(name, fn) {events.set(id + ':' + name, fn);}
        });
        return elements.get(id);
    }};
    const context = vm.createContext({document, escapeHtml: text => String(text).replaceAll('<', '&lt;')});
    vm.runInContext(source, context);
    const review = {review_key: 'reviewed-request-key', delivery_mode: mode, status: 'draft',
        to: mode === 'test' ? ['florence@example.test', 'chris@example.test'] : ['emma@example.test', 'martha@example.test'],
        cc: mode === 'test' ? [] : ['florence@example.test'], subject: mode === 'test' ? '[TEST] Rooms' : 'Rooms'};
    context.record = review;
    vm.runInContext('roomRequestReview = record;', context);
    const calls = [];
    context.capture = async (route, options) => {
        calls.push({route, body: JSON.parse(options.body)});
        return {request: {...review, status: 'sent'}};
    };
    vm.runInContext('roomRequestFetch = capture; loadRoomRequestHistory = async () => {}; showRoomRequestPreview = () => {};', context);
    return {context, elements, document, events, calls, review, focused: () => focused};
}

for (const mode of ['test', 'live']) {
    test(`${mode}: show all recipients before sending; Cancel and Escape send nothing`, async () => {
        const state = setup(mode);
        state.context.sendRoomRequest();
        assert.equal(state.document.getElementById('rr-send-confirmation').open, true);
        assert.equal(state.focused(), 'rr-confirm-cancel');
        const recipients = state.document.getElementById('rr-confirm-recipients').innerHTML;
        for (const address of [...state.review.to, ...state.review.cc]) assert.ok(recipients.includes(address));
        assert.match(state.document.getElementById('rr-confirm-heading').textContent,
            mode === 'test' ? /test email/ : /room request/);
        assert.equal(state.calls.length, 0);
        state.context.cancelRoomRequestSend();
        await state.context.confirmRoomRequestSend();
        assert.equal(state.calls.length, 0);
        state.context.sendRoomRequest();
        state.events.get('rr-send-confirmation:close')();
        state.document.getElementById('rr-send-confirmation').close();
        await state.context.confirmRoomRequestSend();
        assert.equal(state.calls.length, 0);
    });

    test(`${mode}: Confirm send sends the reviewed request once; stale confirmations send nothing`, async () => {
        const state = setup(mode);
        state.context.sendRoomRequest();
        state.context.invalidateRoomRequest();
        await state.context.confirmRoomRequestSend();
        assert.equal(state.calls.length, 0);
        vm.runInContext('roomRequestReview = record;', state.context);
        state.context.sendRoomRequest();
        await Promise.all([state.context.confirmRoomRequestSend(), state.context.confirmRoomRequestSend()]);
        assert.equal(state.calls.length, 1);
        assert.deepEqual(state.calls[0], {route: 'send', body: {review_key: state.review.review_key, confirmed: true}});
    });
}
