import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order_intake_request/order_intake_request.js',import.meta.url),'utf8');
function setup(values={},response) {
  const calls=[],messages=[],routes=[],buttons=new Map(),properties=[],dialogs=[];let handlers,reloads=0,disabled=0,enabled=0;
  const frm={doc:{name:'OIR-PROCESS',modified:'2026-11-12 10:00:00',request_type:'Order',status:'Pending Review',customer:'C-1',items:[{name:'ROW',row_key:'KEY',item:'SKU',quantity:4,unit:'NOS'}],attachments:[],source_messages:[],...values},
    fields:[{df:{fieldname:'customer',read_only:0}},{df:{fieldname:'items',read_only:0}},{df:{fieldname:'order',read_only:1}}],
    fields_dict:new Proxy({}, {get:()=>({$wrapper:{html(){}},grid:{update_docfield_property(){}},df:{}})}),
    is_new(){return this.doc.name.startsWith('new-');},is_dirty(){return Boolean(this.doc.__unsaved);},set_intro(){},set_query(){},toggle_display(){},
    set_df_property(...args){properties.push(args);},page: {add_menu_item(label, action) {buttons.set('Menu/' + label, action);}},
    add_custom_button(label,action,group){buttons.set((group||'')+'/'+label,action);},
    disable_save(){disabled++;},enable_save(){enabled++;},async reload_doc(){reloads++;},
  };
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const context={__:text=>text,frappe:{utils:{escape_html:escape},ui:{form:{on(type,value){if(type==='Order Intake Request')handlers=value;}},
    Dialog:class{constructor(options){Object.assign(this,options);this.fields_dict={conversation:{$wrapper:{html(){}}}};dialogs.push(this);}show(){}hide(){this.hidden=true;}}},
    msgprint(value){messages.push(value);},hide_msgprint(){},show_alert(){},set_route(...args){routes.push(args);},
    async call(value){if (!value.silent) calls.push(value);return{message:response?await response(value):value.type==='GET'?{request:frm.doc.name,modified:frm.doc.modified,revision:'SOURCE-REV',references:[],messages:[]}:{state:'Converted',order:'ORDER-1'}};}}};
  vm.createContext(context);vm.runInContext(source,context);
  return{frm,context,calls,messages,routes,buttons,properties,dialogs,handlers,get reloads(){return reloads;},get disabled(){return disabled;},get enabled(){return enabled;}};
}

test('manual actions depend on saved open request classification and never run on refresh',()=>{
  for(const [values,label] of [[{},'Create Order'],[{request_type:'Stock Inquiry'},'Mark handled'],[{request_type:'Price Inquiry'},'Mark handled']]){
    const flow=setup(values);flow.handlers.refresh(flow.frm);assert.equal(typeof flow.buttons.get('/'+label),'function');assert.ok(flow.calls.every(call=>call.type==='GET'));
  }
  for(const values of [{request_type:'Mixed'},{request_type:'Unclear'},{status:'Resolved'},{status:'Dismissed'},{name:'new-order-intake-request'}]){
    const flow=setup(values);flow.handlers.refresh(flow.frm);assert.equal(flow.buttons.has('/Create Order'),false);assert.equal(flow.buttons.has('/Mark handled'),false);
  }
});

test('dirty or new drafts cannot fetch evidence or process',async()=>{
  for(const values of [{__unsaved:true},{name:'new-order-intake-request'}]){
    const flow=setup(values);await flow.context.process_intake_request(flow.frm,'convert');assert.equal(flow.calls.length,0);assert.match(flow.messages[0],/Save your changes/);
  }
});

test('Create Order confirms saved selections with escaped labels and missing warehouse explanation',async()=>{
  const bad='<img src=x onerror=bad()>';const flow=setup({customer_name:bad,items:[{item:bad,quantity:4,unit:bad}],unresolved_questions:'Uncertain wording'});
  await flow.context.process_intake_request(flow.frm,'convert');
  const prompt=flow.dialogs[0];assert.equal(prompt.title,'Create Order');assert.match(prompt.fields[0].options,/actual Order/);assert.match(prompt.fields[0].options,/confirmed choices and correction reasons can help match future messages/);
  assert.match(prompt.fields[0].options,/warehouse assignment/);assert.match(prompt.fields[0].options,/Messages section/);assert.doesNotMatch(prompt.fields[0].options,/<img/);assert.match(prompt.fields[0].options,/&lt;img/);
  assert.equal(flow.calls.length,1);assert.equal(flow.calls[0].type,'GET');assert.equal(flow.messages.length,0);
});

test('confirmed conversion posts the saved revision and source fence then reloads without automatic navigation',async()=>{
  const flow=setup();await flow.context.process_intake_request(flow.frm,'convert');await flow.dialogs[0].primary_action();
  assert.equal(flow.calls[0].method,'kunal_enterprises.api.order_intake_conversation.messages');
  assert.equal(flow.calls[1].method,'kunal_enterprises.api.order_intake_processing.convert');assert.equal(flow.calls[1].type,'POST');
  assert.equal(flow.calls[1].args.request,'OIR-PROCESS');assert.equal(flow.calls[1].args.expected_modified,'2026-11-12 10:00:00');assert.equal(flow.calls[1].args.revision,'SOURCE-REV');
  assert.equal(flow.reloads,1);assert.equal(flow.routes.length,0);
});

test('inquiries explain confirmed classification feedback without creating an Order and use the separate endpoint',async()=>{
  const flow=setup({request_type:'Price Inquiry'});await flow.context.process_intake_request(flow.frm,'handle_inquiry');
  assert.match(flow.dialogs[0].fields[0].options,/No Order is created/);
  assert.match(flow.dialogs[0].fields[0].options,/request-type corrections and reasons can help classify future messages/);
  await flow.dialogs[0].primary_action();assert.equal(flow.calls[1].method,'kunal_enterprises.api.order_intake_processing.handle_inquiry');
});

test('evidence failures and mismatched evidence cannot publish an Order',async()=>{
  const failed=setup({},()=>{throw new Error('Source access denied');});
  await assert.rejects(failed.context.process_intake_request(failed.frm,'convert'),/Source access denied/);assert.equal(failed.calls.length,1);assert.equal(failed.messages.length,0);
  const wrong=setup({},()=>({request:'OTHER',modified:'other',revision:'REV'}));await wrong.context.process_intake_request(wrong.frm,'convert');
  assert.equal(wrong.calls.length,1);assert.match(wrong.messages[0],/evidence is unavailable/);
});

test('edits or document switches before confirmation prevent processing',async()=>{
  for(const edit of [doc=>{doc.items[0].quantity=9;},doc=>{doc.name='OTHER';},doc=>{doc.__unsaved=true;}]){
    const flow=setup();await flow.context.process_intake_request(flow.frm,'convert');edit(flow.frm.doc);await flow.dialogs[0].primary_action();
    assert.equal(flow.calls.length,1);assert.equal(flow.reloads,0);
  }
});

test('changes while evidence is loading cannot open a stale confirmation',async()=>{
  let done;const flow=setup({},()=>new Promise(resolve=>{done=resolve;}));const action=flow.context.process_intake_request(flow.frm,'convert');
  flow.frm.doc.name='OTHER';done({request:'OIR-PROCESS',modified:'2026-11-12 10:00:00',revision:'REV'});await action;
  assert.equal(flow.calls.length,1);assert.match(flow.messages[0],/request changed/);
});

test('repeated confirmation clicks share one in-flight POST and failed posts leave the draft available',async()=>{
  let done;const flow=setup({},value=>value.type==='GET'?{request:'OIR-PROCESS',modified:'2026-11-12 10:00:00',revision:'REV'}:new Promise(resolve=>{done=resolve;}));
  await flow.context.process_intake_request(flow.frm,'convert');const first=flow.dialogs[0].primary_action();await flow.dialogs[0].primary_action();
  assert.equal(flow.calls.length,2);done({state:'Converted',order:'ORDER-1'});await first;assert.equal(flow.reloads,1);
  const failed=setup({},value=>{if(value.type==='POST')throw new Error('Needs Tally mapping');return{request:'OIR-PROCESS',modified:'2026-11-12 10:00:00',revision:'REV'};});
  await failed.context.process_intake_request(failed.frm,'convert');await assert.rejects(failed.dialogs[0].primary_action(),/Tally mapping/);
  assert.equal(failed.reloads,0);assert.equal(failed.frm.__intake_processing_busy,false);assert.notEqual(failed.dialogs[0].hidden,true);
});

test('converted records display Converted status and View Order; field locks restore on the next draft',()=>{
  const flow=setup({status:'Converted to Order',order:'ORDER-1'});flow.handlers.refresh(flow.frm);
  assert.equal(flow.buttons.has('/Create Order'),false);assert.equal(flow.buttons.has('/View messages'),false);assert.equal(flow.disabled,1);
  assert.ok(flow.properties.some(args=>args[0]==='status'&&args[1]==='options'&&args[2].includes('Converted to Order')));
  flow.buttons.get('/View Order')();assert.deepEqual(flow.routes[0],['Form','Order','ORDER-1']);
  flow.frm.doc={...flow.frm.doc,name:'NEXT',order:null,status:'Pending Review'};flow.handlers.refresh(flow.frm);
  assert.equal(flow.enabled,1);assert.ok(flow.properties.some(args=>args[0]==='customer'&&args[1]==='read_only'&&args[2]===0));
});

test('converted message attachment review is read-only and cannot apply forged changes',async()=>{
  const attachment={name:'REF',review_status:'Needs Manual Review',notes:'original'};
  const flow=setup({status:'Converted to Order',order:'ORDER-1',attachments:[attachment]},()=>({request:'OIR-PROCESS',modified:'2026-11-12 10:00:00',revision:'REV',messages:[],references:[{...attachment,reference_type:'File'}]}));
  await flow.context.view_intake_messages(flow.frm);const dialog=flow.dialogs[0];assert.equal(dialog.primary_action_label,'Close');
  const fields=dialog.fields.find(field=>field.fieldname==='reviews').fields;
  assert.equal(fields.find(field=>field.fieldname==='notes').read_only,true);assert.equal(fields.find(field=>field.fieldname==='review_status').read_only,true);
  await dialog.primary_action({reviews:[{row_name:'REF',review_status:'Reviewed',notes:'forged'}]});assert.equal(flow.frm.doc.attachments[0].notes,'original');assert.equal(flow.calls.length,1);
});


test('read-only requests do not offer processing actions',async()=>{
  const flow=setup();flow.frm.has_perm=()=>false;flow.handlers.refresh(flow.frm);
  assert.equal(flow.buttons.has('/Create Order'),false);assert.equal(flow.buttons.has('/Mark handled'),false);
  await flow.context.process_intake_request(flow.frm,'convert');assert.equal(flow.calls.length,0);
});
