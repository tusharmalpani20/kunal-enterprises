/* Server guards remain authoritative; avoid presenting refused write actions. */
(() => {
 let installed = false;
 const install = () => {
  const roles = frappe.user_roles || [];
  if (installed || frappe.session.user === "Administrator" || !roles.includes("Sales Portal User") ||
      roles.some(role => ["Owner", "Admin", "System Manager"].includes(role))) return;
  installed = true;
  const style = document.createElement("style");
  style.textContent = `
   .form-footer .comment-box, .timeline-actions,
   .form-sidebar .add-attachment-btn, .form-sidebar .add-assignment-btn,
   .form-sidebar .share-doc-btn, .form-sidebar .tag-area,
   .form-sidebar .like-icon, .form-sidebar .anchor-document-follow,
   .form-sidebar .document-follow, .form-sidebar .follow-document-link, .form-sidebar .unfollow-document-link,
   .btn-new-workspace { display:none !important; }
  `;
  document.head.appendChild(style);
  // Account/doctype rooms publish identifiers outside a salesperson's scope.
  // The Inbox already has recovery polling; individual permitted doc rooms work.
  const emit = frappe.realtime.emit;
  frappe.realtime.emit = function(event, doctype, ...args) {
   if (event === "doctype_subscribe" || (event === "doc_subscribe" && doctype === "WhatsApp Account")) return;
   return emit.call(this, event, doctype, ...args);
  };
 };
 $(document).on("app_ready", install);
 install();
})();
