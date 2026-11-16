import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../kunal_enterprises/kunal_enterprises/doctype/order_intake_request/order_intake_request.js',import.meta.url),'utf8');
function setup(row={quantity:0,quantity_unknown:1}) {
 const handlers={},changed=[];
 const context={__:s=>s,locals:{'Order Intake Item':{ROW:row}},frappe:{ui:{form:{on:(type,h)=>handlers[type]=h}},utils:{escape_html:v=>String(v)},model:{set_value:(type,name,field,value)=>{changed.push([field,value]);row[field]=value;return Promise.resolve();}}}};
 vm.createContext(context);vm.runInContext(source,context);return {context,handlers,row,changed};
}
test('unknown quantities render confirmation rather than zero in grid and Order confirmation',()=>{
 const {context}=setup();
 assert.equal(context.intake_quantity_formatter(0,{},null,{quantity_unknown:1}),'Needs confirmation');
 assert.equal(context.intake_quantity_formatter(0,{},null,{quantity_unknown:0}), '0');
 const html=context.intake_processing_summary({name:'OIR',items:[{item:'SKU',quantity:0,quantity_unknown:1}]},'convert');
 assert.match(html,/Needs confirmation/);assert.doesNotMatch(html,/<td>0 /);
});
test('explicit number including zero clears unknown while blank keeps unknown',async()=>{
 for(const quantity of [0,4,null,'']){
  const flow=setup({quantity,quantity_unknown:1});
  await flow.handlers['Order Intake Item'].quantity({},'Order Intake Item','ROW');
  assert.equal(flow.row.quantity_unknown,quantity===null || quantity===''?1:0);
 }
});
