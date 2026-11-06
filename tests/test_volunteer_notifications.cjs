/* Rota request lifecycle checks without a browser, database or real network. */
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../static/js/admin.js'), 'utf8');

function setup(fetch) {
    const name = {value:'Élodie Martin', disabled:false};
    const status = {value:'unavailable', dataset:{date:'2099-01-02'}, disabled:false};
    const note = {value:'Keep my note', disabled:false};
    const start = {value:'09:00', disabled:true};
    const end = {value:'17:00', disabled:true};
    const fields = [name,status,note,start,end];
    const form = {inert:false};
    const coverage = {inert:false};
    const feedback = {textContent:'',className:''};
    const button = {disabled:false,textContent:'Save my availability'};
    const elements = {'vol-name':name,'vol-save-btn':button,'volunteer-status':feedback,'volunteer-coverage':coverage};
    const row = {
        querySelector(selector) {return selector==='.vol-entry-status' ? status : {hidden:true};},
        querySelectorAll() {return [start,end];}
    };
    const document = {
        addEventListener() {},
        getElementById(id) {return elements[id];},
        querySelector(selector) {
            if (selector==='.volunteer-form') return form;
            if (selector.includes('vol-entry-note')) return note;
            if (selector.includes('vol-entry-start')) return start;
            if (selector.includes('vol-entry-end')) return end;
            throw new Error('Unexpected selector '+selector);
        },
        querySelectorAll(selector) {
            if (selector==='.vol-entry-status') return [status];
            if (selector==='.vol-entry-note, .vol-entry-start, .vol-entry-end') return [note,start,end];
            if (selector==='.vol-entry-row') return [row];
            if (selector==='.volunteer-form input, .volunteer-form select, .volunteer-form textarea') return fields;
            throw new Error('Unexpected selector '+selector);
        }
    };
    const context = vm.createContext({document,fetch,confirm:()=>true,console});
    vm.runInContext(source,context);
    vm.runInContext('renderVolunteerCoverage=()=>{}; loadVolunteerNotificationIssues=async()=>{};',context);
    return {context,name,status,note,start,end,fields,form,coverage,feedback,button};
}

test('Slow save locks all fields and actions, then restores relevant controls',async()=>{
    let resolve, calls=0;
    const response = new Promise(r=>{resolve=r;});
    const s=setup(()=>{calls++;return response;});
    const saved=s.context.saveVolunteer();
    assert.equal(s.form.inert,true);
    assert.equal(s.coverage.inert,true);
    assert.ok(s.fields.every(field=>field.disabled));
    assert.equal(s.button.disabled,true);
    await s.context.saveVolunteer();
    await s.context.removeVolunteer('Élodie%20Martin');
    s.context.editVolunteer('Someone%20Else');
    assert.equal(calls,1);
    assert.equal(s.name.value,'Élodie Martin');
    resolve({ok:true,status:200,json:async()=>({notification:{status:'sent'}})});
    await saved;
    assert.equal(s.form.inert,false);
    assert.equal(s.coverage.inert,false);
    assert.equal(s.button.disabled,false);
    assert.equal(s.name.disabled,false);
    assert.equal(s.start.disabled,true); // Blank status still disables shift times.
    assert.equal(s.name.value,'');
    assert.match(s.feedback.textContent,/Florence has been emailed/);
});

test('Unexpected 5xx save preserves inputs and reports uncertainty',async()=>{
    const s=setup(async()=>({ok:false,status:500,json:async()=>({error:'Failed to save. Please try again.'})}));
    await s.context.saveVolunteer();
    assert.match(s.feedback.textContent,/could not confirm whether your changes were saved/);
    assert.equal(s.name.value,'Élodie Martin');
    assert.equal(s.note.value,'Keep my note');
    assert.equal(s.button.disabled,false);
});

test('Unexpected 5xx removal reports uncertainty',async()=>{
    const s=setup(async()=>({ok:false,status:503}));
    await s.context.removeVolunteer('Élodie%20Martin');
    assert.match(s.feedback.textContent,/could not confirm whether the volunteer was removed/);
    assert.equal(s.name.value,'Élodie Martin');
    assert.equal(s.form.inert,false);
});

test('A saved result with an email warning stays a successful save',async()=>{
    const warning='Your rota changes are saved, but email could not be confirmed.';
    const s=setup(async()=>({ok:true,status:200,json:async()=>({notification:{status:'uncertain',warning}})}));
    await s.context.saveVolunteer();
    assert.equal(s.feedback.textContent,warning);
    assert.equal(s.name.value,'');
    assert.equal(s.button.disabled,false);
});

test('Validation failure preserves the form and the server explanation',async()=>{
    const s=setup(async()=>({ok:false,status:400,json:async()=>({error:'Choose valid times.'})}));
    await s.context.saveVolunteer();
    assert.equal(s.feedback.textContent,'Choose valid times.');
    assert.equal(s.name.value,'Élodie Martin');
    assert.equal(s.status.value,'unavailable');
});
