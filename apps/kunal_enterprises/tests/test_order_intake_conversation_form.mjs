import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order_intake_request/order_intake_request.js',import.meta.url),'utf8');
function setup(data={},form={}) {
  const dialogs=[],messages=[],calls=[],changes=[],buttons=new Map();let handlers;
  const frm={doc:{name:'OIR-CHAT',modified:'revision-1',items:[],source_messages:[],attachments:[],...form},fields_dict:new Proxy({}, {get:()=>({$wrapper:{html(){}},grid:{update_docfield_property(){}},df:{}})}),
    is_new(){return this.doc.name.startsWith('new-');},is_dirty(){return Boolean(this.doc.__unsaved);},set_intro(){},set_df_property(){},toggle_display(){},
    page: {add_menu_item(label, action) {buttons.set('Menu/' + label, action);}},
    add_custom_button(label,action,group){buttons.set((group||'')+'/'+label,action);}};
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const context={__:text=>text,frappe:{utils:{escape_html:escape},ui:{form:{on(type,value){if(type==='Order Intake Request')handlers=value;}},
    Dialog:class{constructor(options){Object.assign(this,options);this.fields_dict={conversation:{$wrapper:{html(value){this.rendered=value;}}}};dialogs.push(this);}show(){}hide(){this.hidden=true;}set_secondary_action_label(){}set_secondary_action(action){this.older=action;}get_secondary_btn(){return{hide(){}};}}},
    msgprint(value){messages.push(value);},show_alert(){},async call(value){calls.push(value);return{message:typeof data==='function'?await data(value):data};},
    model:{async set_value(type,name,value){changes.push([type,name,value]);Object.assign(frm.doc.attachments.find(row=>row.name===name),value);frm.doc.__unsaved=true;}}}};
  vm.createContext(context);vm.runInContext(source,context);
  return{frm,dialogs,messages,calls,changes,buttons,handlers,context};
}
const data={request:'OIR-CHAT',modified:'revision-1',revision:'source-hash',has_more:false,messages:[{name:'MSG-1',sender_name:'Sender',received_at:'2026-11-12 10:00',text:'21317 MR 4 NOS',warnings:[]}],references:[]};

test('messages load automatically and the old toolbar button is absent',async()=>{
  const flow=setup(data);flow.handlers.refresh(flow.frm);assert.equal(flow.calls.length,1);assert.equal(flow.buttons.has('/View messages'),false);
  const unsaved=setup(data,{name:'new-order-intake-request'});unsaved.handlers.refresh(unsaved.frm);assert.equal(unsaved.calls.length,0);
});

test('chat text, filenames, warnings, links and location names are escaped without embedding media',async()=>{
  const payload='<img src=x onerror=bad()>';
  const flow=setup({...data,messages:[{name:'M',sender_name:payload,text:payload,received_at:payload,warnings:[payload],location:{name:payload,latitude:0,longitude:0},attachment:{available:true,url:'/private/files/test.pdf',file_name:payload}}],
    references:[{name:'REF',reference_type:'External Link',label:payload,external_url:'https://example.invalid/'+payload,review_status:'Not Reviewed',notes:payload}]},
    {attachments:[{name:'REF',reference_type:'External Link',label:payload,notes:payload}]});
  await flow.context.view_intake_messages(flow.frm);
  const fields=flow.dialogs[0].fields;const html=fields.filter(f=>f.fieldtype==='HTML').map(f=>f.options).join('');
  assert.doesNotMatch(html,/<img|<iframe|<audio|<video/);assert.match(html,/&lt;img/);assert.match(html,/openstreetmap\.org\/\?mlat=0&amp;mlon=0/);assert.doesNotMatch(html,/href="https:\/\/example/);
  const table=fields.find(f=>f.fieldtype==='Table');
  for(const field of table.fields.filter(f=>f.in_list_view))assert.doesNotMatch(field.formatter(payload),/<img/);
  assert.equal(table.data[0].notes,payload);
});

test('pagination preserves the source revision and prepends older messages',async()=>{
  const initial={...data,has_more:true,next_cursor:'MSG-1'};
  const flow=setup(call=>call.args.cursor?{...data,messages:[{name:'OLDER',text:'Earlier',warnings:[]}]}:initial);
  await flow.context.view_intake_messages(flow.frm);await flow.dialogs[0].older();
  assert.equal(flow.calls[1].type,'GET');assert.equal(flow.calls[1].args.cursor,'MSG-1');assert.equal(flow.calls[1].args.revision,'source-hash');
  assert.ok(flow.dialogs[0].fields_dict.conversation.$wrapper.rendered.indexOf('Earlier')<flow.dialogs[0].fields_dict.conversation.$wrapper.rendered.indexOf('21317'));
});

test('an asynchronous response after switching requests cannot open the old chat',async()=>{
  let resolve;const flow=setup(()=>new Promise(done=>{resolve=done;}));const action=flow.context.view_intake_messages(flow.frm);
  flow.frm.doc.name='OTHER';resolve(data);await action;assert.equal(flow.dialogs.length,0);assert.match(flow.messages[0],/request changed/);
});

test('explicit attachment review applies locally and does not save or change order fields',async()=>{
  const attachment={name:'REF',label:'PDF',review_status:'Needs Manual Review',notes:'old'};
  const flow=setup({...data,references:[{...attachment,reference_type:'File',page_count:12,attachment:{available:false}}],pdf_page_limit:10},{attachments:[attachment],customer:'KEEP',items:[{quantity:4}]});
  await flow.context.view_intake_messages(flow.frm);const dialog=flow.dialogs[0];assert.match(dialog.fields.find(field=>field.fieldname==='references_display').options,/Above automatic page limit/);
  await dialog.primary_action({reviews:[{row_name:'REF',review_status:'Reviewed',notes:'Checked all pages'}]});
  assert.equal(flow.frm.doc.attachments[0].notes,'Checked all pages');assert.equal(flow.frm.doc.__unsaved,true);assert.equal(flow.calls.length,2);assert.equal(flow.frm.doc.customer,'KEEP');assert.equal(flow.frm.doc.items[0].quantity,4);
});

test('forged review rows and intervening edits cannot overwrite the request',async()=>{
  for(const changed of [false,true]){
    const attachment={name:'REF',label:'PDF',review_status:'Not Reviewed',notes:'old'};
    const flow=setup({...data,references:[{...attachment,reference_type:'File'}]},{attachments:[attachment]});await flow.context.view_intake_messages(flow.frm);
    if(changed)flow.frm.doc.attachments[0].notes='newer correction';
    await flow.dialogs[0].primary_action({reviews:[{row_name:changed?'REF':'FORGED',review_status:'Reviewed',notes:'modal edit'}]});
    assert.equal(flow.changes.length,0);assert.match(flow.messages[0],/changed/);
  }
});


test('unchanged review rows do not dirty the form and files offer manual downloads',async()=>{
  const attachment={name:'REF',label:'PDF',review_status:'Not Reviewed',notes:null};
  const flow=setup({...data,references:[{...attachment,notes:'',reference_type:'File',attachment:{available:true,url:'/private/files/report.pdf',file_name:'report.pdf'}}]}, {attachments:[attachment]});
  await flow.context.view_intake_messages(flow.frm);
  assert.match(flow.dialogs[0].fields.find(field=>field.fieldname==='references_display').options,/download="report.pdf"/);
  await flow.dialogs[0].primary_action({reviews:[{row_name:'REF',review_status:'Not Reviewed',notes:''}]});
  assert.equal(flow.changes.length,0);assert.equal(flow.frm.is_dirty(),false);
});

test('review changes are not applied when the current evidence revision is rejected',async()=>{
  const attachment={name:'REF',label:'PDF',review_status:'Not Reviewed',notes:'old'};
  const initial={...data,references:[{...attachment,reference_type:'File'}]};
  const flow=setup(call=>{if(call.args.revision)throw new Error('Evidence changed');return initial;},{attachments:[attachment]});
  await flow.context.view_intake_messages(flow.frm);
  await flow.dialogs[0].primary_action({reviews:[{row_name:'REF',review_status:'Reviewed',notes:'Reviewed old evidence'}]});
  assert.equal(flow.calls.length,2);
  assert.equal(flow.calls[1].args.revision,'source-hash');
  assert.equal(flow.calls[1].args.expected_modified,'revision-1');
  assert.equal(flow.changes.length,0);
  assert.equal(flow.frm.doc.attachments[0].review_status,'Not Reviewed');
});

test('edits made while evidence revalidation is pending are preserved',async()=>{
  const attachment={name:'REF',label:'PDF',review_status:'Not Reviewed',notes:'old'};
  const initial={...data,references:[{...attachment,reference_type:'File'}]};
  let resolve;
  const flow=setup(call=>call.args.revision?new Promise(done=>{resolve=done;}):initial,{attachments:[attachment]});
  await flow.context.view_intake_messages(flow.frm);
  const applying=flow.dialogs[0].primary_action({reviews:[{row_name:'REF',review_status:'Reviewed',notes:'Modal choice'}]});
  assert.equal(typeof resolve,'function');
  flow.frm.doc.attachments[0].notes='Newer manual note';
  resolve(initial);await applying;
  assert.equal(flow.changes.length,0);
  assert.equal(flow.frm.doc.attachments[0].notes,'Newer manual note');
});


test('messages and attachments have scoped simple switches only when needed',async()=>{
  const flow=setup({...data,references:[{name:'REF',reference_type:'Location',latitude:0,longitude:0}]},{attachments:[{name:'REF'}]});
  await flow.context.view_intake_messages(flow.frm);
  const dialog=flow.dialogs[0];
  const navigation=dialog.fields.find(field=>field.fieldname==='review_navigation');
  assert.match(navigation.options,/role="tab" data-intake-tab="messages"/);
  assert.match(navigation.options,/role="tab" data-intake-tab="attachments"/);
  assert.equal(dialog.fields.some(field=>field.fieldtype==='Tab Break'),false);
  assert.equal(dialog.primary_action_label,'Done');
  assert.match(dialog.fields.find(field=>field.fieldname==='review_help').options,/Save the request/);
  const visibility={};
  for(const field of ['conversation','references_display','review_help','reviews'])
    dialog.fields_dict[field]={$wrapper:{toggle(visible){visibility[field]=visible;}}};
  flow.context.set_intake_review_tab(dialog,'attachments');
  assert.deepEqual(visibility,{conversation:false,references_display:true,review_help:true,reviews:true});
  flow.context.set_intake_review_tab(dialog,'messages');
  assert.equal(visibility.conversation,true);assert.equal(visibility.reviews,false);
  const plain=setup(data);await plain.context.view_intake_messages(plain.frm);
  assert.equal(plain.dialogs[0].fields.some(field=>field.fieldname==='review_navigation'),false);
});


test('inline Review attachments opens the attachment pane directly',async()=>{
  const flow=setup({...data,references:[{name:'REF',reference_type:'Location',latitude:0,longitude:0}]},{attachments:[{name:'REF'}]});
  let selected;flow.context.set_intake_review_tab=(dialog,tab)=>{selected=tab;};
  await flow.context.view_intake_messages(flow.frm,'attachments');
  assert.equal(flow.dialogs[0].title,'Review attachments');assert.equal(selected,'attachments');
});

test('location references provide a small map host and safe open-map fallback', () => {
  const flow=setup();
  const html=flow.context.intake_reference_html([{name:'LOCATION',reference_type:'Location',label:'Delivery pin',latitude:17.4,longitude:78.3}],10);
  assert.match(html,/data-intake-map="LOCATION"/);
  assert.match(html,/openstreetmap\.org\/\?mlat=17.4&amp;mlon=78.3/);
  assert.match(html,/Open map/);
});

test('attachment review maps are removed when the dialog closes', async () => {
  const flow=setup();let mounted=0,removed=0;
  flow.context.window={KunalWhatsAppMap:{mount(host,location){mounted++;assert.equal(location.latitude,17.4);return()=>removed++;}}};
  const host={isConnected:true,dataset:{intakeMap:'LOCATION'}};
  const dialog={fields_dict:{references_display:{$wrapper:{get:()=>({querySelectorAll:()=>[host]})}}}};
  await flow.context.mount_intake_review_maps(dialog,{references:[{name:'LOCATION',reference_type:'Location',latitude:17.4,longitude:78.3}]},()=>true);
  assert.equal(mounted,1);dialog.onhide();assert.equal(removed,1);
});

test('closing attachment review before its optional map asset loads prevents a late map', async () => {
  const flow=setup();let loaded,mounted=0;
  flow.context.window={};flow.context.frappe.require=()=>new Promise(resolve=>{loaded=resolve;});
  const host={isConnected:true,dataset:{intakeMap:'LOCATION'}};
  const dialog={fields_dict:{references_display:{$wrapper:{get:()=>({querySelectorAll:()=>[host]})}}}};
  const pending=flow.context.mount_intake_review_maps(dialog,{references:[{name:'LOCATION',reference_type:'Location',latitude:17.4,longitude:78.3}]},()=>true);
  dialog.onhide();flow.context.window.KunalWhatsAppMap={mount(){mounted++;return()=>{};}};
  loaded();await pending;assert.equal(mounted,0);
});

test('dialog maps use the current HTML node after an asynchronous asset load', async () => {
  const flow=setup();let loaded,mounted;
  flow.context.window={};flow.context.frappe.require=()=>new Promise(resolve=>{loaded=resolve;});
  const old={isConnected:true,dataset:{intakeMap:'LOCATION'}};
  let current=old;
  const dialog={fields_dict:{references_display:{$wrapper:{get:()=>({querySelectorAll:()=>[current]})}}}};
  const pending=flow.context.mount_intake_review_maps(dialog,{references:[{name:'LOCATION',reference_type:'Location',latitude:17.4,longitude:78.3}]},()=>true);
  old.isConnected=false;current={isConnected:true,dataset:{intakeMap:'LOCATION'}};
  flow.context.window.KunalWhatsAppMap={mount(host){mounted=host;return()=>{};}};
  loaded();await pending;assert.equal(mounted,current);
});
