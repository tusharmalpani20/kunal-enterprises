import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../kunal_enterprises/kunal_enterprises/page/whatsapp_inbox/whatsapp_inbox.js',import.meta.url),'utf8');
const account={name:'ACCOUNT-A',label:'Business A'};
const conversation={sender:'919000000001',display_name:'Customer A',last_received_at:'2026-11-13 10:00:00',preview:'An order',identity:{status:'Matched',matches:[{doctype:'Customer',label:'Customer A'}]}};
const page=(messages=[],extra={})=>({account:account.name,sender:conversation.sender,sender_profile_name:'Customer A',sender_identity:conversation.identity,messages,has_more:false,next_cursor:null,newest_cursor:'CUR-1',...extra});
const message=(name,text=name)=>({name,text,received_at:'2026-11-13 10:00:00',warnings:[]});
function setup(response,extraFrappe={}) {
  const calls=[],emits=[],handlers=new Map(),listeners=new Map(),html={},dialogs=[];let history;
  const list={scrollTop:0};
  const root={appendTo(){return this;},on(event,selector,callback){handlers.set(selector,callback);return this;},html(value){html.root=value;return this;},find(selector){return{
    html(value){html[selector]=value;if(selector==='.wa-chat')history=value.includes('class="wa-history"')?{scrollTop:0,clientHeight:150,scrollHeight:(value.match(/class="wa-bubble"/g)||[]).length*100}:null;return this;},
    get(){return selector==='.wa-history'?history:selector==='.wa-list'?list:null;},each(){},removeClass(){return this;}
  };}};
  const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const realtime={on(name,callback){listeners.set('realtime:'+name,callback);},off(name){listeners.delete('realtime:'+name);},emit(...args){emits.push(args);},socket:{on(name,callback){listeners.set('socket:'+name,callback);},off(name){listeners.delete('socket:'+name);}}};
  const events={addEventListener(name,callback){listeners.set(name,callback);},removeEventListener(name){listeners.delete(name);}};
  const context={__:value=>value,$:()=>root,window:events,document:{...events,visibilityState:'visible'},setTimeout,clearTimeout,
    frappe:{pages:{'whatsapp-inbox':{}},utils:{escape_html:escape},datetime:{get_today:()=> '2026-11-13'},ui:{make_app_page(){return{main:{}};},Dialog:class{constructor(options){Object.assign(this,options);dialogs.push(this);}show(){}hide(){this.hidden=true;}}},realtime,
      ...extraFrappe,async call(value){calls.push(value);const action=value.method.split('.').pop();const result=response?await response(action,value.args):action==='accounts'?{accounts:[account]}:action==='conversations'?{account:account.name,conversations:[conversation],has_more:false}:page([message('M1')]);return{message:result};}}};
  vm.createContext(context);vm.runInContext(source+';this.Inbox=WhatsAppInbox;',context);const inbox=new context.Inbox({});
  return{inbox,calls,emits,listeners,html,handlers,list,dialogs,get history(){return history;}};
}

test('multiple accounts require an explicit choice before any conversations or messages are read',async()=>{
  const flow=setup(action=>action==='accounts'?{accounts:[account,{name:'ACCOUNT-B',label:'Business B'}]}:{account:account.name,conversations:[],has_more:false});
  await flow.inbox.show();assert.equal(flow.calls.length,1);assert.equal(flow.inbox.account,'');assert.match(flow.html.root,/Choose a WhatsApp account/);
  await flow.inbox.chooseAccount(account.name);assert.equal(flow.calls[1].args.account,account.name);assert.deepEqual(flow.emits.at(-1),['doc_subscribe','WhatsApp Account',account.name]);flow.inbox.hide();
});

test('a single readable account opens automatically, with a view-only conversation list and no composer',async()=>{
  const flow=setup();await flow.inbox.show();assert.equal(flow.inbox.account,account.name);assert.equal(flow.calls.length,2);
  assert.match(flow.html.root,/Search name or number/);assert.match(flow.html.root,/Salespersons/);assert.match(flow.html.root,/Clients/);
  await flow.inbox.openChat(conversation.sender);assert.match(flow.html['.wa-chat'],/M1/);assert.doesNotMatch(flow.html['.wa-chat'],/<textarea|Type a message|Voice message|data-action="send"/);
  assert.ok(flow.calls.every(row=>row.type==='GET'));assert.ok(flow.calls.every(row=>!/[Ss]end|read_receipt/.test(row.method)));flow.inbox.hide();
});

test('switching accounts invalidates a pending previous chat and empties the old scope',async()=>{
  let resolve;const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{account:args.account,conversations:[conversation]}:new Promise(done=>{resolve=done;}));
  await flow.inbox.show();const pending=flow.inbox.openChat(conversation.sender);await flow.inbox.chooseAccount('ACCOUNT-B');resolve(page([message('SECRET-A')]));await pending;
  assert.equal(flow.inbox.sender,'');assert.equal(flow.inbox.messages.length,0);assert.doesNotMatch(flow.html['.wa-chat'],/SECRET-A/);flow.inbox.hide();
});

test('later search results cannot be replaced by an older pending list response',async()=>{
  const pending=[];const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:new Promise(resolve=>pending.push({args,resolve})));
  const opening=flow.inbox.show();await new Promise(resolve=>setImmediate(resolve));pending[0].resolve({account:account.name,conversations:[]});await opening;
  flow.inbox.search='first';const first=flow.inbox.loadList();flow.inbox.search='second';const second=flow.inbox.loadList();
  pending[2].resolve({account:account.name,conversations:[{...conversation,display_name:'Second result'}]});await second;
  pending[1].resolve({account:account.name,conversations:[{...conversation,display_name:'Stale result'}]});await first;
  assert.equal(flow.inbox.rows[0].display_name,'Second result');flow.inbox.hide();
});

test('older pages prepend history while incremental updates deduplicate and retain older messages',async()=>{
  const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:args.before?page([message('M0')]):args.after?page([message('M2')],{newest_cursor:'CUR-2'}):page([message('M1')],{has_more:true,next_cursor:'OLD'}));
  await flow.inbox.show();await flow.inbox.openChat(conversation.sender);await flow.inbox.loadChat('older');
  assert.deepEqual(Array.from(flow.inbox.messages,row=>row.name),['M0','M1']);await flow.inbox.loadChat('new');await flow.inbox.loadChat('new');
  assert.deepEqual(Array.from(flow.inbox.messages,row=>row.name),['M0','M1','M2']);assert.equal(flow.calls.filter(row=>row.args.before).length,1);flow.inbox.hide();
});

test('new history uses a local jump indicator when the reader is away from the bottom',async()=>{
  const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:args.after?page([message('M5')],{newest_cursor:'CUR-5'}):page([1,2,3,4].map(i=>message('M'+i))));
  await flow.inbox.show();await flow.inbox.openChat(conversation.sender);flow.history.scrollTop=0;await flow.inbox.loadChat('new');
  assert.equal(flow.inbox.newCount,1);assert.match(flow.html['.wa-chat'],/Jump to latest/);assert.equal(flow.history.scrollTop,0);flow.inbox.hide();
});

test('permission or network errors clear previously displayed message content and offer retry',async()=>{
  let fail=false;const flow=setup((action,args)=>{if(action==='accounts')return{accounts:[account]};if(action==='conversations')return{conversations:[conversation]};if(fail)throw new Error('Permission denied');return page([message('M1','Old content')]);});
  await flow.inbox.show();await flow.inbox.openChat(conversation.sender);fail=true;await flow.inbox.loadChat('new');
  assert.equal(flow.inbox.messages.length,0);assert.doesNotMatch(flow.html['.wa-chat'],/Old content/);assert.match(flow.html['.wa-chat'],/Retry/);flow.inbox.hide();
});

test('hidden page detaches room and window/socket listeners, and pending requests cannot repopulate it',async()=>{
  let done;const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:new Promise(resolve=>{done=resolve;}));
  await flow.inbox.show();const pending=flow.inbox.openChat(conversation.sender);flow.inbox.hide();done(page([message('LATE')]));await pending;
  assert.equal(flow.listeners.size,0);assert.deepEqual(flow.emits.at(-1),['doc_unsubscribe','WhatsApp Account',account.name]);assert.equal(flow.inbox.messages.length,0);
});

test('untrusted chat and file metadata is escaped; attachments and locations are not embedded or fetched',()=>{
  const flow=setup(),attack='<img src=x onerror=bad()>';flow.inbox.messages=[{...message('M',attack),attachment:{available:true,url:'/private/files/report.pdf',file_name:attack,file_type:'pdf',size_bytes:2048},location:{name:attack,latitude:0,longitude:0}}];
  const html=flow.inbox.messageHTML();assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<img|<iframe|<audio|<video/);assert.match(html,/2.0 KB/);assert.match(html,/wa-map-host/);assert.doesNotMatch(html,/0, 0/);
  assert.doesNotMatch(flow.inbox.fileHTML({available:true,url:'https://example.com/file.pdf'}),/href=/);
});


test('refresh revalidates loaded message IDs and replaces changed media while removing revoked rows',async()=>{
  const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:args.after?page([],{refreshed_messages:[{...message('M1'),attachment:{available:true,url:'/private/files/new.pdf',file_name:'new.pdf'}}],removed_names:['M2']}):page([message('M1'),message('M2')]));
  await flow.inbox.show();await flow.inbox.openChat(conversation.sender);await flow.inbox.loadChat('new');
  const call=flow.calls.at(-1);assert.deepEqual(JSON.parse(call.args.refresh_names),['M1','M2']);assert.equal(flow.inbox.messages.length,1);assert.equal(flow.inbox.messages[0].attachment.file_name,'new.pdf');assert.match(flow.html['.wa-chat'],/new.pdf/);flow.inbox.hide();
});

test('incremental pages drain in creation order without skipping messages beyond a page',async()=>{
  const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:!args.after?page([message('M1')]):args.after==='CUR-1'?page([message('M2')],{has_more:true,newest_cursor:'CUR-2'}):page([message('M3')],{newest_cursor:'CUR-3'}));
  await flow.inbox.show();await flow.inbox.openChat(conversation.sender);await flow.inbox.loadChat('new');assert.deepEqual(Array.from(flow.inbox.messages,row=>row.name),['M1','M2','M3']);assert.equal(flow.inbox.after,'CUR-3');flow.inbox.hide();
});

test('routine list updates preserve scroll and deduplicate overlapping sender pages',async()=>{
  const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:{conversations:[conversation],has_more:true,next_cursor:'NEXT'});
  await flow.inbox.show();flow.list.scrollTop=120;await flow.inbox.loadList();assert.equal(flow.list.scrollTop,120);await flow.inbox.loadList(true);assert.equal(flow.inbox.rows.length,1);await flow.inbox.loadList(false,true);assert.equal(flow.list.scrollTop,0);flow.inbox.hide();
});

test('account responses received after page hide cannot restore data or subscribe rooms',async()=>{
  let done;const flow=setup(()=>new Promise(resolve=>{done=resolve;}));const opening=flow.inbox.show();flow.inbox.hide();done({accounts:[account]});await opening;assert.equal(flow.inbox.account,'');assert.equal(flow.emits.length,0);
});

test('incoming events while history is loading request another refresh after it completes',async()=>{
  let done,scheduled=0;const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:new Promise(resolve=>{done=resolve;}));
  await flow.inbox.show();flow.inbox.scheduleRefresh=()=>{scheduled++;};const loading=flow.inbox.openChat(conversation.sender);await flow.inbox.loadChat('new');done(page([message('M1')]));await loading;assert.equal(scheduled,1);flow.inbox.hide();
});


test('configured incoming default opens among multiple accounts and account switch lives at the bottom',async()=>{
  const flow=setup((action,args)=>action==='accounts'?{accounts:[account,{name:'ACCOUNT-B',label:'Business B'}],default_account:'ACCOUNT-B'}:{conversations:[],has_more:false});
  await flow.inbox.show();assert.equal(flow.inbox.account,'ACCOUNT-B');assert.match(flow.html.root,/class="wa-account-footer"/);assert.ok(flow.html.root.indexOf('class="wa-account-footer"')>flow.html.root.indexOf('class="wa-list"'));
  flow.inbox.switchAccount();const dialog=flow.dialogs[0];assert.equal(dialog.fields[0].default,'ACCOUNT-B');await dialog.primary_action({account:account.name});assert.equal(flow.inbox.account,account.name);
  assert.ok(flow.calls.every(row=>row.type==='GET'));flow.inbox.hide();
});

test('a realtime message committed behind the creation cursor is recovered by ID and sorted into history',async()=>{
  const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:args.after?page([],{refreshed_messages:[{...message('LATE'),creation:'2026-11-13 09:00:00'}]}):page([{...message('M1'),creation:'2026-11-13 10:00:00'}]));
  await flow.inbox.show();await flow.inbox.openChat(conversation.sender);flow.inbox.changedMessages.add('LATE');await flow.inbox.loadChat('new');
  assert.deepEqual(Array.from(flow.inbox.messages,row=>row.name),['LATE','M1']);assert.ok(JSON.parse(flow.calls.at(-1).args.refresh_names).includes('LATE'));assert.equal(flow.inbox.changedMessages.size,0);flow.inbox.hide();
});

test('events for the same message arriving during a refresh are retained for another pass',async()=>{
  let done;const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:args.after?new Promise(resolve=>{done=resolve;}):page([message('M1')]));
  await flow.inbox.show();await flow.inbox.openChat(conversation.sender);flow.inbox.changedMessages.add('M1');const pending=flow.inbox.loadChat('new');flow.inbox.changedMessages.add('M1');done(page([],{refreshed_messages:[message('M1')]}));await pending;assert.equal(flow.inbox.changedMessages.has('M1'),true);flow.inbox.hide();
});


test('fresh opening honors configured default after an explicit switch in a previous visit',async()=>{
 const flow=setup(action=>action==='accounts'?{accounts:[account,{name:'ACCOUNT-B'}],default_account:account.name}:{conversations:[]});
 await flow.inbox.show();await flow.inbox.chooseAccount('ACCOUNT-B');flow.inbox.hide();await flow.inbox.show();
 assert.equal(flow.inbox.account,account.name);flow.inbox.hide();
});

test('reactions decorate their target and are not rendered as replies or standalone messages',()=>{
 const flow=setup();flow.inbox.messages=[{...message('ORIGINAL','Hello'),reactions:[{emoji:'👍',count:2,actors:['A','B']}]},{...message('EVENT','👍'),content_type:'reaction',reply_to:'ORIGINAL'}];
 const html=flow.inbox.messageHTML();assert.equal((html.match(/class="wa-bubble"/g)||[]).length,1);assert.match(html,/wa-reactions/);assert.match(html,/👍 2/);assert.doesNotMatch(html,/data-message-name="EVENT"|wa-quote/);
});

test('reply quote uses resolved content, marks absent originals honestly, and plays local audio without autoplay',()=>{
 const flow=setup();flow.inbox.messages=[{...message('REPLY'),reply_context:{available:true,target_name:'OLD',summary:'Earlier order',sender_name:'Client A'}},{...message('MISSING'),reply_to:'gone'}];
 const html=flow.inbox.messageHTML();assert.match(html,/data-reply-target="OLD"/);assert.match(html,/Earlier order/);assert.match(html,/Client A/);assert.match(html,/Original message is not stored/);
 const audio=flow.inbox.fileHTML({available:true,url:'/private/files/voice',file_name:'voice',file_type:'audio/ogg'},{content_type:'audio'});assert.match(audio,/<audio controls preload="none"/);assert.doesNotMatch(audio,/autoplay/);
});

test('reply context received after switching chat cannot replace the active conversation',async()=>{
 let resolve;const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:action==='message_context'?new Promise(done=>{resolve=done;}):page([message('M1')]));
 await flow.inbox.show();await flow.inbox.openChat(conversation.sender);const pending=flow.inbox.jumpToMessage('OLD');await flow.inbox.openChat('919000000002');resolve({target:message('OLD'),messages:[message('OLD')]});await pending;
 assert.equal(flow.inbox.sender,'919000000002');assert.equal(flow.inbox.messages[0].name,'M1');flow.inbox.hide();
});

function virtualFixture(fixed=false,followBottom=false) {
 const observers=[];
 class Element {
  constructor(){this.style={};this.dataset={};this.children=[];this.listeners={};this.scrollTop=0;this.clientHeight=600;this._html='';}
  appendChild(node){if(node.parent)node.remove();this.children.push(node);node.parent=this;return node;}
  insertBefore(node,before){if(node.parent)node.remove();const index=this.children.indexOf(before);if(index<0)this.children.push(node);else this.children.splice(index,0,node);node.parent=this;}
  remove(){if(this.parent)this.parent.children=this.parent.children.filter(node=>node!==this);this.parent=null;}
  set innerHTML(value){this._html=value;}get innerHTML(){return this._html;}
  get scrollHeight(){return Math.max(this.clientHeight,...this.children.map(node=>parseFloat(node.style.height)||0));}
  addEventListener(name,fn){this.listeners[name]=fn;}removeEventListener(name){delete this.listeners[name];}
  getBoundingClientRect(){return{top:this.parent?-this.parent.scrollTop:0,height:parseFloat(this.style.height)||100};}
  querySelector(){return null;}
 }
 const context={document:{createElement:()=>new Element()},ResizeObserver:class{constructor(callback){this.callback=callback;observers.push(this);}observe(){}unobserve(){}disconnect(){this.closed=true;}},frappe:{pages:{'whatsapp-inbox':{}}}};
 vm.createContext(context);vm.runInContext(source+';this.List=WhatsAppVirtualList;',context);
 const container=new Element();let edges=0;
 const list=new context.List(container,{key:row=>row.id,html:row=>row.text,estimate:100,fixed,followBottom,onEdge:()=>edges++});
 list.set(Array.from({length:1000},(_,i)=>({id:'M'+i,text:'Message '+i})));
 return{list,container,observers,get edges(){return edges;}};
}

test('1000 loaded rows mount only the viewport and overscan and recycle distant rows',()=>{
 for(const fixed of [false,true]) {
  const {list,container}=virtualFixture(fixed);assert.ok(list.nodes.size<20);assert.equal(list.canvas.style.height,'100000px');
  container.scrollTop=50000;container.listeners.scroll();assert.ok(list.nodes.size<22);assert.ok(list.nodes.has('M500'));assert.equal(list.nodes.has('M0'),false);
  assert.equal(list.scrollTo('M999'),true);assert.ok(list.nodes.has('M999'));assert.ok(list.nodes.size<22);list.destroy();assert.equal(container.children.length,0);
 }
});

test('variable-height resize and older prepend retain the same visible record anchor',()=>{
 const {list,container,observers}=virtualFixture();container.listeners.wheel();container.scrollTop=1000;container.listeners.scroll();
 observers[0].callback([{target:list.nodes.get('M8').node,borderBoxSize:[{blockSize:250}]}]);
 assert.equal(container.scrollTop,1150);assert.equal(list.anchor().key,'M10');
 list.set([{id:'OLDER',text:'Older'},...list.items]);assert.equal(container.scrollTop,1250);assert.equal(list.anchor().key,'M10');
 const node=list.nodes.get('M10').node;list.set(list.items);assert.equal(list.nodes.get('M10').node,node);
 container.listeners.scroll();assert.equal(typeof container.listeners.scroll,'function');list.destroy();assert.equal(observers.every(observer=>observer.closed),true);
});


test('bottom following survives delayed height measurements while DOM stays chronological',()=>{
 const {list,container,observers}=virtualFixture(false,true);list.set(list.items,{bottom:true});
 const keys=()=>list.canvas.children.map(node=>node.dataset.virtualKey);
 assert.deepEqual(keys(),[...keys()].sort((a,b)=>Number(a.slice(1))-Number(b.slice(1))));
 const final=list.nodes.get('M999').node;observers[0].callback([{target:final,borderBoxSize:[{blockSize:350}]}]);
 assert.equal(container.scrollTop,container.scrollHeight);assert.equal(list.pinnedBottom,true);
 container.listeners.wheel();container.scrollTop=50000;container.listeners.scroll();
 assert.equal(list.pinnedBottom,false);assert.equal(container.scrollTop,50000);
 assert.deepEqual(keys(),[...keys()].sort((a,b)=>Number(a.slice(1))-Number(b.slice(1))));list.destroy();
});


test('routine refresh revalidates all loaded conversation pages and drops stale rows',async()=>{
 let records=Array.from({length:160},(_,i)=>({...conversation,sender:String(i),display_name:'Sender '+i}));
 const flow=setup((action,args)=>{if(action==='accounts')return{accounts:[account]};const start=Number(args.cursor || 0),limit=Number(args.limit || 30),end=Math.min(start+limit,records.length);return{conversations:records.slice(start,end),has_more:end<records.length,next_cursor:String(end)};});
 await flow.inbox.show();for(let i=0;i<3;i++)await flow.inbox.loadList(true);assert.equal(flow.inbox.rows.length,120);
 records=records.filter(row=>row.sender!=='5');await flow.inbox.loadList();assert.equal(flow.inbox.rows.length,120);assert.equal(flow.inbox.rows.some(row=>row.sender==='5'),false);assert.equal(flow.inbox.rows.at(-1).sender,'120');
 assert.equal(flow.calls.at(-2).args.limit,100);assert.equal(flow.calls.at(-1).args.limit,20);flow.inbox.hide();
});


test('failure of optional map assets leaves the read-only inbox usable',async()=>{
 const flow=setup(undefined,{require:async()=>{throw new Error('Asset unavailable');}});
 await flow.inbox.show();assert.equal(flow.inbox.account,account.name);flow.inbox.hide();
});

test('destroyed virtual windows ignore queued resize callbacks and repaint attempts',()=>{
 const {list,container,observers}=virtualFixture();const node=list.nodes.get('M0').node;list.destroy();
 observers[0].callback([{target:node,borderBoxSize:[{blockSize:250}]}]);list.paint();
 assert.equal(list.nodes.size,0);assert.equal(container.children.length,0);
});

test('historical quote context offers return to latest and refreshes without draining all newer history',async()=>{
 let newerCalls=0;const flow=setup((action,args)=>action==='accounts'?{accounts:[account]}:action==='conversations'?{conversations:[conversation]}:action==='message_context'?{target:message('OLD'),messages:[message('OLD')],has_newer:true,newest_cursor:'CUR-OLD'}:args.after?(newerCalls++,page([message('NEWER')],{has_more:true,newest_cursor:'CUR-NEXT'})):page([message('LATEST')]));
 await flow.inbox.show();await flow.inbox.openChat(conversation.sender);await flow.inbox.jumpToMessage('OLD');assert.equal(flow.inbox.historyHasNewer,true);assert.match(flow.html['.wa-chat'],/Jump to latest/);
 await flow.inbox.loadChat('new');assert.equal(newerCalls,1);assert.equal(flow.inbox.historyHasNewer,true);
 flow.handlers.get('[data-action]')({currentTarget:{dataset:{action:'bottom'}}});await new Promise(resolve=>setImmediate(resolve));assert.equal(flow.inbox.historyHasNewer,false);assert.equal(flow.inbox.messages[0].name,'LATEST');flow.inbox.hide();
});

test('a refresh finishing after hide cannot clear a newer lifecycle refresh guard',async()=>{
 const flow=setup();await flow.inbox.show();const pending=[];
 flow.inbox.loadList=()=>new Promise(resolve=>pending.push(resolve));
 const old=flow.inbox.refresh();flow.inbox.hide();flow.inbox.active=true;
 const current=flow.inbox.refresh();assert.equal(flow.inbox.refreshing,true);
 pending[0]();await old;assert.equal(flow.inbox.refreshing,true);
 pending[1]();await current;assert.equal(flow.inbox.refreshing,false);flow.inbox.hide();
});
