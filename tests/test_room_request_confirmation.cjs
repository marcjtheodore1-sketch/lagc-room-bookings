/* Confirmation and editing checks with a fake browser, without network access. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/js/room_requests.js'), 'utf8');

function setup() {
    const elements = new Map(), events = new Map();
    let focused;
    const document = {getElementById(id) {
        if (!elements.has(id)) elements.set(id, {value:'', open:false, hidden:false, disabled:false, textContent:'', innerHTML:'',
            showModal() {this.open=true;}, close() {this.open=false;}, focus() {focused=id;},
            addEventListener(name, fn) {events.set(id+':'+name,fn);}});
        return elements.get(id);
    }};
    const context=vm.createContext({document,escapeHtml:String});
    vm.runInContext(source,context);
    const record={review_key:'reviewed-key',status:'draft',subject:'Rooms',body:'Edited email',
        recipient_names:{to:['Emma','Martha'],cc:['Florence']}};
    context.record=record;
    document.getElementById('rr-email-subject').value=record.subject;
    document.getElementById('rr-email-body').value=record.body;
    vm.runInContext('roomRequestOptions={request_id:"request-123",rooms:[]}; roomRequestReview=record; roomRequestPreviewSelection=currentRoomRequestSelection();',context);
    const calls=[];
    context.capture=async(route,options)=>{calls.push({route,body:JSON.parse(options.body)});return {request:{...record,status:'sent'}};};
    vm.runInContext('roomRequestFetch=capture; loadRoomRequestHistory=async()=>{};',context);
    return {context,document,events,calls,record,focused:()=>focused};
}

test('Confirmation names the recipients, defaults to Cancel, and never sends on Cancel',async()=>{
    const s=setup();s.context.sendRoomRequest();
    assert.equal(s.document.getElementById('rr-send-confirmation').open,true);
    assert.equal(s.focused(),'rr-confirm-cancel');
    assert.equal(s.document.getElementById('rr-confirm-recipients').textContent,'Emma and Martha, with Florence copied in.');
    assert.equal(s.calls.length,0);
    s.context.cancelRoomRequestSend();await s.context.confirmRoomRequestSend();
    assert.equal(s.calls.length,0);
});

test('Confirm send sends the reviewed key only once',async()=>{
    const s=setup();s.context.sendRoomRequest();
    await Promise.all([s.context.confirmRoomRequestSend(),s.context.confirmRoomRequestSend()]);
    assert.deepEqual(s.calls,[{route:'send',body:{review_key:'reviewed-key',confirmed:true}}]);
});

for(const field of ['rr-email-subject','rr-email-body','rr-notes']) {
    test(`Changing ${field} blocks an old confirmation even without an input event`,async()=>{
        const s=setup();s.context.sendRoomRequest();s.document.getElementById(field).value+='changed';
        await s.context.confirmRoomRequestSend();
        assert.equal(s.calls.length,0);assert.equal(s.document.getElementById('rr-send-confirmation').open,false);
        assert.match(s.document.getElementById('rr-status').textContent,/Review email again/);
    });
}

test('Editing the email hides the old final preview and requires a new review',async()=>{
    const s=setup();s.events.get('rr-editor-form:input')();
    assert.equal(s.document.getElementById('rr-preview').hidden,true);
    s.context.sendRoomRequest();assert.equal(s.calls.length,0);
});

test('Previous emails are read-only and cannot reopen an old send',async()=>{
    const s=setup();s.context.showRoomRequestPreview(s.record,true);
    assert.equal(s.document.getElementById('rr-send-btn').hidden,true);
    s.context.sendRoomRequest();assert.equal(s.document.getElementById('rr-send-confirmation').open,false);
    assert.equal(s.calls.length,0);
});
