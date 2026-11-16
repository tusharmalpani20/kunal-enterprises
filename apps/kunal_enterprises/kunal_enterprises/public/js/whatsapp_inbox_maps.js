/* Read-only location previews. Only visible chat rows mount map tiles. */
window.KunalWhatsAppMap = {
 mount(element, location) {
  const numeric=value=>typeof value==='number' || (typeof value==='string' && value.trim()!=='');
  if(!numeric(location?.latitude) || !numeric(location?.longitude))return ()=>{};
  const latitude=Number(location.latitude), longitude=Number(location.longitude);
  if(location?.latitude == null || location?.longitude == null || !Number.isFinite(latitude) || !Number.isFinite(longitude) || Math.abs(latitude)>90 || Math.abs(longitude)>180)return ()=>{};
  let removed=false, map=null;
  const canvas=document.createElement('div');
  canvas.style.cssText='height:160px;width:100%;position:relative;z-index:0';
  const link=document.createElement('a');
  link.textContent=__('Open map');
  link.href=`https://www.openstreetmap.org/?mlat=${latitude}&mlon=${longitude}#map=16/${latitude}/${longitude}`;
  link.target='_blank'; link.rel='noopener noreferrer';
  element.replaceChildren(canvas,link);
  if(!document.getElementById('wa-leaflet-css')){
   const css=document.createElement('link');css.id='wa-leaflet-css';css.rel='stylesheet';css.href='/assets/frappe/js/lib/leaflet/leaflet.css';document.head.append(css);
  }
  const ready=Promise.resolve().then(()=>window.L?undefined:frappe.require('libs.bundle.js'));
  ready.then(()=>{
   if(removed || !element.isConnected || !window.L)return;
   const defaults=frappe.utils.map_defaults;
   L.Icon.Default.imagePath=defaults.image_path;
   map=L.map(canvas,{zoomControl:false,dragging:false,touchZoom:false,doubleClickZoom:false,scrollWheelZoom:false,boxZoom:false,keyboard:false}).setView([latitude,longitude],15);
   L.tileLayer(defaults.tiles,defaults.options).addTo(map);
   L.marker([latitude,longitude],{keyboard:false}).addTo(map);
   map.invalidateSize();
  }).catch(()=>{canvas.textContent='📍';});
  return ()=>{removed=true;if(map)map.remove();};
 }
};
