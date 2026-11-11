/*---------------------------------------------------------------------------------------------
 *  Copyright (c) SAEngine contributors. All rights reserved.
 *  Licensed under the AGPL-3.0-only license. See LICENSE in the repository root for license information.
 *--------------------------------------------------------------------------------------------*/

import { $, addDisposableListener, append, clearNode, EventType } from '../../../../base/browser/dom.js';
import { StandardKeyboardEvent } from '../../../../base/browser/keyboardEvent.js';
import { DomScrollableElement } from '../../../../base/browser/ui/scrollbar/scrollableElement.js';
import { Action } from '../../../../base/common/actions.js';
import { RunOnceScheduler } from '../../../../base/common/async.js';
import { Codicon } from '../../../../base/common/codicons.js';
import { KeyCode } from '../../../../base/common/keyCodes.js';
import { Disposable, DisposableStore, IReference } from '../../../../base/common/lifecycle.js';
import { joinPath } from '../../../../base/common/resources.js';
import { ScrollbarVisibility } from '../../../../base/common/scrollable.js';
import { ThemeIcon } from '../../../../base/common/themables.js';
import { URI } from '../../../../base/common/uri.js';
import { ITextModel } from '../../../../editor/common/model.js';
import { IResolvedTextEditorModel, ITextModelService } from '../../../../editor/common/services/resolverService.js';
import { localize } from '../../../../nls.js';
import { IInstantiationService } from '../../../../platform/instantiation/common/instantiation.js';
import { IWorkbenchContribution, registerWorkbenchContribution2, WorkbenchPhase } from '../../../common/contributions.js';
import { IEditorService } from '../../../services/editor/common/editorService.js';
import { ISaengineModelSelectionService } from '../../../services/saengineProject/common/modelSelection.js';
import { ISaengineProject, ISaengineProjectService, partById } from '../../../services/saengineProject/common/saengineProject.js';
import { headingWithUnit } from '../../../services/saengineProject/common/displayUnits.js';
import { openOwner } from '../../saengineModel/browser/projectDocuments.js';
import { EditorFrame } from '../../saengineProject/browser/editorFrame.js';
import { ISaengineTable } from '../../saengineProject/browser/modelLayoutModel.js';
import { SaengineTables } from '../../saengineProject/browser/tablesView.js';
import { IStoreyRow, lengthCell, storeyRows } from './floorPlanTableModel.js';
import { MembersTable } from './floorPlanTable.js';

/*
 * The floor plan's tables in the Tables panel below the model view: Members (the Members Table,
 * following the storey the model view shows) and Storeys. Both select what the model view, the
 * Properties panel and the Model Explorer show.
 */

const STOREYS_SOURCE = 'storeysTable';

function floorPlanOf(project: ISaengineProject | undefined): URI | undefined {
	const part = partById('floorPlan');
	return project && project.type !== 'structure' && part?.mainFile ? joinPath(project.root, part.folder, part.mainFile) : undefined;
}

/** The Members tab: the Members Table of the open project's floor plan. */
class MembersTab extends Disposable implements ISaengineTable {

	private readonly frame: EditorFrame;
	private readonly table: MembersTable;

	constructor(
		container: HTMLElement,
		@IInstantiationService instantiationService: IInstantiationService,
		@ISaengineProjectService projectService: ISaengineProjectService,
	) {
		super();
		this.frame = this._register(instantiationService.createInstance(EditorFrame, container, { id: 'saengine.tables.membersTable', ariaLabel: localize('tables.members', "Members") }));
		this.table = this._register(instantiationService.createInstance(MembersTable, this.frame, { followStory: true }));
		this._register(projectService.onDidChangeProject(project => void this.table.setFloorPlan(floorPlanOf(project))));
		void this.table.setFloorPlan(floorPlanOf(projectService.project));
	}

	layout(width: number, height: number): void {
		this.table.layout(width, height);
	}

	focus(): void {
		this.table.focus();
	}
}

/**
 * The Storeys tab: the floor plan's storeys, top first, with their elevation, height, typical
 * floor and members. Selecting one shows its plan; Grids & Stories changes them.
 */
class StoreysTab extends Disposable implements ISaengineTable {

	private readonly frame: EditorFrame;
	private readonly body: HTMLElement;
	private readonly scrollable: DomScrollableElement;
	private readonly rowStore = this._register(new DisposableStore());
	private readonly modelStore = this._register(new DisposableStore());
	private readonly renderScheduler = this._register(new RunOnceScheduler(() => this.render(), 100));
	private model: ITextModel | undefined;
	private rows: IStoreyRow[] = [];
	private loading = 0;

	private readonly editAction = this._register(new Action('saengine.tables.storeys.edit', localize('storeys.edit', "Edit in Grids & Stories"), ThemeIcon.asClassName(Codicon.edit), true, () => this.edit()));

	constructor(
		container: HTMLElement,
		@IInstantiationService instantiationService: IInstantiationService,
		@ISaengineProjectService private readonly projectService: ISaengineProjectService,
		@ISaengineModelSelectionService private readonly selectionService: ISaengineModelSelectionService,
		@ITextModelService private readonly textModelService: ITextModelService,
		@IEditorService private readonly editorService: IEditorService,
	) {
		super();
		this.frame = this._register(instantiationService.createInstance(EditorFrame, container, { id: 'saengine.tables.storeysTable', ariaLabel: localize('tables.storeys', "Storeys") }));
		this.frame.element.classList.add('saengine-members-table', 'saengine-storeys-table');
		this.frame.setTitle(localize('storeys.title', "Storeys"));
		this.frame.setActions([this.editAction]);
		this.body = $('.members-body', { tabIndex: 0, role: 'grid', 'aria-label': localize('storeys.aria', "Storeys") });
		this.scrollable = this._register(new DomScrollableElement(this.body, { horizontal: ScrollbarVisibility.Auto, vertical: ScrollbarVisibility.Auto }));
		append(this.frame.main, this.scrollable.getDomNode()).classList.add('members-scroll');
		this._register(this.frame.onDidLayoutMain(() => this.scrollable.scanDomNode()));
		this._register(addDisposableListener(this.body, EventType.KEY_DOWN, e => this.onKey(new StandardKeyboardEvent(e))));
		this._register(selectionService.onDidChangeSelection(() => this.renderRows()));
		this._register(selectionService.onDidChangeActiveStory(() => this.renderRows()));
		this._register(projectService.onDidChangeProject(project => void this.load(floorPlanOf(project))));
		void this.load(floorPlanOf(projectService.project));
	}

	layout(width: number, height: number): void {
		this.frame.layout(width, height);
	}

	focus(): void {
		this.body.focus();
	}

	private async load(floorPlan: URI | undefined): Promise<void> {
		const loading = ++this.loading;
		this.modelStore.clear();
		this.model = undefined;
		if (floorPlan) {
			let reference: IReference<IResolvedTextEditorModel>;
			try {
				reference = await this.textModelService.createModelReference(floorPlan);
			} catch (error) {
				this.frame.setEmpty({ icon: Codicon.warning, title: localize('storeys.noModel', "The floor plan could not be read"), text: String(error) });
				return;
			}
			if (loading !== this.loading) {
				reference.dispose();
				return;
			}
			this.modelStore.add(reference);
			this.model = reference.object.textEditorModel;
			this.modelStore.add(this.model.onDidChangeContent(() => this.renderScheduler.schedule()));
		}
		this.render();
	}

	private render(): void {
		let layout: unknown;
		try {
			layout = this.model ? JSON.parse(this.model.getValue()) : undefined;
		} catch {
			this.frame.setEmpty({ icon: Codicon.warning, title: localize('storeys.invalid', "The floor plan is not valid JSON") });
			return;
		}
		this.frame.setEmpty(undefined);
		this.rows = storeyRows(layout);
		this.renderRows();
	}

	/** The storey selected, else the one the model view shows. */
	private get current(): string | undefined {
		const selection = this.selectionService.selection;
		return selection?.kind === 'story' ? selection.id : this.selectionService.activeStory;
	}

	private renderRows(): void {
		this.rowStore.clear();
		clearNode(this.body);
		const current = this.current;
		const table = append(this.body, $('table.members-table'));
		const headRow = append(append(table, $('thead')), $('tr'));
		const headings = [
			localize('storeys.storey', "Storey"),
			headingWithUnit(localize('storeys.elevation', "Elevation (mm)")),
			headingWithUnit(localize('storeys.height', "Height (mm)")),
			localize('storeys.typical', "Typical of"),
			localize('storeys.members', "Members"),
		];
		for (const heading of headings) {
			append(append(headRow, $('th')), $('span.sort', undefined, heading));
		}
		const tbody = append(table, $('tbody'));
		for (const row of this.rows) {
			const selected = row.id === current;
			const tr = append(tbody, $('tr.member', { 'aria-selected': String(selected) }));
			tr.classList.toggle('selected', selected);
			tr.classList.toggle('focused', selected);
			append(tr, $('td.id', undefined, row.name));
			append(tr, $('td.length', undefined, lengthCell(row.elevation)));
			append(tr, $('td.length', undefined, row.height === undefined ? '' : lengthCell(row.height)));
			append(tr, $('td.kind', undefined, row.typicalOf ?? ''));
			append(tr, $('td.length', undefined, String(row.members)));
			this.rowStore.add(addDisposableListener(tr, EventType.CLICK, () => this.select(row.id)));
			this.rowStore.add(addDisposableListener(tr, EventType.DBLCLICK, () => this.edit()));
		}
		if (!this.rows.length) {
			append(this.body, $('p.members-empty', undefined, this.model
				? localize('storeys.none', "The floor plan has no storeys yet. Add them in Grids & Stories.")
				: localize('storeys.noFloorPlan', "A special structure has no storeys: its levels are in 05 Structural Model.")));
		}
		this.frame.setStatus({ text: localize('storeys.status', "{0} storeys", this.rows.length) });
		this.scrollable.scanDomNode();
	}

	private select(id: string): void {
		this.selectionService.setSelection({ kind: 'story', id }, STOREYS_SOURCE);
		this.body.focus();
	}

	private onKey(e: StandardKeyboardEvent): void {
		const index = this.rows.findIndex(r => r.id === this.current);
		const move = (to: number) => {
			const row = this.rows[Math.max(0, Math.min(this.rows.length - 1, to))];
			if (row) {
				this.select(row.id);
			}
		};
		if (e.keyCode === KeyCode.DownArrow) {
			move(index + 1);
		} else if (e.keyCode === KeyCode.UpArrow) {
			move(index - 1);
		} else if (e.keyCode === KeyCode.Enter || e.keyCode === KeyCode.F2) {
			void this.edit();
		} else {
			return;
		}
		e.preventDefault();
		e.stopPropagation();
	}

	private async edit(): Promise<void> {
		await openOwner(undefined, 'grids', this.projectService.project?.root, this.editorService);
	}
}

/** Registers the floor plan's tables with the Tables panel. */
class FloorPlanTablesContribution extends Disposable implements IWorkbenchContribution {

	static readonly ID = 'workbench.contrib.saengine.floorPlanTables';

	constructor() {
		super();
		const building = (project: ISaengineProject) => project.type !== 'structure';
		this._register(SaengineTables.register({
			id: 'members', order: 10, when: building,
			label: () => localize('tables.members', "Members"),
			create: (container, instantiationService) => instantiationService.createInstance(MembersTab, container),
		}));
		this._register(SaengineTables.register({
			id: 'storeys', order: 20, when: building,
			label: () => localize('tables.storeys', "Storeys"),
			create: (container, instantiationService) => instantiationService.createInstance(StoreysTab, container),
		}));
	}
}

registerWorkbenchContribution2(FloorPlanTablesContribution.ID, FloorPlanTablesContribution, WorkbenchPhase.BlockRestore);
