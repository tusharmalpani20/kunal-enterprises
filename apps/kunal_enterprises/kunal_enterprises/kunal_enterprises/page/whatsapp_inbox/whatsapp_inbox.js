/* A bounded DOM window. Heights are keyed by record, so prepends and late media
 * measurements retain the reader's visible message rather than a pixel guess. */
class WhatsAppVirtualList {
 constructor(container, {key, html, estimate = 100, fixed = false, followBottom = false, onMount, onUnmount, onEdge}) {
  Object.assign(this, {container, key, html, estimate, fixed, followBottom, onMount, onUnmount, onEdge});
  this.items = []; this.heights = new Map(); this.nodes = new Map(); this.offsets = [0];
  this.canvas = document.createElement("div"); this.canvas.className = "wa-virtual-canvas";
  container.appendChild(this.canvas);
  this.scroll = () => {this.pinnedBottom=this.followBottom && this.container.scrollHeight-this.container.scrollTop-this.container.clientHeight<3; this.paint(); this.onEdge?.();};
  this.userScroll=()=>{this.pinnedBottom=false;};
  for(const event of ["wheel","touchstart","pointerdown","keydown"])container.addEventListener(event,this.userScroll,{passive:true});
  container.addEventListener("scroll", this.scroll, {passive:true});
  this.observer = typeof ResizeObserver === "function" ? new ResizeObserver(entries => {
   if(this.destroyed)return; const anchor = this.anchor(); let changed = false;
   for (const entry of entries) {
    const id = entry.target.dataset.virtualKey;
    const height = Math.ceil(entry.borderBoxSize?.[0]?.blockSize || entry.target.getBoundingClientRect().height);
    if (!this.fixed && height > 0 && this.heights.get(id) !== height) {this.heights.set(id, height); changed = true;}
   }
   if (changed) {this.index(); this.canvas.style.height=this.offsets.at(-1)+"px"; this.restore(anchor); if(anchor.bottom || this.pinnedBottom)this.container.scrollTop=this.container.scrollHeight; this.paint();}
  }) : null;
  this.resize = typeof ResizeObserver === "function" ? new ResizeObserver(() => this.paint()) : null;
  this.resize?.observe(container);
 }
 index() {this.offsets = [0]; for (const item of this.items) this.offsets.push(this.offsets.at(-1) + (this.heights.get(this.key(item)) || this.estimate));}
 origin() {return this.canvas.getBoundingClientRect().top - this.container.getBoundingClientRect().top + this.container.scrollTop;}
 find(offset) {let low=0, high=this.items.length; while(low<high) {const mid=(low+high)>>1; if(this.offsets[mid+1] <= offset) low=mid+1; else high=mid;} return low;}
 range(top, height) {return [Math.max(0,this.find(Math.max(0,top-350))), Math.min(this.items.length,this.find(top+height+350)+1)];}
 anchor() {const top=this.container.scrollTop-this.origin(), index=this.find(Math.max(0,top)); return {key:this.items[index] && this.key(this.items[index]), delta:top-this.offsets[index], bottom:this.container.scrollHeight-this.container.scrollTop-this.container.clientHeight<3};}
 restore(anchor) {if(!anchor) return; const index=this.items.findIndex(item=>this.key(item)===anchor.key); if(index>=0) this.container.scrollTop=this.origin()+this.offsets[index]+anchor.delta;}
 set(items, {bottom=false}={}) {if(bottom)this.pinnedBottom=true; const anchor=this.anchor(); this.items=items; this.index(); this.canvas.style.height=this.offsets.at(-1)+"px"; this.restore(anchor); if(bottom) this.container.scrollTop=this.container.scrollHeight; this.paint(); if(bottom && typeof requestAnimationFrame==="function")requestAnimationFrame(()=>{if(this.pinnedBottom){this.container.scrollTop=this.container.scrollHeight;this.paint();}});}
 paint() {
  if(this.destroyed)return;
  this.canvas.style.height=this.offsets.at(-1)+"px";
  const [start,end]=this.range(this.container.scrollTop-this.origin(),this.container.clientHeight);
  const keep=new Set(), ordered=[];
  for(let i=start;i<end;i++) {
   const item=this.items[i], id=this.key(item), html=this.html(item,i); keep.add(id);
   let record=this.nodes.get(id);
   if(!record) {const node=document.createElement("div"); node.className="wa-virtual-row"; node.dataset.virtualKey=id; this.canvas.appendChild(node); record={node}; this.nodes.set(id,record); this.observer?.observe(node);}
   if(record.html!==html) {
    const audio=record.node.querySelector('audio');
    this.onUnmount?.(record.node); record.node.innerHTML=html;
    const replacement=record.node.querySelector('audio');
    if(audio && replacement && audio.getAttribute('src')===replacement.getAttribute('src'))replacement.replaceWith(audio);
    record.html=html; this.onMount?.(record.node,item);
   }
   record.node.style.transform=`translateY(${this.offsets[i]}px)`;
   if(this.fixed) record.node.style.height=this.estimate+"px";
   ordered.push(record.node);
  }
  for(const [id,record] of this.nodes) if(!keep.has(id)) {this.observer?.unobserve(record.node); this.onUnmount?.(record.node); record.node.remove(); this.nodes.delete(id);}
  for(let i=0;i<ordered.length;i++)if(this.canvas.children[i]!==ordered[i])this.canvas.insertBefore(ordered[i],this.canvas.children[i] || null);
  if(this.pinnedBottom)this.container.scrollTop=this.container.scrollHeight;
 }
 scrollTo(id) {this.pinnedBottom=false; const index=this.items.findIndex(item=>this.key(item)===id); if(index<0)return false; this.container.scrollTop=this.origin()+this.offsets[index]-60; this.paint(); return true;}
 destroy() {this.destroyed=true; this.pinnedBottom=false; this.container.removeEventListener("scroll",this.scroll); for(const event of ["wheel","touchstart","pointerdown","keydown"])this.container.removeEventListener(event,this.userScroll); this.observer?.disconnect(); this.resize?.disconnect(); for(const {node} of this.nodes.values())this.onUnmount?.(node); this.nodes.clear(); this.canvas.remove();}
}

/* Incoming history only. All data and file permissions are checked by the API. */
frappe.pages["whatsapp-inbox"].on_page_load = wrapper => {
	wrapper.whatsapp_inbox = new WhatsAppInbox(wrapper);
	$(wrapper).on("hide.whatsappInbox", () => wrapper.whatsapp_inbox.hide());
};
frappe.pages["whatsapp-inbox"].on_page_show = wrapper => wrapper.whatsapp_inbox.show();

class WhatsAppInbox {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({parent: wrapper, title: __("WhatsApp Inbox"), single_column: true});
		this.$root = $('<div class="wa-inbox"></div>').appendTo(this.page.main);
		this.previewCache = new Map();
		this.accounts = [];
		this.account = "";
		this.sender = "";
		this.rows = [];
		this.messages = [];
		this.identity = {};
		this.filter = "All";
		this.search = "";
		this.active = false;
		this.accountVersion = 0;
		this.refreshVersion = 0;
		this.pollVersion = 0;
		this.changedMessages = new Set();
		this.listVersion = 0;
		this.chatVersion = 0;
		this.bind();
		this.onEvent = data => {
			if (data?.account !== this.account) return;
			if (typeof data.message === "string" && data.message) this.changedMessages.add(data.message);
			this.scheduleRefresh();
		};
		this.onReconnect = () => {if (this.active) {this.subscribe(); this.scheduleRefresh();}};
		this.onFocus = () => {if (!this.active)return; this.schedulePolling(); if (document.visibilityState !== "hidden") this.scheduleRefresh();};
	}
	async call(action, args = {}) {
		const response = await frappe.call({method: "kunal_enterprises.api.whatsapp_inbox." + action, type: "GET", args, silent: true});
		return response.message;
	}
	async show() {
		if (this.active) return;
		this.active = true;
		this.accountsLoading = true;
		frappe.realtime?.on?.("whatsapp_inbox_changed", this.onEvent);
		frappe.realtime?.socket?.on("connect", this.onReconnect);
		window.addEventListener("online", this.onReconnect);
		window.addEventListener("focus", this.onFocus);
		document.addEventListener("visibilitychange", this.onFocus);
		this.schedulePolling();
		try {if (frappe.require) await frappe.require("/assets/kunal_enterprises/js/whatsapp_inbox_maps.js");} catch (_) {/* Location fallback remains available if the optional map asset fails. */}
		if (this.active) await this.loadAccounts();
	}
	hide() {
		this.active = false;
		this.destroyWindows();
		this.refreshVersion++; this.pendingRefresh=false; this.pendingHistory=false;
		this.accountVersion++;
		this.changedMessages.clear();
		this.accountsLoading = false; this.listLoading = false; this.chatLoading = false; this.refreshing = false;
		this.listVersion++;
		this.chatVersion++;
		clearTimeout(this.refreshTimer);
		clearTimeout(this.searchTimer);
		clearTimeout(this.pollTimer); this.pollTimer=null; this.pollVersion++;
		this.unsubscribe();
		frappe.realtime?.off?.("whatsapp_inbox_changed", this.onEvent);
		frappe.realtime?.socket?.off("connect", this.onReconnect);
		window.removeEventListener("online", this.onReconnect);
		window.removeEventListener("focus", this.onFocus);
		document.removeEventListener("visibilitychange", this.onFocus);
	}
	subscribe() {
		// Direct room emission avoids Desk's global subscription throttle and
		// re-joins the guarded document room on a fresh Socket.IO connection.
		if (this.active && this.account && frappe.realtime?.socket) frappe.realtime.emit("doc_subscribe", "WhatsApp Account", this.account);
	}
	unsubscribe() {
		if (this.account && frappe.realtime?.socket) frappe.realtime.emit("doc_unsubscribe", "WhatsApp Account", this.account);
	}
	async loadAccounts() {
		const version = ++this.accountVersion;
		this.accountError = "";
		this.accountsLoading = true;
		this.render();
		try {
			const data = await this.call("accounts");
			if (!this.active || version !== this.accountVersion) return;
			this.accounts = data.accounts || [];

			this.accountsLoading = false;
			if (this.accounts.length === 1) await this.chooseAccount(this.accounts[0].name);
			else if (this.accounts.some(row => row.name === data.default_account)) await this.chooseAccount(data.default_account);
			else await this.chooseAccount("");
		} catch (_) {
			if (!this.active || version !== this.accountVersion) return;
			this.unsubscribe(); this.account = ""; this.sender = ""; this.rows = []; this.messages = [];
			this.accountsLoading = false;
			this.accountError = __("Accounts could not be loaded. Check your access and try again.");
			this.render();
		}
	}
	async chooseAccount(account) {
		this.unsubscribe();
		this.listVersion++; this.chatVersion++; this.refreshVersion++;
		this.refreshing=false; this.pendingRefresh=false; this.pendingHistory=false; this.historyHasNewer=false;
		this.account = account;
		this.changedMessages.clear();
		this.sender = ""; this.rows = []; this.messages = []; this.identity = {};
		this.listCursor = null; this.before = null; this.after = null;
		this.listError = ""; this.chatError = ""; this.newCount = 0;
		this.search = ""; this.filter = "All";
		this.subscribe(); this.render();
		if (account) await this.loadList();
	}
	bind() {
		this.$root.on("change", "[data-account]", event => this.chooseAccount(event.currentTarget.value));
		this.$root.on("click", "[data-filter]", event => {
			this.filter = event.currentTarget.dataset.filter;
			this.clearChat(); this.loadList(false, true);
		});
		this.$root.on("input", "[data-search]", event => {
			this.search = event.currentTarget.value;
			this.listVersion++; this.clearChat(); this.rows = []; this.listCursor = null; this.listLoading = true; this.renderList();
			clearTimeout(this.searchTimer);
			this.searchTimer = setTimeout(() => this.active && this.loadList(false, true), 250);
		});
		this.$root.on("click", "[data-sender]", event => this.openChat(event.currentTarget.dataset.sender));
		this.$root.on("click", "[data-reply-target]", event => this.jumpToMessage(event.currentTarget.dataset.replyTarget));
		this.$root.on("click", "[data-action]", event => {
			const action = event.currentTarget.dataset.action;
			if (action === "accounts") this.loadAccounts();
			if (action === "switch-account") this.switchAccount();
			if (action === "refresh") this.refresh();
			if (action === "list-more") this.loadList(true);
			if (action === "list-retry") this.loadList();
			if (action === "older") this.loadChat("older");
			if (action === "chat-retry") this.loadChat("initial");
			if (action === "bottom") {if(this.historyHasNewer)this.openChat(this.sender);else {this.newCount=0;this.renderChat(true);}}
			if (action === "back") {this.sender = ""; this.chatVersion++; this.render();}
		});
	}
	clearChat() {
		this.sender = ""; this.chatVersion++; this.chatLoading = false; this.messages = []; this.identity = {}; this.chatError = "";
		this.$root.find(".wa-layout").removeClass("wa-chat-open");
		this.renderChat();
	}
	// Realtime remains the fast path. This bounded recovery poll also covers
	// disconnected sockets and local development's alternate site/port routing.
	schedulePolling() {
		clearTimeout(this.pollTimer); this.pollTimer=null;
		const version=++this.pollVersion;
		if(!this.active || document.visibilityState==="hidden")return;
		this.pollTimer=setTimeout(async()=>{
			this.pollTimer=null;
			try {
				if(this.active && document.visibilityState!=="hidden" && this.account && !this.accountsLoading && !this.refreshing && !this.listLoading && !this.chatLoading)await this.refresh();
			} finally {if(version===this.pollVersion)this.schedulePolling();}
		},15000);
	}

	scheduleRefresh() {
		if (!this.active || !this.account) return;
		clearTimeout(this.refreshTimer);
		this.refreshTimer = setTimeout(() => this.refresh(), 200);
	}
	async refresh() {
		if (!this.active || !this.account) return;
		if (this.refreshing) {this.pendingRefresh = true; return;}
		this.refreshing = true;
		const version=++this.refreshVersion;
		try {await Promise.all([this.loadList(), this.sender ? this.loadChat("new") : Promise.resolve()]);}
		finally {if(version!==this.refreshVersion)return; this.refreshing = false; if (this.pendingRefresh) {this.pendingRefresh = false; this.scheduleRefresh();}}
	}
	async loadList(older = false, reset = false) {
		if (!this.account || (older && (!this.listCursor || this.listLoading))) return;
		const version = ++this.listVersion;
		const account = this.account;
		const position = reset ? 0 : this.$root.find(".wa-list").get(0)?.scrollTop || 0;
		this.listLoading = true;
		this.listError = "";
		if (reset) {this.rows = []; this.listCursor = null;}
		this.renderList();
		try {
			// Revalidate the already loaded range, not only its first page. This
			// retains scrolling without keeping records whose access was revoked.
			const wanted=older?30:Math.max(30,this.rows.length), collected=[];
			let cursor=older?this.listCursor:null, data;
			do {
				data=await this.call("conversations", {account,search:this.search,sender_type:this.filter,limit:Math.min(100,wanted-collected.length),...(cursor?{cursor}:{})});
				if (!this.active || version !== this.listVersion || account !== this.account) return;
				collected.push(...(data.conversations || []));
				const next=data.has_more?data.next_cursor:null;
				if (!next || next===cursor || older) break;
				cursor=next;
			} while(collected.length<wanted);
			this.rows=[...new Map((older?[...this.rows,...collected]:collected).map(row=>[row.sender,row])).values()];
			this.listCursor=data.has_more?data.next_cursor:null;
		} catch (_) {
			if (!this.active || version !== this.listVersion) return;
			this.rows = []; this.listCursor = null;
			this.listError = __("Conversations could not be loaded. Refresh or check your access.");
			// A failed scope check must not leave a previously readable chat visible.
			this.clearChat(); this.renderChat();
		} finally {
			if (version === this.listVersion) {
				this.listLoading = false; this.renderList();
				const list = this.$root.find(".wa-list").get(0); if (list && (reset || !this.listWindow)) list.scrollTop = position;
			}
		}
	}
	async openChat(sender) {
		if (!this.account) return;
		this.sender = sender;
		this.historyHasNewer=false;
		this.jumpVersion = (this.jumpVersion || 0) + 1;
		this.chatVersion++; this.messages = []; this.identity = {}; this.before = null; this.after = null;
		this.newCount = 0; this.chatError = ""; this.chatLoading = false;
		this.renderList(); this.$root.find(".wa-layout").addClass?.("wa-chat-open"); this.destroyChatWindow(); this.renderChat();
		await this.loadChat("initial");
	}
	async loadChat(mode) {
		if (!this.sender || !this.account || (mode === "older" && !this.before)) return;
		if (this.chatLoading) {if (mode === "new") this.pendingHistory = true; return;}
		const version = ++this.chatVersion, account = this.account, sender = this.sender;
		const bounded = mode === "new" && this.historyHasNewer;
		const previous = this.historyPosition();
		const pinned = !previous || previous.height - previous.top - previous.client < 70;
		this.chatLoading = true; this.chatError = "";
		this.renderChat(false, previous);
		const changed = mode === "new" ? [...this.changedMessages] : [];
		// Remove the snapshot before fetching. Notifications arriving during the
		// request are then retained for another pass, even for the same message.
		for (const name of changed) this.changedMessages.delete(name);
		try {
			let cursor = mode === "older" ? this.before : mode === "new" ? this.after : null;
			const refreshNames = mode === "new" ? [...new Set([...this.messages.map(row => row.name), ...changed])] : [];
			let more;
			do {
				const batch = refreshNames.splice(0, 100);
				const data = await this.call("messages", {account, sender, ...(batch.length ? {refresh_names: JSON.stringify(batch)} : {}), ...(cursor ? {[mode === "older" ? "before" : "after"]: cursor} : {})});
				if (!this.active || version !== this.chatVersion || account !== this.account || sender !== this.sender) return;
				this.identity = data;
				const removed = new Set(data.removed_names || []);
				const existing = mode === "initial" ? [] : this.messages.filter(row => !removed.has(row.name));
				const refreshed = new Map((data.refreshed_messages || []).map(row => [row.name, row]));
				const current = existing.map(row => refreshed.get(row.name) || row);
				const combined = mode === "older" ? [...data.messages, ...current] : [...current, ...(data.refreshed_messages || []), ...data.messages];
				const unique = new Map(combined.map(row => [row.name, row]));
				const added = unique.size - existing.length;
				this.messages = [...unique.values()].sort((a, b) => String(a.creation || a.received_at || "").localeCompare(String(b.creation || b.received_at || "")) || a.name.localeCompare(b.name));
				if (mode === "initial" || mode === "older") this.before = data.has_more ? data.next_cursor : null;
				if (mode !== "older" && data.newest_cursor) this.after = data.newest_cursor;
				if (mode === "new" && !pinned && added > 0) this.newCount += added;
				if(bounded)this.historyHasNewer=Boolean(data.has_more);
				more = !bounded && mode === "new" && data.has_more && data.newest_cursor && data.newest_cursor !== cursor;
				cursor = data.newest_cursor;
			} while (more || refreshNames.length);
		} catch (_) {
			if (!this.active || version !== this.chatVersion) return;
			for (const name of changed) this.changedMessages.add(name);
			this.messages = []; this.identity = {}; this.before = null; this.after = null; this.newCount = 0;
			this.chatError = __("Messages could not be loaded. Refresh or check your access.");
		} finally {
			if (version === this.chatVersion) {
				this.chatLoading = false;
				this.renderChat(mode === "initial" || (mode === "new" && pinned), previous, mode === "older");
				if (this.pendingHistory) {this.pendingHistory = false; this.scheduleRefresh();}
			}
		}
	}
	historyPosition() {
		const element = this.$root.find(".wa-history").get(0);
		return element && {top: element.scrollTop, height: element.scrollHeight, client: element.clientHeight};
	}
	escape(value) {return frappe.utils.escape_html(String(value ?? ""));}
	initials(label) {return String(label || "?").split(/\s+/).slice(0, 2).map(word => Array.from(word)[0] || "").join("").toUpperCase();}
	role(identity) {
		const match = identity?.status === "Matched" && identity.matches?.length === 1 ? identity.matches[0] : null;
		return match?.doctype === "Customer" ? __("Client") : match?.doctype === "Sales Employee" ? __("Salesperson") : identity?.status === "Ambiguous" ? __("Multiple matches") : __("Unknown");
	}
	render() {
		const listPosition = this.$root.find(".wa-list").get(0)?.scrollTop || 0;
		this.destroyWindows();
		const e = value => this.escape(value);
		if (this.accountsLoading || this.accountError || !this.account) {
			const prompt = this.accountsLoading ? __("Loading accounts…") : this.accountError || (this.accounts.length ? __("Choose a WhatsApp account to open its incoming messages.") : __("No WhatsApp accounts are available with your current access."));
			this.$root.html(`<div class="wa-account-gate"><div class="wa-account-icon" aria-hidden="true">◉</div><h3>${__("WhatsApp Inbox")}</h3><p>${e(prompt)}</p>${this.accountsLoading ? "" : this.accountError ? `<button class="btn btn-default" data-action="accounts">${__("Retry")}</button>` : this.accounts.length ? this.accountSelect() : ""}<small>${__("Incoming messages · Read-only")}</small></div>`);
			return;
		}
		this.$root.html(`<div class="wa-layout${this.sender ? " wa-chat-open" : ""}"><aside class="wa-sidebar"><div class="wa-sidebar-header"><div><h3>${__("Chats")}</h3><small>${__("Incoming messages")}</small></div><button class="btn btn-default btn-sm" data-action="refresh" aria-label="${__("Refresh inbox")}" title="${__("Refresh inbox")}">↻</button></div><div class="wa-search"><input data-search type="search" value="${e(this.search)}" placeholder="${__("Search name or number")}" aria-label="${__("Search name or number")}"></div><div class="wa-filters" role="tablist" aria-label="${__("Sender type")}">${["All", "Salespersons", "Clients", "Unknown"].map(filter => `<button role="tab" aria-selected="${this.filter === filter}" data-filter="${filter}">${__(filter)}</button>`).join("")}</div><div class="wa-list" role="list" aria-label="${__("Conversations")}"></div>${this.accountFooter()}</aside><section class="wa-chat" aria-label="${__("Selected conversation")}"></section></div>`);
		this.renderList(); this.renderChat();
		const list = this.$root.find(".wa-list").get(0); if (list) list.scrollTop = listPosition;
	}
	accountFooter() {
		const account = this.accounts.find(row => row.name === this.account);
		const label = account?.label || this.account;
		return `<div class="wa-account-footer"><button type="button" data-action="switch-account" aria-label="${__("Switch WhatsApp account")}"${this.accounts.length < 2 ? " disabled" : ""}>` +
			`<span class="wa-avatar">${this.escape(this.initials(label))}</span><span class="wa-account-footer-label"><strong>${this.escape(label)}</strong><small>${__("WhatsApp account")}</small></span>` +
			(this.accounts.length > 1 ? `<span aria-hidden="true">⇄</span>` : "") + `</button></div>`;
	}
	switchAccount() {
		if (this.accounts.length < 2) return;
		const dialog = new frappe.ui.Dialog({title: __("Switch WhatsApp account"),
			fields: [{fieldname: "account", fieldtype: "Select", label: __("WhatsApp account"), reqd: 1,
				options: this.accounts.map(row => ({value: row.name, label: this.escape(row.label || row.name)})), default: this.account}],
			primary_action_label: __("Open inbox"), primary_action: async values => {
				if (!this.active || !this.accounts.some(row => row.name === values.account)) return;
				dialog.hide();
				if (values.account !== this.account) await this.chooseAccount(values.account);
			}});
		dialog.show();
	}

	accountSelect() {
		return `<label class="wa-account-label"><span>${__("WhatsApp account")}</span><select data-account aria-label="${__("WhatsApp account")}"><option value="">${__("Select an account")}</option>${this.accounts.map(row => `<option value="${this.escape(row.name)}"${row.name === this.account ? " selected" : ""}>${this.escape(row.label || row.name)}</option>`).join("")}</select></label>`;
	}
	renderList() {
		const e = value => this.escape(value), $list = this.$root.find(".wa-list");
		this.$root.find("[data-filter]").each((_, element) => element.setAttribute("aria-selected", String(element.dataset.filter === this.filter)));
		const list=$list.get(0);
		if (list?.appendChild) {
			if (!this.listWindow) {
				list.innerHTML='<div class="wa-list-status"></div>';
				this.listWindow=new WhatsAppVirtualList(list,{key:row=>row.sender,html:row=>this.rowHTML(row),estimate:94,fixed:true,onEdge:()=>{if(list.scrollHeight-list.scrollTop-list.clientHeight<250 && this.listCursor && !this.listLoading)this.loadList(true);}});
			}
			this.listWindow.set(this.rows);
			list.querySelector('.wa-list-status').innerHTML=this.listError?`<p>${e(this.listError)}</p><button data-action="list-retry">${__("Retry")}</button>`:this.listLoading?__("Loading conversations…"):!this.rows.length?this.emptyChatsHTML():this.listCursor?`<button class="wa-list-more" data-action="list-more">${__("Load more conversations")}</button>`:"";
			list.querySelector('.wa-list-status').classList?.toggle('wa-empty-status', !this.listError && !this.listLoading && !this.rows.length);
			list.appendChild(list.querySelector('.wa-list-status'));
			return;
		}
		const body = this.rows.map(row=>this.rowHTML(row)).join("");
		$list.html(body + (this.listError ? `<div class="wa-list-notice" role="status">${e(this.listError)}<button class="btn btn-default btn-sm" data-action="list-retry">${__("Retry")}</button></div>` : this.listLoading ? `<div class="wa-list-notice" role="status">${__("Loading conversations…")}</div>` : !this.rows.length ? this.emptyChatsHTML() : "") + (this.listCursor && !this.listLoading ? `<button class="wa-list-more" data-action="list-more">${__("Load more conversations")}</button>` : ""));
	}
	emptyChatsHTML() {
		const filtered = this.search || this.filter !== "All";
		return `<div class="wa-empty-chats" role="status"><svg viewBox="0 0 160 128" aria-hidden="true" focusable="false"><ellipse cx="80" cy="112" rx="53" ry="8" fill="currentColor" opacity=".08"/><circle cx="80" cy="61" r="51" fill="currentColor" opacity=".07"/><path d="M28 27h79a12 12 0 0 1 12 12v34a12 12 0 0 1-12 12H58L37 99V85h-9a12 12 0 0 1-12-12V39a12 12 0 0 1 12-12Z" fill="var(--wa-panel)" stroke="currentColor" stroke-width="3"/><path d="M90 61h39a10 10 0 0 1 10 10v22a10 10 0 0 1-10 10h-3v11l-16-11H90a10 10 0 0 1-10-10V71a10 10 0 0 1 10-10Z" fill="var(--wa-panel)" stroke="currentColor" stroke-width="3"/><path d="M36 47h57M36 61h35" stroke="currentColor" stroke-width="4" stroke-linecap="round" opacity=".45"/><circle cx="97" cy="82" r="3" fill="currentColor"/><circle cx="110" cy="82" r="3" fill="currentColor"/><circle cx="123" cy="82" r="3" fill="currentColor"/></svg><strong>${__(filtered ? "No matching chats" : "Your chats will appear here")}</strong><p>${__(filtered ? "Try another name, number or filter." : "Incoming messages will appear automatically.")}</p></div>`;
	}
	rowHTML(row) {const e=value=>this.escape(value); return `<button type="button" role="listitem" class="wa-row${row.sender === this.sender ? " selected" : ""}" data-sender="${e(row.sender)}"><span class="wa-avatar">${e(this.initials(row.display_name || row.sender))}</span><span class="wa-row-body"><span class="wa-row-title"><strong>${e(row.display_name || row.sender)}</strong><time>${e(this.shortDate(row.last_received_at))}</time></span><span class="wa-row-preview">${e(row.preview || __("Message"))}</span><span class="wa-row-type">${e(this.role(row.identity))}</span></span></button>`;}

	shortDate(value) {
		const text = String(value || ""), parsed = text.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
		return parsed ? parsed[1] === frappe.datetime?.get_today?.() ? parsed[2] : this.dayLabel(parsed[1]) : text;
	}
	dayLabel(day) {
		if (day === frappe.datetime?.get_today?.()) return __("Today");
		const date = new Date(day + "T12:00:00Z");
		return Number.isNaN(date.getTime()) ? day : date.toLocaleDateString(undefined, {day: "numeric", month: "short", year: "numeric", timeZone: "UTC"});
	}
	renderChat(bottom = false, position = null, prepended = false) {
		const e = value => this.escape(value), $chat = this.$root.find(".wa-chat");
		if (!this.sender) {this.destroyChatWindow(); $chat.html(`<div class="wa-chat-empty"><div aria-hidden="true">◉</div><h3>${__("WhatsApp Inbox")}</h3><p>${__("Select a conversation to view incoming messages.")}</p><small>${__("Read-only · No messages are sent from this page")}</small></div>`); return;}
		const data = this.identity || {}, row = this.rows.find(row => row.sender === this.sender);
		const match = data.sender_identity?.status === "Matched" && data.sender_identity.matches?.length === 1 ? data.sender_identity.matches[0] : null;
		const label = match?.label || data.sender_profile_name || row?.display_name || this.sender;
		const header = `<header class="wa-chat-header"><button class="wa-back" data-action="back" aria-label="${__("Back to conversations")}">‹</button>` +
			`<span class="wa-avatar">${e(this.initials(label))}</span><div><strong>${e(label)}</strong>` +
			`<small>${e(this.sender)} · ${e(this.role(data.sender_identity || row?.identity))}${match && data.sender_profile_name && data.sender_profile_name !== label ? " · " + e(data.sender_profile_name) : ""}</small>` +
			`</div><span class="wa-view-only">${__("Read-only")}</span></header>`;
		if ($chat.get(0)?.appendChild && !this.chatError) {
			const element=$chat.get(0);
			if (!this.chatWindow) {
				element.innerHTML=header+'<div class="wa-history" tabindex="0" role="region" aria-label="'+__("Incoming message history")+'"><div class="wa-older"></div><div class="wa-history-status"></div></div><div class="wa-jump-host"></div>';
				const history=element.querySelector('.wa-history');
				this.chatWindow=new WhatsAppVirtualList(history,{key:row=>row.name,html:(row,index)=>this.messageHTML([row],index),estimate:125,followBottom:true,onMount:(node,row)=>this.mountMessage(node,row),onUnmount:node=>this.unmountMessage(node),onEdge:()=>{if(history.scrollTop<180 && this.before && !this.chatLoading)this.loadChat("older");}});
			}
			element.querySelector('.wa-chat-header').outerHTML=header;
			element.querySelector('.wa-older').innerHTML=this.before?`<button class="btn btn-default btn-sm" data-action="older"${this.chatLoading?' disabled':''}>${__("Load older messages")}</button>`:"";
			this.chatWindow.set(this.visibleMessages(),{bottom});
			element.querySelector('.wa-history-status').textContent=this.chatLoading?__("Loading messages…"):!this.visibleMessages().length?__("No incoming messages in this conversation."):"";
			element.querySelector('.wa-history').appendChild(element.querySelector('.wa-history-status'));
			element.querySelector('.wa-jump-host').innerHTML=(this.newCount || this.historyHasNewer)?`<button class="wa-new-messages" data-action="bottom">${this.newCount || ""} ${__("Jump to latest")} ↓</button>`:"";
			return;
		}
		this.destroyChatWindow();
		const content = this.chatError ? `<div class="wa-chat-notice" role="status">${e(this.chatError)}<button class="btn btn-default" data-action="chat-retry">${__("Retry")}</button></div>` :
			`<div class="wa-history" tabindex="0" role="region" aria-label="${__("Incoming message history")}">` +
			(this.before ? `<div class="wa-older"><button class="btn btn-default btn-sm" data-action="older"${this.chatLoading ? " disabled" : ""}>${__("Load older messages")}</button></div>` : "") +
			this.messageHTML() + (this.chatLoading ? `<div class="wa-history-status" role="status">${__("Loading messages…")}</div>` : !this.messages.length ? `<div class="wa-history-status">${__("No incoming messages in this conversation.")}</div>` : "") +
			`</div>` + ((this.newCount || this.historyHasNewer) ? `<button class="wa-new-messages" data-action="bottom">${e(this.newCount)} ${__("Jump to latest")} ↓</button>` : "");
		$chat.html(header + content);
		const history = this.$root.find(".wa-history").get(0);
		if (history) history.scrollTop = bottom ? history.scrollHeight : position ? position.top + (prepended ? history.scrollHeight - position.height : 0) : 0;
	}
	visibleMessages() {return this.messages.filter(row=>String(row.content_type || "").toLowerCase()!=="reaction");}
	messageHTML(messages=this.visibleMessages(), startIndex=0) {
		const e = value => this.escape(value), byName = new Map(this.messages.map(row => [row.name, row]));
		let lastDay;
		return messages.map((message,index) => {
			const stamp = String(message.received_at || ""), match = stamp.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/);
			const day = match?.[1];
			const previous=this.visibleMessages()[startIndex+index-1];
			if(index===0 && previous)lastDay=String(previous.received_at || "").slice(0,10);
			const separator = day && day !== lastDay ? `<div class="wa-date"><span>${e(this.dayLabel(day))}</span></div>` : "";
			lastDay = day;
			const quoted = byName.get(message.reply_to);
			const context=message.reply_context;
			const quote = context?.summary || quoted?.text || quoted?.attachment?.file_name || __("Original message is not stored");
			const target=context?.target_name || quoted?.name;
			const quoteHTML=message.reply_to || context ? `<button type="button" class="wa-quote" ${target?`data-reply-target="${e(target)}"`:"disabled"}>${context?.sender_name?`<strong>${e(context.sender_name)}</strong>`:""}${e(String(quote).slice(0,200))}</button>`:"";
			const loc = message.location;
			const text=loc && /^Location\s+-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?$/i.test(String(message.text || "").trim()) ? "" : message.text;
			return separator + `<article class="wa-bubble" data-message-name="${e(message.name)}">${quoteHTML}${text ? `<div class="wa-text">${e(text)}</div>` : ""}${message.attachment ? this.fileHTML(message.attachment,message) : ""}${loc ? `<div class="wa-location"><div class="wa-map-host" data-map-name="${e(message.name)}" aria-label="${__("Shared location")}"><span aria-hidden="true">📍</span></div><strong>${e(loc.name || __("Shared location"))}</strong><div>${e(loc.address || "")}</div></div>` : ""}${(message.warnings || []).map(warning => `<small class="wa-warning">${e(warning)}</small>`).join("")}${(message.reactions || []).length?`<div class="wa-reactions">${message.reactions.map(reaction=>`<span title="${e((reaction.actors || []).join(", "))}">${e(reaction.emoji)}${reaction.count>1?" "+e(reaction.count):""}</span>`).join("")}</div>`:""}<footer><time datetime="${e(stamp)}">${e(match?.[2] || stamp)}</time></footer></article>`;
		}).join("");
	}
	fileHTML(file,message={}) {
		const e = value => this.escape(value);
		if (!file.available || typeof file.url !== "string" || !file.url.startsWith("/private/files/")) return `<small class="wa-warning">${e(file.note || __("Attachment unavailable"))}</small>`;
		const name = file.file_name || __("Attachment"), type = String(file.file_type || name.split(".").pop() || "DOC").split("/").pop().toUpperCase();
		const badge = type === "PDF" ? "PDF" : /^(PNG|JPE?G|WEBP|GIF|HEIC)$/.test(type) ? "IMG" : /^(MP3|OGG|WAV|M4A|OPUS)$/.test(type) ? "AUDIO" : /^(MP4|MOV|WEBM)$/.test(type) ? "VIDEO" : "DOC";
		const bytes = Number(file.size_bytes), size = file.size_bytes != null && Number.isFinite(bytes) && bytes >= 0 ? bytes < 1024 ? bytes + " B" : bytes < 1048576 ? (bytes / 1024).toFixed(1) + " KB" : (bytes / 1048576).toFixed(1) + " MB" : "";
		const contentType=String(message.content_type || "").toLowerCase();
		if (badge==="AUDIO" || contentType==="audio") return `<div class="wa-voice"><span aria-hidden="true">🎙</span><audio controls preload="none" src="${e(file.url)}" aria-label="${e(__("Audio message"))}"></audio><a href="${e(file.url)}" download="${e(name)}" aria-label="${e(__("Download audio"))}">↓</a></div>`;
		const preview=badge==="PDF" || badge==="IMG" || contentType==="image" ? `<div class="wa-preview" data-preview-name="${e(message.name || "")}"></div>`:"";
		return preview+`<div class="wa-file"><span class="wa-file-icon" aria-hidden="true">${badge}</span><a href="${e(file.url)}" target="_blank" rel="noopener noreferrer"><strong>${e(name)}</strong><small>${e([size, badge].filter(Boolean).join(" · "))}</small></a><a class="wa-download" href="${e(file.url)}" download="${e(name)}" aria-label="${e(__("Download") + " " + name)}">↓</a></div>`;
	}
 destroyChatWindow() {this.chatWindow?.destroy(); this.chatWindow=null;}
 destroyWindows() {this.listWindow?.destroy(); this.listWindow=null; this.destroyChatWindow();}
 unmountMessage(node) {node._mapCleanup?.(); node._mapCleanup=null;}
 mountMessage(node,message) {
  const map=node.querySelector('.wa-map-host');
  if(map && window.KunalWhatsAppMap?.mount) node._mapCleanup=window.KunalWhatsAppMap.mount(map,message.location);
  const host=node.querySelector('[data-preview-name]');
  if(!host || !message.name)return;
  const account=this.account,sender=this.sender,key=[account,sender,message.name,message.attachment?.url].join(":");
  if(!this.previewCache.has(key))this.previewCache.set(key,frappe.call({method:"kunal_enterprises.api.whatsapp_inbox_previews.preview",type:"GET",silent:true,args:{account,sender,name:message.name}}).then(result=>result.message).catch(()=>({available:false})));
  this.previewCache.get(key).then(preview=>{
   if(!this.active || account!==this.account || sender!==this.sender || !host.isConnected || !preview?.available || typeof preview.url!=="string" || !preview.url.startsWith('/private/files/'))return;
   host.innerHTML=`<a href="${this.escape(message.attachment.url)}" target="_blank" rel="noopener noreferrer"><img src="${this.escape(preview.url)}" alt="${this.escape(__("Attachment preview"))}" width="${Number(preview.width)||300}" height="${Number(preview.height)||200}" style="aspect-ratio:${Number(preview.width)||3}/${Number(preview.height)||2}" loading="lazy"></a>`;
  });
 }
 async jumpToMessage(target) {
  if(!this.sender || !this.active)return;
  const version=++this.jumpVersion || (this.jumpVersion=1), account=this.account,sender=this.sender;
  const highlight=()=>{this.chatWindow?.scrollTo(target); const nodes=this.$root.find('.wa-history').get(0)?.querySelectorAll?.('[data-message-name]') || []; for(const node of nodes)if(node.dataset.messageName===target){node.classList.add('wa-message-highlight'); setTimeout(()=>node.classList.remove('wa-message-highlight'),1800);}};
  if(this.messages.some(row=>row.name===target)){highlight();return;}
  try {
   const data=await this.call('message_context',{account,sender,target});
   if(!this.active || account!==this.account || sender!==this.sender || version!==this.jumpVersion)return;
   if(data.context_only){frappe.msgprint({title:__("Quoted message"),message:this.escape(data.target?.text || data.target?.attachment?.file_name || __("Outgoing message"))});return;}
   if(!data.target || !(data.messages || []).some(row=>row.name===target)){frappe.show_alert?.({message:__("Original message is not stored"),indicator:"orange"});return;}
   this.chatVersion++; this.chatLoading=false; this.messages=data.messages; this.before=data.has_more?data.next_cursor:null; this.after=data.newest_cursor; this.newCount=0;
   this.historyHasNewer=Boolean(data.has_newer); this.renderChat(); highlight();
  } catch (_) {if(this.active && version===this.jumpVersion)frappe.show_alert?.({message:__("Original message could not be loaded"),indicator:"orange"});}
 }

}
