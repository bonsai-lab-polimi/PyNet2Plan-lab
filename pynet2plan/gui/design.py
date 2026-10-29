"""The "Network & traffic" tab: edit the topology and the traffic, run algorithms."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import network as netmod
from .. import traffic as trafmod
from ..errors import PyNet2PlanError
from .canvas import NetworkView
from .widgets import Table, error_dialog

MODES = [("select", "Select"), ("add_node", "Add node"), ("add_link", "Add link"),
         ("add_demand", "Add demand")]
MODE_HINTS = {
    "select": "Click a node or a link to select it.",
    "add_node": "Click on an empty point of the map to add a node there.",
    "add_link": "Click the origin node, then the destination node.",
    "add_demand": "Click the origin node, then the destination node of the demand.",
}


class DesignTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.mode = tk.StringVar(value="select")
        self.bidirectional = tk.BooleanVar(value=True)
        self.new_capacity = tk.StringVar(value=str(netmod.DEFAULT_CAPACITY))
        self.pending = None               # first node clicked in add_link / add_demand
        self.selected_node = None
        self.selected_link = None
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        bar = ttk.Frame(self, padding=(4, 4))
        bar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(bar, text="Mode:").pack(side=tk.LEFT)
        for key, text in MODES:
            ttk.Radiobutton(bar, text=text, value=key, variable=self.mode,
                            command=self._mode_changed).pack(side=tk.LEFT, padx=2)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Checkbutton(bar, text="new links bidirectional", variable=self.bidirectional).pack(side=tk.LEFT)
        ttk.Label(bar, text="  capacity:").pack(side=tk.LEFT)
        ttk.Spinbox(bar, from_=0, to=10000, textvariable=self.new_capacity, width=6).pack(side=tk.LEFT)
        ttk.Label(bar, text="λ").pack(side=tk.LEFT)
        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        ttk.Button(bar, text="Fail / repair selected", command=self.toggle_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Delete selected", command=self.delete_selected).pack(side=tk.LEFT, padx=2)

        # run bar (packed before the map so that it always stays visible)
        run = ttk.LabelFrame(self, text="Run an algorithm on this network and traffic", padding=(6, 4))
        run.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=4)
        run.columnconfigure(1, weight=1)
        ttk.Label(run, text="Algorithm:").grid(row=0, column=0, sticky=tk.W)
        self.algo_var = tk.StringVar()
        self.algo_combo = ttk.Combobox(run, textvariable=self.algo_var, state="readonly", width=70)
        self.algo_combo.grid(row=0, column=1, sticky=tk.EW, padx=4)
        self.algo_combo.bind("<<ComboboxSelected>>", lambda e: self.app.algorithm_changed())
        ttk.Button(run, text="Parameters...", command=self.app.action_edit_parameters).grid(row=0, column=2, padx=2)
        self.run_button = ttk.Button(run, text="▶ Run", command=self.app.action_run)
        self.run_button.grid(row=0, column=3, padx=2)
        self.sweep_button = ttk.Button(run, text="Compare (sweep)...", command=self.app.action_sweep)
        self.sweep_button.grid(row=0, column=4, padx=2)
        self.check_button = ttk.Button(run, text="Check", command=self.app.action_check_formulation)
        self.check_button.grid(row=0, column=5, padx=2)
        ttk.Button(run, text="Reload files", command=self.app.reload_formulations).grid(row=0, column=6, padx=2)
        self.params_label = ttk.Label(run, text="", foreground="#555555")
        self.params_label.grid(row=1, column=0, columnspan=2, sticky=tk.W, padx=4, pady=(4, 0))
        self.job_label = ttk.Label(run, text="", foreground="#555555")
        self.job_label.grid(row=1, column=2, sticky=tk.E, pady=(4, 0))
        self.progress = ttk.Progressbar(run, mode="indeterminate", length=160)
        self.progress.grid(row=1, column=3, columnspan=2, sticky=tk.EW, padx=2, pady=(4, 0))
        self.cancel_button = ttk.Button(run, text="Cancel", command=self.app.action_cancel_job,
                                        state=tk.DISABLED)
        self.cancel_button.grid(row=1, column=5, columnspan=2, sticky=tk.EW, padx=2, pady=(4, 0))

        paned = ttk.Panedwindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        self.paned = paned
        self.view = NetworkView(paned, on_click=self.canvas_clicked,
                                pdf=lambda: (None, self.app.G.graph.get("name") or "network"))
        paned.add(self.view, weight=3)
        right = ttk.Notebook(paned)
        paned.add(right, weight=2)
        self.notebook = right

        # nodes
        f = ttk.Frame(right)
        self.nodes_table = Table(f, [("name", "name", 140, "w"), ("lat", "lat", 70), ("lon", "lon", 70),
                                     ("degree", "out-degree", 70), ("state", "state", 60)],
                                 on_select=self._node_rows_selected)
        self.nodes_table.pack(fill=tk.BOTH, expand=True)
        b = ttk.Frame(f)
        b.pack(side=tk.BOTTOM, fill=tk.X, pady=3, before=self.nodes_table)
        ttk.Button(b, text="Rename...", command=self.rename_node).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Fail / repair", command=self.toggle_selected).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Delete", command=self.delete_selected).pack(side=tk.LEFT, padx=2)
        right.add(f, text="Nodes")

        # links
        f = ttk.Frame(right)
        self.links_table = Table(f, [("origin", "origin", 110, "w"), ("destination", "destination", 110, "w"),
                                     ("fibers", "fibers", 56), ("capacity", "λ per fiber", 84),
                                     ("length", "length", 80),
                                     ("state", "state", 60)],
                                 on_select=self._link_rows_selected)
        self.links_table.pack(fill=tk.BOTH, expand=True)
        b = ttk.Frame(f)
        b.pack(side=tk.BOTTOM, fill=tk.X, pady=3, before=self.links_table)
        for text, command in (("Edit capacity...", self.edit_capacity),
                              ("Same capacity for all...", self.uniform_capacity),
                              ("Fibers...", self.edit_fibers),
                              ("Fail / repair", self.toggle_selected), ("Delete", self.delete_selected)):
            # width=-1: as wide as the text, so that the five buttons fit next to the table
            ttk.Button(b, text=text, command=command, width=-1).pack(side=tk.LEFT, padx=2)
        right.add(f, text="Links")

        # traffic
        f = ttk.Frame(right)
        self.traffic_info = ttk.Label(f, text="", foreground="#444444")
        self.traffic_info.pack(fill=tk.X, padx=2, pady=2)
        self.traffic_table = Table(f, [("id", "id", 50), ("origin", "origin", 120, "w"),
                                       ("destination", "destination", 120, "w"),
                                       ("traffic", "wavelengths", 90)],
                                   on_select=self._demand_rows_selected)
        self.traffic_table.pack(fill=tk.BOTH, expand=True)
        b = ttk.Frame(f)
        b.pack(side=tk.BOTTOM, fill=tk.X, pady=3, before=self.traffic_table)
        ttk.Button(b, text="Load...", command=self.app.action_open_traffic).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Random...", command=self.app.action_random_traffic).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Save...", command=self.app.action_save_traffic_as).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Edit...", command=self.edit_demand).pack(side=tk.LEFT, padx=2)
        ttk.Button(b, text="Delete", command=self.delete_demands).pack(side=tk.LEFT, padx=2)
        right.add(f, text="Traffic")

        # info
        f = ttk.Frame(right)
        self.info_text = tk.Text(f, wrap=tk.WORD, height=20, font="PNPMono")
        self.info_text.pack(fill=tk.BOTH, expand=True)
        right.add(f, text="Info")

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    def refresh(self, tables=True):
        G = self.app.G
        if self.selected_node is not None and self.selected_node not in G:
            self.selected_node = None
        if self.selected_link is not None and not G.has_edge(*self.selected_link):
            self.selected_link = None
        self.view.draw(G, show_names=self.app.show_names.get(),
                       label_mode="capacity" if self.app.show_link_labels.get() else None,
                       selected_node=self.selected_node, selected_link=self.selected_link,
                       title=self._title(), map_background=self.app.map_background.get())
        if tables:
            self._fill_tables()

    def _title(self):
        G = self.app.G
        name = G.graph.get("name", "")
        return f"{name}   ({G.number_of_nodes()} nodes, {G.number_of_edges()} links, " \
               f"{len(self.app.demands)} demands)"

    def _fill_tables(self):
        G = self.app.G
        rows = []
        for n, a in G.nodes(data=True):
            rows.append(dict(name=n, lat=round(a["lat"], 4) if a.get("lat") is not None else "",
                             lon=round(a["lon"], 4) if a.get("lon") is not None else "",
                             degree=G.out_degree(n), state="UP" if a.get("up", True) else "DOWN"))
        self.nodes_table.set_rows(rows, tags=lambda r: "bad" if r["state"] == "DOWN" else None)
        rows = [dict(origin=u, destination=v, fibers=a.get("fibers", 1), capacity=a["capacity"],
                     length=round(a["length"], 2),
                     state="UP" if a.get("up", True) else "DOWN") for u, v, a in G.edges(data=True)]
        self.links_table.set_rows(rows, tags=lambda r: "bad" if r["state"] == "DOWN" else None)
        dem = self.app.demands
        problems = trafmod.validate_traffic(dem, G)
        bad_ids = set()
        for d in dem:
            if d.origin not in G or d.destination not in G:
                bad_ids.add(d.id)
        self.traffic_table.set_rows([dict(id=d.id, origin=d.origin, destination=d.destination,
                                          traffic=d.traffic) for d in dem],
                                    tags=lambda r: "bad" if r["id"] in bad_ids else None)
        src = self.app.traffic_path or "not saved"
        txt = f"{len(dem)} demands, {trafmod.total_traffic(dem)} wavelengths   |   file: {src}"
        if self.app.dirty_traffic:
            txt += "  (modified)"
        if problems:
            txt += f"\n⚠ {len(problems)} problem(s): {problems[0]}"
        self.traffic_info.configure(text=txt, foreground="#c62828" if problems else "#444444")
        self._fill_info()

    def _fill_info(self):
        G = self.app.G
        s = netmod.summary(G)
        lines = [
            f"Network:   {s['name']}",
            f"File:      {self.app.topology_path or 'not saved'}{'  (modified)' if self.app.dirty_topology else ''}",
            "",
            f"Nodes:     {s['num_nodes']}  ({s['num_nodes_up']} up)",
            f"Links:     {s['num_links']}  ({s['num_links_up']} up), unidirectional",
            f"Capacity:  {s['min_capacity']} - {s['max_capacity']} wavelengths per fiber",
            f"Fibers:    {s['min_fibers']} - {s['max_fibers']} per link "
            f"(total {s['total_capacity']} wavelengths on all links)",
            f"Mean out-degree: {s['avg_out_degree']:.2f}",
            f"Strongly connected (up elements): {'yes' if s['strongly_connected'] else 'NO'}",
            f"Geographic (lat/lon) nodes: {'yes' if s['geographic'] else 'no'}",
            "",
            f"Traffic:   {len(self.app.demands)} demands, {trafmod.total_traffic(self.app.demands)} "
            f"wavelengths",
            f"File:      {self.app.traffic_path or 'not saved'}{'  (modified)' if self.app.dirty_traffic else ''}",
        ]
        if G.graph.get("description"):
            lines += ["", "Description: " + str(G.graph["description"])]
        if G.graph.get("load_warnings"):
            lines += ["", "Notes from loading the file:"] + [f"  - {w}" for w in G.graph["load_warnings"]]
        lines += ["", "In Python this network is a networkx.DiGraph:",
                  "  G.nodes, G.edges, G.edges[i, j]['capacity'], G.edges[i, j]['fibers'],",
                  "  G.out_edges(n), ..."]
        self.info_text.configure(state=tk.NORMAL)
        self.info_text.delete("1.0", tk.END)
        self.info_text.insert("1.0", "\n".join(lines))
        self.info_text.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Canvas interaction
    # ------------------------------------------------------------------
    def _mode_changed(self):
        self.pending = None
        self.app.set_status(MODE_HINTS.get(self.mode.get(), ""))

    def _capacity(self) -> int:
        try:
            c = int(str(self.new_capacity.get()).strip())
        except ValueError:
            raise PyNet2PlanError("The capacity of new links must be a whole number.") from None
        if c < 0:
            raise PyNet2PlanError("The capacity of new links cannot be negative.")
        return c

    def canvas_clicked(self, x, y, node, link):
        mode = self.mode.get()
        G = self.app.G
        try:
            if mode == "select":
                self.selected_node, self.selected_link = node, link
                if node is not None:
                    self.nodes_table.select(lambda r: r["name"] == node)
                    self.notebook.select(0)
                    self.app.set_status(f"Node {node}: out-degree {G.out_degree(node)}, "
                                        f"{'UP' if G.nodes[node].get('up', True) else 'DOWN'}")
                elif link is not None:
                    self.links_table.select(lambda r: (r["origin"], r["destination"]) == link)
                    self.notebook.select(1)
                    a = G.edges[link]
                    cap = (f"{a['fibers']} fibers x {a['capacity']} λ" if a.get("fibers", 1) > 1
                           else f"{a['capacity']} λ")
                    self.app.set_status(f"Link {link[0]}->{link[1]}: {cap}, "
                                        f"{a['length']:g} km, {'UP' if a.get('up', True) else 'DOWN'}")
                self.refresh(tables=False)
            elif mode == "add_node":
                if node is not None:
                    self.app.set_status(f"There is already a node here ({node}).")
                    return
                default = netmod.unique_name(G, f"N{G.number_of_nodes()}")
                name = self.app.ask_string("Add node", "Node name:", default)
                if not name:
                    return
                netmod.add_node(G, name, x=x, y=y)
                self.app.topology_changed()
            elif mode in ("add_link", "add_demand"):
                if node is None:
                    return
                if self.pending is None:
                    self.pending = node
                    self.selected_node = node
                    what = "link" if mode == "add_link" else "demand"
                    self.app.set_status(f"New {what} from {node}: now click the destination node.")
                    self.refresh(tables=False)
                    return
                origin, self.pending = self.pending, None
                self.selected_node = None
                if mode == "add_link":
                    netmod.add_link(G, origin, node, capacity=self._capacity(),
                                    bidirectional=self.bidirectional.get())
                    self.app.topology_changed()
                    self.app.set_status(f"Link {origin}->{node} added"
                                        + (" (both directions)." if self.bidirectional.get() else "."))
                else:
                    if origin == node:
                        raise PyNet2PlanError("A demand needs two different nodes.")
                    t = self.app.ask_integer("Add demand", f"Wavelengths requested {origin} -> {node}:", 1, 1)
                    if t is None:
                        self.refresh(tables=False)
                        return
                    self.app.add_demand(origin, node, t)
        except PyNet2PlanError as e:
            self.pending = None
            error_dialog(self, "Cannot do that", str(e))
            self.refresh(tables=False)

    # ------------------------------------------------------------------
    # Table selections
    # ------------------------------------------------------------------
    def _node_rows_selected(self, rows):
        self.selected_node = rows[0]["name"] if rows else None
        self.selected_link = None
        self.refresh(tables=False)

    def _link_rows_selected(self, rows):
        self.selected_link = (rows[0]["origin"], rows[0]["destination"]) if rows else None
        self.selected_node = None
        self.refresh(tables=False)

    def _demand_rows_selected(self, rows):
        if rows:
            self.selected_node = rows[0]["origin"] if rows[0]["origin"] in self.app.G else None
            self.app.set_status(f"Demand {rows[0]['id']}: {rows[0]['origin']} -> "
                                f"{rows[0]['destination']}, {rows[0]['traffic']} λ")
            self.refresh(tables=False)

    # ------------------------------------------------------------------
    # Editing actions
    # ------------------------------------------------------------------
    def _current_selection(self):
        """('nodes', [names]) / ('links', [(u, v)]) / ('demands', [ids]) / (None, [])."""
        tab = self.notebook.index(self.notebook.select())
        if tab == 0 and self.nodes_table.selected_rows():
            return "nodes", [r["name"] for r in self.nodes_table.selected_rows()]
        if tab == 1 and self.links_table.selected_rows():
            return "links", [(r["origin"], r["destination"]) for r in self.links_table.selected_rows()]
        if tab == 2 and self.traffic_table.selected_rows():
            return "demands", [r["id"] for r in self.traffic_table.selected_rows()]
        if self.selected_node is not None:
            return "nodes", [self.selected_node]
        if self.selected_link is not None:
            return "links", [self.selected_link]
        return None, []

    def toggle_selected(self):
        kind, items = self._current_selection()
        G = self.app.G
        if kind == "nodes":
            for n in items:
                netmod.set_node_up(G, n, not G.nodes[n].get("up", True))
        elif kind == "links":
            for e in items:
                netmod.set_link_up(G, *e, not G.edges[e].get("up", True))
        else:
            self.app.set_status("Select a node or a link first (click it on the map or in a table).")
            return
        self.app.topology_changed()
        self.app.set_status(f"State of {len(items)} {kind[:-1]}(s) changed. Failed elements are "
                            f"ignored by the algorithms.")

    def delete_selected(self):
        kind, items = self._current_selection()
        G = self.app.G
        if kind == "nodes":
            for n in items:
                if n in G:
                    netmod.remove_node(G, n)
            self.selected_node = None
            self.app.topology_changed()
            orphan = [d for d in self.app.demands if d.origin not in G or d.destination not in G]
            if orphan:
                self.app.set_demands([d for d in self.app.demands if d not in orphan], dirty=True)
                self.app.set_status(f"Deleted {len(items)} node(s) and {len(orphan)} demand(s) using them.")
        elif kind == "links":
            for e in items:
                if G.has_edge(*e):
                    netmod.remove_link(G, *e)
            self.selected_link = None
            self.app.topology_changed()
        elif kind == "demands":
            self.delete_demands()
        else:
            self.app.set_status("Select something to delete first.")

    def rename_node(self):
        rows = self.nodes_table.selected_rows()
        if not rows:
            self.app.set_status("Select a node in the table first.")
            return
        old = rows[0]["name"]
        new = self.app.ask_string("Rename node", f"New name for '{old}':", old)
        if not new or new == old:
            return
        try:
            netmod.rename_node(self.app.G, old, new)
        except PyNet2PlanError as e:
            error_dialog(self, "Rename node", str(e))
            return
        self.app.set_demands([trafmod.Demand(d.id, new if d.origin == old else d.origin,
                                             new if d.destination == old else d.destination, d.traffic)
                              for d in self.app.demands], dirty=True)
        self.selected_node = new
        self.app.topology_changed()

    def edit_capacity(self):
        rows = self.links_table.selected_rows()
        if not rows:
            self.app.set_status("Select one or more links in the Links table first.")
            return
        c = self.app.ask_integer("Edit capacity", f"Wavelengths per fiber of {len(rows)} link(s):",
                                 rows[0]["capacity"], 0)
        if c is None:
            return
        for r in rows:
            netmod.set_link_capacity(self.app.G, r["origin"], r["destination"], c)
        self.app.topology_changed()

    def uniform_capacity(self):
        c = self.app.ask_integer("Same capacity for all links", "Wavelengths per fiber of every link:",
                                 netmod.DEFAULT_CAPACITY, 0)
        if c is None:
            return
        netmod.set_uniform_capacity(self.app.G, c)
        self.app.topology_changed()

    def edit_fibers(self):
        """Number of fibers of the selected links (all links if none is selected)."""
        rows = self.links_table.selected_rows()
        G = self.app.G
        if rows:
            prompt, initial = f"Number of fibers of {len(rows)} link(s):", rows[0].get("fibers", 1)
        else:
            prompt, initial = "No link selected: number of fibers of every link:", netmod.DEFAULT_FIBERS
        f = self.app.ask_integer("Fibers", prompt, initial, 1)
        if f is None:
            return
        if rows:
            for r in rows:
                netmod.set_link_fibers(G, r["origin"], r["destination"], f)
        else:
            netmod.set_uniform_fibers(G, f)
        self.app.topology_changed()

    def edit_demand(self):
        rows = self.traffic_table.selected_rows()
        if not rows:
            self.app.set_status("Select one or more demands in the Traffic table first.")
            return
        t = self.app.ask_integer("Edit demand", f"Wavelengths requested by {len(rows)} demand(s):",
                                 rows[0]["traffic"], 1)
        if t is None:
            return
        ids = {r["id"] for r in rows}
        self.app.set_demands([trafmod.Demand(d.id, d.origin, d.destination, t) if d.id in ids else d
                              for d in self.app.demands], dirty=True)

    def delete_demands(self):
        rows = self.traffic_table.selected_rows()
        if not rows:
            self.app.set_status("Select one or more demands in the Traffic table first.")
            return
        ids = {r["id"] for r in rows}
        self.app.set_demands([d for d in self.app.demands if d.id not in ids], dirty=True)
        self.app.set_status(f"Deleted {len(ids)} demand(s).")
