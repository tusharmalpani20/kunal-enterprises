(() => {
	const METHOD = "kunal_enterprises.api.whatsapp_intake_report.read";
	const PICKERS = [
		["account", __("WhatsApp account")], ["sales_employee", __("Sales employee")],
		["godown", __("Godown")], ["customer", __("Customer")], ["item", __("Item")],
	];
	const METRICS = [
		["received", __("Messages received")], ["processed", __("Processed")],
		["intakes", __("Intake requests")], ["orders", __("Orders created")],
		["unaccounted", __("Unaccounted")],
	];
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	const number = value => (Number(value) || 0).toLocaleString("en-IN");
	const count = (value, attrs) => `<button type="button" class="wir-link" ${attrs}>${number(value)}</button>`;
	// Display the same site-local dates used to build the report cohort.
	const receivedDateTime = value => value ? String(value).replace("T", " ").slice(0, 16) : "";
	const MESSAGE_LABELS = new Map([
		["image", __("Photo")], ["document", __("Document")], ["audio", __("Audio message")],
		["video", __("Video")], ["sticker", __("Sticker")], ["location", __("Shared location")],
		["contact", __("Shared contact")], ["contacts", __("Shared contacts")],
		["restricted", __("Restricted message")],
	]);
	const siteToday = () => new Intl.DateTimeFormat("en-CA", {
		timeZone: frappe.boot?.time_zone?.system || "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit",
	}).format(new Date());
	const shiftDay = (iso, offset) => {
		const date = new Date(iso + "T00:00:00Z");
		date.setUTCDate(date.getUTCDate() + offset);
		return date.toISOString().slice(0, 10);
	};
	const defaultDates = () => {
		const today = siteToday();
		return {from_date: today.slice(0, 7) + "-01", to_date: today};
	};

	function localFile(value) {
		if (typeof value !== "string" || !/^\/(?:private\/)?files\//.test(value)) return "";
		try {
			const url = new URL(value, location.origin);
			return url.origin === location.origin && /^\/(?:private\/)?files\//.test(url.pathname)
				? url.pathname + url.search : "";
		} catch (_) {
			return "";
		}
	}

	function headers(labels) {
		return `<thead><tr>${labels.map(label => `<th scope="col">${escape(label)}</th>`).join("")}</tr></thead>`;
	}

	/* Fixed-height rows keep the DOM bounded even after loading several pages. */
	class ReportRows {
		constructor(container, labels, renderRow, openRow, rowHeight = 44) {
			this.container = container;
			this.columns = labels.length;
			this.renderRow = renderRow;
			this.items = [];
			this.window = "";
			this.rowHeight = rowHeight;
			container.innerHTML = `<table class="wir-table">${headers(labels)}<tbody></tbody></table>`;
			this.body = container.querySelector("tbody");
			this.nodes = new Map();
			this.top = this.spacer();
			this.bottom = this.spacer();
			this.body.append(this.top, this.bottom);
			container.onscroll = () => this.paint();
			container.addEventListener("keydown", event => this.navigate(event));
			this.body.onclick = event => {
				const button = event.target.closest("[data-row]");
				if (button) openRow(this.items[Number(button.dataset.row)], button);
			};
		}
		spacer() {
			const row = this.body.insertRow();
			row.className = "wir-spacer";
			row.setAttribute("aria-hidden", "true");
			row.insertCell().colSpan = this.columns;
			return row;
		}
		set(items, reset) {
			this.items = items;
			if (reset) {
				for (const node of this.nodes.values()) node.remove();
				this.nodes.clear();
				this.container.scrollTop = 0;
			}
			this.window = "";
			this.paint();
		}
		navigate(event) {
			const steps = {ArrowUp: -1, ArrowDown: 1};
			if (!this.items.length || !Object.hasOwn(steps, event.key) || event.altKey || event.ctrlKey || event.metaKey) return;
			const row = event.target.closest("tbody tr:not(.wir-spacer)");
			const firstVisible = Math.floor(this.container.scrollTop / this.rowHeight);
			const index = row ? Number(row.dataset.index) + steps[event.key] : firstVisible;
			event.preventDefault();
			this.focusRow(Math.max(0, Math.min(this.items.length - 1, index)));
		}
		focusRow(next) {
			const visibleHeight = this.container.clientHeight - this.container.querySelector("thead").offsetHeight;
			const top = next * this.rowHeight;
			if (top < this.container.scrollTop) this.container.scrollTop = top;
			if (top + this.rowHeight > this.container.scrollTop + visibleHeight) {
				this.container.scrollTop = top + this.rowHeight - visibleHeight;
			}
			this.paint();
			const row = this.nodes.get(next);
			(row?.querySelector("button") || row)?.focus({preventScroll: true});
		}
		paint() {
			const start = Math.max(0, Math.floor(this.container.scrollTop / this.rowHeight) - 5);
			const end = Math.min(this.items.length, start + Math.ceil(this.container.clientHeight / this.rowHeight) + 12);
			const window = `${start}:${end}`;
			if (window === this.window) return;
			this.window = window;
			this.top.cells[0].style.height = `${start * this.rowHeight}px`;
			this.bottom.cells[0].style.height = `${(this.items.length - end) * this.rowHeight}px`;
			for (const [index, node] of this.nodes) {
				if (index < start || index >= end) {
					node.remove();
					this.nodes.delete(index);
				}
			}
			const template = document.createElement("template");
			let next = this.top.nextElementSibling;
			for (let index = start; index < end; index++) {
				let node = this.nodes.get(index);
				if (!node) {
					template.innerHTML = this.renderRow(this.items[index], index);
					node = template.content.firstElementChild;
					node.dataset.index = index;
					node.tabIndex = -1;
					this.body.insertBefore(node, next);
					this.nodes.set(index, node);
				} else {
					next = node.nextElementSibling;
				}
			}
		}
	}

	class WhatsAppIntakeReport {
		constructor(wrapper) {
			const page = frappe.ui.make_app_page({parent: wrapper, title: __("WhatsApp Intake Report"), single_column: true});
			this.root = $('<div class="wir"></div>').appendTo(page.main)[0];
			this.filters = defaultDates();
			this.labels = {};
			this.generation = 0;
			this.detailGeneration = 0;
			this.pickerGeneration = 0;
			this.breakdownGeneration = 0;
			this.mode = "overview";
			this.root.innerHTML = `
				<div class="wir-toolbar">
					<div class="wir-tabs" aria-label="${escape(__("Report view"))}" hidden></div>
					<button type="button" class="wir-link" data-reset>${escape(__("Reset filters"))}</button>
				</div>
				<div class="wir-filters">
					${[["from_date", __("Received from")], ["to_date", __("Received to")]].map(([key, label]) =>
						`<label class="wir-filter"><span>${escape(label)}</span><input type="date" data-date="${key}" value="${this.filters[key]}" required></label>`).join("")}
					${PICKERS.map(([key, label]) => `<div class="wir-filter wir-picker" data-field="${key}">
						<span id="wir-label-${key}">${escape(label)}</span>
						<button type="button" aria-expanded="false" aria-labelledby="wir-label-${key} wir-value-${key}" data-picker="${key}">
							<span id="wir-value-${key}">${escape(__("All"))}</span><span aria-hidden="true">⌄</span>
						</button>
					</div>`).join("")}
				</div>
				<p class="wir-status" role="status"></p>
				<div class="wir-summary"></div>
				<dialog class="wir-detail" aria-labelledby="wir-detail-title"></dialog>`;
			this.status = this.root.querySelector(".wir-status");
			this.summary = this.root.querySelector(".wir-summary");
			this.dialog = this.root.querySelector("dialog");
			this.dialog.addEventListener("close", () => {
				if (this.dialog.open) return;
				++this.detailGeneration;
				this.previewObserver?.disconnect();
				this.dialog.replaceChildren();
				this.returnFocus?.focus();
				this.returnFocus = null;
			});
			this.root.addEventListener("click", event => this.click(event));
			this.root.addEventListener("change", event => {
				if (!event.target.dataset.date) return;
				this.filters[event.target.dataset.date] = event.target.value;
				this.refresh();
			});
			this.outside = event => {
				if (this.picker && !this.picker.host.contains(event.target)) this.closePicker();
			};
		}

		show() {
			document.addEventListener("pointerdown", this.outside);
			void this.refresh();
		}

		hide() {
			document.removeEventListener("pointerdown", this.outside);
			++this.generation;
			++this.breakdownGeneration;
			this.closePicker();
			this.closeDetail();
		}

		call(view, filter = {}, args = {}) {
			return frappe.call({
				method: METHOD, type: "GET", silent: true,
				args: {view, filters: {...this.filters, ...filter}, ...args},
			}).then(result => result.message);
		}

		click(event) {
			const date = event.target.closest("input[data-date]");
			if (date) {
				try { date.showPicker?.(); } catch (_) { /* Native calendar control remains usable. */ }
				return;
			}
			const button = event.target.closest("button");
			if (!button) return;
			const {dataset} = button;
			if (dataset.reset !== undefined) {
				this.filters = defaultDates();
				this.labels = {};
				this.mode = "overview";
				for (const input of this.root.querySelectorAll("[data-date]")) input.value = this.filters[input.dataset.date];
				this.updatePickers();
				this.refresh();
			} else if (dataset.picker) {
				const alreadyOpen = this.picker?.field === dataset.picker;
				this.closePicker();
				if (!alreadyOpen) this.openPicker(button, dataset.picker);
			} else if (dataset.mode) {
				this.mode = dataset.mode;
				this.drawTabs();
				this.renderMode();
				this.root.querySelector(`[data-mode="${this.mode}"]`)?.focus();
			} else if (dataset.metric) {
				const mode = dataset.metric === "intakes" || dataset.metric === "orders" ? "intakes" : "messages";
				this.drill(mode, {metric: dataset.metric}, METRICS.find(([key]) => key === dataset.metric)[1], button);
			} else if (dataset.coverage) {
				const row = this.data.coverage[Number(dataset.coverage)];
				if (row) this.drill("messages", {metric: row.key}, row.label, button);
			} else if (dataset.type) {
				const row = this.data.types[Number(dataset.type) - 1];
				const title = dataset.converted ? __("{0} converted to Orders", [row.label]) : row.label;
				this.drill("intakes", {request_type: row.key, metric: dataset.converted ? "orders" : "intakes"}, title, button);
			}
		}

		updatePickers() {
			for (const [key] of PICKERS) this.root.querySelector(`#wir-value-${key}`).textContent = this.labels[key] || __("All");
		}

		closePicker(focus = false) {
			++this.pickerGeneration;
			const picker = this.picker;
			if (!picker) return;
			clearTimeout(picker.timer);
			picker.panel.remove();
			picker.trigger.setAttribute("aria-expanded", "false");
			if (focus) picker.trigger.focus();
			this.picker = null;
		}

		openPicker(trigger, field) {
			const label = PICKERS.find(([key]) => key === field)[1];
			const host = trigger.parentElement;
			const panel = document.createElement("div");
			panel.className = "wir-pick-panel";
			panel.innerHTML = `<input type="search" aria-label="${escape(__("Search {0}", [label]))}" placeholder="${escape(__("Search…"))}">
				<div class="wir-options" role="group" aria-label="${escape(label)}"></div>
				<button class="wir-link wir-picker-more" type="button" hidden>${escape(__("Load more"))}</button>`;
			host.append(panel);
			const search = panel.querySelector("input");
			const list = panel.querySelector(".wir-options");
			const more = panel.querySelector(".wir-picker-more");
			const picker = this.picker = {trigger, host, panel, search, list, more, field, rows: [], cursor: null, nodes: new Map()};
			list.onscroll = () => this.paintOptions(picker);
			trigger.setAttribute("aria-expanded", "true");
			panel.addEventListener("keydown", event => {
				if (event.key === "Escape") {
					event.preventDefault();
					event.stopPropagation();
					this.closePicker(true);
					return;
				}
				const option = event.target.closest("[data-choice]");
				if (event.target === search && (event.key === "ArrowDown" || event.key === "Enter")) {
					event.preventDefault();
					if (picker.searching) return;
					list.scrollTop = 0;
					this.paintOptions(picker);
					const first = list.querySelector('[data-choice="0"]') || list.querySelector("button");
					if (event.key === "Enter") list.querySelector('[data-choice="0"]')?.click();
					else first?.focus();
				} else if (option && ["ArrowDown", "ArrowUp"].includes(event.key)) {
					event.preventDefault();
					const next = Math.max(-1, Math.min(picker.rows.length - 1,
						Number(option.dataset.choice) + (event.key === "ArrowDown" ? 1 : -1)));
					this.focusOption(picker, next);
				}
			});
			search.addEventListener("input", () => {
				++this.pickerGeneration;
				clearTimeout(picker.timer);
				list.textContent = __("Searching…");
				picker.rows = [];
				picker.searching = true;
				picker.window = "";
				picker.list.scrollTop = 0;
				more.hidden = true;
				picker.timer = setTimeout(() => this.loadOptions(picker, true), 180);
			});
			list.addEventListener("click", event => {
				const choice = event.target.closest("[data-choice]");
				if (!choice) return;
				const index = Number(choice.dataset.choice);
				if (index === -1) {
					delete this.filters[field];
					delete this.labels[field];
				} else {
					const row = picker.rows[index];
					this.filters[field] = row.value;
					this.labels[field] = row.label;
				}
				this.closePicker(true);
				this.updatePickers();
				this.refresh();
			});
			more.onclick = () => this.loadOptions(picker, picker.retryReset);
			search.focus();
			void this.loadOptions(picker, true);
		}

		async loadOptions(picker, reset = false) {
			if (!reset && picker.loading) return;
			const epoch = ++this.pickerGeneration;
			const previousCount = picker.rows.length;
			picker.loading = true;
			picker.more.setAttribute("aria-disabled", "true");
			picker.more.textContent = __("Load more");
			if (reset) {
				picker.rows = [];
				picker.searching = true;
				picker.cursor = null;
				picker.list.textContent = __("Searching…");
			}
			try {
				const result = await this.call("options", {}, {field: picker.field, search: picker.search.value, cursor: picker.cursor});
				if (epoch !== this.pickerGeneration) return;
				picker.rows.push(...(result.rows || []));
				picker.cursor = result.next_cursor;
				picker.searching = false;
				picker.retryReset = false;
				picker.window = "";
				if (reset) picker.list.scrollTop = 0;
				this.paintOptions(picker);
				if (document.activeElement === picker.more) {
					if (reset || picker.rows.length === previousCount) picker.search.focus();
					else this.focusOption(picker, previousCount);
				}
				picker.more.hidden = !picker.cursor;
			} catch (_) {
				if (epoch === this.pickerGeneration) {
					picker.searching = false;
					picker.retryReset = reset;
					picker.more.hidden = false;
					picker.more.textContent = __("Try again");
					if (reset) picker.list.textContent = __("Could not load options.");
				}
			} finally {
				if (epoch === this.pickerGeneration) {
					picker.loading = false;
					picker.more.removeAttribute("aria-disabled");
				}
			}
		}

		focusOption(picker, index) {
			const top = (index + 1) * 36;
			if (top < picker.list.scrollTop) picker.list.scrollTop = top;
			if (top + 36 > picker.list.scrollTop + picker.list.clientHeight) {
				picker.list.scrollTop = top + 36 - picker.list.clientHeight;
			}
			this.paintOptions(picker);
			picker.nodes.get(index + 1)?.focus({preventScroll: true});
		}

		paintOptions(picker) {
			if (picker.searching) return;
			const count = picker.rows.length + 1;
			const start = Math.max(0, Math.floor(picker.list.scrollTop / 36) - 3);
			const end = Math.min(count, start + 13);
			const window = `${start}:${end}:${count}`;
			if (picker.window === window) return;
			picker.window = window;
			if (!picker.optionWindow?.isConnected) {
				picker.optionWindow = document.createElement("div");
				picker.optionWindow.className = "wir-option-window";
				picker.empty = document.createElement("p");
				picker.empty.textContent = __("No matching records.");
				picker.list.replaceChildren(picker.optionWindow, picker.empty);
				picker.nodes.clear();
			}
			picker.optionWindow.style.height = `${count * 36}px`;
			picker.empty.hidden = Boolean(picker.rows.length);
			for (const [index, button] of picker.nodes) {
				if (index < start || index >= end) {
					button.remove();
					picker.nodes.delete(index);
				}
			}
			let next = picker.optionWindow.firstElementChild;
			for (let i = start; i < end; i++) {
				let button = picker.nodes.get(i);
				if (!button) {
					const row = picker.rows[i - 1];
					button = document.createElement("button");
					button.type = "button";
					button.dataset.choice = i - 1;
					button.style.top = `${i * 36}px`;
					button.textContent = row?.label || row?.value || __("All");
					picker.nodes.set(i, button);
					picker.optionWindow.insertBefore(button, next);
				} else next = button.nextElementSibling;
			}
		}

		async refresh() {
			const epoch = ++this.generation;
			++this.breakdownGeneration;
			this.closePicker();
			this.closeDetail();
			this.data = null;
			this.summary.replaceChildren();
			this.root.querySelector(".wir-tabs").hidden = true;
			const {from_date, to_date} = this.filters;
			if (!from_date || !to_date || from_date > to_date || to_date > shiftDay(from_date, 365)) {
				this.status.textContent = __("Choose a received date range of up to 366 days.");
				return;
			}
			this.status.textContent = __("Loading report…");
			try {
				const result = await this.call("summary");
				if (epoch !== this.generation) return;
				if (!result?.totals) throw new Error("Missing report totals");
				this.data = result;
				this.sections = this.data.scope === "sales" ? ["overview", "godown"] :
					this.data.scope === "godown" ? ["overview", "godown"] : ["overview", "sales_employee", "godown"];
				if (!this.sections.includes(this.mode)) this.mode = "overview";
				this.root.querySelector('[data-field="sales_employee"]').hidden = !this.sections.includes("sales_employee");
				this.drawTabs();
				this.status.textContent = "";
				this.renderMode();
			} catch (_) {
				if (epoch === this.generation) this.status.textContent = __("Could not load the report. Check your access or try again.");
			}
		}

		drawTabs() {
			const labels = {overview: __("Overall"), sales_employee: __("Sales employee"), godown: __("Godown")};
			const tabs = this.root.querySelector(".wir-tabs");
			tabs.hidden = false;
			tabs.innerHTML = this.sections.map(mode =>
				`<button type="button" data-mode="${mode}" aria-pressed="${mode === this.mode}">${escape(labels[mode])}</button>`).join("");
		}

		renderMode() {
			const epoch = ++this.breakdownGeneration;
			const {totals, coverage = [], types = []} = this.data;
			const total = Number(totals.received) || 0;
			this.summary.innerHTML = `
				<section class="wir-totals" aria-label="${escape(__("Report totals"))}">
					${METRICS.map(([key, label]) => `<button type="button" class="wir-card ${key === "unaccounted" ? "wir-attention" : ""}" data-metric="${key}">
						<span>${escape(label)}</span><strong>${number(totals[key])}</strong>
					</button>`).join("")}
				</section>
				<div class="wir-breakdown"></div>
				<div class="wir-panels">
					<section class="wir-panel">
						<h2>${escape(__("Message coverage"))}</h2>
						${coverage.map((row, index) => {
							const width = Math.max(0, Math.min(100, total ? Number(row.count) / total * 100 : 0));
							return `<button type="button" class="wir-coverage" data-coverage="${index}">
								<span>${escape(row.label)}</span><span class="wir-track" aria-hidden="true"><i style="width:${width}%"></i></span>
								<strong>${number(row.count)}</strong></button>`;
						}).join("")}
					</section>
					<section class="wir-panel">
						<h2>${escape(__("Intake to Order"))}</h2>
						<table class="wir-table">${headers([__("Original type"), __("Intakes"), __("Converted")])}<tbody>
						${types.map((row, index) => `<tr><td>${escape(row.label)}</td>
							<td>${count(row.intakes, `data-type="${index + 1}"`)}</td>
							<td>${count(row.orders, `data-type="${index + 1}" data-converted="true"`)}</td></tr>`).join("")}
						</tbody></table>
					</section>
				</div>
				<section class="wir-panel wir-queue"><h2>${escape(__("Unaccounted messages"))}</h2><div class="wir-list-host"></div></section>`;
			if (this.mode !== "overview") void this.breakdown(this.mode, epoch);
			const queue = this.summary.querySelector(".wir-queue .wir-list-host");
			void this.messageList(queue, {metric: "unaccounted"}, () => epoch === this.breakdownGeneration,
				(row, opener) => this.openMessage(row, null, opener));
		}

		breakdown(group, epoch) {
			const host = this.summary.querySelector(".wir-breakdown");
			const label = group === "godown" ? __("By godown") : __("By sales employee");
			host.innerHTML = `<section class="wir-panel"><h2>${escape(label)}</h2><div class="wir-list-host"></div></section>`;
			return this.paged(host.querySelector(".wir-list-host"), {
				view: "breakdown", filter: {group}, current: () => epoch === this.breakdownGeneration,
				columns: [group === "godown" ? __("Godown") : __("Sales employee"), __("Received"), __("Intakes"), __("Orders"), __("Unaccounted")],
				row: (item, i) => `<tr><td><button class="wir-link" type="button" data-row="${i}">${escape(item.label || item.name)}</button></td>
					<td>${number(item.received)}</td><td>${number(item.intakes)}</td><td>${number(item.orders)}</td><td>${number(item.unaccounted)}</td></tr>`,
				open: item => {
					if (item.name == null) return;
					this.filters[group] = item.name;
					this.labels[group] = item.label || item.name;
					this.updatePickers();
					this.root.querySelector(`[data-picker="${group}"]`)?.focus();
					this.refresh();
				},
			});
		}

		paged(host, config) {
			const sizes = [50, 100, 500, 2000];
			host.innerHTML = `<div class="wir-scroll" tabindex="0"></div>
				<div class="wir-pager"><p class="wir-page-status" role="status"></p>
				<nav class="wir-page-actions" aria-label="${escape(__("Pagination"))}">
					<button class="wir-page-button" type="button" data-previous aria-label="${escape(__("Previous page"))}" disabled>‹</button>
					<span class="wir-page-number" aria-label="${escape(__("Page {0}", [1]))}">1</span>
					<button class="wir-page-button" type="button" data-next aria-label="${escape(__("Next page"))}" disabled>›</button>
				</nav>
				<label class="wir-page-size">${escape(__("Rows per page"))}
					<select>${sizes.map(size => `<option value="${size}">${number(size)}</option>`).join("")}</select>
				</label></div>`;
			const scroll = host.querySelector(".wir-scroll");
			if (config.view === "messages") scroll.classList.add("wir-message-list");
			const actions = host.querySelector(".wir-page-actions");
			const previous = host.querySelector("[data-previous]");
			const next = host.querySelector("[data-next]");
			const pageNumber = host.querySelector(".wir-page-number");
			const pageSize = host.querySelector(".wir-page-size select");
			const status = host.querySelector(".wir-page-status");
			const starts = [{cursor: null, offset: 0}];
			let currentPage = 0, size = sizes[0], retry = null, loading = false;
			const table = new ReportRows(scroll, config.columns, config.row, (row, trigger) => {
				if (!loading) config.open?.(row, trigger);
			}, config.rowHeight);
			const load = async (index, requestedSize = size) => {
				const changingSize = requestedSize !== size;
				const start = starts[index];
				if (loading || !start) return;
				loading = true;
				scroll.setAttribute("aria-busy", "true");
				status.textContent = __("Loading…");
				try {
					const {cursor, offset} = start;
					const result = await this.call(config.view, config.filter, {cursor, page_size: requestedSize});
					if (!config.current()) return;
					const rows = result.rows || [];
					const end = offset + rows.length;
					const focusOnPager = actions.contains(document.activeElement);
					retry = null;
					next.textContent = "›";
					next.setAttribute("aria-label", __("Next page"));
					if (!rows.length && index > currentPage) {
						// A live queue can shrink between page requests.
						starts.length = index;
						status.textContent = __("No more records.");
					} else {
						size = requestedSize;
						pageSize.value = String(size);
						currentPage = index;
						pageNumber.textContent = number(index + 1);
						pageNumber.setAttribute("aria-label", __("Page {0}", [number(index + 1)]));
						starts.length = index + 1;
						if (result.next_cursor) starts.push({cursor: result.next_cursor, offset: end});
						scroll.hidden = !rows.length;
						table.set(rows, true);
						const range = rows.length === 1 ? number(end) : `${number(offset + 1)}–${number(end)}`;
						const total = result.next_cursor ? config.total : end;
						status.textContent = !rows.length ? __("No records for these filters.") :
							total == null || (result.next_cursor && total <= end) ? __("Showing {0}", [range]) :
								__("Showing {0} of {1}", [range, number(total)]);
					}
					if (focusOnPager) scroll.focus({preventScroll: true});
					previous.disabled = currentPage === 0;
					next.disabled = !starts[currentPage + 1];
				} catch (_) {
					if (config.current()) {
						status.textContent = changingSize ? __("Could not change page size.") : __("Could not load page.");
						pageSize.value = String(size);
						retry = {index, size: requestedSize};
						previous.disabled = currentPage === 0;
						next.disabled = false;
						next.textContent = __("Try again");
						next.setAttribute("aria-label", __("Try again"));
					}
				} finally {
					loading = false;
					scroll.removeAttribute("aria-busy");
				}
			};
			previous.onclick = () => load(currentPage - 1);
			next.onclick = () => retry ? load(retry.index, retry.size) : load(currentPage + 1);
			pageSize.onchange = () => {
				if (loading) {
					pageSize.value = size;
					return;
				}
				return load(0, Number(pageSize.value));
			};
			return load(0);
		}

		closeDetail() {
			++this.detailGeneration;
			this.previewObserver?.disconnect();
			if (this.dialog.open) this.dialog.close();
		}

		detailShell(title, opener) {
			const epoch = ++this.detailGeneration;
			this.previewObserver?.disconnect();
			this.returnFocus ||= opener;
			this.dialog.innerHTML = `<div class="wir-detail-head">
				<h2 id="wir-detail-title">${escape(title)}</h2>
				<button type="button" class="wir-close">${escape(__("Close"))}</button>
			</div><div class="wir-detail-body"></div>`;
			this.dialog.querySelector(".wir-close").onclick = () => this.closeDetail();
			if (!this.dialog.open) this.dialog.showModal();
			return {epoch, host: this.dialog.querySelector(".wir-detail-body")};
		}

		messageList(host, filter, current, open) {
			return this.paged(host, {
				view: "messages", filter, current, open,
				total: this.data?.totals[filter.metric] ?? this.data?.coverage?.find(row => row.key === filter.metric)?.count,
				columns: [__("Message"), __("Status")], rowHeight: 58,
				row: (row, i) => {
					const label = row.preview || MESSAGE_LABELS.get(row.message_kind) || __("Open message");
					const meta = [row.sender_name, receivedDateTime(row.received_at)].filter(Boolean).join(" · ");
					const reason = row.coverage === "failed" ? row.reason :
						row.coverage === "review" && row.intake_ai_state === "Drafted" ? __("Check intake link") : "";
					return `<tr><td><button type="button" class="wir-link" data-row="${i}" title="${escape(label)}">${escape(label)}</button>
						<span class="wir-message-meta" title="${escape(meta)}">${escape(meta)}</span></td>
						<td><span class="wir-message-status">${escape(row.status || "—")}</span>
						${reason ? `<span class="wir-message-meta" title="${escape(reason)}">${escape(reason)}</span>` : ""}</td></tr>`;
				},
			});
		}

		drill(view, filter, title, opener) {
			const {epoch, host} = this.detailShell(title, opener);
			const current = () => epoch === this.detailGeneration;
			if (view === "messages") {
				const cohort = this.generation;
				void this.messageList(host, filter, () => this.dialog.open && cohort === this.generation, (row, trigger) => {
					const list = host.querySelector(".wir-scroll");
					const position = list.scrollTop;
					this.openMessage(row, () => {
						const detail = this.detailShell(title, opener);
						detail.host.replaceWith(host);
						list.scrollTop = position;
						trigger.focus({preventScroll: true});
					});
				});
				return;
			}
			const doc = (name, doctype, allowed) => {
				if (!name) return "—";
				if (!allowed) return escape(name);
				return `<button type="button" class="wir-link" data-doc="${escape(name)}" data-doctype="${doctype}">${escape(name)}</button>`;
			};
			host.addEventListener("click", event => {
				const link = event.target.closest("[data-doc]");
				if (link) {
					this.closeDetail();
					frappe.set_route("Form", link.dataset.doctype, link.dataset.doc);
				}
			});
			void this.paged(host, {
				view, filter, current,
				total: (filter.request_type ? this.data?.types.find(row => row.key === filter.request_type) : this.data?.totals)?.[filter.metric],
				columns: [__("Intake"), __("Customer"), __("Original type"), __("Order")],
				row: row => `<tr><td>${doc(row.name, "Order Intake Request", row.can_open_intake)}</td><td>${escape(row.customer_name || row.customer || "—")}</td>
					<td>${escape(row.original_type || __("Unknown"))}</td><td>${doc(row.order, "Order", row.can_open_order)}</td></tr>`,
			});
		}

		async openMessage(row, back, opener) {
			const {epoch, host} = this.detailShell(__("WhatsApp conversation"), opener);
			const current = () => epoch === this.detailGeneration;
			const addBack = () => {
				if (!back) return;
				const button = document.createElement("button");
				button.className = "wir-link wir-back";
				button.type = "button";
				button.textContent = __("Back to messages");
				button.onclick = back;
				host.prepend(button);
			};
			host.textContent = __("Loading conversation…");
			try {
				const data = await this.call("message", {message: row.name});
				if (!current()) return;
				const target = data.target;
				if (!target?.name) throw new Error("Message unavailable");
				const messages = Array.isArray(data.messages) && data.messages.some(message => message.name === target.name)
					? data.messages : [target];
				host.innerHTML = `
					<div class="wir-chat-layout">
						<section class="wir-chat" aria-label="${escape(__("Conversation"))}">
							<header><strong>${escape(target.sender_name || row.sender_name || target.sender || __("WhatsApp"))}</strong>
								<span>${escape(data.account || row.account || "")}</span></header>
							${messages.length > 1 ? `<p class="wir-context">${escape(__("Nearby messages are shown for context."))}</p>` : ""}
							<div class="wir-bubbles" tabindex="0">
								${messages.map(message => this.bubble(message, target.name)).join("")}
							</div>
						</section>
						<aside class="wir-message-review">
							<h3>${escape(__("Message details"))}</h3>
							<p>${escape(receivedDateTime(target.received_at || row.received_at))}</p>
							${data.status || row.status ? `<p><strong>${escape(data.status || row.status)}</strong></p>` : ""}
							${data.reason || row.reason ? `<p>${escape(data.reason || row.reason)}</p>` : ""}
							${data.can_retry_attachment ? `<button class="wir-load-more" type="button" data-retry>${escape(__("Retry attachment"))}</button>` : ""}
							<p class="wir-retry-status" role="status"></p>
						</aside>
					</div>`;
				addBack();
				const bubbles = host.querySelector(".wir-bubbles");
				const selected = bubbles.querySelector(".wir-selected");
				bubbles.scrollTop = Math.max(0, selected.offsetTop - 14);
				bubbles.focus({preventScroll: true});
				if (!data.context_only && data.account && data.sender) this.mountPreviews(bubbles, data, current);
				const retry = host.querySelector("[data-retry]");
				if (retry) retry.onclick = () => this.retryAttachment(target.name, retry, current);
			} catch (_) {
				if (current()) {
					host.textContent = __("This message could not be opened.");
					addBack();
				}
			}
		}

		bubble(message, selected) {
			const quote = message.reply_context;
			const attachment = message.attachment;
			const href = attachment?.available ? localFile(attachment.url) : "";
			const location = message.location;
			const kind = String(message.content_type || "").toLowerCase();
			const isMedia = ["image", "document", "audio", "video", "sticker"].includes(kind);
			const preview = href && (kind === "image" || /^image\//.test(attachment.file_type || "") ||
				/\.pdf$/i.test(attachment.file_name || "") || attachment.file_type === "application/pdf");
			const fileName = attachment?.file_name;
			const generatedName = fileName?.replace(/\.[^.]+$/, "") === `whatsapp-${message.name}`;
			const useFileName = !generatedName && fileName && (!isMedia || kind === "document");
			const file = href ? `<a class="wir-file" href="${escape(href)}" target="_blank" rel="noopener noreferrer">
				${preview ? `<span class="wir-preview" data-preview-name="${escape(message.name)}"></span>` : ""}
				${escape(useFileName ? fileName : __("Open attachment"))}</a>` :
				(attachment || isMedia) ? `<p class="wir-quote">${escape(__("Attachment unavailable"))}</p>` : "";
			const latitude = Number(location?.latitude);
			const longitude = Number(location?.longitude);
			const coords = location?.latitude != null && location?.longitude != null &&
				Number.isFinite(latitude) && Number.isFinite(longitude) ? `${latitude}, ${longitude}` : "";
			return `<article class="wir-bubble${message.name === selected ? " wir-selected" : ""}">
				${message.name === selected ? `<strong class="wir-selected-label">${escape(__("Selected message"))}</strong>` : ""}
				${quote ? `<p class="wir-quote">${escape(quote.summary || __("Reply"))}</p>` : ""}
				${file}${location ? `<p class="wir-quote">${escape(location.name || __("Shared location"))}${location.address || coords ? "<br>" + escape(location.address || coords) : ""}</p>` : ""}
				${message.text ? `<p class="wir-message-text">${escape(message.text)}</p>` : ""}
				<time>${escape(receivedDateTime(message.received_at || message.creation))}</time>
			</article>`;
		}

		mountPreviews(bubbles, data, current) {
			const render = async node => {
				try {
					const response = await frappe.call({
						method: "kunal_enterprises.api.whatsapp_inbox_previews.preview", type: "GET", silent: true,
						args: {account: data.account, sender: data.sender, name: node.dataset.previewName},
					});
					const preview = response.message;
					const source = preview?.available && localFile(preview.url);
					if (!source || !current() || !node.isConnected) return;
					const image = document.createElement("img");
					image.src = source;
					image.alt = __("Attachment preview");
					image.width = Number(preview.width) || 300;
					image.height = Number(preview.height) || 200;
					node.append(image);
				} catch (_) { /* An attachment link remains available if its preview cannot be loaded. */ }
			};
			const nodes = [...bubbles.querySelectorAll("[data-preview-name]")];
			if (!nodes.length) return;
			if (typeof IntersectionObserver !== "function") {
				const selected = bubbles.querySelector(".wir-selected [data-preview-name]");
				if (selected) void render(selected);
				return;
			}
			const observer = new IntersectionObserver(entries => {
				for (const entry of entries) {
					if (!entry.isIntersecting) continue;
					observer.unobserve(entry.target);
					if (current()) void render(entry.target);
				}
			}, {root: bubbles, rootMargin: "80px"});
			this.previewObserver = observer;
			nodes.forEach(node => observer.observe(node));
		}

		async retryAttachment(name, button, current) {
			button.disabled = true;
			const status = button.parentElement.querySelector(".wir-retry-status");
			try {
				const result = await frappe.call({method: "kunal_enterprises.api.order_intake_capture.retry_attachment",
					type: "POST", silent: true, args: {message: name}});
				if (current()) {
					const state = result.message?.state;
					button.hidden = state === "Queued" || state === "Downloaded";
					button.disabled = button.hidden;
					status.textContent = state === "Queued" ? __("Attachment retry queued.") :
						state === "Downloaded" ? __("Attachment is available. Reopen the message to view it.") :
						__("This attachment cannot be retried.");
				}
			} catch (_) {
				if (current()) {
					button.disabled = false;
					status.textContent = __("Could not retry this attachment.");
				}
			}
		}
	}

	frappe.pages["whatsapp-intake-report"].on_page_load = wrapper => {
		wrapper.whatsappIntakeReport = new WhatsAppIntakeReport(wrapper);
		$(wrapper).on("hide.whatsappIntakeReport", () => wrapper.whatsappIntakeReport.hide());
	};
	frappe.pages["whatsapp-intake-report"].on_page_show = wrapper => wrapper.whatsappIntakeReport.show();
})();
