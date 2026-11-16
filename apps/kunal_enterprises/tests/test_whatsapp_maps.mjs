import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const source=readFileSync(new URL('../kunal_enterprises/public/js/whatsapp_inbox_maps.js',import.meta.url),'utf8');
function setup({load}={}) {
  const centers=[];let removed=0,children;
  const map={setView(center){centers.push([...center]);return this;},invalidateSize(){},remove(){removed++;}};
  const L={Icon:{Default:{}},map(){return map;},tileLayer(){return{addTo(){}};},marker(){return{addTo(){}};}};
  const context={__:value=>value,window:{L:load?undefined:L},L,document:{createElement(){return{style:{}};},getElementById(){return{};}},frappe:{require:load,utils:{map_defaults:{image_path:'/icons',tiles:'tiles',options:{}}}}};
  vm.createContext(context);vm.runInContext(source,context);
  const element={isConnected:true,replaceChildren(...nodes){children=nodes;}};
  return{context,element,centers,get children(){return children;},get removed(){return removed;}};
}
test('blank, boolean, absent and out-of-range coordinates never create a map or external link',()=>{
  for(const latitude of ['', ' ',false,true,null,undefined,[],{},91,Infinity]) {
    const flow=setup();flow.context.window.KunalWhatsAppMap.mount(flow.element,{latitude,longitude:0});
    assert.equal(flow.children,undefined,`invalid coordinate ${String(latitude)}`);
  }
});
test('valid zero coordinates keep the map link, marker location and cleanup',async()=>{
  const flow=setup();const cleanup=flow.context.window.KunalWhatsAppMap.mount(flow.element,{latitude:0,longitude:0});
  await Promise.resolve();await Promise.resolve();
  assert.match(flow.children[1].href,/mlat=0&mlon=0/);
  assert.equal(flow.children[1].rel,'noopener noreferrer');assert.deepEqual(flow.centers,[[0,0]]);
  cleanup();assert.equal(flow.removed,1);
});
test('a failed optional library leaves the ordinary map link usable',async()=>{
  const flow=setup({load(){throw new Error('Unavailable library');}});
  assert.doesNotThrow(()=>flow.context.window.KunalWhatsAppMap.mount(flow.element,{latitude:17,longitude:78}));
  await Promise.resolve();await Promise.resolve();await Promise.resolve();
  assert.match(flow.children[1].href,/mlat=17&mlon=78/);
});
