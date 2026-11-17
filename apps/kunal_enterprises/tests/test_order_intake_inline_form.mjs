import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order_intake_request/order_intake_request.js',import.meta.url),'utf8');
const data={request:'OIR-CHAT',modified:'rev-1',revision:'evidence-1',total_linked:2,has_more:false,sender_profile_name:'Sender',messages:[{name:'MSG-2',sender_name:'Sender',received_at:'2026-11-12 10:00',text:'21317 MR 4 NOS',warnings:[]}],references:[]};
function setup(response=data,values={}) {
  const calls=[],html=[],buttons=new Map(),childHandlers={};let handlers,click,history;
  const wrapper={html(value){html.push(value);history=value.includes('intake-chat-history')?{scrollTop:0,scrollHeight:(value.match(/Open original message/g)||[]).length*100}:null;return this;},find(){return{get(){return history;}};},off(){return this;},on(event,selector,handler){click=handler;return this;}};
  const frm={doc:{name:'OIR-CHAT',modified:'rev-1',request_type:'Unclear',status:'Pending Review',source_messages:[{name:'ROW',message:'MSG-2'}],attachments:[],items:[],...values},
    fields_dict:new Proxy({}, {get:(target,name)=>({$wrapper:name==='conversation_display'?wrapper:{html(){}},grid:{update_docfield_property(){}},df:{}})}),
    is_new(){return this.doc.name.startsWith('new-');},is_dirty(){return Boolean(this.doc.__unsaved);},set_intro(){},set_df_property(){},toggle_display(){},page: {add_menu_item(label, action) {buttons.set('Menu/' + label, action);}},
    add_custom_button(label,action,group){buttons.set((group||'')+'/'+label,action);}};
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const context={__:text=>text,frappe:{utils:{escape_html:escape},ui:{form:{on(type,value){if(type==='Order Intake Request')handlers=value;else childHandlers[type]=value;}}},async call(value){calls.push(value);return{message:typeof response==='function'?await response(value):response};}}};
  vm.createContext(context);vm.runInContext(source,context);
  return{frm,context,calls,html,buttons,handlers,childHandlers,get history(){return history;},click(action){return click({currentTarget:{dataset:{intakeChat:action}}});}};
}

test('saved requests automatically render safe chronological bubbles in a bounded chat area without the old toolbar action',async()=>{
  const flow=setup();await flow.context.refresh_intake_messages(flow.frm);
  assert.equal(flow.calls.length,1);assert.equal(flow.calls[0].type,'GET');assert.equal(flow.calls[0].silent,true);assert.equal(flow.calls[0].args.expected_modified,'rev-1');
  const html=flow.html.at(-1);assert.match(html,/21317 MR 4 NOS/);assert.match(html,/Sender/);assert.match(html,/Nov/);assert.match(html,/>10:00<\/time>/);assert.match(html,/max-height:480px;overflow-y:auto/);
  flow.handlers.refresh(flow.frm);assert.equal(flow.buttons.has('/View messages'),false);
});

test('new requests show save guidance and do not read persisted messages',async()=>{
  const flow=setup(data,{name:'new-order-intake-request'});await flow.context.refresh_intake_messages(flow.frm);
  assert.equal(flow.calls.length,0);assert.match(flow.html.at(-1),/after this request is saved/);
});

test('newer refreshes and switched records cannot receive an earlier asynchronous chat response',async()=>{
  const pending=[];const flow=setup(()=>new Promise(resolve=>pending.push(resolve)));
  const first=flow.context.refresh_intake_messages(flow.frm);flow.frm.doc.name='OTHER';const second=flow.context.refresh_intake_messages(flow.frm);
  pending[1]({...data,request:'OTHER',messages:[{name:'OTHER-MSG',text:'New request text'}]});await second;
  pending[0](data);await first;assert.match(flow.html.at(-1),/New request text/);assert.doesNotMatch(flow.html.at(-1),/21317/);
});

test('older pages preserve evidence revision and prepend messages without allowing duplicate clicks',async()=>{
  let resolve;const flow=setup(call=>call.args.cursor?new Promise(done=>{resolve=done;}):{...data,has_more:true,next_cursor:'MSG-2'});
  await flow.context.refresh_intake_messages(flow.frm);assert.equal(flow.history.scrollTop,100);flow.history.scrollTop=20;const first=flow.click('older');await flow.click('older');assert.equal(flow.calls.length,2);
  resolve({...data,messages:[{name:'MSG-1',text:'Earlier request',warnings:[]}]});await first;
  assert.equal(flow.history.scrollTop,120);assert.equal(flow.calls[1].args.revision,'evidence-1');assert.equal(flow.calls[1].args.cursor,'MSG-2');
  const html=flow.html.at(-1);assert.ok(html.indexOf('Earlier request')<html.indexOf('21317'));assert.doesNotMatch(html,/Load older messages/);
});

test('failed or stale pagination removes old evidence and offers an explicit fresh retry',async()=>{
  let fail=false;const flow=setup(call=>{if(call.args.cursor){fail=true;throw new Error('Access denied');}return{...data,has_more:!fail,next_cursor:'MSG-2'};});
  await flow.context.refresh_intake_messages(flow.frm);await flow.click('older');
  assert.match(flow.html.at(-1),/Retry/);assert.doesNotMatch(flow.html.at(-1),/21317/);
  await flow.click('refresh');assert.match(flow.html.at(-1),/21317/);assert.equal(flow.calls[2].args.revision,undefined);
});

test('item corrections keep chat usable but unsaved sender/account/source changes clear it and require saving',async()=>{
  for(const [field,value] of [['sender_number','919000000000'],['whatsapp_account','OTHER'],['source_messages',[{message:'DIFFERENT'}]]]){
    const flow=setup();await flow.context.refresh_intake_messages(flow.frm);
    flow.frm.doc.__unsaved=true;flow.frm.doc.items.push({quantity:9});await flow.click('refresh');assert.match(flow.html.at(-1),/21317/);
    flow.frm.doc[field]=value;flow.context.invalidate_intake_messages(flow.frm);
    assert.match(flow.html.at(-1),/Save your message changes/);assert.doesNotMatch(flow.html.at(-1),/21317/);
    const count=flow.calls.length;await flow.click('refresh');assert.equal(flow.calls.length,count);
    await flow.context.refresh_intake_messages(flow.frm);assert.equal(flow.calls.length,count);
  }
});

test('messages and references stay escaped and media/files require a manual action',async()=>{
  const attack='<img src=x onerror=bad()>';
  const flow=setup({...data,messages:[{name:'M',text:attack,sender_name:attack,location:{name:attack,latitude:0,longitude:0},attachment:{available:true,url:'/private/files/test.pdf',file_name:attack},warnings:[attack]}],references:[{name:'REF',reference_type:'File'}]});
  await flow.context.refresh_intake_messages(flow.frm);const html=flow.html.at(-1);
  assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img|<iframe|<audio|<video/);assert.match(html,/openstreetmap\.org\/\?mlat=0&amp;mlon=0/);assert.match(html,/Review attachments/);assert.match(html,/Open file/);
});


test('chat uses compact incoming bubbles, date separators and bottom timestamps without a header or composer',()=>{
  const flow=setup();const html=flow.context.intake_conversation_html({...data,messages:[...data.messages,{...data.messages[0],name:'M3',text:'Second',received_at:'2026-11-12 10:05'},{...data.messages[0],name:'M4',text:'Next day',received_at:'2026-11-13 09:00'}]});
  assert.equal((html.match(/class="intake-chat-date"/g)||[]).length,2);
  assert.equal((html.match(/class="intake-chat-bubble"/g)||[]).length,3);
  assert.match(html,/width:fit-content/);assert.match(html,/max-width:78%/);assert.match(html,/>10:05<\/time>/);
  assert.match(html,/class="intake-chat-meta"/);assert.doesNotMatch(html,/class="intake-chat-sender"/);
  assert.doesNotMatch(html,/<input|<textarea|class="intake-chat-header"/);
});


test('attachment tiles show type icons, filenames and known metadata with manual open/download actions',()=>{
  const flow=setup();const file={available:true,url:'/private/files/report.pdf',file_name:'report.pdf',file_type:'pdf',size_bytes:2048,page_count:12};
  const html=flow.context.intake_conversation_file(file);assert.match(html,/>PDF<\/span>/);assert.match(html,/12 pages · 2.0 KB · PDF/);assert.match(html,/download="report.pdf"/);assert.match(html,/title="Open file"/);assert.doesNotMatch(html,/<iframe|<embed/);
  const chat=flow.context.intake_conversation_html({...data,messages:[{name:'PDF-MESSAGE',attachment:file}],references:[{reference_type:'File',source_message:'PDF-MESSAGE',page_count:12,attachment:file}]});assert.match(chat,/12 pages/);
  assert.match(flow.context.intake_conversation_file({...file,file_name:'photo.png',file_type:'PNG',size_bytes:undefined,page_count:undefined}),/>IMG<\/span>/);
  const unknown=flow.context.intake_conversation_file({...file,size_bytes:undefined,page_count:undefined});assert.doesNotMatch(unknown,/KB|pages|NaN/);
});


test('sender summary distinguishes registered sender identity from WhatsApp profile and selected ordering customer',async()=>{
  const payload={...data,sender_number:'919000000001',sender_name:'Reviewer Request Title',sender_profile_name:'WhatsApp Sales Alias',sender_identity:{status:'Matched',matches:[{doctype:'Sales Employee',name:'S-1',label:'Registered Salesperson'}]}};
  const flow=setup(payload,{customer:'ORDERING-CUSTOMER',customer_name:'Ordering Customer'});await flow.context.refresh_intake_messages(flow.frm);
  const html=flow.html.at(-1);assert.doesNotMatch(html,/Sender of these messages/);assert.match(html,/background:#075e54/);assert.match(html,/border-radius:8px 8px 0 0/);assert.match(html,/Registered Salesperson/);assert.match(html,/919000000001 · Salesperson/);assert.match(html,/WhatsApp name: WhatsApp Sales Alias/);assert.doesNotMatch(html,/Ordering Customer|Reviewer Request Title/);
  assert.ok(html.indexOf('intake-chat-sender-summary')<html.indexOf('<div class="intake-chat-history"'));
});

test('sender summary shows unknown, ambiguous and missing numbers without claiming a registered match',()=>{
  const flow=setup();const unknown=flow.context.intake_sender_html({sender_number:'919000000001',sender_profile_name:'Unregistered Alias',sender_identity:{status:'Unknown',matches:[]}});
  assert.match(unknown,/Unregistered Alias/);assert.match(unknown,/Not found in our records/);
  const ambiguous=flow.context.intake_sender_html({sender_number:'919000000001',sender_identity:{status:'Ambiguous',matches:[{doctype:'Customer',label:'Customer A'},{doctype:'Sales Employee',label:'Salesperson B'}]}});
  assert.match(ambiguous,/Multiple matching records/);assert.match(ambiguous,/Customer: Customer A/);assert.match(ambiguous,/Salesperson: Salesperson B/);
  assert.match(flow.context.intake_sender_html({}),/No sender number linked/);
  const attack='<img src=x onerror=bad()>';const escaped=flow.context.intake_sender_html({sender_number:attack,sender_name:attack,sender_identity:{status:'Matched',matches:[{doctype:'Customer',label:attack}]}});
  assert.doesNotMatch(escaped,/<img/);assert.match(escaped,/&lt;img/);
});


test('a reviewer request title is not described as a WhatsApp profile name',()=>{
  const flow=setup();const html=flow.context.intake_sender_html({sender_number:'919000000001',sender_name:'Reviewer Title',sender_identity:{status:'Matched',matches:[{doctype:'Customer',name:'C-1',label:'Actual Customer'}]}});
  assert.match(html,/Actual Customer/);assert.doesNotMatch(html,/WhatsApp name|Reviewer Title/);
});

test('unknown sender uses their number when no actual WhatsApp profile name exists',()=>{
  const flow=setup();const html=flow.context.intake_sender_html({sender_number:'919000000001',sender_name:'Reviewer Request Title',sender_identity:{status:'Unknown',matches:[]}});
  assert.match(html,/<strong[^>]*>919000000001<\/strong>/);assert.doesNotMatch(html,/Reviewer Request Title/);
});


test('the scrollable transcript can receive keyboard focus and has an accessible label',()=>{
  const flow=setup();const html=flow.context.intake_conversation_html(data);
  assert.match(html,/<div class="intake-chat-history" tabindex="0" role="region" aria-label="Linked WhatsApp messages"/);
});

test('replies quote available source text safely without exposing internal message IDs',()=>{
  const flow=setup();const html=flow.context.intake_conversation_html({messages:[{name:'internal-parent-id',text:'<b>Original requested item</b>'},{name:'reply',text:'Five please',reply_to:'internal-parent-id'},{name:'other',text:'Another reply',reply_to:'unloaded-internal-id'}]});
  assert.match(html,/<div class="intake-chat-reply">&lt;b&gt;Original requested item&lt;\/b&gt;<\/div>/);
  assert.match(html,/<div class="intake-chat-reply">Reply to an earlier message<\/div>/);
  assert.doesNotMatch(html,/Reply to linked message|intake-chat-reply">unloaded-internal-id/);
});

test('linked image and PDF bubbles reserve Inbox-style preview slots while other documents remain file tiles',()=>{
  const flow=setup();
  for(const [name,type] of [['photo.png','PNG'],['pages.pdf','PDF']]){
    const html=flow.context.intake_conversation_html({...data,messages:[{name:'MEDIA',attachment:{available:true,url:'/private/files/'+name,file_name:name,file_type:type}}]},true);
    assert.match(html,/data-intake-preview="MEDIA"/);assert.match(html,/Attachment preview/);assert.match(html,/download=/);
  }
  assert.match(flow.context.intake_conversation_html({...data,messages:[{name:'NO-EXT',content_type:'image',attachment:{available:true,url:'/private/files/whatsapp-image',file_name:'whatsapp-image'}}]},true),/data-intake-preview="NO-EXT"/);
  assert.doesNotMatch(flow.context.intake_conversation_file({available:true,url:'/private/files/list.csv',file_name:'list.csv'},'MEDIA'),/data-intake-preview/);
});

test('preview loading is request-scoped and late responses cannot paint switched or edited evidence',async()=>{
  for(const change of ['none','request','revision','context','external','disconnected']){
    let resolve;const flow=setup(()=>new Promise(done=>{resolve=done;}));
    const host={dataset:{intakePreview:'MSG-2'},isConnected:true,innerHTML:''};
    const history={querySelectorAll:()=>[host],scrollHeight:100,scrollTop:0,clientHeight:100};
    const payload={...data,messages:[{name:'MSG-2',attachment:{available:true,url:'/private/files/photo.png'}}]};
    const chat={request:flow.frm.doc.name,context:flow.context.intake_inline_context(flow.frm),data:payload};flow.frm.__intake_chat=chat;
    const pending=flow.context.mount_intake_previews(flow.frm,chat,history);
    assert.equal(flow.calls[0].method,'kunal_enterprises.api.order_intake_conversation.preview');
    assert.equal(flow.calls[0].args.request,'OIR-CHAT');assert.equal(flow.calls[0].args.revision,'evidence-1');assert.equal(flow.calls[0].args.expected_modified,'rev-1');
    if(change==='request')flow.frm.__intake_chat={};
    if(change==='disconnected')host.isConnected=false;
    if(change==='revision')chat.data={...payload,revision:'new-evidence'};
    if(change==='context')flow.frm.doc.sender_number='other';
    resolve({available:true,url:change==='external'?'https://example.com/private.png':'/private/files/preview.png',width:400,height:300});await pending;
    if(change==='none'){assert.match(host.innerHTML,/<img/);assert.match(host.innerHTML,/href="\/private\/files\/photo.png"/);}
    else assert.equal(host.innerHTML,'');
  }
});

test('shared locations render a map host and safe open-map fallback, including zero coordinates', () => {
  const flow=setup();
  const html=flow.context.intake_conversation_html({messages:[{name:'PIN',location:{latitude:0,longitude:0,name:'<Site>'}}]});
  assert.match(html,/data-intake-map="PIN"/);
  assert.match(html,/openstreetmap\.org\/\?mlat=0&amp;mlon=0/);
  assert.match(html,/Open map/);
  assert.match(html,/&lt;Site&gt;/);
  const invalid=flow.context.intake_conversation_html({messages:[{name:'BAD',location:{latitude:'javascript:alert(1)',longitude:0}}]});
  assert.doesNotMatch(invalid,/data-intake-map=|href="https:\/\/www.openstreetmap/);
});

test('inline maps reuse the Inbox renderer and are cleaned up when the transcript refreshes', async () => {
  const flow=setup({...data,messages:[{name:'PIN',location:{latitude:17,longitude:78}}]});
  await flow.context.refresh_intake_messages(flow.frm);
  let mounted=0,removed=0;
  flow.context.window={KunalWhatsAppMap:{mount(host,location){assert.equal(location.latitude,17);mounted++;return()=>removed++;}}};
  const host={dataset:{intakeMap:'PIN'},isConnected:true};
  await flow.context.mount_intake_maps(flow.frm,flow.frm.__intake_chat,{querySelectorAll:()=>[host]});
  assert.equal(mounted,1);
  flow.context.render_intake_messages(flow.frm,flow.frm.__intake_chat);
  assert.equal(removed,1);
});

test('a delayed map asset cannot paint a different request after navigation', async () => {
  const flow=setup({...data,messages:[{name:'PIN',location:{latitude:17,longitude:78}}]});
  await flow.context.refresh_intake_messages(flow.frm);
  let loaded,mounted=0;
  flow.context.window={};
  flow.context.frappe.require=()=>new Promise(resolve=>{loaded=resolve;});
  const host={dataset:{intakeMap:'PIN'},isConnected:true};
  const pending=flow.context.mount_intake_maps(flow.frm,flow.frm.__intake_chat,{querySelectorAll:()=>[host]});
  flow.frm.doc.name='ANOTHER';
  flow.context.window.KunalWhatsAppMap={mount(){mounted++;return()=>{};}};
  loaded();await pending;
  assert.equal(mounted,0);
});

test('a reply keeps its authorized quote when the original is on an older page', () => {
  const flow=setup();
  const html=flow.context.intake_conversation_html({messages:[{name:'REPLY',reply_to:'OLDER',text:'Please send',reply_context:{text:'<21317 MR+ 2 sheets>'}}]});
  assert.match(html,/&lt;21317 MR\+ 2 sheets&gt;/);
  assert.doesNotMatch(html,/Reply to an earlier message|<21317/);
});

test('empty coordinates do not silently become a zero-location pin', () => {
  const flow=setup();
  for(const latitude of ['', ' ',false,[],{}]) {
    const html=flow.context.intake_conversation_html({messages:[{name:'PIN',location:{latitude,longitude:0}}]});
    assert.doesNotMatch(html,/data-intake-map="/);
    assert.match(html,/Location preview unavailable/);
  }
});

test('a deleted or failed thumbnail falls back to the original attachment action', async () => {
  const flow=setup({available:true,url:'/private/files/thumb.png',width:100,height:100});
  let onError;
  const host={dataset:{intakePreview:'MSG-2'},isConnected:true,innerHTML:'',querySelector(){return{addEventListener(event,handler){assert.equal(event,'error');onError=handler;}};}};
  const history={querySelectorAll:()=>[host],scrollHeight:100,scrollTop:0,clientHeight:100};
  const chat={request:flow.frm.doc.name,context:flow.context.intake_inline_context(flow.frm),data:{...data,messages:[{name:'MSG-2',attachment:{available:true,url:'/private/files/original.pdf'}}]}};
  flow.frm.__intake_chat=chat;
  await flow.context.mount_intake_previews(flow.frm,chat,history);
  assert.match(host.innerHTML,/href="\/private\/files\/original.pdf"/);
  onError();assert.match(host.textContent,/Preview unavailable. Open the attachment below/);
});

test('current questions appear once above the chat; historical AI labels never appear on message bubbles', async()=>{
  const stale='AI: Needs review: Are these separate scopes?';
  const question='Select the product or variant for “102 HG”.';
  const payload={...data,review_questions:[question,question,'  '+question+'  '],messages:[
    {...data.messages[0],warnings:[stale,'Attachment unavailable']},
    {...data.messages[0],name:'MSG-3',warnings:[stale,'Attachment unavailable']}]};
  const flow=setup(payload);await flow.context.refresh_intake_messages(flow.frm);
  const html=flow.html.at(-1);
  assert.equal((html.match(/class="intake-review-section"/g)||[]).length,1);
  assert.equal((html.match(/Select the product or variant/g)||[]).length,1);
  assert.equal((html.match(/Attachment unavailable/g)||[]).length,1);
  assert.ok(html.indexOf('Please review')<html.indexOf('intake-chat-sender-summary'));
  assert.doesNotMatch(html,/separate scopes|AI: Needs review|class="intake-chat-warning"/);
});

test('review section is absent when nothing needs review, and question text is escaped',()=>{
  const flow=setup();assert.equal(flow.context.intake_review_html({...data,review_questions:[]}), '');
  const html=flow.context.intake_review_html({...data,review_questions:['<img src=x onerror=bad()>']});
  assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img/);
});
